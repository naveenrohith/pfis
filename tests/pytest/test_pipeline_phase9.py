"""Phase 9 parser pipeline contracts."""

# pyright: reportMissingImports=false

from __future__ import annotations

from datetime import date

from app.models.email import RawEmail
from app.services.parser import extractors
from app.services.parser.base_parser import ParseResult, TransactionTypeEnum
from app.services.parser.identity import build_identity
from app.services.parser.pipeline import (
    get_pipeline_metrics,
    list_parse_failures,
    process_raw_emails,
    reprocess_raw_emails,
)
from app.services.parser.registry import get_parser_registry
from app.services.parser.validation import validate_parse_result

from tests.pytest.helpers import create_user


def test_field_extractors_preserve_existing_pattern_outputs():
    text = (
        "INR 499.00 has been debited from your ICICI Bank Account XX5678 "
        "on 05-May-2026 towards NETFLIX.COM on UPI Ref 412399999991"
    )

    fields = extractors.extract_all(text)

    assert fields.amount == 499.0
    assert fields.currency == "INR"
    assert fields.transaction_type == TransactionTypeEnum.DEBIT
    assert fields.merchant_raw == "NETFLIX"
    assert fields.date == date(2026, 5, 5)
    assert fields.account_last4 == "5678"
    assert fields.reference_id is not None


def test_parser_result_exposes_field_confidence_without_changing_overall_score():
    registry = get_parser_registry()
    result = registry.parse_email(
        "alerts@example-payments.test",
        "Debit alert",
        "Rs.99.00 has been debited.",
    )

    assert result.confidence_score == 0.6
    assert result.field_confidence["amount"] == 1.0
    assert result.field_confidence["type"] == 1.0
    assert result.field_confidence["merchant"] < 1.0
    assert result.parser_name == "GenericParser"


def test_validation_layer_flags_missing_date_but_allows_low_confidence_parse():
    result = ParseResult(
        amount=99.0,
        transaction_type=TransactionTypeEnum.DEBIT,
        merchant_raw="BANK DEBIT",
        merchant_source="generic",
    )
    result.compute_confidence()

    issues = validate_parse_result(result)

    assert result.confidence_score == 0.6
    assert [issue.code for issue in issues] == ["missing_date"]


def test_identity_uses_reference_level_before_fingerprint_level():
    with_reference = build_identity(
        user_id="user-1",
        amount=100.0,
        transaction_date=date(2026, 5, 1),
        merchant="Netflix",
        reference_id="ABC12345",
        account_last4="1111",
    )
    without_reference = build_identity(
        user_id="user-1",
        amount=100.0,
        transaction_date=date(2026, 5, 1),
        merchant="Netflix",
        reference_id=None,
        account_last4="1111",
    )

    assert with_reference.level == "reference"
    assert with_reference.reference_key is not None
    assert without_reference.level == "fingerprint"
    assert without_reference.fuzzy_key is not None


async def test_pipeline_records_dlq_metadata_and_metrics(client, test_session_factory):
    user = await create_user(client, "phase9dlq")

    async with test_session_factory() as db:
        db.add(
            RawEmail(
                user_id=user["id"],
                gmail_message_id=f"{user['id']}:missing-date",
                sender="alerts@example-payments.test",
                subject="Debit alert",
                body="Rs.99.00 has been debited.",
            )
        )
        await db.commit()

        stats = await process_raw_emails(db, user["id"])
        failures = await list_parse_failures(db, user["id"], resolved=False)
        metrics = await get_pipeline_metrics(db, user["id"])

    assert stats["parsed_failed"] == 1
    assert failures["total"] == 1
    failure = failures["failures"][0]
    assert failure["failure_stage"] == "validate"
    assert failure["failure_code"] == "missing_date"
    assert "Rs.99.00 has been debited" not in str(failure["diagnostic"])
    assert metrics["dlq_size"] == 1
    assert metrics["parse_attempts"] >= 1


async def test_reprocess_dry_run_compares_without_mutating_transactions(
    client, test_session_factory
):
    user = await create_user(client, "phase9replay")

    async with test_session_factory() as db:
        email = RawEmail(
            user_id=user["id"],
            gmail_message_id=f"{user['id']}:replay",
            sender="alerts@icicibank.com",
            subject="ICICI Bank Alert",
            body=(
                "INR 499.00 has been debited from your ICICI Bank Account XX5678 "
                "on 05-May-2026 towards NETFLIX.COM on UPI"
            ),
            processed_flag=True,
        )
        db.add(email)
        await db.commit()

        result = await reprocess_raw_emails(
            db,
            user["id"],
            email_ids=[email.id],
            dry_run=True,
        )

    assert result["dry_run"] is True
    assert result["email_count"] == 1
    assert result["comparisons"][0]["new_result"]["amount"] == 499.0
