"""Pure decision coverage for provider readiness and transfer matching."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.transaction import CardEvent, PaymentMethod, PaymentRail, TransactionType
from app.services.balance_provider_status_service import BalanceProviderStatusService
from app.services.transaction_transfer_service import TransactionTransferService


def _account(account_id: str = "account-1", *, account_type: str = "bank"):
    return SimpleNamespace(
        id=account_id,
        institution_name="Policy Bank",
        account_type=account_type,
        balance_kind="liability" if account_type == "credit_card" else "asset",
        masked_number="****1234",
    )


def test_provider_status_source_selection_prefers_exact_latest_and_safe_fallbacks():
    earlier = SimpleNamespace(
        source_account_id="provider-1",
        last_success_at=datetime(2026, 9, 18, tzinfo=UTC),
        last_observed_at=None,
    )
    later = SimpleNamespace(
        source_account_id="provider-1",
        last_success_at=datetime(2026, 9, 19, tzinfo=UTC),
        last_observed_at=None,
    )
    other = SimpleNamespace(
        source_account_id="provider-2",
        last_success_at=datetime(2026, 9, 20, tzinfo=UTC),
        last_observed_at=None,
    )
    assert BalanceProviderStatusService._source_state([earlier, later], "provider-1") is later
    assert BalanceProviderStatusService._source_state([other], "missing") is other
    assert BalanceProviderStatusService._source_state([other, earlier], "missing") is None
    assert BalanceProviderStatusService._as_utc(None) is None
    naive = datetime(2026, 9, 19, 12, 0)
    assert BalanceProviderStatusService._as_utc(naive).tzinfo == UTC
    aware = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    assert BalanceProviderStatusService._as_utc(aware) == aware


class _Coverage:
    def __init__(
        self,
        *,
        complete: bool = True,
        freshness: str = "fresh",
        last_success: datetime | None = None,
        reasons: list[str] | None = None,
    ):
        self.source_account_id = "provider-1"
        self.expected_next_at = datetime(2026, 9, 20, tzinfo=UTC)
        self.last_observed_at = datetime(2026, 9, 19, tzinfo=UTC)
        self.last_success_at = last_success
        self.coverage_complete = complete
        self.freshness_status = freshness
        self.reason_codes = reasons or []


class _CoverageService:
    def __init__(self, coverage: _Coverage):
        self.coverage = coverage

    def _coverage_response(self, state, *, now):
        del state, now
        return self.coverage


@pytest.mark.parametrize(
    ("provider_id", "state", "coverage", "expected_status", "expected_reason"),
    [
        (None, None, None, "unmapped", "account_mapping_required"),
        ("provider-1", None, None, "not_configured", "provider_observation_missing"),
        (
            "provider-1",
            SimpleNamespace(last_success_at=None, last_error_code="refresh_failed"),
            _Coverage(complete=True, last_success=None),
            "incomplete",
            "refresh_failed",
        ),
        (
            "provider-1",
            SimpleNamespace(
                last_success_at=datetime(2026, 9, 19, tzinfo=UTC), last_error_code=None
            ),
            _Coverage(complete=False, last_success=datetime(2026, 9, 19, tzinfo=UTC)),
            "incomplete",
            None,
        ),
        (
            "provider-1",
            SimpleNamespace(
                last_success_at=datetime(2026, 9, 19, tzinfo=UTC), last_error_code=None
            ),
            _Coverage(
                freshness="overdue",
                last_success=datetime(2026, 9, 19, tzinfo=UTC),
                reasons=["stale"],
            ),
            "overdue",
            "stale",
        ),
        (
            "provider-1",
            SimpleNamespace(
                last_success_at=datetime(2026, 9, 19, tzinfo=UTC), last_error_code=None
            ),
            _Coverage(
                freshness="due",
                last_success=datetime(2026, 9, 19, tzinfo=UTC),
                reasons=["refresh_due"],
            ),
            "due",
            "refresh_due",
        ),
        (
            "provider-1",
            SimpleNamespace(
                last_success_at=datetime(2026, 9, 19, tzinfo=UTC), last_error_code=None
            ),
            _Coverage(freshness="unknown", last_success=datetime(2026, 9, 19, tzinfo=UTC)),
            "incomplete",
            "provider_freshness_unknown",
        ),
        (
            "provider-1",
            SimpleNamespace(
                last_success_at=datetime(2026, 9, 19, tzinfo=UTC), last_error_code=None
            ),
            _Coverage(freshness="fresh", last_success=datetime(2026, 9, 19, tzinfo=UTC)),
            "ready",
            None,
        ),
    ],
)
def test_provider_status_classifies_account_state_without_exposing_secrets(
    provider_id, state, coverage, expected_status, expected_reason
):
    response = BalanceProviderStatusService._account_status(
        _account(), state, provider_id, _CoverageService(coverage) if coverage else None
    )
    assert response.status == expected_status
    if expected_reason:
        assert expected_reason in response.reason_codes


def _transaction(
    transaction_id: str,
    transaction_type: TransactionType,
    *,
    card_event: CardEvent = CardEvent.NONE,
    payment_method: PaymentMethod = PaymentMethod.OTHER,
    payment_rail: PaymentRail = PaymentRail.OTHER,
    merchant: str = "",
):
    return SimpleNamespace(
        id=transaction_id,
        transaction_type=transaction_type,
        card_event=card_event,
        payment_method=payment_method,
        payment_rail=payment_rail,
        merchant_raw=merchant,
        merchant_normalized=merchant,
        transfer_group_id=None,
        amount=Decimal("1500"),
        currency="INR",
        transaction_date=date(2026, 9, 19),
    )


def test_transfer_classifier_distinguishes_card_payment_asset_transfer_and_unrelated_pairs():
    bank = _account("bank", account_type="bank")
    card = _account("card", account_type="credit_card")
    cash = _account("cash", account_type="cash")
    debit = _transaction("debit", TransactionType.DEBIT, merchant="Own transfer")
    credit = _transaction("credit", TransactionType.CREDIT, card_event=CardEvent.NONE)
    kind, confidence, reasons = TransactionTransferService._classify_pair(debit, credit, bank, card)
    assert kind == "card_payment"
    assert confidence == 0.84
    assert "bank_to_card_counterparty" in reasons

    payment_credit = _transaction(
        "payment-credit",
        TransactionType.CREDIT,
        card_event=CardEvent.PAYMENT,
        payment_rail=PaymentRail.TRANSFER,
    )
    kind, confidence, reasons = TransactionTransferService._classify_pair(
        debit, payment_credit, bank, card
    )
    assert kind == "card_payment"
    assert confidence == 0.98
    assert {"card_payment_event", "transfer_rail_evidence"}.issubset(reasons)

    asset_credit = _transaction("asset-credit", TransactionType.CREDIT, merchant="From own account")
    kind, confidence, reasons = TransactionTransferService._classify_pair(
        debit, asset_credit, bank, cash
    )
    assert kind == "account_transfer"
    assert confidence == 0.78
    assert "transfer_evidence" in reasons
    unrelated = _transaction("unrelated", TransactionType.CREDIT, merchant="Refund")
    assert TransactionTransferService._classify_pair(debit, unrelated, card, card) is None


def test_transfer_evidence_and_response_helpers_cover_all_explicit_signals():
    debit = _transaction("debit", TransactionType.DEBIT)
    credit = _transaction("credit", TransactionType.CREDIT)
    assert not TransactionTransferService._has_transfer_evidence(debit, credit)
    debit.payment_rail = PaymentRail.TRANSFER
    assert TransactionTransferService._has_transfer_evidence(debit, credit)
    debit.payment_rail = PaymentRail.OTHER
    credit.payment_method = PaymentMethod.BANK_TRANSFER
    assert TransactionTransferService._has_transfer_evidence(debit, credit)
    credit.payment_method = PaymentMethod.OTHER
    debit.merchant_raw = "NEFT to own account"
    assert TransactionTransferService._has_transfer_evidence(debit, credit)
    account = _account("bank", account_type="bank")
    assert TransactionTransferService._account_label(account) == "Policy Bank · ****1234"
    debit.transfer_group_id = "group-1"
    response = TransactionTransferService._response_for_pair(debit, credit)
    assert response.transfer_group_id == "group-1"
    assert response.payment_rail == "transfer"
