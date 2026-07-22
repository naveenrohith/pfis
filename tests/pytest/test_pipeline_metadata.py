"""Pipeline metadata regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

from app.models.email import RawEmail
from app.models.sync import ParseFailure
from app.models.transaction import Transaction
from app.services.domain_events import domain_event_dispatcher
from app.services.parser.pipeline import process_raw_emails
from sqlalchemy import select

from tests.pytest.helpers import create_user


async def test_pipeline_result_includes_parser_metadata_for_generic_fallback(
    client,
    test_session_factory,
):
    user = await create_user(client, "pipelinegeneric")

    async with test_session_factory() as db:
        db.add(
            RawEmail(
                user_id=user["id"],
                gmail_message_id=f"{user['id']}:generic-fallback",
                sender="alerts@example-payments.test",
                subject="Payment successful",
                body=(
                    "Payment of Rs.750.00 paid to BOOKMYSHOW via UPI on 07-05-2026. "
                    "Ref No: 555555123456."
                ),
            )
        )
        await db.commit()

        stats = await process_raw_emails(db, user["id"])

    assert stats["stored"] == 1
    assert stats["parsed_success"] == 1
    assert stats["results"][0]["status"] == "stored"
    assert stats["results"][0]["bank"] == "GENERIC"
    assert stats["results"][0]["parser_version"] == 1
    assert stats["results"][0]["parser_fallback"] is True


async def test_pipeline_result_includes_parser_metadata_for_invalid_parse(
    client,
    test_session_factory,
):
    user = await create_user(client, "pipelineinvalid")

    async with test_session_factory() as db:
        db.add(
            RawEmail(
                user_id=user["id"],
                gmail_message_id=f"{user['id']}:invalid-parse",
                sender="alerts@hdfcbank.net",
                subject="HDFC transaction alert",
                body="Transaction of Rs.123.00 was processed on 08-05-2026.",
            )
        )
        await db.commit()

        stats = await process_raw_emails(db, user["id"])

        failure_result = await db.execute(select(ParseFailure))
        failure = failure_result.scalar_one()

    result = stats["results"][0]
    assert stats["parsed_failed"] == 1
    assert stats["stored"] == 0
    assert result["status"] == "parse_failed"
    assert result["bank"] == "HDFC"
    assert result["parser_version"] == 2
    assert result["parser_fallback"] is False
    assert failure.parser_version == 2
    assert failure.resolved is False
    assert failure.error_message == "Invalid parse: amount=123.0, type=None"


async def test_pipeline_rolls_back_ledger_when_post_parse_step_fails(
    client,
    test_session_factory,
    monkeypatch,
):
    user = await create_user(client, "pipelineatomic")

    secret = "simulated-event-secret-must-not-leak"

    async def fail_publish(_event):
        raise RuntimeError(secret)

    monkeypatch.setattr(domain_event_dispatcher, "publish", fail_publish)

    async with test_session_factory() as db:
        email = RawEmail(
            user_id=user["id"],
            gmail_message_id=f"{user['id']}:atomic-failure",
            sender="alerts@example-payments.test",
            subject="Payment successful",
            body=(
                "Payment of Rs.750.00 paid to BOOKMYSHOW via UPI on 07-05-2026. "
                "Ref No: 555555654321."
            ),
        )
        db.add(email)
        await db.commit()

        stats = await process_raw_emails(db, user["id"])
        transactions = list((await db.scalars(select(Transaction))).all())
        failures = list((await db.scalars(select(ParseFailure))).all())
        await db.refresh(email)

    assert stats["stored"] == 0
    assert stats["parsed_failed"] == 1
    assert transactions == []
    assert len(failures) == 1
    assert failures[0].error_message == "Pipeline processing failed"
    assert stats["results"][0]["error"] == "pipeline_processing_failed"
    assert secret not in str(stats)
    assert secret not in failures[0].error_message
    assert email.processed_flag is True


async def test_pipeline_duplicate_result_preserves_parse_metadata(
    client,
    test_session_factory,
):
    user = await create_user(client, "pipelinedupe")
    duplicate_body = (
        "Payment of Rs.750.00 paid to BOOKMYSHOW via UPI on 07-05-2026. Ref No: 555555123456."
    )

    async with test_session_factory() as db:
        for suffix in ("a", "b"):
            db.add(
                RawEmail(
                    user_id=user["id"],
                    gmail_message_id=f"{user['id']}:generic-fallback-{suffix}",
                    sender="alerts@example-payments.test",
                    subject="Payment successful",
                    body=duplicate_body,
                )
            )
        await db.commit()

        stats = await process_raw_emails(db, user["id"])

    statuses = {result["status"] for result in stats["results"]}
    duplicate_result = next(
        result for result in stats["results"] if result["status"] == "duplicate"
    )

    assert stats["stored"] == 1
    assert stats["duplicates"] == 1
    assert statuses == {"stored", "duplicate"}
    assert duplicate_result["bank"] == "GENERIC"
    assert duplicate_result["parser_version"] == 1
    assert duplicate_result["parser_fallback"] is True


async def test_pipeline_rejects_financial_email_without_transaction_date(
    client,
    test_session_factory,
):
    """A transaction-shaped email with an amount but no date must not become a
    transaction stamped with today's date; it goes to the parse-failure queue."""
    user = await create_user(client, "pipelinenodate")

    async with test_session_factory() as db:
        db.add(
            RawEmail(
                user_id=user["id"],
                gmail_message_id=f"{user['id']}:txn-no-date",
                sender="alerts@hdfcbank.net",
                subject="HDFC transaction alert",
                body=(
                    "Rs.1000.00 has been debited from your A/c XX1234 via UPI. "
                    "UPI Ref No 412399999999."
                ),
            )
        )
        await db.commit()

        stats = await process_raw_emails(db, user["id"])

        failure_result = await db.execute(select(ParseFailure))
        failure = failure_result.scalar_one()

    result = stats["results"][0]
    assert stats["stored"] == 0
    assert stats["parsed_failed"] == 1
    assert result["status"] == "parse_failed"
    assert failure.error_message == "Invalid parse: missing transaction date"
    assert failure.resolved is False
