"""Deterministic, explainable next-statement card projection.

This read model deliberately forecasts only inside the currently observed
billing cycle. It never treats an old statement or an unanchored balance as a
current fact.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.schemas.financial_position import (
    CardRecurringChargeProjection,
    CardStatementProjectionEvidence,
    CardStatementProjectionPoint,
    CardStatementProjectionResponse,
)

RULESET_VERSION = "pfis-card-statement-projection-9"
_MONEY = Decimal("0.01")
ProjectionStatus = Literal[
    "available",
    "needs_recent_statement",
    "needs_current_position",
    "needs_credit_limit",
    "needs_activity",
]
ProjectionNextState = Literal[
    "monitor_cycle",
    "reduce_spend_or_pay",
    "prepare_statement_payment",
    "review_evidence",
]
ProjectionCalibration = Literal["current_cycle_only", "historical_blend"]
ProjectionTargetStatus = Literal["under_target", "at_risk", "over_target", "unavailable"]
ProjectionLimitStatus = Literal["under_limit", "at_risk", "over_limit", "unavailable"]
HistoricalCycleMovements = tuple[date, date, list[tuple[date, Decimal]]]


@dataclass(frozen=True, slots=True)
class CardRecurringChargeCandidate:
    """A bounded merchant-cadence charge expected before the next close."""

    expected_date: date
    amount: Decimal
    merchant: str
    cadence: str | None
    occurrences: int
    confidence: Decimal
    amount_low: Decimal | None = None
    amount_high: Decimal | None = None
    expected_date_low: date | None = None
    expected_date_high: date | None = None


def _bounded_candidate_amount_range(
    candidate: CardRecurringChargeCandidate,
) -> tuple[Decimal, Decimal]:
    """Return a safe amount envelope around the candidate's central amount.

    RecurringPatternService supplies a range from settled observations. The
    fallback keeps older callers compatible, and the final clamp prevents an
    untrusted caller from turning one candidate into an unbounded forecast.
    """

    amount = max(candidate.amount, Decimal("0"))
    low = candidate.amount_low if candidate.amount_low is not None else amount
    high = candidate.amount_high if candidate.amount_high is not None else amount
    low = max(Decimal("0"), min(low, amount))
    high = max(amount, high)
    if amount > 0:
        low = max(low, amount * Decimal("0.50"))
        high = min(high, amount * Decimal("1.50"))
    return low, high


def _bounded_candidate_date_range(
    candidate: CardRecurringChargeCandidate,
) -> tuple[date, date]:
    """Return a bounded timing envelope around the central candidate date."""

    low = candidate.expected_date_low or candidate.expected_date
    high = candidate.expected_date_high or candidate.expected_date
    low = min(low, candidate.expected_date)
    high = max(high, candidate.expected_date)
    max_window = timedelta(days=45)
    return (
        max(low, candidate.expected_date - max_window),
        min(high, candidate.expected_date + max_window),
    )


def _build_seasonal_profile(
    historical_cycles: list[HistoricalCycleMovements] | None,
    expected_cycle_days: int,
) -> tuple[dict[int, Decimal], dict[int, Decimal], int]:
    """Build a conservative day-of-cycle profile from prior settled cycles.

    Only positive liability movement with at least two observations at the same
    cycle offset is used. Missing or zero-history days fall back to the current
    daily pace; this prevents sparse statements from predicting that a quiet
    historical day guarantees no future spend.
    """

    if not historical_cycles or expected_cycle_days <= 0:
        return {}, {}, 0
    observations: dict[int, list[Decimal]] = defaultdict(list)
    valid_cycle_count = 0
    for cycle_start, cycle_end, movements in historical_cycles:
        cycle_days = (cycle_end - cycle_start).days + 1
        if cycle_days < 21 or cycle_days > 45:
            continue
        valid_cycle_count += 1
        daily: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        for movement_date, amount in movements:
            if cycle_start <= movement_date <= cycle_end:
                offset = (movement_date - cycle_start).days
                if 0 <= offset < expected_cycle_days:
                    daily[offset] += amount
        for offset in range(min(cycle_days, expected_cycle_days)):
            observations[offset].append(daily[offset])

    profile: dict[int, Decimal] = {}
    variability: dict[int, Decimal] = {}
    for offset, values in observations.items():
        if len(values) < 2:
            continue
        average = sum(values, Decimal("0")) / Decimal(len(values))
        if average <= 0:
            continue
        profile[offset] = average
        variability[offset] = sum(
            (abs(value - average) for value in values), Decimal("0")
        ) / Decimal(len(values))
    return profile, variability, valid_cycle_count if profile else 0


def build_card_statement_projection(
    *,
    today: date,
    statement_date: date | None,
    period_start: date | None,
    period_end: date | None,
    current_balance: Decimal | None,
    credit_limit: Decimal | None,
    balance_confidence: float,
    eligible_movements: list[Decimal],
    utilization_target_pct: Decimal | None,
    historical_daily_paces: list[Decimal] | None = None,
    historical_cycle_movements: list[HistoricalCycleMovements] | None = None,
    future_planned_payments: list[tuple[date, Decimal]] | None = None,
    future_scheduled_charges: list[tuple[date, Decimal, str]] | None = None,
    future_recurring_charges: list[CardRecurringChargeCandidate] | None = None,
    pending_refund_amount: Decimal | None = None,
) -> CardStatementProjectionResponse:
    """Project the next statement from verified cycle-to-date evidence.

    ``eligible_movements`` use liability signs: purchases/fees are positive,
    while refunds and other non-payment credits are negative. Card payments
    are intentionally excluded because the current balance already reflects
    them and they do not predict future spend.
    """

    if statement_date is None or period_start is None or period_end is None:
        return _unavailable("needs_recent_statement", "missing_statement_cycle")

    cycle_days = (period_end - period_start).days + 1
    if cycle_days < 21 or cycle_days > 45:
        return _unavailable("needs_recent_statement", "irregular_statement_cycle")

    projected_statement_date = statement_date.fromordinal(statement_date.toordinal() + cycle_days)
    if today <= statement_date or projected_statement_date <= today:
        return _unavailable(
            "needs_recent_statement",
            "statement_cycle_is_not_current",
            projected_statement_date=projected_statement_date,
        )
    if current_balance is None:
        return _unavailable(
            "needs_current_position",
            "current_balance_is_not_anchored",
            projected_statement_date=projected_statement_date,
        )
    if credit_limit is None or credit_limit <= 0:
        return _unavailable(
            "needs_credit_limit",
            "credit_limit_is_not_available",
            projected_statement_date=projected_statement_date,
        )

    elapsed_days = (today - statement_date).days
    remaining_days = (projected_statement_date - today).days
    if elapsed_days < 3 or len(eligible_movements) < 3:
        return _unavailable(
            "needs_activity",
            "insufficient_cycle_activity",
            projected_statement_date=projected_statement_date,
            as_of=today,
        )

    net_movement = sum(eligible_movements, Decimal("0"))
    gross_movement = sum((abs(value) for value in eligible_movements), Decimal("0"))
    current_daily_net = net_movement / Decimal(elapsed_days)
    historical_paces = sorted(
        pace for pace in (historical_daily_paces or []) if pace >= Decimal("0")
    )
    historical_baseline = None
    if historical_paces:
        middle = len(historical_paces) // 2
        historical_baseline = (
            historical_paces[middle]
            if len(historical_paces) % 2
            else (historical_paces[middle - 1] + historical_paces[middle]) / Decimal("2")
        )
    if historical_baseline is not None and len(historical_paces) >= 2:
        daily_net = current_daily_net * Decimal("0.70") + historical_baseline * Decimal("0.30")
        calibration: ProjectionCalibration = "historical_blend"
    else:
        daily_net = current_daily_net
        calibration = "current_cycle_only"
    daily_gross = gross_movement / Decimal(elapsed_days)
    seasonal_profile, seasonal_variability_by_offset, seasonal_sample_count = (
        _build_seasonal_profile(historical_cycle_movements, cycle_days)
    )
    planned_payments = [
        (planned_for, amount)
        for planned_for, amount in (future_planned_payments or [])
        if today < planned_for <= projected_statement_date and amount > 0
    ]
    planned_payment_total = sum((amount for _, amount in planned_payments), Decimal("0"))
    scheduled_charges = [
        (charge_date, amount, label)
        for charge_date, amount, label in (future_scheduled_charges or [])
        if today < charge_date <= projected_statement_date and amount > 0
    ]
    scheduled_charge_total = sum((amount for _, amount, _ in scheduled_charges), Decimal("0"))
    scheduled_charge_keys = {(charge_date, amount) for charge_date, amount, _ in scheduled_charges}
    recurring_charges = [
        candidate
        for candidate in (future_recurring_charges or [])
        if (
            today < candidate.expected_date <= projected_statement_date
            and candidate.amount > 0
            and candidate.confidence >= Decimal("0.55")
            and (candidate.expected_date, candidate.amount) not in scheduled_charge_keys
        )
    ]
    recurring_charge_total = sum(
        (candidate.amount for candidate in recurring_charges), Decimal("0")
    )
    recurring_amount_ranges = [
        _bounded_candidate_amount_range(candidate) for candidate in recurring_charges
    ]
    recurring_date_ranges = [
        _bounded_candidate_date_range(candidate) for candidate in recurring_charges
    ]
    path_events: dict[date, Decimal] = {}
    path_event_labels: dict[date, list[str]] = defaultdict(list)
    for event_date, amount, _ in scheduled_charges:
        path_events[event_date] = path_events.get(event_date, Decimal("0")) + amount
    for event_date, _, label in scheduled_charges:
        path_event_labels[event_date].append(f"Scheduled: {label}")
    for candidate in recurring_charges:
        path_events[candidate.expected_date] = (
            path_events.get(candidate.expected_date, Decimal("0")) + candidate.amount
        )
        path_event_labels[candidate.expected_date].append(f"Recurring: {candidate.merchant}")
    for event_date, amount in planned_payments:
        path_events[event_date] = path_events.get(event_date, Decimal("0")) - amount
        path_event_labels[event_date].append("Planned payment")
    forecast_daily_movement: dict[date, Decimal] = {}
    seasonal_days_covered = 0
    seasonal_uncertainty = Decimal("0")
    projected_cycle_start = statement_date + timedelta(days=1)
    for day_offset in range(1, remaining_days + 1):
        forecast_date = today + timedelta(days=day_offset)
        cycle_offset = (forecast_date - projected_cycle_start).days
        seasonal_value = seasonal_profile.get(cycle_offset)
        if seasonal_value is None:
            forecast_daily_movement[forecast_date] = daily_net
            continue
        # Shrink the historical day signal toward the current pace so a
        # small cohort can refine timing without overwhelming current evidence.
        forecast_daily_movement[forecast_date] = daily_net * Decimal(
            "0.65"
        ) + seasonal_value * Decimal("0.35")
        seasonal_days_covered += 1
        seasonal_uncertainty += seasonal_variability_by_offset.get(
            cycle_offset, Decimal("0")
        ) * Decimal("0.50")
    daily_path_balances: list[tuple[date, Decimal, Decimal, list[str]]] = []
    path_balance = current_balance
    for day_offset in range(1, remaining_days + 1):
        path_date = today + timedelta(days=day_offset)
        event_amount = path_events.get(path_date, Decimal("0"))
        path_balance = max(
            path_balance + forecast_daily_movement.get(path_date, daily_net) + event_amount,
            Decimal("0"),
        )
        daily_path_balances.append(
            (
                path_date,
                path_balance,
                event_amount,
                list(path_event_labels.get(path_date, [])),
            )
        )
    projected_change = (
        sum(forecast_daily_movement.values(), Decimal("0"))
        + scheduled_charge_total
        + recurring_charge_total
        - planned_payment_total
    )
    projected_balance = max(current_balance + projected_change, Decimal("0"))

    # The range widens with the observed gross pace. This is an uncertainty
    # band, not a statistical confidence interval, and is labelled as such.
    uncertainty = daily_gross * Decimal(remaining_days) * Decimal("0.50")
    if historical_baseline is not None and len(historical_paces) >= 2:
        historical_deviation = sum(
            (abs(pace - historical_baseline) for pace in historical_paces), Decimal("0")
        ) / Decimal(len(historical_paces))
        uncertainty += historical_deviation * Decimal(remaining_days)
    uncertainty += seasonal_uncertainty
    # Cadence candidates are useful forward evidence, but they are not
    # guaranteed issuer charges. Widen the band by the untrusted portion of
    # each candidate rather than presenting the central estimate as certain.
    uncertainty += sum(
        (
            candidate.amount * (Decimal("1") - min(candidate.confidence, Decimal("1")))
            for candidate in recurring_charges
        ),
        Decimal("0"),
    )
    # A recurring cadence can be real while its amount drifts (for example,
    # usage-based utilities). Keep the central estimate at the observed
    # average and widen only the uncertainty range by half of each bounded
    # historical envelope.
    recurring_amount_uncertainty = sum(
        ((high - low) / Decimal("2") for low, high in recurring_amount_ranges),
        Decimal("0"),
    )
    uncertainty += recurring_amount_uncertainty
    recurring_date_variability = [(low, high) for low, high in recurring_date_ranges if low != high]
    potential_pending_refund = max(pending_refund_amount or Decimal("0"), Decimal("0"))
    range_low = max(projected_balance - uncertainty - potential_pending_refund, Decimal("0"))
    range_high = projected_balance + uncertainty
    utilization = projected_balance / credit_limit * Decimal("100")

    credit_limit_headroom_amount = max(credit_limit - projected_balance, Decimal("0"))
    credit_limit_excess_amount = max(projected_balance - credit_limit, Decimal("0"))
    credit_limit_breach_date: date | None = None
    credit_limit_breach_days: int | None = None
    if current_balance >= credit_limit:
        credit_limit_breach_date = today
        credit_limit_breach_days = 0
    else:
        for day_offset, (path_date, daily_balance, _, _) in enumerate(daily_path_balances, start=1):
            if daily_balance >= credit_limit:
                credit_limit_breach_date = path_date
                credit_limit_breach_days = day_offset
                break
    if projected_balance >= credit_limit:
        credit_limit_status: ProjectionLimitStatus = "over_limit"
    elif range_high > credit_limit:
        credit_limit_status = "at_risk"
    else:
        credit_limit_status = "under_limit"
    credit_limit_evidence = [
        CardStatementProjectionEvidence(
            label="Credit-limit runway",
            value=(
                f"{credit_limit_excess_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)} over limit"
                if credit_limit_status == "over_limit"
                else (
                    f"{credit_limit_headroom_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)} central headroom; "
                    "uncertainty range crosses the limit"
                    if credit_limit_status == "at_risk"
                    else f"{credit_limit_headroom_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)} headroom"
                )
            ),
            basis=(
                "Projected close compared with the issuer credit limit; this is a PFIS estimate, "
                "not a live available-credit or issuer warning."
            ),
        ),
        CardStatementProjectionEvidence(
            label="Central credit-limit breach timing",
            value=(
                f"{credit_limit_breach_days} day(s) · {credit_limit_breach_date.isoformat()}"
                if credit_limit_breach_days is not None and credit_limit_breach_date is not None
                else "No central breach before projected close"
            ),
            basis=(
                "Central pace path with known dated events; this does not model issuer holds, "
                "settlement latency, or live available credit."
            ),
        ),
    ]

    target = utilization_target_pct
    target_status: ProjectionTargetStatus = "unavailable"
    target_headroom_amount: Decimal | None = None
    target_excess_amount: Decimal | None = None
    target_breach_date: date | None = None
    target_breach_days: int | None = None
    target_evidence: list[CardStatementProjectionEvidence] = []
    if target is not None:
        target_balance = credit_limit * target / Decimal("100")
        target_headroom_amount = max(target_balance - projected_balance, Decimal("0"))
        target_excess_amount = max(projected_balance - target_balance, Decimal("0"))
        path_balance = current_balance
        if path_balance >= target_balance:
            target_breach_date = today
            target_breach_days = 0
        else:
            for day_offset, (path_date, daily_balance, _, _) in enumerate(
                daily_path_balances, start=1
            ):
                if daily_balance >= target_balance:
                    target_breach_date = path_date
                    target_breach_days = day_offset
                    break
        if projected_balance >= target_balance:
            target_status = "over_target"
        elif range_high > target_balance:
            target_status = "at_risk"
        else:
            target_status = "under_target"
        if target_status == "over_target":
            target_evidence_value = f"{target_excess_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)} above {target.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}% target"
        elif target_status == "at_risk":
            target_evidence_value = (
                f"{target_headroom_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)} central headroom; uncertainty range crosses "
                f"{target.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}% target"
            )
        else:
            target_evidence_value = (
                f"{target_headroom_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)} central headroom to "
                f"{target.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}% target"
            )
        target_evidence = [
            CardStatementProjectionEvidence(
                label="Utilization target runway",
                value=target_evidence_value,
                basis="Projected close compared with the issuer credit limit and the user target; this is not an issuer forecast.",
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Central target breach timing",
                        value=(
                            f"{target_breach_days} day(s) · {target_breach_date.isoformat()}"
                            if target_breach_days is not None and target_breach_date is not None
                            else "No central breach before projected close"
                        ),
                        basis=(
                            "Central pace path, planned payments, scheduled charges, and recurring "
                            "charge candidates; this is not an issuer warning."
                        ),
                    )
                ]
            ),
        ]

    sample_factor = min(Decimal(len(eligible_movements)) / Decimal("8"), Decimal("1"))
    cycle_factor = min(Decimal(elapsed_days) / Decimal("14"), Decimal("1"))
    confidence = Decimal(str(max(0.0, min(balance_confidence, 1.0))))
    confidence *= Decimal("0.55") + sample_factor * Decimal("0.25") + cycle_factor * Decimal("0.20")
    if historical_baseline is not None and len(historical_paces) >= 2:
        confidence += Decimal("0.05")
    confidence = min(confidence, Decimal("0.90"))

    daily_path: list[CardStatementProjectionPoint] = []
    target_balance_for_path = credit_limit * target / Decimal("100") if target is not None else None
    for day_offset, (path_date, daily_balance, event_amount, event_labels) in enumerate(
        daily_path_balances, start=1
    ):
        point_uncertainty = uncertainty * Decimal(day_offset) / Decimal(remaining_days)
        point_low = max(daily_balance - point_uncertainty - potential_pending_refund, Decimal("0"))
        point_high = daily_balance + point_uncertainty
        point_target_status: ProjectionTargetStatus = "unavailable"
        if target_balance_for_path is not None:
            if daily_balance >= target_balance_for_path:
                point_target_status = "over_target"
            elif point_high > target_balance_for_path:
                point_target_status = "at_risk"
            else:
                point_target_status = "under_target"
        if daily_balance >= credit_limit:
            point_credit_limit_status: ProjectionLimitStatus = "over_limit"
        elif point_high > credit_limit:
            point_credit_limit_status = "at_risk"
        else:
            point_credit_limit_status = "under_limit"
        daily_path.append(
            CardStatementProjectionPoint(
                date=path_date,
                days_from_today=day_offset,
                projected_balance=float(daily_balance.quantize(_MONEY, rounding=ROUND_HALF_UP)),
                range_low=float(point_low.quantize(_MONEY, rounding=ROUND_HALF_UP)),
                range_high=float(point_high.quantize(_MONEY, rounding=ROUND_HALF_UP)),
                projected_utilization_pct=float(
                    (daily_balance / credit_limit * Decimal("100")).quantize(Decimal("0.1"))
                ),
                target_status=point_target_status,
                credit_limit_status=point_credit_limit_status,
                event_amount=float(event_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)),
                event_labels=[label[:96] for label in event_labels[:5]],
            )
        )

    if credit_limit_status in {"over_limit", "at_risk"} or target_status == "over_target":
        next_state: ProjectionNextState = "reduce_spend_or_pay"
    elif remaining_days <= 7 and projected_balance > 0:
        next_state = "prepare_statement_payment"
    else:
        next_state = "monitor_cycle"

    return CardStatementProjectionResponse(
        status="available",
        as_of=today,
        projected_statement_date=projected_statement_date,
        projected_balance=float(projected_balance.quantize(_MONEY, rounding=ROUND_HALF_UP)),
        range_low=float(range_low.quantize(_MONEY, rounding=ROUND_HALF_UP)),
        range_high=float(range_high.quantize(_MONEY, rounding=ROUND_HALF_UP)),
        projected_utilization_pct=float(utilization.quantize(Decimal("0.1"))),
        confidence=float(confidence.quantize(Decimal("0.01"))),
        next_state=next_state,
        reason_codes=[
            (
                "historical_pace_blended"
                if calibration == "historical_blend"
                else "current_cycle_pace_extrapolated"
            ),
            "uncertainty_band_not_guarantee",
            *(["daily_projection_path"] if daily_path else []),
            *(["calendar_spending_seasonality_blended"] if seasonal_days_covered > 0 else []),
            *(["calendar_spending_seasonality_uncertainty"] if seasonal_uncertainty > 0 else []),
            *(["pending_refund_credit_uncertainty"] if potential_pending_refund > 0 else []),
            *(["recurring_charge_candidates_included"] if recurring_charges else []),
            *(
                ["recurring_amount_variability_uncertainty"]
                if recurring_amount_uncertainty > 0
                else []
            ),
            *(["recurring_date_variability_observed"] if recurring_date_variability else []),
            *(
                [
                    {
                        "under_target": "utilization_target_headroom",
                        "at_risk": "utilization_target_at_risk",
                        "over_target": "utilization_target_exceeded",
                        "unavailable": "utilization_target_unavailable",
                    }[target_status]
                ]
                if target is not None
                else []
            ),
            {
                "under_limit": "credit_limit_headroom",
                "at_risk": "credit_limit_at_risk",
                "over_limit": "credit_limit_exceeded",
                "unavailable": "credit_limit_unavailable",
            }[credit_limit_status],
        ],
        target_status=target_status,
        target_headroom_amount=(
            float(target_headroom_amount.quantize(_MONEY, rounding=ROUND_HALF_UP))
            if target_headroom_amount is not None
            else None
        ),
        target_excess_amount=(
            float(target_excess_amount.quantize(_MONEY, rounding=ROUND_HALF_UP))
            if target_excess_amount is not None
            else None
        ),
        target_breach_date=target_breach_date,
        target_breach_days=target_breach_days,
        credit_limit_status=credit_limit_status,
        credit_limit_headroom_amount=float(
            credit_limit_headroom_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)
        ),
        credit_limit_excess_amount=float(
            credit_limit_excess_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)
        ),
        credit_limit_breach_date=credit_limit_breach_date,
        credit_limit_breach_days=credit_limit_breach_days,
        calibration=calibration,
        historical_sample_count=len(historical_paces),
        seasonal_sample_count=seasonal_sample_count,
        seasonal_days_covered=seasonal_days_covered,
        known_future_payment_total=float(planned_payment_total.quantize(_MONEY)),
        known_future_charge_total=float(scheduled_charge_total.quantize(_MONEY)),
        known_future_recurring_charge_total=float(recurring_charge_total.quantize(_MONEY)),
        potential_pending_refund_total=float(potential_pending_refund.quantize(_MONEY)),
        recurring_charge_candidates=[
            CardRecurringChargeProjection(
                merchant=candidate.merchant,
                expected_date=candidate.expected_date,
                expected_amount=float(candidate.amount.quantize(_MONEY)),
                expected_amount_low=float(recurring_amount_ranges[index][0].quantize(_MONEY)),
                expected_amount_high=float(recurring_amount_ranges[index][1].quantize(_MONEY)),
                expected_date_low=recurring_date_ranges[index][0],
                expected_date_high=recurring_date_ranges[index][1],
                cadence=candidate.cadence,
                occurrences=candidate.occurrences,
                confidence=float(candidate.confidence.quantize(Decimal("0.01"))),
            )
            for index, candidate in enumerate(recurring_charges)
        ],
        daily_path=daily_path,
        evidence=[
            CardStatementProjectionEvidence(
                label="Current balance anchor",
                value=f"{current_balance.quantize(_MONEY)}",
                basis="PFIS current card position as of the projection date.",
            ),
            CardStatementProjectionEvidence(
                label="Observed cycle activity",
                value=f"{len(eligible_movements)} settled non-payment events over {elapsed_days} days",
                basis="Only settled, ledger-eligible card activity in the current cycle.",
            ),
            CardStatementProjectionEvidence(
                label="Days remaining",
                value=str(remaining_days),
                basis=f"The latest observed billing cycle is {cycle_days} days.",
            ),
            CardStatementProjectionEvidence(
                label="Daily projection path",
                value=f"{len(daily_path)} day(s) through projected close",
                basis=(
                    "Each point applies the current or seasonally adjusted daily pace, "
                    "known dated events, and a cumulative uncertainty band; it is not an issuer schedule."
                ),
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Historical pace calibration",
                        value=f"{len(historical_paces)} prior cycles",
                        basis="Current pace is blended with prior settled card-cycle pace.",
                    )
                ]
                if calibration == "historical_blend"
                else []
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Planned payment before close",
                        value=f"{planned_payment_total.quantize(_MONEY)}",
                        basis="User-recorded payment intention; not issuer settlement proof.",
                    )
                ]
                if planned_payment_total > 0
                else []
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Scheduled card charges",
                        value=f"{scheduled_charge_total.quantize(_MONEY)} across {len(scheduled_charges)} item(s)",
                        basis="Active card-EMI schedule evidence due before the projected close.",
                    )
                ]
                if scheduled_charge_total > 0
                else []
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Recurring charge candidates",
                        value=(
                            f"{recurring_charge_total.quantize(_MONEY)} across "
                            f"{len(recurring_charges)} merchant cadence(s)"
                        ),
                        basis=(
                            "Early or mature settled merchant cadence observed on this card; "
                            "expected dates and amounts are estimates, not issuer-confirmed charges."
                        ),
                    )
                ]
                if recurring_charge_total > 0
                else []
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Recurring amount variability",
                        value=(
                            f"up to {recurring_amount_uncertainty.quantize(_MONEY, rounding=ROUND_HALF_UP)} "
                            f"range movement across "
                            f"{sum(1 for low, high in recurring_amount_ranges if high > low)} candidate(s)"
                        ),
                        basis=(
                            "The central recurring amount remains the observed average; only bounded "
                            "historical amount movement widens the estimate range."
                        ),
                    )
                ]
                if recurring_amount_uncertainty > 0
                else []
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Recurring timing envelope",
                        value=(
                            f"{len(recurring_date_variability)} candidate(s) with up to "
                            f"{max((high - low).days for low, high in recurring_date_variability)} day(s) "
                            "of observed timing movement"
                        ),
                        basis=(
                            "The central expected date remains the median cadence path; the displayed "
                            "window reflects observed interval variation and is not an issuer promise."
                        ),
                    )
                ]
                if recurring_date_variability
                else []
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Calendar spending pattern",
                        value=(
                            f"{seasonal_days_covered} future day(s) across "
                            f"{seasonal_sample_count} prior cycle(s)"
                        ),
                        basis=(
                            "Settled liability movement aligned by statement-cycle day; "
                            "the profile is shrunk toward the current pace and is not an issuer forecast."
                        ),
                    )
                ]
                if seasonal_days_covered > 0
                else []
            ),
            *(
                [
                    CardStatementProjectionEvidence(
                        label="Pending refund potential credit",
                        value=f"up to {potential_pending_refund.quantize(_MONEY, rounding=ROUND_HALF_UP)}",
                        basis=(
                            "Explicit pending refund lifecycle evidence widens only the lower bound; "
                            "the central estimate excludes it until settlement is observed."
                        ),
                    )
                ]
                if potential_pending_refund > 0
                else []
            ),
            *target_evidence,
            *credit_limit_evidence,
        ],
        ruleset_version=RULESET_VERSION,
    )


def _unavailable(
    status: ProjectionStatus,
    reason_code: str,
    *,
    projected_statement_date: date | None = None,
    as_of: date | None = None,
) -> CardStatementProjectionResponse:
    return CardStatementProjectionResponse(
        status=status,
        as_of=as_of,
        projected_statement_date=projected_statement_date,
        next_state="review_evidence",
        reason_codes=[reason_code],
        ruleset_version=RULESET_VERSION,
    )
