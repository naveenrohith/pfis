"""Verified financial-position APIs: account reconciliation, planning and statements."""

import asyncio
import hashlib
import json
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.sync import ConnectorAuditEvent
from app.models.user import User
from app.schemas.balance_forecast import (
    AccountBalanceForecastEvaluationResponse,
    AccountBalanceForecastOutcomeResponse,
    AccountBalanceForecastResponse,
    AccountBalanceForecastSnapshotCreate,
    AccountBalanceForecastSnapshotResponse,
)
from app.schemas.financial_position import (
    AccountPositionResponse,
    BalanceReconciliationResponse,
    CardDueRunwayResponse,
    CardOverviewResponse,
    CardPaymentIntentCreate,
    CardPaymentIntentResponse,
    CardPaymentIntentUpdate,
    CardPortfolioPaymentPlanResponse,
    CardPortfolioUpcomingStateResponse,
    CardPreferenceResponse,
    CardPreferenceUpsert,
    CardSpendRoutingRequest,
    CardSpendRoutingResponse,
    CardUpcomingStateResponse,
    CardUtilizationHistoryResponse,
    CashPlanResponse,
    CashPlanUpsert,
    CommitmentCreate,
    CommitmentResponse,
    CommitmentUpdate,
    CreditCardStatementResponse,
    DepositStatementLineReviewRequest,
    DepositStatementLineReviewResponse,
    DepositStatementReviewItemResponse,
    FinancialIntelligenceRepairRequest,
    FinancialIntelligenceRepairResponse,
    LiabilityCreate,
    LiabilityOverviewResponse,
    LiabilityResponse,
    LiabilityScheduleConfirm,
    LiabilityScheduleItemResponse,
    LiabilityScheduleItemUpdate,
    ReservePlanCreate,
    ReservePlanResponse,
    ReservePlanUpdate,
    StatementAnalysisResponse,
    StatementAnalysisReviewCreate,
    StatementAnalysisReviewResponse,
    StatementCardPaymentCandidateResponse,
    StatementDetectionRequest,
    StatementDetectionResponse,
    StatementDocumentDetectionResponse,
    StatementImportResultResponse,
    StatementLineReviewRequest,
    StatementLineReviewResponse,
    StatementReviewItemResponse,
    StatementTextImport,
)
from app.schemas.roadmap import (
    CardCalendarItemCreate,
    CardCalendarItemResponse,
    CardCalendarItemUpdate,
)
from app.security import ensure_user_owns_resource, get_current_user_optional, resolve_user_scope
from app.services.balance_forecast_accountability_service import (
    BalanceForecastAccountabilityService,
)
from app.services.balance_forecast_service import BalanceForecastService
from app.services.balance_reconciliation_service import BalanceReconciliationService
from app.services.card_due_runway_service import CardDueRunwayService
from app.services.card_portfolio_payment_plan_service import CardPortfolioPaymentPlanService
from app.services.card_portfolio_upcoming_service import CardPortfolioUpcomingStateService
from app.services.card_spend_routing_service import CardSpendRoutingService
from app.services.card_upcoming_state_service import CardUpcomingStateService
from app.services.card_utilization_history_service import CardUtilizationHistoryService
from app.services.financial_position_service import FinancialPositionService
from app.services.hdfc_statement_extractor import detect_hdfc_statement_document
from app.services.roadmap_service import RoadmapService
from app.services.statement_analysis import analyze_statement
from app.services.statement_analysis_review_service import StatementAnalysisReviewService
from app.services.statement_detection import detect_statement
from app.services.statement_pdf_extractor import StatementPdfText, extract_statement_pdf_text

router = APIRouter(tags=["Financial position"])
logger = logging.getLogger(__name__)


def _scoped_user_id(user_id: str, current_user: User | None) -> str:
    scoped_user_id = resolve_user_scope(user_id, current_user)
    ensure_user_owns_resource(scoped_user_id, current_user)
    return scoped_user_id


async def _extract_statement_pdf(payload: bytes) -> StatementPdfText:
    """Keep PDF/OCR work off the async event loop while retaining bytes in memory."""

    return await asyncio.to_thread(extract_statement_pdf_text, payload)


@router.post("/statements/detect", response_model=StatementDetectionResponse)
async def detect_statement_document(
    data: StatementDetectionRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Recognize a statement before account selection or persistence."""

    resolve_user_scope(user_id, current_user)
    detection = detect_statement(data.statement_text)
    return StatementDetectionResponse(
        institution=detection.institution,
        product_type=detection.product_type,
        format_id=detection.format_id,
        support_status=detection.support_status,
        confidence=detection.confidence,
        reason_codes=list(detection.reason_codes),
        activity_types=list(detection.activity_types),
        detector_version=detection.detector_version,
        analysis=StatementAnalysisResponse.model_validate(
            analyze_statement(data.statement_text, detection)
        ),
    )


@router.post("/statements/detect/upload", response_model=StatementDetectionResponse)
async def detect_statement_pdf_document(
    request: Request,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Recognize an unencrypted PDF in memory, with bounded OCR when enabled."""

    resolve_user_scope(user_id, current_user)
    payload = await request.body()
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Statements must be 10 MB or smaller")
    if not payload.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Upload a digital PDF statement")
    try:
        text = (await _extract_statement_pdf(payload)).text
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="PDF statement detection is unavailable on this server"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    detection = detect_statement(text)
    return StatementDetectionResponse(
        institution=detection.institution,
        product_type=detection.product_type,
        format_id=detection.format_id,
        support_status=detection.support_status,
        confidence=detection.confidence,
        reason_codes=list(detection.reason_codes),
        activity_types=list(detection.activity_types),
        detector_version=detection.detector_version,
        analysis=StatementAnalysisResponse.model_validate(analyze_statement(text, detection)),
    )


@router.post(
    "/statements/hdfc/detect",
    response_model=StatementDocumentDetectionResponse,
)
async def detect_hdfc_statement_document_pdf(
    request: Request,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Classify an HDFC PDF without extracting or persisting values."""

    resolve_user_scope(user_id, current_user)
    payload = await request.body()
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Statements must be 10 MB or smaller")
    if not payload.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Upload a digital PDF statement")
    try:
        text = (await _extract_statement_pdf(payload)).text
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="PDF statement detection is unavailable on this server"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    detection = detect_hdfc_statement_document(text)
    return StatementDocumentDetectionResponse(
        status=detection.status,
        issuer=detection.issuer,
        document_kind=detection.document_kind,
        format_id=detection.format_id,
        import_supported=detection.import_supported,
        import_endpoint=detection.import_endpoint,
        reason_code=detection.reason_code,
        matched_signal_codes=list(detection.matched_signal_codes),
        detector_version=detection.detector_version,
    )


@router.post(
    "/statements/review/text",
    response_model=StatementAnalysisReviewResponse,
    status_code=201,
)
async def review_statement_text(
    data: StatementAnalysisReviewCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Persist a bounded analysis for explicit review without importing rows."""

    scoped_user_id = resolve_user_scope(user_id, current_user)
    return await StatementAnalysisReviewService(db).create(
        scoped_user_id,
        data.statement_text,
        data.document_fingerprint,
    )


@router.get(
    "/statements/review",
    response_model=list[StatementAnalysisReviewResponse],
)
async def list_statement_analysis_reviews(
    user_id: str,
    status: str | None = Query(None, pattern="^(ready_to_import|pending_review)$"),
    limit: int = Query(50, ge=1, le=100),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List user-owned durable statement analyses, newest first."""

    return await StatementAnalysisReviewService(db).list(
        resolve_user_scope(user_id, current_user), status=status, limit=limit
    )


@router.get(
    "/statements/review/{review_id}",
    response_model=StatementAnalysisReviewResponse,
)
async def get_statement_analysis_review(
    review_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Read one user-owned analysis artifact without exposing source text."""

    try:
        return await StatementAnalysisReviewService(db).get(
            resolve_user_scope(user_id, current_user), review_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/statements/review/upload",
    response_model=StatementAnalysisReviewResponse,
    status_code=201,
)
async def review_statement_pdf(
    request: Request,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Extract and persist only bounded analysis from an unencrypted PDF."""

    scoped_user_id = resolve_user_scope(user_id, current_user)
    payload = await request.body()
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Statements must be 10 MB or smaller")
    if not payload.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Upload a digital PDF statement")
    try:
        statement_text = (await _extract_statement_pdf(payload)).text
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="PDF statement review is unavailable on this server"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await StatementAnalysisReviewService(db).create(
        scoped_user_id,
        statement_text,
        hashlib.sha256(payload).hexdigest(),
    )


def _detection_response(statement_text: str) -> StatementDetectionResponse:
    detection = detect_statement(statement_text)
    return StatementDetectionResponse(
        institution=detection.institution,
        product_type=detection.product_type,
        format_id=detection.format_id,
        support_status=detection.support_status,
        confidence=detection.confidence,
        reason_codes=list(detection.reason_codes),
        activity_types=list(detection.activity_types),
        detector_version=detection.detector_version,
        analysis=StatementAnalysisResponse.model_validate(
            analyze_statement(statement_text, detection)
        ),
    )


async def _import_detected_statement(
    db: AsyncSession,
    user_id: str,
    data: StatementTextImport,
) -> StatementImportResultResponse:
    detection = _detection_response(data.statement_text)
    if detection.support_status != "supported":
        raise ValueError("Statement is recognized but not supported for import")
    service = FinancialPositionService(db)
    if detection.product_type == "credit_card":
        card = (
            await service.import_hdfc_statement_text(user_id, data)
            if detection.institution == "hdfc"
            else await service.import_generic_credit_card_statement_text(user_id, data)
        )
        return StatementImportResultResponse(
            product_type="credit_card",
            detection=detection,
            credit_card_statement=card,
        )
    if detection.product_type == "deposit_account":
        deposit = (
            await service.import_hdfc_deposit_statement_text(user_id, data)
            if detection.institution == "hdfc"
            else await service.import_generic_deposit_statement_text(user_id, data)
        )
        return StatementImportResultResponse(
            product_type="deposit_account",
            detection=detection,
            deposit_account_statement=deposit,
        )
    raise ValueError("Statement product could not be determined safely")


@router.post(
    "/financial-intelligence/repair",
    response_model=FinancialIntelligenceRepairResponse,
)
async def repair_financial_intelligence(
    data: FinancialIntelligenceRepairRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Repair stale resolver output and unique cross-source duplicates."""
    return await FinancialPositionService(db).repair_financial_intelligence(
        resolve_user_scope(user_id, current_user), dry_run=data.dry_run
    )


@router.get(
    "/review/statement-lines",
    response_model=list[StatementReviewItemResponse],
)
async def statement_review_items(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await FinancialPositionService(db).statement_review_items(
        resolve_user_scope(user_id, current_user)
    )


@router.get(
    "/review/deposit-statement-lines",
    response_model=list[DepositStatementReviewItemResponse],
)
async def deposit_statement_review_items(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List owned bank-statement rows whose payment rail needs review."""

    return await FinancialPositionService(db).deposit_statement_review_items(
        resolve_user_scope(user_id, current_user)
    )


@router.patch(
    "/deposit-statement-lines/{line_id}/review",
    response_model=DepositStatementLineReviewResponse,
)
async def review_deposit_statement_line(
    line_id: str,
    data: DepositStatementLineReviewRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Import or ignore one unknown-rail bank-statement row after confirmation."""

    try:
        return await FinancialPositionService(db).review_deposit_statement_line(
            resolve_user_scope(user_id, current_user), line_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/statement-lines/{line_id}/payment-candidates",
    response_model=list[StatementCardPaymentCandidateResponse],
)
async def statement_line_payment_candidates(
    line_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Suggest owned bank debits for a card-payment line without mutating data."""

    try:
        return await FinancialPositionService(db).card_payment_candidates(
            resolve_user_scope(user_id, current_user), line_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/statement-lines/{line_id}/review",
    response_model=StatementLineReviewResponse,
)
async def review_statement_line(
    line_id: str,
    data: StatementLineReviewRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).review_statement_line(
            resolve_user_scope(user_id, current_user), line_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/liabilities/{liability_id}/schedule/{item_id}",
    response_model=LiabilityScheduleItemResponse,
)
async def update_liability_schedule_item(
    liability_id: str,
    item_id: str,
    data: LiabilityScheduleItemUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await FinancialPositionService(db).update_liability_schedule_item(
            resolve_user_scope(user_id, current_user), liability_id, item_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Liability schedule item not found")
    return result


@router.get(
    "/cards/portfolio/upcoming-state",
    response_model=CardPortfolioUpcomingStateResponse,
)
async def card_portfolio_upcoming_state(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Compose dated next-state evidence across active cards without merging issuers."""

    return await CardPortfolioUpcomingStateService(db).upcoming(
        resolve_user_scope(user_id, current_user)
    )


@router.get(
    "/cards/portfolio/payment-plan",
    response_model=CardPortfolioPaymentPlanResponse,
)
async def card_portfolio_payment_plan(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Compare minimum- and total-due plans across active cards without submitting payments."""

    return await CardPortfolioPaymentPlanService(db).compare(
        resolve_user_scope(user_id, current_user)
    )


@router.post(
    "/cards/portfolio/spend-routing",
    response_model=CardSpendRoutingResponse,
)
async def card_portfolio_spend_routing(
    data: CardSpendRoutingRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Preview a hypothetical purchase route without mutating financial data."""

    return await CardSpendRoutingService(db).preview(
        resolve_user_scope(user_id, current_user), data
    )


@router.get("/cards/{account_id}", response_model=CardOverviewResponse)
async def card_overview(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).card_overview(
            resolve_user_scope(user_id, current_user), account_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/cards/{account_id}/utilization-history",
    response_model=CardUtilizationHistoryResponse,
)
async def card_utilization_history(
    account_id: str,
    user_id: str,
    statement_limit: int = Query(12, ge=1, le=36),
    daily_limit: int = Query(60, ge=1, le=120),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return issuer utilization history plus a bounded current-cycle estimate."""

    try:
        return await CardUtilizationHistoryService(db).history(
            resolve_user_scope(user_id, current_user),
            account_id,
            statement_limit=statement_limit,
            daily_limit=daily_limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cards/{account_id}/due-runway", response_model=CardDueRunwayResponse)
async def card_due_runway(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Compare issuer total due with the conservative funding-account path."""

    try:
        result = await CardDueRunwayService(db).runway(
            resolve_user_scope(user_id, current_user), account_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Financial account not found")
    return result


@router.get(
    "/cards/{account_id}/upcoming-state",
    response_model=CardUpcomingStateResponse,
)
async def card_upcoming_state(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Compose the next dated card state from existing read-only evidence."""

    try:
        return await CardUpcomingStateService(db).upcoming(
            resolve_user_scope(user_id, current_user), account_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/cards/{account_id}/preferences", response_model=CardPreferenceResponse)
async def save_card_preferences(
    account_id: str,
    data: CardPreferenceUpsert,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).save_card_preference(
            resolve_user_scope(user_id, current_user), account_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/cards/{account_id}/payment-intents", response_model=CardPaymentIntentResponse, status_code=201
)
async def create_card_payment_intent(
    account_id: str,
    data: CardPaymentIntentCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).create_card_payment_intent(
            resolve_user_scope(user_id, current_user), account_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/cards/{account_id}/payment-intents/{intent_id}",
    response_model=CardPaymentIntentResponse,
)
async def update_card_payment_intent(
    account_id: str,
    intent_id: str,
    data: CardPaymentIntentUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).update_card_payment_intent(
            resolve_user_scope(user_id, current_user), account_id, intent_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cards/{account_id}/calendar", response_model=list[CardCalendarItemResponse])
async def list_card_calendar_events(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).list_card_calendar(
            _scoped_user_id(user_id, current_user), account_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/cards/{account_id}/calendar", response_model=CardCalendarItemResponse, status_code=201
)
async def create_card_calendar_event(
    account_id: str,
    data: CardCalendarItemCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await RoadmapService(db).create_card_calendar(
            _scoped_user_id(user_id, current_user), account_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/cards/{account_id}/calendar/{event_id}",
    response_model=CardCalendarItemResponse,
)
async def update_card_calendar_event(
    account_id: str,
    event_id: str,
    data: CardCalendarItemUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await RoadmapService(db).update_card_calendar(
            _scoped_user_id(user_id, current_user), account_id, event_id, data
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Card calendar event not found")
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/cards/{account_id}/calendar/{event_id}", status_code=204)
async def delete_card_calendar_event(
    account_id: str,
    event_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        deleted = await RoadmapService(db).delete_card_calendar(
            _scoped_user_id(user_id, current_user), account_id, event_id
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Card calendar event not found")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/accounts/{account_id}/position", response_model=AccountPositionResponse)
async def account_position(
    account_id: str,
    user_id: str,
    period_start: date | None = None,
    period_end: date | None = None,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    result = await FinancialPositionService(db).account_position(
        user_id, account_id, period_start, period_end
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Financial account not found")
    return result


@router.get(
    "/accounts/{account_id}/balance-reconciliations",
    response_model=list[BalanceReconciliationResponse],
)
async def account_balance_reconciliations(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return immutable observation-to-observation drift evidence."""

    result = await BalanceReconciliationService(db).list_for_account(
        resolve_user_scope(user_id, current_user), account_id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Financial account not found")
    return result


@router.get(
    "/accounts/{account_id}/balance-forecast",
    response_model=AccountBalanceForecastResponse,
)
async def account_balance_forecast(
    account_id: str,
    user_id: str,
    horizon_days: int = Query(30, ge=1, le=180),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return an evidence-labelled daily path from the current account position."""

    result = await BalanceForecastService(db).forecast(
        resolve_user_scope(user_id, current_user),
        account_id,
        horizon_days=horizon_days,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Financial account not found")
    return result


@router.post(
    "/accounts/{account_id}/balance-forecast/snapshots",
    response_model=AccountBalanceForecastSnapshotResponse,
)
async def create_account_balance_forecast_snapshot(
    account_id: str,
    data: AccountBalanceForecastSnapshotCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Freeze one current account path for prospective calibration."""

    try:
        return await BalanceForecastAccountabilityService(db).create_snapshot(
            resolve_user_scope(user_id, current_user), account_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/accounts/{account_id}/balance-forecast/snapshots",
    response_model=list[AccountBalanceForecastSnapshotResponse],
)
async def list_account_balance_forecast_snapshots(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List immutable forecast cutoffs for one owned account."""

    try:
        return await BalanceForecastAccountabilityService(db).list_snapshots(
            resolve_user_scope(user_id, current_user), account_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/accounts/{account_id}/balance-forecast/outcomes/evaluate",
    response_model=AccountBalanceForecastEvaluationResponse,
)
async def evaluate_account_balance_forecast_outcomes(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Match frozen paths to later verified observations when available."""

    try:
        return await BalanceForecastAccountabilityService(db).evaluate(
            resolve_user_scope(user_id, current_user), account_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/accounts/{account_id}/balance-forecast/outcomes",
    response_model=list[AccountBalanceForecastOutcomeResponse],
)
async def list_account_balance_forecast_outcomes(
    account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List observed outcomes used to calibrate one account's forecast."""

    try:
        return await BalanceForecastAccountabilityService(db).list_outcomes(
            resolve_user_scope(user_id, current_user), account_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/commitments", response_model=list[CommitmentResponse])
async def list_commitments(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await FinancialPositionService(db).list_commitments(
        resolve_user_scope(user_id, current_user)
    )


@router.post("/commitments", response_model=CommitmentResponse, status_code=201)
async def create_commitment(
    data: CommitmentCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).create_commitment(
            resolve_user_scope(user_id, current_user), data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/commitments/{commitment_id}", response_model=CommitmentResponse)
async def update_commitment(
    commitment_id: str,
    data: CommitmentUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    result = await FinancialPositionService(db).update_commitment(
        resolve_user_scope(user_id, current_user), commitment_id, data
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Commitment not found")
    return result


@router.get("/cash-plan", response_model=CashPlanResponse)
async def cash_plan(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await FinancialPositionService(db).cash_plan(resolve_user_scope(user_id, current_user))


@router.put("/cash-plan", response_model=CashPlanResponse)
async def upsert_cash_plan(
    data: CashPlanUpsert,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).upsert_cash_plan(
            resolve_user_scope(user_id, current_user), data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/reserves", response_model=list[ReservePlanResponse])
async def list_reserves(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await FinancialPositionService(db).list_reserves(
        resolve_user_scope(user_id, current_user)
    )


@router.post("/reserves", response_model=ReservePlanResponse, status_code=201)
async def create_reserve(
    data: ReservePlanCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).create_reserve(
            resolve_user_scope(user_id, current_user), data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/reserves/{reserve_id}", response_model=ReservePlanResponse)
async def update_reserve(
    reserve_id: str,
    data: ReservePlanUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    result = await FinancialPositionService(db).update_reserve(
        resolve_user_scope(user_id, current_user), reserve_id, data
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Reserve not found")
    return result


@router.get("/liabilities", response_model=list[LiabilityResponse])
async def list_liabilities(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await FinancialPositionService(db).list_liabilities(
        resolve_user_scope(user_id, current_user)
    )


@router.get("/liabilities/overview", response_model=LiabilityOverviewResponse)
async def liability_overview(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await FinancialPositionService(db).liability_overview(
        resolve_user_scope(user_id, current_user)
    )


@router.post("/liabilities", response_model=LiabilityResponse, status_code=201)
async def create_liability(
    data: LiabilityCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).create_liability(
            resolve_user_scope(user_id, current_user), data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/liabilities/{liability_id}/schedule",
    response_model=list[LiabilityScheduleItemResponse],
)
async def liability_schedule(
    liability_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).liability_schedule(
            resolve_user_scope(user_id, current_user), liability_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/liabilities/{liability_id}/schedule/confirm",
    response_model=list[LiabilityScheduleItemResponse],
    status_code=201,
)
async def confirm_liability_schedule(
    liability_id: str,
    data: LiabilityScheduleConfirm,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).confirm_liability_schedule(
            resolve_user_scope(user_id, current_user), liability_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/statements/hdfc/text", response_model=CreditCardStatementResponse, status_code=201)
async def import_hdfc_statement_text(
    data: StatementTextImport,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    scoped_user_id = resolve_user_scope(user_id, current_user)
    try:
        return await FinancialPositionService(db).import_hdfc_statement_text(scoped_user_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await _record_statement_rejection(db, scoped_user_id, str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/statements/import/text",
    response_model=StatementImportResultResponse,
    status_code=201,
)
async def import_detected_statement_text(
    data: StatementTextImport,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Detect the product and import only a write-enabled statement profile."""

    scoped_user_id = resolve_user_scope(user_id, current_user)
    try:
        return await _import_detected_statement(db, scoped_user_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await _record_statement_rejection(
            db, scoped_user_id, str(exc), format_name="statement_auto"
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/statements/import/upload",
    response_model=StatementImportResultResponse,
    status_code=201,
)
async def import_detected_statement_pdf(
    request: Request,
    financial_account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Detect and atomically import an unencrypted PDF in memory."""

    scoped_user_id = resolve_user_scope(user_id, current_user)
    payload = await request.body()
    if len(payload) > 10 * 1024 * 1024:
        await _record_statement_rejection(
            db,
            scoped_user_id,
            "statement exceeds the 10 MB limit",
            format_name="statement_auto",
        )
        raise HTTPException(status_code=413, detail="Statements must be 10 MB or smaller")
    if not payload.startswith(b"%PDF"):
        await _record_statement_rejection(
            db, scoped_user_id, "upload is not a PDF", format_name="statement_auto"
        )
        raise HTTPException(status_code=422, detail="Upload a digital PDF statement")
    try:
        statement_text = (await _extract_statement_pdf(payload)).text
    except ImportError as exc:
        await _record_statement_rejection(
            db,
            scoped_user_id,
            "PDF statement extractor is unavailable",
            format_name="statement_auto",
        )
        raise HTTPException(
            status_code=503, detail="PDF statement import is unavailable on this server"
        ) from exc
    except ValueError as exc:
        await _record_statement_rejection(
            db, scoped_user_id, str(exc), format_name="statement_auto"
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return await _import_detected_statement(
            db,
            scoped_user_id,
            StatementTextImport(
                financial_account_id=financial_account_id,
                document_fingerprint=hashlib.sha256(payload).hexdigest(),
                statement_text=statement_text,
            ),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await _record_statement_rejection(
            db, scoped_user_id, str(exc), format_name="statement_auto"
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/statements/hdfc/upload", response_model=CreditCardStatementResponse, status_code=201)
async def import_hdfc_statement_pdf(
    request: Request,
    financial_account_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Import an unencrypted PDF without retaining its bytes or password."""
    user_id = resolve_user_scope(user_id, current_user)
    payload = await request.body()
    if len(payload) > 10 * 1024 * 1024:
        await _record_statement_rejection(db, user_id, "statement exceeds the 10 MB limit")
        raise HTTPException(status_code=413, detail="Statements must be 10 MB or smaller")
    if not payload.startswith(b"%PDF"):
        await _record_statement_rejection(db, user_id, "upload is not a PDF")
        raise HTTPException(status_code=422, detail="Upload a digital PDF statement")
    try:
        text = (await _extract_statement_pdf(payload)).text
    except ImportError as exc:
        await _record_statement_rejection(db, user_id, "PDF statement extractor is unavailable")
        raise HTTPException(
            status_code=503, detail="PDF statement import is unavailable on this server"
        ) from exc
    except ValueError as exc:
        await _record_statement_rejection(db, user_id, str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return await FinancialPositionService(db).import_hdfc_statement_text(
            user_id,
            StatementTextImport(
                financial_account_id=financial_account_id,
                document_fingerprint=hashlib.sha256(payload).hexdigest(),
                statement_text=text,
            ),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await _record_statement_rejection(db, user_id, str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _record_statement_rejection(
    db: AsyncSession,
    user_id: str,
    detail: str,
    *,
    format_name: str = "hdfc_digital",
) -> None:
    """Persist aggregate-friendly statement rejection telemetry without source text."""

    await db.rollback()
    db.add(
        ConnectorAuditEvent(
            user_id=user_id,
            connector_type="statement",
            connector_account_id=None,
            event_type="statement_import_rejected",
            payload_json=json.dumps(
                {
                    "format": format_name,
                    "reason_code": _statement_rejection_code(detail),
                },
                sort_keys=True,
            ),
        )
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning("Statement rejection telemetry could not be persisted", exc_info=True)


def _statement_rejection_code(detail: str) -> str:
    """Map user-facing validation text to a stable, non-sensitive metric key."""

    normalized = detail.casefold()
    if "encrypted" in normalized:
        return "encrypted_pdf"
    if "scanned" in normalized or "empty" in normalized:
        return "scanned_or_empty_pdf"
    if "10 mb" in normalized:
        return "payload_too_large"
    if "not a pdf" in normalized:
        return "not_pdf"
    if "extractor" in normalized and "unavailable" in normalized:
        return "extractor_unavailable"
    if "different credit-card" in normalized or "masked card identity" in normalized:
        return "account_identity_mismatch"
    if "billing period" in normalized:
        return "missing_billing_period"
    if "supported hdfc" in normalized or "supported hdfc digital" in normalized:
        return "unsupported_layout"
    if "currency" in normalized:
        return "ledger_currency_mismatch"
    if "credit-card account" in normalized:
        return "wrong_account_type"
    if "conflicts with an existing" in normalized:
        return "duplicate_statement"
    if "import is incomplete" in normalized:
        return "incomplete_duplicate"
    return "validation_failed"


@router.get("/statements/{statement_id}", response_model=CreditCardStatementResponse)
async def get_statement(
    statement_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await FinancialPositionService(db).statement(
            resolve_user_scope(user_id, current_user), statement_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
