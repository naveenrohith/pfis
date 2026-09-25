from __future__ import annotations

from datetime import date

from app.services.transaction_service import TransactionService

from tests.pytest.helpers import create_user


class _EmptyResult:
    def scalar_one_or_none(self):
        return None


async def test_monthly_summary_cache_insert_tolerates_concurrent_writer(
    client, test_session_factory
):
    user = await create_user(client, "summary-race")
    today = date.today()

    async with test_session_factory() as first:
        expected = await TransactionService(first).get_monthly_summary(
            user["id"], today.month, today.year
        )

    async with test_session_factory() as second:
        original_execute = second.execute
        calls = {"count": 0}

        async def execute_missing_cache_once(statement, *args, **kwargs):
            sql = str(statement).lower()
            if not calls["count"] and sql.startswith("select") and "monthly_summaries" in sql:
                calls["count"] += 1
                # Simulate a writer that cached the period after this request's lookup.
                return _EmptyResult()
            return await original_execute(statement, *args, **kwargs)

        second.execute = execute_missing_cache_once  # type: ignore[method-assign]
        summary = await TransactionService(second).get_monthly_summary(
            user["id"], today.month, today.year
        )

    assert calls["count"] == 1
    assert summary["month"] == expected["month"]
    assert summary["total_spend"] == expected["total_spend"]
