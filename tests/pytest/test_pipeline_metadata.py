"""Pipeline metadata regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

from app.models.email import RawEmail
from app.models.sync import ParseFailure
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
