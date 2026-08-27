"""Persist and summarize explicit anomaly feedback without exposing source rows."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anomaly import AnomalyAdjudication
from app.schemas.intelligence import (
    AnomalyAdjudicationResponse,
    SpendingAnomaly,
)


class AnomalyAdjudicationService:
    """Append-only anomaly decisions and privacy-safe workspace summaries."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        user_id: str,
        anomaly: SpendingAnomaly,
        *,
        month: int,
        year: int,
        decision: str,
        note: str | None,
        predicted_alert: bool = True,
    ) -> AnomalyAdjudicationResponse:
        row = AnomalyAdjudication(
            user_id=user_id,
            anomaly_id=anomaly.id,
            predicted_alert=predicted_alert,
            kind=anomaly.kind,
            label=anomaly.label,
            period_start=date(year, month, 1),
            period_end=date(year, month, monthrange(year, month)[1]),
            decision=decision,
            note=note,
            current_amount=anomaly.current_amount,
            baseline_amount=anomaly.baseline_amount,
            delta_amount=anomaly.delta_amount,
            confidence=anomaly.confidence,
            transaction_count=anomaly.transaction_count,
            ruleset_version=anomaly.ruleset_version,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return self._response(row)

    async def latest_for(
        self, user_id: str, anomaly_ids: list[str]
    ) -> dict[str, AnomalyAdjudicationResponse]:
        if not anomaly_ids:
            return {}
        rows = list(
            (
                await self.db.scalars(
                    select(AnomalyAdjudication)
                    .where(
                        AnomalyAdjudication.user_id == user_id,
                        AnomalyAdjudication.anomaly_id.in_(anomaly_ids),
                    )
                    .order_by(AnomalyAdjudication.created_at.desc())
                )
            ).all()
        )
        latest: dict[str, AnomalyAdjudicationResponse] = {}
        for row in rows:
            if row.anomaly_id not in latest:
                latest[row.anomaly_id] = self._response(row)
        return latest

    async def list_for_user(
        self, user_id: str, limit: int = 100
    ) -> list[AnomalyAdjudicationResponse]:
        rows = list(
            (
                await self.db.scalars(
                    select(AnomalyAdjudication)
                    .where(AnomalyAdjudication.user_id == user_id)
                    .order_by(AnomalyAdjudication.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        return [self._response(row) for row in rows]

    async def summary(self, user_id: str) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(AnomalyAdjudication.decision, func.count(AnomalyAdjudication.id))
                .where(AnomalyAdjudication.user_id == user_id)
                .group_by(AnomalyAdjudication.decision)
            )
        ).all()
        counts = {"total": 0, "expected": 0, "material": 0, "insufficient_evidence": 0}
        for decision, count in rows:
            key = str(decision)
            if key not in counts or key == "total":
                continue
            counts[key] = int(count or 0)
            counts["total"] += int(count or 0)
        return counts

    async def protected_evaluation_cases(self, user_id: str) -> list[dict[str, bool | str]]:
        """Return evaluator-shaped cases without labels, amounts, or identifiers.

        The caller is expected to write this payload to a protected release
        artifact. Runtime APIs intentionally expose the owned decision history,
        not cross-user evaluation data.
        """

        rows = list(
            (
                await self.db.scalars(
                    select(AnomalyAdjudication)
                    .where(
                        AnomalyAdjudication.user_id == user_id,
                        AnomalyAdjudication.ruleset_version == "pfis-anomaly-2",
                        AnomalyAdjudication.decision.in_(("expected", "material")),
                    )
                    .order_by(AnomalyAdjudication.created_at.desc())
                )
            ).all()
        )
        latest: dict[str, AnomalyAdjudication] = {}
        for row in rows:
            latest.setdefault(row.anomaly_id, row)
        return [
            {
                "kind": row.kind,
                "predicted_alert": row.predicted_alert,
                "adjudicated_material": row.decision == "material",
            }
            for row in reversed(list(latest.values()))
        ]

    @staticmethod
    def _response(row: AnomalyAdjudication) -> AnomalyAdjudicationResponse:
        return AnomalyAdjudicationResponse(
            id=row.id,
            anomaly_id=row.anomaly_id,
            predicted_alert=row.predicted_alert,
            kind=cast(Literal["category", "merchant"], row.kind),
            label=row.label,
            period_start=row.period_start,
            period_end=row.period_end,
            decision=cast(Literal["expected", "material", "insufficient_evidence"], row.decision),
            note=row.note,
            current_amount=float(row.current_amount),
            baseline_amount=float(row.baseline_amount),
            delta_amount=float(row.delta_amount),
            confidence=float(row.confidence),
            transaction_count=row.transaction_count,
            ruleset_version=row.ruleset_version,
            created_at=row.created_at,
        )
