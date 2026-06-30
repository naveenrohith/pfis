"""Connector source-record contract tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

from datetime import UTC, datetime

from app.models.email import RawEmail
from app.services.connectors.source_record import SourceRecord, SourceType


def test_source_record_maps_raw_email_to_parser_inputs():
    received_at = datetime(2026, 5, 7, tzinfo=UTC)
    email = RawEmail(
        user_id="user-1",
        gmail_message_id="user-1:gmail-1",
        sender="alerts@example.test",
        subject="Payment alert",
        body="Payment of Rs.750.00 to BOOKMYSHOW via UPI.",
        received_at=received_at,
    )

    record = SourceRecord.from_raw_email(email)

    assert record.user_id == "user-1"
    assert record.source_type == SourceType.GMAIL
    assert record.source_message_id == "user-1:gmail-1"
    assert record.received_at == received_at
    assert record.to_parser_inputs() == (
        "alerts@example.test",
        "Payment alert",
        "Payment of Rs.750.00 to BOOKMYSHOW via UPI.",
    )


def test_source_record_supports_future_connector_types_without_pipeline_duplication():
    record = SourceRecord(
        user_id="user-1",
        source_type=SourceType.SMS,
        source_message_id="sms-1",
        sender="VM-HDFCBK",
        subject="SMS transaction alert",
        body="Rs.500.00 debited from A/c XX1234.",
    )

    assert record.to_parser_inputs() == (
        "VM-HDFCBK",
        "SMS transaction alert",
        "Rs.500.00 debited from A/c XX1234.",
    )
