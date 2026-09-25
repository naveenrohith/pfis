"""Direct branch coverage for financial-position orchestration routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.api.routes import financial_position as routes
from app.schemas.financial_position import (
    DepositAccountStatementResponse,
    StatementDetectionResponse,
)
from app.services.statement_pdf_extractor import StatementPdfText
from fastapi import HTTPException


class _Request:
    def __init__(self, payload: bytes):
        self.payload = payload

    async def body(self):
        return self.payload


class _Db:
    def __init__(self, *, commit_error: Exception | None = None):
        self.commit_error = commit_error
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def rollback(self):
        self.rollbacks += 1

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error


class _FinancialService:
    behavior = {}

    def __init__(self, _db):
        pass

    def __getattr__(self, name):
        async def call(*_args, **_kwargs):
            value = self.behavior.get(name, f"{name}-result")
            if isinstance(value, BaseException):
                raise value
            return value

        return call


class _AuxService:
    behavior = {}

    def __init__(self, _db):
        pass

    def __getattr__(self, name):
        async def call(*_args, **_kwargs):
            value = self.behavior.get(name, f"{name}-result")
            if isinstance(value, BaseException):
                raise value
            return value

        return call


async def _expect_status(awaitable, status_code):
    with pytest.raises(HTTPException) as caught:
        await awaitable
    assert caught.value.status_code == status_code


def _analysis():
    return {
        "status": "available",
        "source_kind": "generic_table",
        "period_start": None,
        "period_end": None,
        "opening_balance": None,
        "closing_balance": None,
        "row_count": 0,
        "preview_count": 0,
        "omitted_line_count": 0,
        "debit_total": 0,
        "credit_total": 0,
        "rail_totals": {},
        "reconciled": None,
        "confidence": 0.5,
        "reason_codes": [],
        "ruleset_version": "coverage",
        "lines": [],
    }


def _detection():
    return SimpleNamespace(
        institution="hdfc",
        product_type="credit_card",
        format_id="coverage",
        support_status="supported",
        confidence=0.9,
        reason_codes=[],
        activity_types=[],
        detector_version="coverage",
    )


def _detected_response(*, product_type: str, institution: str, support_status: str = "supported"):
    return StatementDetectionResponse(
        institution=institution,
        product_type=product_type,
        format_id="coverage",
        support_status=support_status,
        confidence=0.9,
        reason_codes=[],
        activity_types=[],
        detector_version="coverage",
        analysis=None,
    )


@pytest.mark.asyncio
async def test_statement_detection_review_and_import_routes_cover_success_and_failures(monkeypatch):
    db = _Db()
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    monkeypatch.setattr(routes, "detect_statement", lambda _text: _detection())
    monkeypatch.setattr(routes, "analyze_statement", lambda _text, _detection: _analysis())
    monkeypatch.setattr(
        routes,
        "detect_hdfc_statement_document",
        lambda _text: SimpleNamespace(
            status="recognized",
            issuer="hdfc",
            document_kind="credit_card_statement",
            format_id="coverage",
            import_supported=True,
            import_endpoint="/api/statements/hdfc/text",
            reason_code="recognized_hdfc_credit_card",
            matched_signal_codes=[],
            detector_version="coverage",
        ),
    )
    monkeypatch.setattr(
        routes,
        "_extract_statement_pdf",
        lambda _payload: _pdf_text("statement text with enough content"),
    )

    data = SimpleNamespace(statement_text="statement text with enough content")
    detected = await routes.detect_statement_document(data, "user-1", None)
    assert detected.product_type == "credit_card"
    assert routes._detection_response(data.statement_text).format_id == "coverage"

    class _ReviewService:
        def __init__(self, _db):
            pass

        async def create(self, *args):
            return ("created", args)

        async def list(self, *args, **kwargs):
            return [(args, kwargs)]

        async def get(self, *_args):
            raise LookupError("review missing")

    monkeypatch.setattr(routes, "StatementAnalysisReviewService", _ReviewService)
    review_data = SimpleNamespace(
        statement_text="statement text with enough content", document_fingerprint="f" * 64
    )
    assert (await routes.review_statement_text(review_data, "user-1", None, db))[0] == "created"
    assert await routes.list_statement_analysis_reviews("user-1", "pending_review", 5, None, db)
    await _expect_status(routes.get_statement_analysis_review("missing", "user-1", None, db), 404)
    reviewed = await routes.review_statement_pdf(_Request(b"%PDF bytes"), "user-1", None, db)
    assert reviewed[0] == "created"

    monkeypatch.setattr(routes, "FinancialPositionService", _FinancialService)
    _FinancialService.behavior = {}
    assert await routes.repair_financial_intelligence(
        SimpleNamespace(dry_run=True), "user-1", None, db
    )
    assert await routes.statement_review_items("user-1", None, db)
    assert await routes.deposit_statement_review_items("user-1", None, db)
    assert await routes.review_deposit_statement_line("line", object(), "user-1", None, db)
    assert await routes.statement_line_payment_candidates("line", "user-1", None, db)
    assert await routes.review_statement_line("line", object(), "user-1", None, db)
    assert await routes.update_liability_schedule_item(
        "liability", "item", object(), "user-1", None, db
    )

    _FinancialService.behavior.update(
        {
            "import_hdfc_statement_text": "hdfc-imported",
            "import_generic_credit_card_statement_text": "generic-card",
            "import_generic_deposit_statement_text": "generic-deposit",
        }
    )
    import_data = SimpleNamespace(
        financial_account_id="account-1",
        document_fingerprint="d" * 64,
        statement_text="statement text with enough content",
    )
    assert (
        await routes.import_hdfc_statement_text(import_data, "user-1", None, db)
    ) == "hdfc-imported"
    hdfc_card = routes.CreditCardStatementResponse.model_construct()
    generic_card = routes.CreditCardStatementResponse.model_construct()
    generic_deposit = DepositAccountStatementResponse.model_construct()
    _FinancialService.behavior["import_hdfc_statement_text"] = hdfc_card
    _FinancialService.behavior["import_generic_credit_card_statement_text"] = generic_card
    _FinancialService.behavior["import_generic_deposit_statement_text"] = generic_deposit
    assert (
        await routes._import_detected_statement(db, "user-1", import_data)
    ).product_type == "credit_card"
    _FinancialService.behavior["import_hdfc_statement_text"] = LookupError("account missing")
    await _expect_status(routes.import_hdfc_statement_text(import_data, "user-1", None, db), 404)
    _FinancialService.behavior["import_hdfc_statement_text"] = "hdfc-imported"

    monkeypatch.setattr(
        routes,
        "_detection_response",
        lambda _text: _detected_response(product_type="credit_card", institution="generic"),
    )
    assert (
        await routes._import_detected_statement(db, "user-1", import_data)
    ).credit_card_statement is generic_card
    monkeypatch.setattr(
        routes,
        "_detection_response",
        lambda _text: _detected_response(product_type="deposit_account", institution="hdfc"),
    )
    hdfc_deposit = DepositAccountStatementResponse.model_construct()
    _FinancialService.behavior["import_hdfc_deposit_statement_text"] = hdfc_deposit
    assert (
        await routes._import_detected_statement(db, "user-1", import_data)
    ).deposit_account_statement is hdfc_deposit
    monkeypatch.setattr(
        routes,
        "_detection_response",
        lambda _text: _detected_response(product_type="deposit_account", institution="generic"),
    )
    assert (
        await routes._import_detected_statement(db, "user-1", import_data)
    ).deposit_account_statement is generic_deposit
    monkeypatch.setattr(
        routes,
        "_detection_response",
        lambda _text: _detected_response(
            product_type="credit_card",
            institution="hdfc",
            support_status="recognized_not_supported",
        ),
    )
    with pytest.raises(ValueError, match="not supported"):
        await routes._import_detected_statement(db, "user-1", import_data)
    monkeypatch.setattr(
        routes,
        "_detection_response",
        lambda _text: _detected_response(product_type="unknown", institution="generic"),
    )
    with pytest.raises(ValueError, match="could not be determined"):
        await routes._import_detected_statement(db, "user-1", import_data)

    assert (
        await routes.detect_statement_pdf_document(_Request(b"%PDF bytes"), "user-1", None)
    ).product_type == "credit_card"
    assert (
        await routes.detect_hdfc_statement_document_pdf(_Request(b"%PDF bytes"), "user-1", None)
    ).status == "recognized"


async def _pdf_text(text):
    return StatementPdfText(text=text, extraction_mode="embedded_text")


@pytest.mark.asyncio
async def test_financial_position_route_wrappers_cover_cards_accounts_and_planning(monkeypatch):
    db = _Db()
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    monkeypatch.setattr(routes, "FinancialPositionService", _FinancialService)
    monkeypatch.setattr(routes, "RoadmapService", _FinancialService)
    monkeypatch.setattr(routes, "CardPortfolioUpcomingStateService", _AuxService)
    monkeypatch.setattr(routes, "CardPortfolioPaymentPlanService", _AuxService)
    monkeypatch.setattr(routes, "CardSpendRoutingService", _AuxService)
    monkeypatch.setattr(routes, "CardUtilizationHistoryService", _AuxService)
    monkeypatch.setattr(routes, "CardDueRunwayService", _AuxService)
    monkeypatch.setattr(routes, "CardUpcomingStateService", _AuxService)
    monkeypatch.setattr(routes, "BalanceReconciliationService", _AuxService)
    monkeypatch.setattr(routes, "BalanceForecastService", _AuxService)
    monkeypatch.setattr(routes, "BalanceForecastAccountabilityService", _AuxService)
    _FinancialService.behavior = {}
    _AuxService.behavior = {}

    assert await routes.card_portfolio_upcoming_state("user-1", None, db)
    assert await routes.card_portfolio_payment_plan("user-1", None, db)
    assert await routes.card_portfolio_spend_routing(object(), "user-1", None, db)
    assert await routes.card_overview("card", "user-1", None, db)
    assert await routes.card_utilization_history("card", "user-1", 3, 4, None, db)
    assert await routes.card_due_runway("card", "user-1", None, db)
    assert await routes.card_upcoming_state("card", "user-1", None, db)
    assert await routes.save_card_preferences("card", object(), "user-1", None, db)
    assert await routes.create_card_payment_intent("card", object(), "user-1", None, db)
    assert await routes.update_card_payment_intent("card", "intent", object(), "user-1", None, db)
    assert await routes.create_card_calendar_event("card", object(), "user-1", None, db)
    assert await routes.update_card_calendar_event("card", "event", object(), "user-1", None, db)
    assert await routes.delete_card_calendar_event("card", "event", "user-1", None, db) is None
    assert await routes.account_position("account", "user-1", None, None, None, db)
    assert await routes.account_balance_reconciliations("account", "user-1", None, db)
    assert await routes.account_balance_forecast("account", "user-1", 30, None, db)
    assert await routes.create_account_balance_forecast_snapshot(
        "account", object(), "user-1", None, db
    )
    assert await routes.list_account_balance_forecast_snapshots("account", "user-1", None, db)
    assert await routes.evaluate_account_balance_forecast_outcomes("account", "user-1", None, db)
    assert await routes.list_account_balance_forecast_outcomes("account", "user-1", None, db)
    assert await routes.list_commitments("user-1", None, db)
    assert await routes.create_commitment(object(), "user-1", None, db)
    assert await routes.update_commitment("commitment", object(), "user-1", None, db)
    assert await routes.cash_plan("user-1", None, db)
    assert await routes.upsert_cash_plan(object(), "user-1", None, db)
    assert await routes.list_reserves("user-1", None, db)
    assert await routes.create_reserve(object(), "user-1", None, db)
    assert await routes.update_reserve("reserve", object(), "user-1", None, db)
    assert await routes.list_liabilities("user-1", None, db)
    assert await routes.liability_overview("user-1", None, db)
    assert await routes.create_liability(object(), "user-1", None, db)
    assert await routes.liability_schedule("liability", "user-1", None, db)
    assert await routes.confirm_liability_schedule("liability", object(), "user-1", None, db)
    assert await routes.get_statement("statement", "user-1", None, db)

    _FinancialService.behavior.update(
        {
            "card_overview": LookupError("missing"),
            "card_payment_candidates": ValueError("invalid"),
            "update_commitment": None,
            "update_reserve": None,
            "account_position": None,
            "upsert_cash_plan": ValueError("invalid"),
            "create_liability": ValueError("invalid"),
            "statement": LookupError("missing"),
        }
    )
    _AuxService.behavior["create_snapshot"] = LookupError("missing")
    await _expect_status(routes.card_overview("card", "user-1", None, db), 404)
    await _expect_status(routes.statement_line_payment_candidates("line", "user-1", None, db), 422)
    await _expect_status(routes.update_commitment("commitment", object(), "user-1", None, db), 404)
    await _expect_status(routes.update_reserve("reserve", object(), "user-1", None, db), 404)
    await _expect_status(routes.account_position("account", "user-1", None, None, None, db), 404)
    await _expect_status(
        routes.create_account_balance_forecast_snapshot("account", object(), "user-1", None, db),
        404,
    )
    await _expect_status(routes.upsert_cash_plan(object(), "user-1", None, db), 422)
    await _expect_status(routes.create_liability(object(), "user-1", None, db), 422)
    await _expect_status(routes.get_statement("statement", "user-1", None, db), 404)

    _AuxService.behavior.update(
        {
            "history": ValueError("bad"),
            "runway": None,
            "upcoming": LookupError("missing"),
            "list_for_account": None,
            "forecast": None,
        }
    )
    await _expect_status(routes.card_utilization_history("card", "user-1", 3, 4, None, db), 422)
    await _expect_status(routes.card_due_runway("card", "user-1", None, db), 404)
    await _expect_status(routes.card_upcoming_state("card", "user-1", None, db), 404)
    await _expect_status(routes.account_balance_reconciliations("account", "user-1", None, db), 404)
    await _expect_status(routes.account_balance_forecast("account", "user-1", 30, None, db), 404)


@pytest.mark.asyncio
async def test_statement_upload_guards_and_rejection_telemetry_cover_all_categories(monkeypatch):
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    db = _Db()
    request = _Request(b"not-pdf")
    await _expect_status(routes.detect_statement_pdf_document(request, "user-1", None), 422)
    await _expect_status(routes.detect_hdfc_statement_document_pdf(request, "user-1", None), 422)
    await _expect_status(routes.review_statement_pdf(request, "user-1", None, db), 422)
    await _expect_status(
        routes.import_detected_statement_pdf(request, "account", "user-1", None, db), 422
    )
    await _expect_status(
        routes.import_hdfc_statement_pdf(request, "account", "user-1", None, db), 422
    )

    huge = _Request(b"x" * (10 * 1024 * 1024 + 1))
    await _expect_status(routes.detect_statement_pdf_document(huge, "user-1", None), 413)
    await _expect_status(routes.detect_hdfc_statement_document_pdf(huge, "user-1", None), 413)
    await _expect_status(routes.review_statement_pdf(huge, "user-1", None, db), 413)
    await _expect_status(
        routes.import_detected_statement_pdf(huge, "account", "user-1", None, db), 413
    )
    await _expect_status(routes.import_hdfc_statement_pdf(huge, "account", "user-1", None, db), 413)

    async def unavailable(_payload):
        raise ImportError("extractor unavailable")

    monkeypatch.setattr(routes, "_extract_statement_pdf", unavailable)
    pdf = _Request(b"%PDF bytes")
    await _expect_status(routes.detect_statement_pdf_document(pdf, "user-1", None), 503)
    await _expect_status(routes.detect_hdfc_statement_document_pdf(pdf, "user-1", None), 503)
    await _expect_status(routes.review_statement_pdf(pdf, "user-1", None, db), 503)
    await _expect_status(
        routes.import_detected_statement_pdf(pdf, "account", "user-1", None, db), 503
    )
    await _expect_status(routes.import_hdfc_statement_pdf(pdf, "account", "user-1", None, db), 503)

    async def invalid(_payload):
        raise ValueError("scanned or empty statement")

    monkeypatch.setattr(routes, "_extract_statement_pdf", invalid)
    await _expect_status(routes.detect_statement_pdf_document(pdf, "user-1", None), 422)
    await _expect_status(routes.detect_hdfc_statement_document_pdf(pdf, "user-1", None), 422)
    await _expect_status(routes.review_statement_pdf(pdf, "user-1", None, db), 422)
    await _expect_status(
        routes.import_detected_statement_pdf(pdf, "account", "user-1", None, db), 422
    )
    await _expect_status(routes.import_hdfc_statement_pdf(pdf, "account", "user-1", None, db), 422)

    details = [
        "encrypted PDF",
        "scanned PDF",
        "statement exceeds the 10 MB limit",
        "upload is not a PDF",
        "PDF statement extractor is unavailable",
        "different credit-card identity",
        "masked card identity mismatch",
        "missing billing period",
        "supported HDFC digital layout",
        "currency mismatch",
        "credit-card account required",
        "conflicts with an existing statement",
        "import is incomplete",
        "other validation failure",
    ]
    assert {routes._statement_rejection_code(item) for item in details} == {
        "encrypted_pdf",
        "scanned_or_empty_pdf",
        "payload_too_large",
        "not_pdf",
        "extractor_unavailable",
        "account_identity_mismatch",
        "missing_billing_period",
        "unsupported_layout",
        "ledger_currency_mismatch",
        "wrong_account_type",
        "duplicate_statement",
        "incomplete_duplicate",
        "validation_failed",
    }
    failing_db = _Db(commit_error=RuntimeError("telemetry unavailable"))
    await routes._record_statement_rejection(
        failing_db, "user-1", "other validation failure", format_name="statement_auto"
    )
    assert failing_db.rollbacks == 2
