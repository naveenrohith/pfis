"""Deep validation tests for connector contracts and public errors."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services.connectors.base import (
    BalanceAccountCandidate,
    BalanceObservation,
    BalanceObservationBatch,
    CardPositionObservation,
    ConnectorCursor,
    ConnectorError,
    ConnectorErrorType,
)
from app.services.connectors.errors import (
    classify_connector_exception,
    public_connector_error,
)
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

OBSERVED_AT = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
COVERAGE_START = OBSERVED_AT - timedelta(days=1)
COVERAGE_END = OBSERVED_AT


def _balance(**overrides: object) -> BalanceObservation:
    values: dict[str, object] = {
        "financial_account_id": "account-1",
        "amount": Decimal("125.00"),
        "currency": "INR",
        "as_of": date(2026, 9, 20),
        "source_record_id": "record-1",
        "observed_at": OBSERVED_AT,
        "effective_at": COVERAGE_START,
        "coverage_start": COVERAGE_START,
        "coverage_end": COVERAGE_END,
    }
    values.update(overrides)
    return BalanceObservation(**values)  # type: ignore[arg-type]


def _card(**overrides: object) -> CardPositionObservation:
    values: dict[str, object] = {
        "financial_account_id": "account-1",
        "currency": "INR",
        "current_outstanding": Decimal("125.00"),
        "as_of": date(2026, 9, 20),
        "source_record_id": "card-record-1",
        "observed_at": OBSERVED_AT,
        "source_account_id": "provider-account-1",
        "coverage_start": COVERAGE_START,
        "coverage_end": COVERAGE_END,
    }
    values.update(overrides)
    return CardPositionObservation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (RefreshError("refresh token revoked"), ConnectorErrorType.PERMANENT),
        (
            HttpError(SimpleNamespace(status=401, reason="unauthorized"), b"unauthorized"),
            ConnectorErrorType.PERMANENT,
        ),
        (
            HttpError(
                SimpleNamespace(status=503, reason="temporarily unavailable"),
                b"temporarily unavailable",
            ),
            ConnectorErrorType.TRANSIENT,
        ),
        (
            HttpError(
                SimpleNamespace(status=418, reason="provider response"), b"provider response"
            ),
            ConnectorErrorType.UNKNOWN,
        ),
        (ValueError("invalid credential"), ConnectorErrorType.PERMANENT),
        (TimeoutError("network timeout"), ConnectorErrorType.TRANSIENT),
        (RuntimeError("unexpected provider payload"), ConnectorErrorType.UNKNOWN),
    ],
)
def test_connector_exception_classification_is_stable(exception, expected):
    assert classify_connector_exception(exception) == expected


def test_public_connector_errors_are_provider_safe_and_normalize_labels():
    assert public_connector_error(ConnectorErrorType.PERMANENT, provider_name=" Gmail ") == (
        "Gmail authorization is invalid or revoked"
    )
    assert public_connector_error(ConnectorErrorType.TRANSIENT, provider_name="") == (
        "provider is temporarily unavailable"
    )
    assert public_connector_error(ConnectorErrorType.UNKNOWN, provider_name="Bank") == (
        "Bank synchronization failed"
    )


def test_connector_cursor_rejects_oversized_opaque_tokens():
    assert ConnectorCursor(history_id="history-1", opaque_token="page-1").opaque_token == "page-1"
    with pytest.raises(ValueError, match="512 characters"):
        ConnectorCursor(opaque_token="x" * 513)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"financial_account_id": ""}, "financial_account_id is required"),
        ({"source_record_id": ""}, "source_record_id is required"),
        ({"amount": Decimal("-1")}, "amount must be non-negative"),
        ({"observed_at": datetime(2026, 9, 20, 12, 0)}, "observed_at must include a timezone"),
        ({"effective_at": datetime(2026, 9, 20, 12, 0)}, "effective_at must include a timezone"),
        (
            {"effective_at": OBSERVED_AT + timedelta(minutes=1)},
            "effective_at cannot be after observed_at",
        ),
        (
            {"coverage_start": datetime(2026, 9, 19, 12, 0)},
            "coverage_start must include a timezone",
        ),
        (
            {"coverage_end": datetime(2026, 9, 20, 12, 0)},
            "coverage_end must include a timezone",
        ),
        (
            {"coverage_start": COVERAGE_END, "coverage_end": COVERAGE_START},
            "coverage_end must be on or after coverage_start",
        ),
        (
            {"coverage_start": None, "coverage_end": None},
            "complete coverage requires coverage_start and coverage_end",
        ),
        ({"expected_cadence_minutes": 0}, "expected_cadence_minutes must be positive"),
    ],
)
def test_balance_observation_rejects_invalid_provider_facts(overrides, message):
    with pytest.raises(ValueError, match=message):
        _balance(**overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"financial_account_id": ""}, "financial_account_id is required"),
        ({"source_record_id": ""}, "source_record_id is required"),
        ({"source": "estimated"}, "source=connector"),
        ({"current_outstanding": Decimal("-1")}, "current_outstanding must be non-negative"),
        ({"billed_due": Decimal("-1")}, "billed_due must be non-negative"),
        ({"pending_amount": Decimal("-1")}, "pending_amount must be non-negative"),
        ({"credit_limit": Decimal("-1")}, "credit_limit must be non-negative"),
        ({"available_credit": Decimal("-1")}, "available_credit must be non-negative"),
        ({"observed_at": datetime(2026, 9, 20, 12, 0)}, "observed_at must include a timezone"),
        (
            {"effective_at": OBSERVED_AT + timedelta(minutes=1)},
            "effective_at cannot be after observed_at",
        ),
        ({"coverage_complete": False, "coverage_start": None, "coverage_end": None}, None),
        ({"expected_cadence_minutes": 0}, "expected_cadence_minutes must be positive"),
    ],
)
def test_card_position_observation_validates_issuer_fields(overrides, message):
    if message is None:
        assert _card(**overrides).coverage_complete is False
    else:
        with pytest.raises(ValueError, match=message):
            _card(**overrides)


def test_card_position_observation_validates_coverage_window_and_mapping_fields():
    with pytest.raises(ValueError, match="coverage_start must include a timezone"):
        _card(coverage_start=datetime(2026, 9, 19, 12, 0))
    with pytest.raises(ValueError, match="coverage_end must include a timezone"):
        _card(coverage_end=datetime(2026, 9, 20, 12, 0))
    with pytest.raises(ValueError, match="coverage_end must be on or after"):
        _card(coverage_start=COVERAGE_END, coverage_end=COVERAGE_START)
    with pytest.raises(ValueError, match="complete coverage requires"):
        _card(coverage_start=None, coverage_end=None)

    assert _card(effective_at=COVERAGE_START).effective_at == COVERAGE_START


def test_balance_account_candidate_limits_identity_fields():
    candidate = BalanceAccountCandidate(
        provider_account_id="provider-1",
        display_name="Primary account",
        masked_number="****1234",
        account_type="savings",
        currency="INR",
    )
    assert candidate.currency == "INR"

    with pytest.raises(ValueError, match="provider_account_id is required"):
        BalanceAccountCandidate(provider_account_id=" ")
    with pytest.raises(ValueError, match="provider_account_id is too long"):
        BalanceAccountCandidate(provider_account_id="x" * 129)
    with pytest.raises(ValueError, match="display_name is too long"):
        BalanceAccountCandidate(provider_account_id="provider-1", display_name="x" * 161)
    with pytest.raises(ValueError, match="masked_number is too long"):
        BalanceAccountCandidate(provider_account_id="provider-1", masked_number="x" * 33)
    with pytest.raises(ValueError, match="account_type is too long"):
        BalanceAccountCandidate(provider_account_id="provider-1", account_type="x" * 41)
    with pytest.raises(ValueError, match="currency is too long"):
        BalanceAccountCandidate(provider_account_id="provider-1", currency="x" * 4)


def test_balance_observation_batch_rejects_cross_account_and_duplicate_provider_records():
    balance = _balance()
    card = _card()
    valid = BalanceObservationBatch(
        source="connector",
        observations=[balance],
        card_observations=[card],
        affected_account_ids=["account-1"],
        errors=[ConnectorError(ConnectorErrorType.UNKNOWN, "provider failed", False)],
    )
    valid.validate_for_accounts({"account-1"})

    with pytest.raises(ValueError, match="At least one requested account"):
        valid.validate_for_accounts(set())
    with pytest.raises(ValueError, match="source=connector"):
        BalanceObservationBatch(source="gmail").validate_for_accounts({"account-1"})
    with pytest.raises(ValueError, match="affected accounts must be unique"):
        BalanceObservationBatch(
            source="connector", affected_account_ids=["account-1", "account-1"]
        ).validate_for_accounts({"account-1"})
    with pytest.raises(ValueError, match="unrequested account"):
        BalanceObservationBatch(
            source="connector", affected_account_ids=["account-2"]
        ).validate_for_accounts({"account-1"})
    with pytest.raises(ValueError, match="duplicate source record"):
        BalanceObservationBatch(
            source="connector", observations=[balance, balance]
        ).validate_for_accounts({"account-1"})
    with pytest.raises(ValueError, match="unrequested account"):
        BalanceObservationBatch(
            source="connector", observations=[_balance(financial_account_id="account-2")]
        ).validate_for_accounts({"account-1"})
    with pytest.raises(ValueError, match="duplicate source record"):
        BalanceObservationBatch(
            source="connector", card_observations=[card, card]
        ).validate_for_accounts({"account-1"})
    with pytest.raises(ValueError, match="unrequested account"):
        BalanceObservationBatch(
            source="connector", card_observations=[_card(financial_account_id="account-2")]
        ).validate_for_accounts({"account-1"})
