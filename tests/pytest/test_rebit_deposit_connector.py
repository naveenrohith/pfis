"""Regression fixtures for the ReBIT deposit balance adapter."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.services.connectors.base import ConnectorCursor, ConnectorErrorType
from app.services.connectors.rebit_deposit import (
    RebitDepositConnector,
    RebitDepositPayload,
    parse_rebit_deposit_payload,
)

REBIT_DEPOSIT_XML = """
<aa:Account xmlns:aa="http://api.rebit.org.in/FISchema/deposit"
            linkedAccRef="linked-bank-001"
            maskedAccNumber="XXXXXX7788"
            type="deposit"
            version="2.0.0">
  <aa:Summary accountSubType="SAVINGS"
              accountType="INDIVIDUAL"
              balanceDateTime="2026-08-03T09:15:00+05:30"
              branch="ignored"
              currency="INR"
              currentBalance="42000.25"
              facility="NO_FACILITY_GRANTED"
              status="ACTIVE" />
  <aa:Transactions startDate="2026-07-01" endDate="2026-08-03">
    <aa:Transaction amount="100.00"
                    mode="UPI"
                    narration="ignored"
                    transactionalBalance="42000.25"
                    transactionTimestamp="2026-08-03T09:00:00+05:30"
                    txnId="ignored"
                    type="CREDIT"
                    valueDate="2026-08-03" />
  </aa:Transactions>
</aa:Account>
"""


def test_rebit_deposit_parser_maps_current_balance_and_coverage():
    retrieval_time = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
    batch = parse_rebit_deposit_payload(
        REBIT_DEPOSIT_XML,
        {"local-bank-001": "linked-bank-001"},
        observed_at=retrieval_time,
        expected_cadence_minutes=720,
        cursor=ConnectorCursor(opaque_token="next-page"),
    )

    assert batch.errors == []
    assert batch.coverage_complete is True
    assert batch.affected_account_ids == []
    assert batch.cursor.opaque_token == "next-page"
    observation = batch.observations[0]
    assert observation.financial_account_id == "local-bank-001"
    assert observation.source_account_id == "linked-bank-001"
    assert observation.amount == Decimal("42000.25")
    assert observation.currency == "INR"
    assert observation.as_of.isoformat() == "2026-08-03"
    assert observation.effective_at == datetime(2026, 8, 3, 3, 45, tzinfo=UTC)
    assert observation.observed_at == retrieval_time
    assert observation.coverage_start == datetime(2026, 7, 1, tzinfo=UTC)
    assert observation.coverage_end is not None
    assert observation.coverage_end.date().isoformat() == "2026-08-03"
    assert observation.expected_cadence_minutes == 720
    assert observation.source_record_id.startswith("rebit-deposit:")
    assert len(observation.source_record_id) <= 128


def test_rebit_deposit_parser_fails_closed_for_missing_requested_account():
    batch = parse_rebit_deposit_payload(
        REBIT_DEPOSIT_XML,
        {"local-bank-001": "linked-bank-001", "local-bank-002": "linked-bank-002"},
        observed_at=datetime(2026, 8, 3, 5, 0, tzinfo=UTC),
    )

    assert batch.coverage_complete is False
    assert batch.errors == []
    assert batch.affected_account_ids == ["local-bank-002"]
    assert [item.financial_account_id for item in batch.observations] == ["local-bank-001"]


def test_rebit_deposit_parser_rejects_negative_balance_without_clamping():
    payload = REBIT_DEPOSIT_XML.replace('currentBalance="42000.25"', 'currentBalance="-1.00"')
    batch = parse_rebit_deposit_payload(
        payload,
        {"local-bank-001": "linked-bank-001"},
        observed_at=datetime(2026, 8, 3, 5, 0, tzinfo=UTC),
    )

    assert batch.observations == []
    assert batch.coverage_complete is False
    assert batch.affected_account_ids == ["local-bank-001"]
    assert len(batch.errors) == 1
    assert batch.errors[0].error_type == ConnectorErrorType.PERMANENT
    assert batch.errors[0].retryable is False


def test_rebit_deposit_parser_keeps_pending_amounts_out_of_settled_coverage():
    payload = REBIT_DEPOSIT_XML.replace(
        'status="ACTIVE" />',
        'status="ACTIVE"><aa:PendingTxns><aa:PendingTxn amount="10.00" /></aa:PendingTxns></aa:Summary>',
    )
    batch = parse_rebit_deposit_payload(
        payload,
        {"local-bank-001": "linked-bank-001"},
        observed_at=datetime(2026, 8, 3, 5, 0, tzinfo=UTC),
    )

    assert len(batch.observations) == 1
    assert batch.coverage_complete is False
    assert batch.affected_account_ids == ["local-bank-001"]
    assert batch.observations[0].coverage_complete is False


@pytest.mark.asyncio
async def test_rebit_connector_injects_payload_transport_and_cursor():
    seen: list[tuple[str, list[str], str | None]] = []

    async def fetch_payload(user_id, provider_account_ids, cursor):
        seen.append((user_id, provider_account_ids, cursor.opaque_token))
        return RebitDepositPayload(
            body=REBIT_DEPOSIT_XML,
            cursor=ConnectorCursor(opaque_token="provider-next"),
        )

    connector = RebitDepositConnector(
        {"local-bank-001": "linked-bank-001"},
        fetch_payload,
        expected_cadence_minutes=1440,
    )
    batch = await connector.fetch_balance_observations(
        "user-001",
        ["local-bank-001"],
        ConnectorCursor(opaque_token="provider-current"),
    )

    assert seen == [("user-001", ["linked-bank-001"], "provider-current")]
    assert batch.cursor.opaque_token == "provider-next"
    assert batch.observations[0].source_account_id == "linked-bank-001"
