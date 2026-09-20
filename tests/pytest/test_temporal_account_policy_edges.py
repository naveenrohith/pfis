"""Temporal/account boundary coverage for retained inactive identities."""

from datetime import date

from app.services.temporal_event_service import TemporalEventService


def test_temporal_account_identity_retains_inactive_unresolved_evidence():
    event = TemporalEventService(None)._account_identity_event(
        user_id="user-1",
        currency="INR",
        source_id="account-1",
        occurrence_date=date(2026, 9, 19),
        institution_name="History Bank",
        account_type="bank",
        masked_number="****1100",
        balance_kind="asset",
        is_active=False,
        identity_status="inferred",
        identity_confidence=0.72,
        as_of=date(2026, 9, 20),
    )

    assert event.kind == "account_identity"
    assert event.state == "cancelled"
    assert event.data_sufficiency == "medium"
    assert any("historical evidence remains retained" in item for item in event.assumptions)
    assert any("unresolved" in item for item in event.assumptions)
