"""Direct branch coverage for low-traffic CRUD and orchestration routes."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from app.api.routes import budgets, insights, transactions, users
from app.schemas.user import UserCreate, UserUpdate
from fastapi import HTTPException


class _Result:
    def __init__(self, *, scalar=None, rows=(), one=None):
        self.scalar_value = scalar
        self.rows = list(rows)
        self.one_value = one

    def scalar_one_or_none(self):
        return self.scalar_value

    def all(self):
        return list(self.rows)

    def scalars(self):
        return self

    def one(self):
        return self.one_value


class _Db:
    def __init__(self, *, scalar_values=(), execute_values=(), scalar_results=()):
        self.scalar_values = list(scalar_values)
        self.execute_values = list(execute_values)
        self.scalar_results = list(scalar_results)
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def execute(self, _statement):
        return self.execute_values.pop(0) if self.execute_values else _Result()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, item):
        if getattr(item, "id", None) is None:
            item.id = "generated-id"
        if getattr(item, "created_at", None) is None:
            item.created_at = datetime(2026, 9, 20, tzinfo=UTC)

    def add(self, item):
        self.added.append(item)

    async def delete(self, item):
        self.deleted.append(item)


async def _expect_status(awaitable, status_code):
    with pytest.raises(HTTPException) as caught:
        await awaitable
    assert caught.value.status_code == status_code


@pytest.mark.asyncio
async def test_budget_routes_cover_missing_duplicate_tracking_and_status_order(monkeypatch):
    monkeypatch.setattr(budgets, "resolve_user_scope", lambda user_id, _current: user_id)
    category = SimpleNamespace(id="cat-1")
    created_db = _Db(
        scalar_values=[category],
        execute_values=[_Result(scalar=None)],
    )
    result = await budgets.create_budget(
        SimpleNamespace(category_id="cat-1", monthly_limit=1000), "user-1", None, created_db
    )
    assert result["status"] == "created"
    assert created_db.commits == 1

    await _expect_status(
        budgets.create_budget(
            SimpleNamespace(category_id="missing", monthly_limit=1000),
            "user-1",
            None,
            _Db(scalar_values=[None]),
        ),
        404,
    )
    await _expect_status(
        budgets.create_budget(
            SimpleNamespace(category_id="cat-1", monthly_limit=1000),
            "user-1",
            None,
            _Db(scalar_values=[category], execute_values=[_Result(scalar=object())]),
        ),
        409,
    )

    empty = await budgets.track_budgets("user-1", 9, 2026, None, _Db(execute_values=[_Result()]))
    assert empty == []
    budget_rows = [
        (SimpleNamespace(id="over", category_id="cat-1", monthly_limit=100), "Over", "o"),
        (SimpleNamespace(id="warning", category_id="cat-2", monthly_limit=100), "Warning", "w"),
        (SimpleNamespace(id="under", category_id="cat-3", monthly_limit=100), "Under", "u"),
        (SimpleNamespace(id="zero", category_id="cat-4", monthly_limit=0), "Zero", "z"),
    ]
    spend_rows = [
        SimpleNamespace(category_id="cat-1", total=120),
        SimpleNamespace(category_id="cat-2", total=80),
        SimpleNamespace(category_id="cat-3", total=25),
        SimpleNamespace(category_id="cat-4", total=5),
    ]
    tracked = await budgets.track_budgets(
        "user-1",
        9,
        2026,
        None,
        _Db(execute_values=[_Result(rows=budget_rows), _Result(rows=spend_rows)]),
    )
    assert [item.status for item in tracked] == ["over", "warning", "under", "under"]

    budget = SimpleNamespace(id="budget-1", user_id="user-1", monthly_limit=100)
    monkeypatch.setattr(budgets, "ensure_user_owns_resource", lambda *_: None)
    assert await budgets.update_budget(
        "budget-1",
        SimpleNamespace(monthly_limit=200),
        None,
        _Db(execute_values=[_Result(scalar=budget)]),
    ) == {
        "id": "budget-1",
        "monthly_limit": 200,
        "status": "updated",
    }
    await _expect_status(
        budgets.delete_budget("missing", None, _Db(execute_values=[_Result()])), 404
    )


@pytest.mark.asyncio
async def test_user_routes_cover_auth_modes_duplicate_profile_and_retention_job(monkeypatch):
    monkeypatch.setattr(users, "resolve_user_scope", lambda user_id, _current: user_id)
    monkeypatch.setattr(users, "normalize_email", lambda value: value.strip().lower())
    monkeypatch.setattr(
        users,
        "settings",
        SimpleNamespace(
            is_production=False,
            AUTH_REQUIRED=False,
            SESSION_COOKIE_NAME="session",
            CSRF_COOKIE_NAME="csrf",
            OAUTH_COOKIE_NAME="oauth",
        ),
    )
    try:
        db = _Db(scalar_values=[None])
        created = await users.create_user(UserCreate(email="USER@EXAMPLE.COM", name="User"), db)
        assert created.email == "user@example.com"
        await _expect_status(
            users.create_user(
                UserCreate(email="duplicate@example.com", name="User"),
                _Db(execute_values=[_Result(scalar=object())]),
            ),
            409,
        )

        current = SimpleNamespace(id="user-1")
        assert await users.list_users(current, _Db()) == [current]
        listed = [SimpleNamespace(id="user-2")]
        assert await users.list_users(None, _Db(execute_values=[_Result(rows=listed)])) == listed
        user = SimpleNamespace(
            id="user-1", raw_email_retention_days=None, name="Old", timezone="UTC"
        )
        db = _Db(scalar_values=[user])
        jobs_created = []

        async def create_job(*args, **kwargs):
            job = SimpleNamespace(id="job-1")
            jobs_created.append((args, kwargs))
            return job

        monkeypatch.setattr(users, "create_job", create_job)
        monkeypatch.setattr(users, "schedule_job", lambda job_id: jobs_created.append(job_id))
        updated = await users.update_user(
            "user-1", UserUpdate(name="New", raw_email_retention_days=90), None, db
        )
        assert updated.name == "New"
        assert jobs_created[-1] == "job-1"
    finally:
        monkeypatch.setattr(
            users,
            "settings",
            SimpleNamespace(
                is_production=True,
                AUTH_REQUIRED=False,
                SESSION_COOKIE_NAME="session",
                CSRF_COOKIE_NAME="csrf",
                OAUTH_COOKIE_NAME="oauth",
            ),
        )
    await _expect_status(
        users.create_user(UserCreate(email="prod@example.com", name="Prod"), _Db()), 404
    )


@pytest.mark.asyncio
async def test_user_routes_cover_not_found_auth_and_account_delete_guards(monkeypatch):
    monkeypatch.setattr(users, "resolve_user_scope", lambda user_id, _current: user_id)
    monkeypatch.setattr(
        users,
        "settings",
        SimpleNamespace(
            is_production=False,
            AUTH_REQUIRED=True,
            SESSION_COOKIE_NAME="session",
            CSRF_COOKIE_NAME="csrf",
            OAUTH_COOKIE_NAME="oauth",
        ),
    )
    try:
        await _expect_status(users.list_users(None, _Db()), 401)
    finally:
        users.settings.AUTH_REQUIRED = False
    await _expect_status(users.get_user("missing", None, _Db(execute_values=[_Result()])), 404)
    await _expect_status(
        users.update_user("missing", UserUpdate(name="x"), None, _Db(scalar_values=[None])),
        404,
    )

    request = SimpleNamespace(cookies={})
    response = SimpleNamespace(delete_cookie=lambda *args, **kwargs: None)
    current = SimpleNamespace(id="user-1", email="u@example.com")
    monkeypatch.setattr(users, "has_recent_authentication", lambda *_: _async_false())
    with pytest.raises(HTTPException) as caught:
        await users.delete_user_account.__wrapped__(
            request,
            response,
            "user-1",
            SimpleNamespace(confirmation="DELETE u@example.com"),
            current,
            _Db(),
        )
    assert caught.value.status_code == 403

    monkeypatch.setattr(users, "has_recent_authentication", lambda *_: _async_true())
    await _expect_status(
        users.delete_user_account.__wrapped__(
            request,
            response,
            "user-1",
            SimpleNamespace(confirmation="wrong confirmation"),
            current,
            _Db(),
        ),
        422,
    )


async def _async_true():
    return True


async def _async_false():
    return False


class _TransactionService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def _call(self, name, *args, **kwargs):
        value = self.behavior.get(name)
        if isinstance(value, BaseException):
            raise value
        return value

    async def create_transaction(self, *args, **kwargs):
        return await self._call("create_transaction", *args, **kwargs)

    async def get_transactions(self, *args, **kwargs):
        return await self._call("get_transactions", *args, **kwargs)

    async def get_transaction_count(self, *args, **kwargs):
        return await self._call("get_transaction_count", *args, **kwargs)

    async def get_monthly_summary(self, *args, **kwargs):
        return await self._call("get_monthly_summary", *args, **kwargs)

    async def get_transaction_by_id(self, *args, **kwargs):
        return await self._call("get_transaction_by_id", *args, **kwargs)

    async def bulk_update_transactions(self, *args, **kwargs):
        return await self._call("bulk_update_transactions", *args, **kwargs)

    async def list_splits(self, *args, **kwargs):
        return await self._call("list_splits", *args, **kwargs)

    async def replace_splits(self, *args, **kwargs):
        return await self._call("replace_splits", *args, **kwargs)

    async def link_atm_withdrawal_to_cash(self, *args, **kwargs):
        return await self._call("link_atm_withdrawal_to_cash", *args, **kwargs)

    async def update_transaction(self, *args, **kwargs):
        return await self._call("update_transaction", *args, **kwargs)

    async def delete_transaction(self, *args, **kwargs):
        return await self._call("delete_transaction", *args, **kwargs)


class _TransferService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def _call(self, name, *args, **kwargs):
        value = self.behavior.get(name)
        if isinstance(value, BaseException):
            raise value
        return value

    async def list_candidates(self, *args, **kwargs):
        return await self._call("list_candidates", *args, **kwargs)

    async def link_pair(self, *args, **kwargs):
        return await self._call("link_pair", *args, **kwargs)


@pytest.mark.asyncio
async def test_transaction_routes_cover_filters_ownership_and_error_mapping(monkeypatch):
    monkeypatch.setattr(transactions, "TransactionService", _TransactionService)
    monkeypatch.setattr(transactions, "TransactionTransferService", _TransferService)
    monkeypatch.setattr(transactions, "resolve_user_scope", lambda user_id, _current: user_id)
    monkeypatch.setattr(transactions, "ensure_user_owns_resource", lambda *_: None)
    _TransactionService.behavior = {
        "create_transaction": "created",
        "get_transactions": [],
        "get_transaction_count": 0,
        "get_monthly_summary": {"total_spend": 0},
        "get_transaction_by_id": SimpleNamespace(id="txn-1", user_id="user-1"),
        "bulk_update_transactions": {"updated_count": 1},
        "list_splits": [],
        "replace_splits": ["split"],
        "link_atm_withdrawal_to_cash": "atm",
        "update_transaction": "updated",
        "delete_transaction": True,
    }
    _TransferService.behavior = {"list_candidates": ["candidate"], "link_pair": "linked"}
    db = object()
    data = SimpleNamespace(
        merchant_normalized=None,
        merchant_raw=None,
        model_copy=lambda **kwargs: SimpleNamespace(),
    )
    assert await transactions.create_transaction("user-1", data, None, db) == "created"
    response = await transactions.list_transactions(
        "user-1",
        month=9,
        year=2026,
        q="merchant",
        text="override",
        transaction_type="debit",
        type_filter="credit",
        reviewed=None,
        review_state="reviewed",
        sort="amount",
        direction="asc",
        current_user=None,
        db=db,
    )
    assert response.headers["X-Total-Count"] == "0"
    assert await transactions.get_monthly_summary("user-1", 9, 2026, None, db) == {"total_spend": 0}
    assert await transactions.list_transfer_match_candidates("user-1", None, 10, None, db) == [
        "candidate"
    ]
    assert (
        await transactions.link_transfer_match(
            "txn-1",
            SimpleNamespace(counterparty_transaction_id="txn-2", kind="account_transfer"),
            "user-1",
            None,
            db,
        )
        == "linked"
    )
    assert await transactions.bulk_update_transactions(SimpleNamespace(), "user-1", None, db) == {
        "updated_count": 1
    }
    fetched = await transactions.get_transaction("txn-1", None, db)
    assert fetched.id == "txn-1"
    assert await transactions.list_transaction_splits("txn-1", "user-1", None, db) == []
    assert await transactions.replace_transaction_splits(
        "txn-1", SimpleNamespace(), "user-1", None, db
    ) == ["split"]
    assert (
        await transactions.link_atm_withdrawal_to_cash(
            "txn-1", SimpleNamespace(), "user-1", None, db
        )
        == "atm"
    )
    assert await transactions.update_transaction("txn-1", SimpleNamespace(), None, db) == "updated"
    assert await transactions.delete_transaction("txn-1", None, db) is None

    _TransactionService.behavior["create_transaction"] = ValueError("duplicate")
    await _expect_status(transactions.create_transaction("user-1", data, None, db), 409)
    _TransferService.behavior["list_candidates"] = LookupError("account missing")
    await _expect_status(
        transactions.list_transfer_match_candidates("user-1", None, 10, None, db), 404
    )
    _TransferService.behavior["link_pair"] = LookupError("transaction missing")
    await _expect_status(
        transactions.link_transfer_match(
            "txn-1",
            SimpleNamespace(counterparty_transaction_id="x", kind="account_transfer"),
            "user-1",
            None,
            db,
        ),
        404,
    )
    _TransferService.behavior["link_pair"] = ValueError("invalid pair")
    await _expect_status(
        transactions.link_transfer_match(
            "txn-1",
            SimpleNamespace(counterparty_transaction_id="x", kind="account_transfer"),
            "user-1",
            None,
            db,
        ),
        422,
    )
    _TransactionService.behavior["get_transaction_by_id"] = None
    await _expect_status(transactions.get_transaction("missing", None, db), 404)
    _TransactionService.behavior["list_splits"] = LookupError("not found")
    await _expect_status(transactions.list_transaction_splits("missing", "user-1", None, db), 404)
    _TransactionService.behavior["replace_splits"] = LookupError("not found")
    await _expect_status(
        transactions.replace_transaction_splits("missing", SimpleNamespace(), "user-1", None, db),
        404,
    )
    _TransactionService.behavior["replace_splits"] = ValueError("bad split")
    await _expect_status(
        transactions.replace_transaction_splits("missing", SimpleNamespace(), "user-1", None, db),
        422,
    )


class _InsightsService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def _call(self, name, *args, **kwargs):
        value = self.behavior.get(name, [])
        if isinstance(value, BaseException):
            raise value
        return value

    async def generate_insights(self, *args, **kwargs):
        return await self._call("generate_insights", *args, **kwargs)

    async def anomalies_for_period(self, *args, **kwargs):
        return await self._call("anomalies_for_period", *args, **kwargs)

    async def anomaly_samples_for_period(self, *args, **kwargs):
        return await self._call("anomaly_samples_for_period", *args, **kwargs)


class _AdjudicationService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def record(self, *args, **kwargs):
        return self.behavior.get("record")

    async def list_for_user(self, *args, **kwargs):
        return self.behavior.get("list", [])


@pytest.mark.asyncio
async def test_insights_routes_cover_defaults_samples_and_missing_anomalies(monkeypatch):
    monkeypatch.setattr(insights, "resolve_user_scope", lambda user_id, _current: user_id)
    monkeypatch.setattr(insights, "InsightsService", _InsightsService)
    monkeypatch.setattr(insights, "AnomalyAdjudicationService", _AdjudicationService)
    monkeypatch.setattr(insights, "user_financial_today", lambda *_: _today())
    sample = SimpleNamespace(id="s-1")
    _InsightsService.behavior = {
        "generate_insights": "insights",
        "anomalies_for_period": [SimpleNamespace(id="a-1")],
        "anomaly_samples_for_period": [sample],
    }
    _AdjudicationService.behavior = {"record": "recorded", "list": ["decision"]}
    assert await insights.get_insights("user-1", None, None, None, object()) == "insights"
    assert (
        await insights.adjudicate_anomaly(
            "a-1", SimpleNamespace(decision="confirm", note=None), "user-1", 9, 2026, None, object()
        )
        == "recorded"
    )
    samples = await insights.get_anomaly_samples("user-1", 9, 2026, 4, None, object())
    assert samples[0].id == "s-1"
    assert (
        await insights.adjudicate_anomaly_sample(
            "s-1", SimpleNamespace(decision="dismiss", note="n"), "user-1", 9, 2026, None, object()
        )
        == "recorded"
    )
    assert await insights.list_anomaly_adjudications("user-1", 100, None, object()) == ["decision"]
    _InsightsService.behavior["anomalies_for_period"] = []
    await _expect_status(
        insights.adjudicate_anomaly(
            "missing",
            SimpleNamespace(decision="confirm", note=None),
            "user-1",
            9,
            2026,
            None,
            object(),
        ),
        404,
    )
    _InsightsService.behavior["anomaly_samples_for_period"] = []
    await _expect_status(
        insights.adjudicate_anomaly_sample(
            "missing",
            SimpleNamespace(decision="confirm", note=None),
            "user-1",
            9,
            2026,
            None,
            object(),
        ),
        404,
    )


async def _today():
    return date(2026, 9, 20)
