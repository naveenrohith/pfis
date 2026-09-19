"""Deterministic, read-only routing advice for a hypothetical card spend.

This service deliberately models a proposed *purchase* rather than a card bill
payment.  Reward inputs are user-entered assumptions and are never interpreted
as issuer facts.  The service only ranks active, user-owned cards and never
writes transactions, payment intents, or preferences.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.schemas.financial_position import (
    CardOverviewResponse,
    CardSpendRoutingOption,
    CardSpendRoutingPriority,
    CardSpendRoutingRequest,
    CardSpendRoutingResponse,
)
from app.services.financial_clock import user_financial_today
from app.services.financial_position_service import FinancialPositionService
from app.services.ledger_currency import get_ledger_currency

RULESET_VERSION = "pfis-card-spend-routing-1"
_MONEY = Decimal("0.01")
_PERCENT = Decimal("0.01")
_UNSAFE_BALANCE_STATUSES = {
    "needs_observation",
    "stale",
    "incomplete",
    "needs_review",
}

RoutingStatus = Literal[
    "recommended",
    "eligible",
    "over_target",
    "over_limit",
    "needs_review",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class _RewardRule:
    label: str | None
    rate_pct: Decimal
    category: str | None
    source_index: int


@dataclass(frozen=True, slots=True)
class _RewardSelection:
    label: str | None
    rate_pct: Decimal | None
    status: Literal["explicit", "no_rule", "category_mismatch", "invalid_rule"]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RoutingCandidate:
    option: CardSpendRoutingOption
    eligible: bool
    target_rank: int
    projected_utilization: Decimal | None
    reward_rate: Decimal | None


class CardSpendRoutingService:
    """Build a bounded purchase-routing preview across active credit cards."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def preview(
        self, user_id: str, data: CardSpendRoutingRequest
    ) -> CardSpendRoutingResponse:
        as_of = await user_financial_today(self.db, user_id)
        ledger_currency = await get_ledger_currency(self.db, user_id)
        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount)
                    .where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                        FinancialAccount.account_type == "credit_card",
                    )
                    .order_by(FinancialAccount.institution_name, FinancialAccount.id)
                )
            ).all()
        )
        if not accounts:
            return CardSpendRoutingResponse(
                as_of=as_of,
                amount=float(_money(data.amount)),
                category=data.category,
                priority=data.priority,
                currency=ledger_currency,
                state="no_active_cards",
                confidence=0.0,
                reason_codes=["no_active_cards"],
                assumptions=self._root_assumptions(),
                ruleset_version=RULESET_VERSION,
            )

        position_service = FinancialPositionService(self.db)
        candidates: list[_RoutingCandidate] = []
        for account in accounts:
            overview = await position_service.card_overview(user_id, account.id)
            candidates.append(
                _build_candidate(
                    account,
                    overview,
                    amount=data.amount,
                    category=data.category,
                    ledger_currency=ledger_currency,
                )
            )

        ordered = _rank_candidates(candidates, data.priority)
        recommendation_index = next(
            (index for index, candidate in enumerate(ordered) if candidate.eligible),
            None,
        )
        options: list[CardSpendRoutingOption] = []
        for index, candidate in enumerate(ordered):
            if index == recommendation_index:
                options.append(
                    candidate.option.model_copy(
                        update={
                            "status": "recommended",
                            "reason_codes": list(
                                dict.fromkeys(
                                    [
                                        *candidate.option.reason_codes,
                                        "recommended_by_explicit_priority",
                                    ]
                                )
                            ),
                        }
                    )
                )
            else:
                options.append(candidate.option)

        review_count = sum(option.status == "needs_review" for option in options)
        recommended_card_id = (
            options[recommendation_index].financial_account_id
            if recommendation_index is not None
            else None
        )
        if recommended_card_id is not None:
            state: Literal["ready", "partial", "needs_review"] = (
                "partial" if review_count else "ready"
            )
        else:
            state = "needs_review"
        root_reasons = ["routing_preview_composed"]
        if recommended_card_id is not None:
            root_reasons.append("recommended_card_present")
        else:
            root_reasons.append("no_card_with_hard_limit_headroom")
        if review_count:
            root_reasons.append("partial_card_evidence")
        if data.category is not None:
            root_reasons.append("category_filter_applied")
        if any(option.reward_status == "explicit" for option in options):
            root_reasons.append("explicit_reward_rule_available")
        else:
            root_reasons.append("no_usable_reward_rule")
        usable_confidence = [
            option.confidence
            for option in options
            if option.status in {"recommended", "eligible", "over_target"}
        ]
        confidence = min(usable_confidence) if usable_confidence else 0.0
        return CardSpendRoutingResponse(
            as_of=as_of,
            amount=float(_money(data.amount)),
            category=data.category,
            priority=data.priority,
            currency=ledger_currency,
            state=state,
            recommended_card_id=recommended_card_id,
            options=options,
            confidence=confidence,
            reason_codes=list(dict.fromkeys(root_reasons)),
            assumptions=self._root_assumptions(),
            ruleset_version=RULESET_VERSION,
        )

    @staticmethod
    def _root_assumptions() -> list[str]:
        return [
            "This is a read-only purchase-routing preview; PFIS does not create a transaction, reserve cash, or submit a payment.",
            "Current outstanding uses a verified provider position when available and otherwise a bounded ledger estimate.",
            "Projected statement balances are PFIS estimates inside the observed billing cycle, not issuer guarantees.",
            "Reward estimates use only explicit user-entered rules and apply to the hypothetical purchase, not to card bill payments.",
            "A recommendation stays below the observed or estimated hard credit limit; authorization and issuer policy remain outside PFIS.",
        ]


def _build_candidate(
    account: FinancialAccount,
    overview: CardOverviewResponse,
    *,
    amount: Decimal,
    category: str | None,
    ledger_currency: str,
) -> _RoutingCandidate:
    reason_codes: list[str] = []
    assumptions: list[str] = []
    current, source_kind = _current_position(overview)
    credit_limit = _credit_limit(overview)
    reward = _select_reward(overview.reward_rules, category)
    reason_codes.extend(reward.reason_codes)
    if reward.status == "explicit":
        assumptions.append(
            "Reward rate is an explicit user-entered assumption, not an issuer quote."
        )
    elif reward.status == "category_mismatch":
        assumptions.append("No category-matching user reward rule was applied.")
    elif reward.status == "invalid_rule":
        assumptions.append("Invalid user reward rules were ignored and did not influence ranking.")

    if source_kind == "provider":
        reason_codes.append("provider_current_outstanding_used")
        assumptions.append("Current outstanding comes from the latest typed provider observation.")
    elif source_kind == "ledger_estimate":
        reason_codes.append("ledger_estimate_current_outstanding_used")
        assumptions.append(
            "Current outstanding is a settled ledger roll-forward, not a live issuer balance."
        )
    else:
        reason_codes.append("current_outstanding_unavailable")

    if credit_limit is None:
        reason_codes.append("credit_limit_unavailable")
    elif overview.provider_credit_limit is not None:
        reason_codes.append("provider_credit_limit_used")
    else:
        reason_codes.append("statement_credit_limit_used")

    projection = overview.next_statement_projection
    projection_available = (
        projection.status == "available" and projection.projected_balance is not None
    )
    projected_base = Decimal(str(projection.projected_balance)) if projection_available else current
    if projection_available:
        reason_codes.append("statement_projection_available")
        assumptions.append(
            "Projected close balance includes the hypothetical amount on the current PFIS statement trajectory."
        )
    else:
        reason_codes.append("statement_projection_unavailable")
        assumptions.append(
            "No usable statement projection was available; the immediate balance is used as a conservative proxy."
        )

    currency_matches = account.currency == ledger_currency
    if not currency_matches:
        reason_codes.append("account_currency_mismatch")
        assumptions.append(
            "This card is excluded because its account currency does not match the user's ledger currency."
        )

    current_after = current + amount if current is not None else None
    projected_after = projected_base + amount if projected_base is not None else None
    current_utilization = _utilization(current, credit_limit)
    projected_utilization = _utilization(projected_after, credit_limit)
    target = _decimal(overview.utilization_target_pct)
    target_amount = (
        credit_limit * target / Decimal("100")
        if credit_limit is not None and target is not None
        else None
    )
    target_headroom = (
        target_amount - projected_after
        if target_amount is not None and projected_after is not None
        else None
    )
    hard_headroom = (
        credit_limit - current_after
        if credit_limit is not None and current_after is not None
        else None
    )
    hard_excess = (hard_headroom is not None and hard_headroom < 0) or (
        credit_limit is not None and projected_after is not None and projected_after > credit_limit
    )
    balance_needs_review = overview.balance_status in _UNSAFE_BALANCE_STATUSES

    critical_reasons: list[str] = []
    if current is None:
        critical_reasons.append("current_outstanding_missing")
    if credit_limit is None or credit_limit <= 0:
        critical_reasons.append("credit_limit_missing")
    if balance_needs_review:
        critical_reasons.append("balance_position_needs_review")
    if not currency_matches:
        critical_reasons.append("currency_mismatch")
    if current is not None and current < 0:
        critical_reasons.append("negative_current_outstanding")
    reason_codes.extend(critical_reasons)

    utilization_status: Literal[
        "within_target", "over_target", "within_limit", "over_limit", "unavailable"
    ]
    status: RoutingStatus
    eligible = False
    if critical_reasons:
        utilization_status = "unavailable"
        status = "needs_review"
    elif hard_excess:
        utilization_status = "over_limit"
        status = "over_limit"
        reason_codes.append("hypothetical_spend_exceeds_credit_limit")
        if (
            credit_limit is not None
            and projected_after is not None
            and projected_after > credit_limit
            and (hard_headroom is None or hard_headroom >= 0)
        ):
            reason_codes.append("projected_statement_exceeds_credit_limit")
    elif (
        target_amount is not None
        and projected_after is not None
        and projected_after > target_amount
    ):
        utilization_status = "over_target"
        status = "over_target"
        eligible = True
        reason_codes.append("hypothetical_spend_exceeds_utilization_target")
    elif target_amount is not None:
        utilization_status = "within_target"
        status = "eligible"
        eligible = True
        reason_codes.append("hypothetical_spend_within_utilization_target")
    else:
        utilization_status = "within_limit"
        status = "eligible"
        eligible = True
        reason_codes.append("hypothetical_spend_within_credit_limit")

    reward_rate = reward.rate_pct
    estimated_reward = (
        _money(amount * reward_rate / Decimal("100")) if reward_rate is not None else None
    )
    if reward_rate is not None:
        reason_codes.append("estimated_reward_from_explicit_rule")

    confidence = _confidence(
        overview,
        source_kind=source_kind,
        credit_limit=credit_limit,
        projection_available=projection_available,
        critical=bool(critical_reasons),
    )
    if status == "over_target":
        confidence = min(confidence, 0.75)
    if status == "over_limit":
        confidence = min(confidence, 0.85)
    option = CardSpendRoutingOption(
        financial_account_id=account.id,
        label=account.institution_name.strip() or "Credit card",
        currency=account.currency,
        status=status,
        current_outstanding=_float_or_none(current),
        credit_limit=_float_or_none(credit_limit),
        current_utilization_pct=_float_or_none(current_utilization),
        projected_statement_balance=_float_or_none(projected_after),
        projected_statement_utilization_pct=_float_or_none(projected_utilization),
        utilization_status=utilization_status,
        utilization_target_pct=_float_or_none(target),
        target_headroom_amount=_float_or_none(target_headroom),
        hard_headroom_amount=_float_or_none(hard_headroom),
        reward_label=reward.label,
        reward_rate_pct=_float_or_none(reward_rate),
        estimated_reward=_float_or_none(estimated_reward),
        reward_status=reward.status,
        source_kind=source_kind,
        confidence=confidence,
        reason_codes=list(dict.fromkeys(reason_codes)),
        assumptions=list(dict.fromkeys(assumptions)),
    )
    return _RoutingCandidate(
        option=option,
        eligible=eligible,
        target_rank=_target_rank(utilization_status),
        projected_utilization=projected_utilization,
        reward_rate=reward_rate,
    )


def _rank_candidates(
    candidates: list[_RoutingCandidate], priority: CardSpendRoutingPriority
) -> list[_RoutingCandidate]:
    def projected_key(item: _RoutingCandidate) -> Decimal:
        return (
            item.projected_utilization
            if item.projected_utilization is not None
            else Decimal("1000000000")
        )

    def reward_key(item: _RoutingCandidate) -> Decimal:
        return -(item.reward_rate if item.reward_rate is not None else Decimal("-1"))

    def eligibility_key(item: _RoutingCandidate) -> int:
        return 0 if item.eligible else 1

    if priority == "utilization_safety":

        def key(item: _RoutingCandidate):
            return (
                eligibility_key(item),
                item.target_rank,
                projected_key(item),
                reward_key(item),
                item.option.financial_account_id,
            )

    elif priority == "rewards":

        def key(item: _RoutingCandidate):
            return (
                eligibility_key(item),
                reward_key(item),
                item.target_rank,
                projected_key(item),
                item.option.financial_account_id,
            )

    else:

        def key(item: _RoutingCandidate):
            return (
                eligibility_key(item),
                item.target_rank,
                reward_key(item),
                projected_key(item),
                item.option.financial_account_id,
            )

    return sorted(candidates, key=key)


def _select_reward(raw_rules: object, category: str | None) -> _RewardSelection:
    rules: list[_RewardRule] = []
    invalid_count = 0
    category_specific_count = 0
    for index, raw_rule in enumerate(raw_rules if isinstance(raw_rules, list) else []):
        if not isinstance(raw_rule, dict):
            invalid_count += 1
            continue
        try:
            rate = _parse_reward_rate(raw_rule.get("rate_pct"))
            label_value = raw_rule.get("label")
            category_value = raw_rule.get("category")
            if label_value is not None and not isinstance(label_value, str):
                raise ValueError("reward label must be text")
            if category_value is not None and not isinstance(category_value, str):
                raise ValueError("reward category must be text")
            label = label_value.strip() if isinstance(label_value, str) else None
            normalized_category = (
                category_value.strip().casefold()
                if isinstance(category_value, str) and category_value.strip()
                else None
            )
            if normalized_category is not None:
                category_specific_count += 1
            rules.append(
                _RewardRule(
                    label=label or None,
                    rate_pct=rate,
                    category=normalized_category,
                    source_index=index,
                )
            )
        except (InvalidOperation, TypeError, ValueError):
            invalid_count += 1

    normalized_request_category = category.strip().casefold() if category else None
    matches: list[_RewardRule] = []
    if normalized_request_category:
        matches = [rule for rule in rules if rule.category == normalized_request_category] or [
            rule for rule in rules if rule.category is None
        ]
    elif rules:
        matches = [rule for rule in rules if rule.category is None]

    reason_codes: list[str] = []
    if invalid_count:
        reason_codes.append("invalid_reward_rule_ignored")
    if matches:
        best = sorted(
            matches,
            key=lambda rule: (-rule.rate_pct, rule.label or "", rule.source_index),
        )[0]
        if sum(rule.rate_pct == best.rate_pct for rule in matches) > 1:
            reason_codes.append("multiple_reward_rules_best_rate")
        if normalized_request_category and best.category == normalized_request_category:
            reason_codes.append("reward_rule_category_match")
        elif best.category is None:
            reason_codes.append("reward_rule_wildcard_match")
        reason_codes.append("reward_rule_explicit")
        return _RewardSelection(
            label=best.label,
            rate_pct=best.rate_pct,
            status="explicit",
            reason_codes=tuple(dict.fromkeys(reason_codes)),
        )
    if invalid_count and not rules:
        reason_codes.append("all_reward_rules_invalid")
        return _RewardSelection(
            label=None,
            rate_pct=None,
            status="invalid_rule",
            reason_codes=tuple(dict.fromkeys(reason_codes)),
        )
    if normalized_request_category and category_specific_count:
        reason_codes.append("reward_rule_category_mismatch")
        return _RewardSelection(
            label=None,
            rate_pct=None,
            status="category_mismatch",
            reason_codes=tuple(dict.fromkeys(reason_codes)),
        )
    reason_codes.append("no_reward_rule")
    return _RewardSelection(
        label=None,
        rate_pct=None,
        status="no_rule",
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _parse_reward_rate(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("reward rate must be numeric")
    rate = Decimal(str(value))
    if not rate.is_finite() or rate < 0 or rate > 100:
        raise ValueError("reward rate must be between 0 and 100")
    return rate


def _current_position(
    overview: CardOverviewResponse,
) -> tuple[Decimal | None, Literal["provider", "ledger_estimate", "none"]]:
    if overview.provider_current_outstanding is not None:
        return _decimal(overview.provider_current_outstanding), "provider"
    if overview.estimated_current_balance is not None:
        return _decimal(overview.estimated_current_balance), "ledger_estimate"
    return None, "none"


def _credit_limit(overview: CardOverviewResponse) -> Decimal | None:
    provider_limit = _decimal(overview.provider_credit_limit)
    if provider_limit is not None and provider_limit > 0:
        return provider_limit
    statement_limit = _decimal(overview.credit_limit)
    if statement_limit is not None and statement_limit > 0:
        return statement_limit
    return None


def _utilization(value: Decimal | None, limit: Decimal | None) -> Decimal | None:
    if value is None or limit is None or limit <= 0:
        return None
    return (value / limit * Decimal("100")).quantize(_PERCENT, rounding=ROUND_HALF_UP)


def _confidence(
    overview: CardOverviewResponse,
    *,
    source_kind: Literal["provider", "ledger_estimate", "none"],
    credit_limit: Decimal | None,
    projection_available: bool,
    critical: bool,
) -> float:
    if critical or source_kind == "none" or credit_limit is None:
        return 0.0
    value = 0.88 if source_kind == "provider" else max(0.35, min(0.80, overview.balance_confidence))
    if projection_available:
        value = min(value, max(0.35, overview.next_statement_projection.confidence))
    if overview.balance_status == "estimated":
        value = min(value, 0.70)
    return round(value, 2)


def _target_rank(
    utilization_status: Literal[
        "within_target", "over_target", "within_limit", "over_limit", "unavailable"
    ],
) -> int:
    return {
        "within_target": 0,
        "within_limit": 1,
        "over_target": 2,
        "over_limit": 3,
        "unavailable": 4,
    }[utilization_status]


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _float_or_none(value: Decimal | None) -> float | None:
    return float(_money(value)) if value is not None else None
