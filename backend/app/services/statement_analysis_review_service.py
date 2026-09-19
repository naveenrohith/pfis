"""Durable, redacted review artifacts for statement formats not yet import-safe."""

from __future__ import annotations

import hashlib
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial_position import StatementAnalysisReview
from app.schemas.financial_position import (
    StatementAnalysisResponse,
    StatementAnalysisReviewResponse,
)
from app.services.statement_analysis import analyze_statement
from app.services.statement_detection import detect_statement

REVIEW_STATUS_READY = "ready_to_import"
REVIEW_STATUS_PENDING = "pending_review"


class StatementAnalysisReviewService:
    """Persist only the bounded analysis, never uploaded statement content."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: str,
        statement_text: str,
        document_fingerprint: str | None = None,
    ) -> StatementAnalysisReviewResponse:
        fingerprint = (
            document_fingerprint or hashlib.sha256(statement_text.encode("utf-8")).hexdigest()
        )
        existing = await self.db.scalar(
            select(StatementAnalysisReview).where(
                StatementAnalysisReview.user_id == user_id,
                StatementAnalysisReview.document_fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return self._response(existing)

        detection = detect_statement(statement_text)
        analysis = StatementAnalysisResponse.model_validate(
            analyze_statement(statement_text, detection)
        )
        review = StatementAnalysisReview(
            user_id=user_id,
            document_fingerprint=fingerprint,
            institution=detection.institution,
            product_type=detection.product_type,
            format_id=detection.format_id,
            support_status=detection.support_status,
            confidence=detection.confidence,
            detector_version=detection.detector_version,
            activity_types=list(detection.activity_types),
            reason_codes=list(detection.reason_codes),
            analysis_payload=analysis.model_dump(mode="json"),
            status=(
                REVIEW_STATUS_READY
                if detection.support_status == "supported"
                else REVIEW_STATUS_PENDING
            ),
        )
        self.db.add(review)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            concurrent = await self.db.scalar(
                select(StatementAnalysisReview).where(
                    StatementAnalysisReview.user_id == user_id,
                    StatementAnalysisReview.document_fingerprint == fingerprint,
                )
            )
            if concurrent is None:
                raise
            return self._response(concurrent)
        await self.db.refresh(review)
        return self._response(review)

    async def list(
        self,
        user_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[StatementAnalysisReviewResponse]:
        statement = (
            select(StatementAnalysisReview)
            .where(StatementAnalysisReview.user_id == user_id)
            .order_by(StatementAnalysisReview.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            statement = statement.where(StatementAnalysisReview.status == status)
        rows = list((await self.db.scalars(statement)).all())
        return [self._response(row) for row in rows]

    async def get(self, user_id: str, review_id: str) -> StatementAnalysisReviewResponse:
        row = await self.db.scalar(
            select(StatementAnalysisReview).where(
                StatementAnalysisReview.id == review_id,
                StatementAnalysisReview.user_id == user_id,
            )
        )
        if row is None:
            raise LookupError("Statement analysis review not found")
        return self._response(row)

    @staticmethod
    def _response(row: StatementAnalysisReview) -> StatementAnalysisReviewResponse:
        return StatementAnalysisReviewResponse(
            id=row.id,
            document_fingerprint=row.document_fingerprint,
            institution=row.institution,
            product_type=cast(
                Literal["credit_card", "deposit_account", "unknown"], row.product_type
            ),
            format_id=row.format_id,
            support_status=cast(
                Literal["supported", "recognized_not_supported", "ambiguous", "unsupported"],
                row.support_status,
            ),
            confidence=row.confidence,
            reason_codes=list(row.reason_codes),
            activity_types=list(row.activity_types),
            detector_version=row.detector_version,
            status=cast(Literal["ready_to_import", "pending_review"], row.status),
            analysis=StatementAnalysisResponse.model_validate(row.analysis_payload),
            created_at=row.created_at,
        )
