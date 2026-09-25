"""Deterministic, evidence-backed explanations for embedded AI surfaces.

Supplied aggregates are treated as claims. When a user scope and period are
available they are checked against existing PFIS read models; otherwise they
are returned as explicitly unverified. No LLM, raw email body, or secret is
used or echoed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.intelligence import (
    CategoryIntelligenceItem,
    EvidenceItem,
    ExplainAction,
    ExplainEvidenceStatus,
    ExplainMetric,
    ExplainRequest,
    ExplainResponse,
    ExplainSurfaceKind,
    FinancialHealthScore,
    MerchantSummary,
    SourceCoverageResponse,
)
from app.services.intelligence_service import IntelligenceService

RULESET_VERSION = "pfis-explain-1"
MAX_METRICS = 12
MAX_ACTIONS = 4
MAX_DRIVERS = 6
MAX_TEXT_VALUE = 80
SAFETY_NOTE = (
    "Uses aggregate dashboard context and owned PFIS read models only; raw email bodies, "
    "tokens, and secrets are not included."
)

_SURFACE_ALIASES: dict[str, ExplainSurfaceKind] = {
    "category": "category",
    "categories": "category",
    "budget": "budget",
    "budgets": "budget",
    "merchant": "merchant",
    "merchants": "merchant",
    "financial_health": "financial_health",
    "health": "financial_health",
    "health_score": "financial_health",
    "cash_flow": "cash_flow",
    "cashflow": "cash_flow",
}
_SENSITIVE_KEY = re.compile(
    r"token|secret|password|passwd|otp|oauth|cookie|session|credential|api_?key|"
    r"authorization|raw_?email|email_?body|body|email|phone|account_?number|card_?number"
)

# Kind -> (validator, comparison tolerance)
_KINDS: dict[str, tuple[Callable[[float], bool], float]] = {
    "amount": (lambda v: v >= 0, 0.01),
    "count": (lambda v: v >= 0 and float(v).is_integer(), 0.0),
    "score": (lambda v: 0 <= v <= 100, 0.5),
    "usage_pct": (lambda v: v >= 0, 0.1),
    "change_pct": (lambda v: v >= -100, 0.1),
    "number": (lambda v: True, 0.1),
}


@dataclass(frozen=True)
class _Spec:
    label: str
    kind: str


_CATEGORY_SPECS = {
    "total_spend": _Spec("Total spend", "amount"),
    "transaction_count": _Spec("Transactions", "count"),
    "month_change_pct": _Spec("Change vs previous month %", "change_pct"),
    "budget_limit": _Spec("Monthly limit", "amount"),
    "budget_usage_pct": _Spec("Budget usage %", "usage_pct"),
}
_SPECS: dict[ExplainSurfaceKind, dict[str, _Spec]] = {
    "category": _CATEGORY_SPECS,
    "budget": _CATEGORY_SPECS,
    "merchant": {
        "total_spend": _Spec("Total spend", "amount"),
        "transaction_count": _Spec("Transactions", "count"),
        "avg_spend": _Spec("Average spend", "amount"),
        "month_change_pct": _Spec("Change vs previous month %", "change_pct"),
    },
    "financial_health": {
        "score": _Spec("Health score", "score"),
        "monthly_stability": _Spec("Monthly stability", "score"),
        "data_confidence": _Spec("Data confidence", "score"),
        "source_coverage_score": _Spec("Source coverage score", "score"),
        "savings_rate": _Spec("Savings rate %", "number"),
        "budget_adherence": _Spec("Budget adherence %", "usage_pct"),
        "review_cleanliness": _Spec("Review cleanliness", "score"),
    },
    "cash_flow": {},
    "general": {},
}
_ALIASES = {"spent": "total_spend", "spend": "total_spend", "limit": "budget_limit"}


def normalize_surface(surface: str) -> ExplainSurfaceKind:
    key = re.sub(r"[\s\-]+", "_", surface.strip().casefold())
    return _SURFACE_ALIASES.get(key, "general")


def _format(value: float | int | str) -> str:
    if isinstance(value, str):
        return value
    number = float(value)
    return str(int(number)) if number.is_integer() else str(round(number, 2))


def _label(key: str) -> str:
    return key.replace("_", " ").strip().capitalize() or key


@dataclass
class _Subject:
    """Verified read-model values for the explained subject."""

    values: dict[str, float | None]
    evidence: list[EvidenceItem]
    extra: dict[str, Any]


class ExplanationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.intelligence = IntelligenceService(db)

    async def explain(self, data: ExplainRequest, user_id: str | None) -> ExplainResponse:
        kind = normalize_surface(data.surface)
        specs = _SPECS[kind]
        missing: list[str] = []
        assumptions: list[str] = [
            "Supplied figures are treated as claims; only values matched against PFIS read "
            "models are marked verified.",
        ]
        evidence: list[EvidenceItem] = []
        coverage: SourceCoverageResponse | None = None
        subject: _Subject | None = None
        health: FinancialHealthScore | None = None
        month, year = data.month, data.year
        has_period = month is not None and year is not None

        if user_id is None:
            missing.append(
                "No user scope was supplied, so figures were not checked against the owned "
                "ledger and source coverage is unknown."
            )
        else:
            coverage = await self.intelligence.source_coverage(user_id)
            assumptions.extend(coverage.assumptions)
            if not specs:
                missing.append(
                    f"PFIS has no verification read model for the {kind.replace('_', ' ')} "
                    "surface; supplied figures remain unverified."
                )
            elif month is None or year is None:
                missing.append(
                    "month and year were not supplied, so period-specific aggregates were "
                    "not verified."
                )
            else:
                if kind == "financial_health":
                    health = await self.intelligence.financial_health(user_id, month, year)
                    subject = self._health_subject(health)
                elif kind in {"category", "budget"}:
                    subject = await self._category_subject(user_id, month, year, data)
                elif kind == "merchant":
                    subject = await self._merchant_subject(user_id, month, year, data)
                if subject is None:
                    missing.append(
                        f"No owned {kind} record matching this surface was found for "
                        f"{month:02d}/{year}; supplied figures are unverified."
                    )
                else:
                    evidence.extend(subject.evidence)

        metrics, skipped = self._qualify_metrics(data.metrics or {}, specs, subject)
        if skipped:
            missing.append(f"{skipped} additional metric(s) exceeded the limit and were ignored.")
        if data.description:
            assumptions.append("The surface description is client-supplied context, not evidence.")
        if coverage is not None:
            for source in coverage.sources:
                if source.completeness == "unknown":
                    missing.append(f"{source.label} completeness is unknown.")

        status = self._evidence_status(metrics, subject is not None)
        actions = self._actions(kind, data, metrics, subject, health, coverage, user_id)
        drivers = self._drivers(metrics, subject)

        return ExplainResponse(
            surface=data.surface,
            summary=self._summary(data.title, status, metrics, coverage),
            drivers=drivers[:MAX_DRIVERS],
            next_actions=[action.label for action in actions],
            safety_note=SAFETY_NOTE,
            ruleset_version=RULESET_VERSION,
            surface_kind=kind,
            evidence_status=status,
            source="pfis_read_model" if subject is not None else "client_supplied",
            as_of=coverage.as_of if coverage is not None else None,
            period_month=month if has_period else None,
            period_year=year if has_period else None,
            metrics=metrics,
            evidence=evidence,
            coverage_score=coverage.overall_score if coverage is not None else None,
            coverage=coverage.sources if coverage is not None else [],
            assumptions=assumptions,
            missing_evidence=missing,
            actions=actions,
        )

    @staticmethod
    def _health_subject(health: FinancialHealthScore) -> _Subject:
        values: dict[str, float | None] = {
            "score": health.score,
            "monthly_stability": health.monthly_stability,
            "data_confidence": health.data_confidence,
            "source_coverage_score": health.source_coverage_score,
            "savings_rate": health.savings_rate,
            "budget_adherence": health.budget_adherence,
            "review_cleanliness": health.review_cleanliness,
        }
        return _Subject(
            values=values,
            evidence=[
                EvidenceItem(label="Health ruleset", value=health.ruleset_version),
                EvidenceItem(
                    label="Data confidence ruleset",
                    value=health.data_confidence_ruleset_version,
                ),
                EvidenceItem(label="Data sufficiency", value=health.data_sufficiency),
            ],
            extra={},
        )

    async def _category_subject(
        self, user_id: str, month: int, year: int, data: ExplainRequest
    ) -> _Subject | None:
        response = await self.intelligence.category_intelligence(user_id, month, year)
        match: CategoryIntelligenceItem | None = None
        title = data.title.strip().casefold()
        for item in response.categories:
            if data.subject_id is not None:
                if item.category_id == data.subject_id:
                    match = item
                    break
            elif item.name.casefold() == title:
                match = item
                break
        if match is None:
            return None
        top = match.top_merchants[0] if match.top_merchants else None
        return _Subject(
            values={
                "total_spend": match.total_spend,
                "transaction_count": match.transaction_count,
                "month_change_pct": match.month_change_pct,
                "budget_limit": match.budget_limit,
                "budget_usage_pct": match.budget_usage_pct,
            },
            evidence=[
                EvidenceItem(label="Read model", value="Category intelligence"),
                EvidenceItem(label="Category", value=match.name),
                EvidenceItem(label="Transactions", value=str(match.transaction_count)),
                EvidenceItem(
                    label="Budget limit",
                    value=_format(match.budget_limit) if match.budget_limit else "Not set",
                ),
            ],
            extra={"top_merchant": top.name if top else None},
        )

    async def _merchant_subject(
        self, user_id: str, month: int, year: int, data: ExplainRequest
    ) -> _Subject | None:
        merchants = await self.intelligence.list_merchants(user_id, month, year)
        match: MerchantSummary | None = None
        title = data.title.strip().casefold()
        for item in merchants:
            if data.subject_id is not None:
                if item.merchant_key == data.subject_id:
                    match = item
                    break
            elif item.name.casefold() == title:
                match = item
                break
        if match is None:
            return None
        return _Subject(
            values={
                "total_spend": match.total_spend,
                "transaction_count": match.transaction_count,
                "avg_spend": match.avg_spend,
                "month_change_pct": match.month_change_pct,
            },
            evidence=[
                EvidenceItem(label="Read model", value="Merchant intelligence"),
                EvidenceItem(label="Merchant", value=match.name),
                EvidenceItem(label="Transactions", value=str(match.transaction_count)),
                EvidenceItem(label="Category", value=match.category or "Uncategorized"),
                EvidenceItem(label="Recurrence", value=match.recurrence_status),
            ],
            extra={"category": match.category, "recurrence_status": match.recurrence_status},
        )

    @staticmethod
    def _qualify_metrics(
        raw: dict, specs: dict[str, _Spec], subject: _Subject | None
    ) -> tuple[list[ExplainMetric], int]:
        items = list(raw.items())
        out: list[ExplainMetric] = []
        for raw_key, value in items[:MAX_METRICS]:
            key = str(raw_key)[:MAX_TEXT_VALUE]
            canonical = _ALIASES.get(key.casefold(), key.casefold())
            spec = specs.get(canonical)
            label = spec.label if spec else _label(key)
            if _SENSITIVE_KEY.search(key.casefold()):
                out.append(
                    ExplainMetric(
                        key=key,
                        label=label,
                        status="withheld",
                        note="Value withheld because the key may carry sensitive data.",
                    )
                )
                continue
            if value is None or value == "":
                continue
            if isinstance(value, dict | list | tuple):
                out.append(
                    ExplainMetric(
                        key=key,
                        label=label,
                        status="invalid",
                        note="Nested values are not accepted as aggregates.",
                    )
                )
                continue
            if spec is None:
                supplied = (
                    _format(value)
                    if isinstance(value, int | float) and not isinstance(value, bool)
                    else str(value)[:MAX_TEXT_VALUE]
                )
                out.append(
                    ExplainMetric(
                        key=key,
                        label=label,
                        supplied_value=supplied,
                        status="unverified",
                        note="Not a recognized aggregate for this surface; shown as reported.",
                    )
                )
                continue
            out.append(ExplanationService._qualify_known(key, value, spec, canonical, subject))
        return out, max(0, len(items) - MAX_METRICS)

    @staticmethod
    def _qualify_known(
        key: str, value: Any, spec: _Spec, canonical: str, subject: _Subject | None
    ) -> ExplainMetric:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return ExplainMetric(
                key=key,
                label=spec.label,
                supplied_value=str(value)[:MAX_TEXT_VALUE],
                status="invalid",
                note="Expected a numeric aggregate.",
            )
        number = float(value)
        validator, tolerance = _KINDS[spec.kind]
        if not math.isfinite(number) or not validator(number):
            return ExplainMetric(
                key=key,
                label=spec.label,
                supplied_value=_format(value) if math.isfinite(number) else str(value),
                status="invalid",
                note=f"Outside the valid range for a {spec.kind.replace('_', ' ')} value.",
            )
        supplied = _format(number)
        if subject is None:
            return ExplainMetric(
                key=key,
                label=spec.label,
                supplied_value=supplied,
                status="unverified",
                note="Structurally valid but not checked against PFIS read models.",
            )
        verified = subject.values.get(canonical)
        if verified is None:
            return ExplainMetric(
                key=key,
                label=spec.label,
                supplied_value=supplied,
                status="mismatch",
                note="PFIS has no value for this aggregate in the selected period.",
            )
        if abs(float(verified) - number) <= tolerance:
            return ExplainMetric(
                key=key,
                label=spec.label,
                supplied_value=supplied,
                verified_value=_format(verified),
                status="verified",
                note="Matches the current PFIS read model.",
            )
        return ExplainMetric(
            key=key,
            label=spec.label,
            supplied_value=supplied,
            verified_value=_format(verified),
            status="mismatch",
            note="Differs from the current PFIS read model; the verified value is authoritative.",
        )

    @staticmethod
    def _evidence_status(
        metrics: list[ExplainMetric], subject_found: bool
    ) -> ExplainEvidenceStatus:
        statuses = {metric.status for metric in metrics}
        if "mismatch" in statuses:
            return "conflict"
        if not subject_found:
            return "unverified"
        checked = [m for m in metrics if m.status in {"verified", "unverified", "invalid"}]
        if checked and all(m.status == "verified" for m in checked):
            return "verified"
        return "partial"

    @staticmethod
    def _drivers(metrics: list[ExplainMetric], subject: _Subject | None) -> list[str]:
        drivers: list[str] = []
        for metric in metrics:
            if metric.status == "verified":
                drivers.append(f"{metric.label}: {metric.verified_value} (verified)")
            elif metric.status == "mismatch" and metric.verified_value is not None:
                drivers.append(
                    f"{metric.label}: {metric.verified_value} per PFIS "
                    f"(supplied {metric.supplied_value})"
                )
            elif metric.status == "unverified":
                drivers.append(f"{metric.label}: {metric.supplied_value} (unverified)")
        if subject is not None and subject.extra.get("top_merchant"):
            drivers.append(f"Largest merchant: {subject.extra['top_merchant']}")
        return drivers

    @staticmethod
    def _summary(
        title: str,
        status: ExplainEvidenceStatus,
        metrics: list[ExplainMetric],
        coverage: SourceCoverageResponse | None,
    ) -> str:
        verified = sum(1 for m in metrics if m.status == "verified")
        numeric = sum(1 for m in metrics if m.status != "withheld")
        if status == "conflict":
            core = f"{title}: some supplied figures differ from the current PFIS ledger."
        elif numeric == 0:
            core = f"{title}: no figures were supplied to verify."
        elif status == "verified":
            core = f"{title}: {verified} of {numeric} figure(s) verified against the PFIS ledger."
        elif status == "partial":
            core = f"{title}: {verified} of {numeric} figure(s) verified; the rest are qualified."
        else:
            core = f"{title}: figures are shown as supplied and have not been verified."
        if coverage is not None:
            core += f" Source coverage score {coverage.overall_score}/100."
        return core

    @staticmethod
    def _actions(
        kind: ExplainSurfaceKind,
        data: ExplainRequest,
        metrics: list[ExplainMetric],
        subject: _Subject | None,
        health: FinancialHealthScore | None,
        coverage: SourceCoverageResponse | None,
        user_id: str | None,
    ) -> list[ExplainAction]:
        actions: list[ExplainAction] = []

        def add(label: str, reason: str, target: str | None = None) -> None:
            if len(actions) < MAX_ACTIONS and all(a.label != label for a in actions):
                actions.append(ExplainAction(label=label, reason=reason, target=target))

        if any(m.status == "mismatch" for m in metrics):
            add(
                "Refresh this view before acting on it.",
                "Supplied figures differ from the current PFIS ledger.",
            )

        values = subject.values if subject is not None else {}
        title = data.title
        if kind in {"category", "budget"} and subject is not None:
            usage = values.get("budget_usage_pct")
            change = values.get("month_change_pct")
            if values.get("transaction_count") == 0:
                add(
                    f"Check whether {title} spend was categorized elsewhere.",
                    "No spend is recorded in this category for the period.",
                    "transactions",
                )
            if usage is not None and usage >= 100:
                add(
                    f"Review {title} transactions.",
                    f"Spend is at {_format(usage)}% of the monthly limit.",
                    "budgets",
                )
            elif usage is not None and usage >= 80:
                add(
                    f"Pace remaining {title} spend.",
                    f"Spend is at {_format(usage)}% of the monthly limit.",
                    "budgets",
                )
            elif values.get("budget_limit") is None:
                add(
                    f"Set a monthly limit for {title}.",
                    "No budget exists, so adherence cannot be measured.",
                    "budgets",
                )
            if change is not None and change >= 25:
                add(
                    f"Compare {title} with last month.",
                    f"Spend rose {_format(change)}% versus the previous month.",
                    "insights",
                )
            if subject.extra.get("top_merchant"):
                add(
                    f"Check {subject.extra['top_merchant']} first.",
                    "It is the largest contributor to this category.",
                    "transactions",
                )
        elif kind == "merchant" and subject is not None:
            if subject.extra.get("category") is None:
                add(
                    "Assign a default category for this merchant.",
                    "Its spend is currently uncategorized.",
                    "transactions",
                )
            change = values.get("month_change_pct")
            if change is not None and change >= 25:
                add(
                    "Review the latest transactions for this merchant.",
                    f"Spend rose {_format(change)}% versus the previous month.",
                    "transactions",
                )
        elif kind == "financial_health" and health is not None:
            weak = sorted(
                (
                    dim
                    for dim in health.data_confidence_breakdown
                    if dim.status != "strong" and dim.remediation_label
                ),
                key=lambda dim: dim.score,
            )
            for dim in weak:
                add(
                    str(dim.remediation_label),
                    f"{dim.label} confidence is {dim.status} ({dim.score}/100).",
                    dim.remediation_target,
                )
            if health.budget_adherence is None:
                add(
                    "Create budgets for your main categories.",
                    "Budget adherence cannot be scored without budgets.",
                    "budgets",
                )

        if coverage is not None:
            for source in sorted(coverage.sources, key=lambda s: s.score):
                if source.remediation_label:
                    add(
                        source.remediation_label,
                        f"{source.label} is {source.status} ({source.score}/100).",
                        source.remediation_target,
                    )

        if user_id is None:
            add(
                "Open this view signed in to attach ledger evidence.",
                "Without a user scope PFIS cannot verify these figures.",
            )
        elif subject is None and kind in {"category", "budget", "merchant", "financial_health"}:
            add(
                "Reopen this explanation from the dashboard for the selected month.",
                "The period or subject was not available for verification.",
            )
        if not actions:
            add(
                "No corrective action is indicated by the available evidence.",
                "Verified figures and source coverage raise no flags.",
            )
        return actions
