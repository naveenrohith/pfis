"""Helpers for enforcing request-level SQL statement budgets in pytest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.engine import Engine

BUDGET_FILE = Path(__file__).parent / "fixtures" / "query_budgets.json"


@dataclass(frozen=True)
class RequestQueryCount:
    response: Response
    statements: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.statements)


class QueryRecorder:
    """Count SQL statements executed on the sync engine under an async engine."""

    def __init__(self, sync_engine: Engine) -> None:
        self._sync_engine = sync_engine
        self._statements: list[str] = []

    @property
    def statements(self) -> tuple[str, ...]:
        return tuple(self._statements)

    def _before_cursor_execute(
        self,
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        self._statements.append(statement)

    def __enter__(self) -> QueryRecorder:
        event.listen(
            self._sync_engine,
            "before_cursor_execute",
            self._before_cursor_execute,
        )
        return self

    def __exit__(self, *_exc_info: object) -> None:
        event.remove(
            self._sync_engine,
            "before_cursor_execute",
            self._before_cursor_execute,
        )


def load_query_budgets() -> dict[str, Any]:
    return json.loads(BUDGET_FILE.read_text(encoding="utf-8"))


async def count_request_statements(
    client: AsyncClient,
    sync_engine: Engine,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> RequestQueryCount:
    with QueryRecorder(sync_engine) as recorder:
        response = await client.request(method, url, json=json_body)
    return RequestQueryCount(response=response, statements=recorder.statements)
