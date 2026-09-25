"""Typed deterministic query planning for PFIS guidance.

The planner deliberately keeps raw query text in memory only. It emits a small,
typed execution contract that guidance_service can use before touching any
financial read model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final


class GuidanceIntent(StrEnum):
    MONTHLY_SPEND = "monthly_spend"
    MONTHLY_INCOME = "monthly_income"
    MONTHLY_SAVINGS = "monthly_savings"
    MERCHANT_SPEND = "merchant_spend"
    RECURRING_CHARGES = "recurring_charges"
    BUDGET_STATUS = "budget_status"
    MONTH_COMPARISON = "month_comparison"
    BANK_POSITION = "bank_position"
    CARD_POSITION = "card_position"
    CARD_POSITIONS = "card_positions"
    SAFE_TO_SPEND = "safe_to_spend"
    CURRENT_NET_WORTH = "current_net_worth"
    CARD_DUE_AFFORDABILITY = "card_due_affordability"
    CARD_UPCOMING_STATE = "card_upcoming_state"
    CARD_PORTFOLIO_UPCOMING = "card_portfolio_upcoming"
    CARD_PORTFOLIO_PAYMENT_PLAN = "card_portfolio_payment_plan"


class GuidanceSlot(StrEnum):
    PERIOD = "period"
    ACCOUNT_SCOPE = "account"
    CARD_SCOPE = "card"
    AMOUNT_SCOPE = "amount"
    MERCHANT = "merchant"
    COMPARISON_PERIOD = "comparison_period"
    RISK_SCOPE = "risk_scope"


@dataclass(frozen=True)
class IntentSpec:
    intent: GuidanceIntent
    required_slots: tuple[GuidanceSlot, ...]
    read_models: tuple[str, ...]
    temporal_scope: str
    phrases: tuple[str, ...] = ()
    tokens: tuple[str, ...] = ()
    required_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypedGuidanceQueryPlan:
    intent: GuidanceIntent
    required_slots: tuple[GuidanceSlot, ...]
    slots: dict[str, str]
    read_models: tuple[str, ...]
    temporal_scope: str
    confidence: float
    matched_signals: tuple[str, ...] = field(default_factory=tuple)

    @property
    def merchant(self) -> str | None:
        return self.slots.get(GuidanceSlot.MERCHANT.value)

    @property
    def evidence_sources(self) -> tuple[str, ...]:
        return self.read_models


@dataclass(frozen=True)
class GuidanceQueryRefusal:
    reason: str
    confidence: float
    candidates: tuple[str, ...] = ()


PlanResult = TypedGuidanceQueryPlan | GuidanceQueryRefusal


READ_MODELS: Final[dict[GuidanceIntent, tuple[str, ...]]] = {
    GuidanceIntent.MONTHLY_SPEND: ("transactions",),
    GuidanceIntent.MONTHLY_INCOME: ("transactions",),
    GuidanceIntent.MONTHLY_SAVINGS: ("transactions",),
    GuidanceIntent.MERCHANT_SPEND: ("transactions",),
    GuidanceIntent.RECURRING_CHARGES: ("transactions", "recurring_read_model"),
    GuidanceIntent.BUDGET_STATUS: ("transactions", "budgets"),
    GuidanceIntent.MONTH_COMPARISON: ("transactions",),
    GuidanceIntent.BANK_POSITION: ("financial_accounts", "account_balance_snapshots"),
    GuidanceIntent.CARD_POSITION: (
        "financial_accounts",
        "card_position_observations",
        "credit_card_statements",
    ),
    GuidanceIntent.CARD_POSITIONS: ("financial_accounts", "card_position_observations"),
    GuidanceIntent.SAFE_TO_SPEND: (
        "cash_plans",
        "financial_accounts",
        "account_balance_snapshots",
    ),
    GuidanceIntent.CURRENT_NET_WORTH: ("financial_accounts", "account_balance_snapshots"),
    GuidanceIntent.CARD_DUE_AFFORDABILITY: (
        "credit_card_statements",
        "card_position_observations",
        "account_balance_forecast_snapshots",
    ),
    GuidanceIntent.CARD_UPCOMING_STATE: (
        "credit_card_statements",
        "card_position_observations",
        "card_statement_projection",
        "card_payment_intents",
        "card_calendar_events",
        "card_refund_tracker",
    ),
    GuidanceIntent.CARD_PORTFOLIO_UPCOMING: (
        "credit_card_statements",
        "card_position_observations",
        "card_statement_projection",
        "card_payment_intents",
        "card_calendar_events",
        "card_refund_tracker",
    ),
    GuidanceIntent.CARD_PORTFOLIO_PAYMENT_PLAN: (
        "credit_card_statements",
        "card_position_observations",
        "account_balance_forecast_snapshots",
        "card_payment_intents",
        "financial_accounts",
    ),
}


_SPECS: Final[tuple[IntentSpec, ...]] = (
    IntentSpec(
        GuidanceIntent.CARD_PORTFOLIO_PAYMENT_PLAN,
        (GuidanceSlot.CARD_SCOPE, GuidanceSlot.AMOUNT_SCOPE),
        READ_MODELS[GuidanceIntent.CARD_PORTFOLIO_PAYMENT_PLAN],
        "current_card_cycle",
        phrases=(
            "minimum vs total",
            "minimum and total",
            "minimum versus total",
            "compare payment plans",
            "card payment plan",
            "payment plan across",
            "pay all cards",
            "which cards can i pay",
        ),
        tokens=("minimum", "total", "plan", "payment"),
        required_any=("card", "cards", "credit"),
    ),
    IntentSpec(
        GuidanceIntent.CARD_DUE_AFFORDABILITY,
        (GuidanceSlot.CARD_SCOPE, GuidanceSlot.AMOUNT_SCOPE),
        READ_MODELS[GuidanceIntent.CARD_DUE_AFFORDABILITY],
        "current_card_cycle",
        phrases=(
            "pay my card",
            "pay the card",
            "pay this card",
            "pay card",
            "card due",
            "cover the card",
            "cover my card",
            "afford the card",
            "afford my card",
            "before due date",
        ),
        tokens=("pay", "cover", "afford", "due"),
        required_any=("card", "cards", "credit"),
    ),
    IntentSpec(
        GuidanceIntent.CARD_PORTFOLIO_UPCOMING,
        (GuidanceSlot.CARD_SCOPE, GuidanceSlot.RISK_SCOPE),
        READ_MODELS[GuidanceIntent.CARD_PORTFOLIO_UPCOMING],
        "current_card_cycle",
        phrases=(
            "all cards",
            "all credit cards",
            "across my cards",
            "across all cards",
            "my cards",
            "card portfolio",
            "which card is due",
            "which cards are due",
            "cards upcoming",
            "upcoming risk",
        ),
        tokens=("upcoming", "due", "risk", "coming"),
        required_any=("cards", "card", "credit"),
    ),
    IntentSpec(
        GuidanceIntent.CARD_UPCOMING_STATE,
        (GuidanceSlot.CARD_SCOPE, GuidanceSlot.RISK_SCOPE),
        READ_MODELS[GuidanceIntent.CARD_UPCOMING_STATE],
        "current_card_cycle",
        phrases=(
            "what happens next",
            "what's next",
            "whats next",
            "what is next",
            "coming up",
            "upcoming",
            "next card",
            "next statement",
            "statement close",
            "next payment",
            "when is my card payment",
            "when is the card payment",
            "utilization forecast",
            "utilisation forecast",
            "card forecast",
            "card projection",
            "utilization pressure",
            "utilisation pressure",
            "limit pressure",
            "credit limit pressure",
            "credit limit breach",
            "go over my limit",
            "exceed my limit",
        ),
        tokens=("next", "upcoming", "forecast", "projection", "pressure", "limit"),
        required_any=("card", "cards", "credit", "statement"),
    ),
    IntentSpec(
        GuidanceIntent.SAFE_TO_SPEND,
        (GuidanceSlot.PERIOD, GuidanceSlot.ACCOUNT_SCOPE, GuidanceSlot.RISK_SCOPE),
        READ_MODELS[GuidanceIntent.SAFE_TO_SPEND],
        "current_position",
        phrases=("safe to spend", "is it safe", "am i safe", "spendable", "available cash"),
        tokens=("safe", "spendable", "cash"),
    ),
    IntentSpec(
        GuidanceIntent.CURRENT_NET_WORTH,
        (GuidanceSlot.PERIOD, GuidanceSlot.ACCOUNT_SCOPE),
        READ_MODELS[GuidanceIntent.CURRENT_NET_WORTH],
        "current_position",
        phrases=("net worth", "financial position"),
        tokens=("worth", "assets", "liabilities"),
    ),
    IntentSpec(
        GuidanceIntent.CARD_POSITION,
        (GuidanceSlot.PERIOD, GuidanceSlot.CARD_SCOPE),
        READ_MODELS[GuidanceIntent.CARD_POSITION],
        "current_position",
        phrases=(
            "card balance",
            "credit card balance",
            "available credit",
            "current outstanding",
            "outstanding balance",
        ),
        tokens=("card", "credit", "outstanding"),
    ),
    IntentSpec(
        GuidanceIntent.BANK_POSITION,
        (GuidanceSlot.PERIOD, GuidanceSlot.ACCOUNT_SCOPE),
        READ_MODELS[GuidanceIntent.BANK_POSITION],
        "current_position",
        phrases=("current balance", "bank balance", "current bank cash"),
        tokens=("bank", "balance", "cash"),
    ),
    IntentSpec(
        GuidanceIntent.RECURRING_CHARGES,
        (GuidanceSlot.PERIOD,),
        READ_MODELS[GuidanceIntent.RECURRING_CHARGES],
        "selected_calendar_month",
        phrases=("recurring charges", "recurring spending", "subscriptions"),
        tokens=("recurring", "subscription", "subscriptions"),
    ),
    IntentSpec(
        GuidanceIntent.BUDGET_STATUS,
        (GuidanceSlot.PERIOD,),
        READ_MODELS[GuidanceIntent.BUDGET_STATUS],
        "selected_calendar_month",
        phrases=("budget status", "budgets doing", "how is my budget"),
        tokens=("budget", "budgets", "guardrail"),
    ),
    IntentSpec(
        GuidanceIntent.MONTH_COMPARISON,
        (GuidanceSlot.PERIOD, GuidanceSlot.COMPARISON_PERIOD),
        READ_MODELS[GuidanceIntent.MONTH_COMPARISON],
        "selected_calendar_month",
        phrases=("last month", "previous month", "what changed", "why totals differ"),
        tokens=("compare", "changed", "difference", "differ"),
        required_any=("last", "previous", "changed", "difference", "differ", "totals"),
    ),
    IntentSpec(
        GuidanceIntent.MERCHANT_SPEND,
        (GuidanceSlot.PERIOD, GuidanceSlot.MERCHANT),
        READ_MODELS[GuidanceIntent.MERCHANT_SPEND],
        "selected_calendar_month",
        phrases=("spend at", "spent at", "spend from", "spent from"),
        tokens=("merchant", "spend", "spent"),
    ),
    IntentSpec(
        GuidanceIntent.MONTHLY_SPEND,
        (GuidanceSlot.PERIOD,),
        READ_MODELS[GuidanceIntent.MONTHLY_SPEND],
        "selected_calendar_month",
        phrases=(
            "how much did i spend",
            "how much were my expenses",
            "spend this month",
            "spent this month",
            "monthly spend",
        ),
        tokens=("spend", "spent", "expenses"),
    ),
    IntentSpec(
        GuidanceIntent.MONTHLY_INCOME,
        (GuidanceSlot.PERIOD,),
        READ_MODELS[GuidanceIntent.MONTHLY_INCOME],
        "selected_calendar_month",
        phrases=("what was my income", "how much income", "monthly income", "income this month"),
        tokens=("income", "salary", "earned"),
    ),
    IntentSpec(
        GuidanceIntent.MONTHLY_SAVINGS,
        (GuidanceSlot.PERIOD,),
        READ_MODELS[GuidanceIntent.MONTHLY_SAVINGS],
        "selected_calendar_month",
        phrases=("how much were my savings", "monthly savings", "saved this month"),
        tokens=("saved", "savings"),
    ),
)

_UNSUPPORTED_SIGNALS: Final[tuple[str, ...]] = (
    "joke",
    "poem",
    "weather",
    "stock",
    "crypto",
    "invest",
    "investment",
    "should i do",
    "tax advice",
    "loan should i take",
    "call my bank",
    "negotiate",
    "ignore instructions",
    "raw email",
    "password",
    "token",
    "secret",
)

_MERCHANT_STOPS: Final[set[str]] = {
    "this",
    "last",
    "month",
    "year",
    "today",
    "yesterday",
    "please",
    "compare",
    "with",
    "and",
    "or",
}


def normalize_query(raw_query: str) -> str:
    """Normalize in memory without logging or retaining the raw query."""

    lowered = raw_query.casefold()
    return " ".join(
        "".join(
            character if character.isalnum() or character.isspace() else " "
            for character in lowered
        ).split()
    )


def plan_guidance_query(raw_query: str) -> PlanResult:
    query = normalize_query(raw_query)
    if not query:
        return GuidanceQueryRefusal("empty_query", 1.0)
    if unsupported := tuple(signal for signal in _UNSUPPORTED_SIGNALS if signal in query):
        return GuidanceQueryRefusal("unsupported_or_sensitive_prompt", 0.98, unsupported)

    tokens = tuple(query.split())
    token_set = set(tokens)
    scored = sorted(
        (
            (_score_spec(spec, query, token_set), spec)
            for spec in _SPECS
            if not spec.required_any or token_set.intersection(spec.required_any)
        ),
        key=lambda item: (item[0][0], item[1].intent.value),
        reverse=True,
    )
    top = [(score, spec, signals) for (score, signals), spec in scored if score > 0]
    if not top:
        return GuidanceQueryRefusal("unsupported_intent", 0.0)

    best_score, best_spec, best_signals = top[0]
    second_score = top[1][0] if len(top) > 1 else 0
    confidence = _confidence(best_score, second_score, best_spec)
    if confidence < 0.58:
        return GuidanceQueryRefusal("low_confidence_intent", confidence, (best_spec.intent.value,))
    if second_score and best_score - second_score <= 0.5:
        candidates = (best_spec.intent.value, top[1][1].intent.value)
        return GuidanceQueryRefusal("ambiguous_intent", confidence, candidates)

    slots = _slots_for(best_spec, query, tokens)
    missing = [slot.value for slot in best_spec.required_slots if slot.value not in slots]
    if missing:
        return GuidanceQueryRefusal(
            "missing_required_slots",
            min(confidence, 0.5),
            (best_spec.intent.value, *missing),
        )

    return TypedGuidanceQueryPlan(
        intent=best_spec.intent,
        required_slots=best_spec.required_slots,
        slots=slots,
        read_models=best_spec.read_models,
        temporal_scope=best_spec.temporal_scope,
        confidence=confidence,
        matched_signals=best_signals,
    )


def _score_spec(spec: IntentSpec, query: str, token_set: set[str]) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    signals: list[str] = []
    for phrase in spec.phrases:
        normalized_phrase = normalize_query(phrase)
        if normalized_phrase in query:
            score += 3.0
            signals.append(phrase)
    token_hits = token_set.intersection(spec.tokens)
    if token_hits:
        score += float(len(token_hits))
        signals.extend(sorted(token_hits))
    if spec.intent == GuidanceIntent.MERCHANT_SPEND and _extract_merchant(tuple(query.split())):
        score += 2.5
        signals.append("merchant_slot")
    if spec.required_any and token_set.intersection(spec.required_any):
        score += 0.75
    return score, tuple(signals)


def _confidence(best_score: float, second_score: float, spec: IntentSpec) -> float:
    separation = best_score - second_score
    slot_weight = 0.05 * len(spec.required_slots)
    confidence = 0.45 + min(best_score, 7.0) * 0.06 + min(separation, 4.0) * 0.06 + slot_weight
    return round(min(confidence, 0.99), 2)


def _slots_for(spec: IntentSpec, query: str, tokens: tuple[str, ...]) -> dict[str, str]:
    slots: dict[str, str] = {}
    if GuidanceSlot.PERIOD in spec.required_slots:
        slots[GuidanceSlot.PERIOD.value] = _period_slot(query)
    if GuidanceSlot.COMPARISON_PERIOD in spec.required_slots:
        slots[GuidanceSlot.COMPARISON_PERIOD.value] = "previous_calendar_month"
    if GuidanceSlot.ACCOUNT_SCOPE in spec.required_slots:
        slots[GuidanceSlot.ACCOUNT_SCOPE.value] = "owned_accounts"
    if GuidanceSlot.CARD_SCOPE in spec.required_slots:
        slots[GuidanceSlot.CARD_SCOPE.value] = (
            "active_card_portfolio"
            if spec.intent
            in {
                GuidanceIntent.CARD_PORTFOLIO_PAYMENT_PLAN,
                GuidanceIntent.CARD_PORTFOLIO_UPCOMING,
                GuidanceIntent.CARD_POSITIONS,
            }
            else "active_card"
        )
    if GuidanceSlot.AMOUNT_SCOPE in spec.required_slots:
        slots[GuidanceSlot.AMOUNT_SCOPE.value] = "issuer_due_or_position_amount"
    if GuidanceSlot.RISK_SCOPE in spec.required_slots:
        slots[GuidanceSlot.RISK_SCOPE.value] = "upcoming_cash_or_card_risk"
    if GuidanceSlot.MERCHANT in spec.required_slots:
        merchant = _extract_merchant(tokens)
        if merchant:
            slots[GuidanceSlot.MERCHANT.value] = merchant
    return slots


def _period_slot(query: str) -> str:
    if "last month" in query or "previous month" in query:
        return "previous_calendar_month"
    if "today" in query or "current" in query:
        return "current_position_date"
    return "selected_calendar_month"


def _extract_merchant(tokens: tuple[str, ...]) -> str | None:
    for marker in ("at", "from"):
        if marker not in tokens:
            continue
        start = tokens.index(marker) + 1
        collected: list[str] = []
        for token in tokens[start:]:
            if token in _MERCHANT_STOPS:
                break
            collected.append(token)
        merchant = " ".join(collected).strip()
        if merchant:
            return merchant
    return None
