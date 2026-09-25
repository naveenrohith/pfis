"""AI-ready explanation routes.

Explanations are deterministic and evidence-backed. Supplied aggregates are
qualified against owned PFIS read models when a user scope is available, and
never require raw email bodies or secrets.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.intelligence import ExplainRequest, ExplainResponse
from app.security import get_current_user_optional, resolve_user_scope
from app.services.explanation_service import ExplanationService

router = APIRouter(prefix="/ai", tags=["AI"])


@router.post("/explain", response_model=ExplainResponse)
async def explain_surface(
    data: ExplainRequest,
    user_id: str | None = None,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Qualify supplied surface aggregates and return an evidence-backed explanation."""
    scoped_user_id = (
        resolve_user_scope(user_id, current_user) if user_id or current_user is not None else None
    )
    try:
        return await ExplanationService(db).explain(data, scoped_user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
