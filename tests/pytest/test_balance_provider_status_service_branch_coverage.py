"""Direct branch coverage for provider readiness status classification."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.services.balance_provider_status_service import BalanceProviderStatusService


def _account(account_id="account-1"):
    return SimpleNamespace(
        id=account_id,
        account_type="bank",
        masked_number="****1234",
    )


def _source(**values):
    fields = {
        "source_account_id": "provider-1",
        "last_success_at": datetime.now(UTC),
        "last_observed_at": None,
        "last_error_code": None,
    }
    fields.update(values)
    return SimpleNamespace(**fields)


class _Coverage:
    def __init__(self, **values):
        self.values = values

    def _coverage_response(self, state, *, now):
        return SimpleNamespace(
            source_account_id=state.source_account_id,
            expected_next_at=self.values.get("expected_next_at"),
            last_observed_at=self.values.get("last_observed_at"),
            last_success_at=state.last_success_at,
            coverage_complete=self.values.get("coverage_complete", True),
            freshness_status=self.values.get("freshness_status", "fresh"),
            reason_codes=self.values.get("reason_codes", []),
        )


def test_source_state_prefers_exact_latest_and_safe_fallbacks():
    old = _source(last_success_at=datetime(2026, 9, 1, tzinfo=UTC))
    new = _source(last_success_at=datetime(2026, 9, 2, tzinfo=UTC))
    assert BalanceProviderStatusService._source_state([old, new], "provider-1") is new
    assert BalanceProviderStatusService._source_state([old], "missing") is old
    assert BalanceProviderStatusService._source_state([old, new], "missing") is None
    assert BalanceProviderStatusService._as_utc(None) is None
    naive = datetime(2026, 9, 1)
    assert BalanceProviderStatusService._as_utc(naive).tzinfo == UTC
    aware = datetime(2026, 9, 1, tzinfo=UTC)
    assert BalanceProviderStatusService._as_utc(aware) == aware


@pytest.mark.parametrize(
    ("provider_id", "state", "coverage", "expected"),
    [
        (None, None, {}, "unmapped"),
        ("provider-1", None, {}, "not_configured"),
        (
            "provider-1",
            _source(last_success_at=None, last_error_code="connector_error"),
            {"coverage_complete": True, "freshness_status": "fresh"},
            "incomplete",
        ),
        (
            "provider-1",
            _source(),
            {"coverage_complete": False, "freshness_status": "fresh"},
            "incomplete",
        ),
        ("provider-1", _source(), {"freshness_status": "overdue"}, "overdue"),
        ("provider-1", _source(), {"freshness_status": "due"}, "due"),
        ("provider-1", _source(), {"freshness_status": "unknown"}, "incomplete"),
        (
            "provider-1",
            _source(last_success_at=None),
            {"freshness_status": "fresh"},
            "not_configured",
        ),
        ("provider-1", _source(), {"freshness_status": "fresh"}, "ready"),
    ],
)
def test_account_status_classifies_mapping_coverage_and_freshness(
    provider_id, state, coverage, expected
):
    response = BalanceProviderStatusService._account_status(
        _account(),
        state,
        provider_id,
        _Coverage(**coverage),
    )

    assert response.status == expected
    if expected == "unmapped":
        assert response.reason_codes == ["account_mapping_required"]
    if expected == "not_configured" and state is None:
        assert response.reason_codes == ["provider_observation_missing"]
    if (
        expected == "incomplete"
        and state is not None
        and (state.last_error_code or coverage.get("freshness_status") == "unknown")
    ):
        assert response.reason_codes


def test_source_state_uses_observed_timestamp_when_success_is_missing():
    older = _source(last_success_at=None, last_observed_at=datetime(2026, 9, 1))
    newer = _source(last_success_at=None, last_observed_at=datetime(2026, 9, 2))
    assert BalanceProviderStatusService._source_state([older, newer], "provider-1") is newer
