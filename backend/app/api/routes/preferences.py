"""User-owned dashboard preference routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.preferences import (
    DashboardPreferenceResponse,
    DashboardPreferenceUpdate,
    UserPreferencePolicyRollbackRequest,
    UserPreferencePolicyUpdate,
    UserPreferencePolicyVersionResponse,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.preferences_service import PreferencesService

router = APIRouter(prefix="/preferences", tags=["Preferences"])


@router.get("/dashboard", response_model=DashboardPreferenceResponse)
async def get_dashboard_preferences(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await PreferencesService(db).get(user_id)


@router.patch("/dashboard", response_model=DashboardPreferenceResponse)
async def update_dashboard_preferences(
    data: DashboardPreferenceUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await PreferencesService(db).update(user_id, data)


@router.delete("/dashboard", response_model=DashboardPreferenceResponse)
async def reset_dashboard_preferences(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await PreferencesService(db).reset(user_id)


@router.get("/policy", response_model=UserPreferencePolicyVersionResponse)
async def get_preference_policy(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await PreferencesService(db).get_policy(user_id)


@router.put("/policy", response_model=UserPreferencePolicyVersionResponse)
async def update_preference_policy(
    data: UserPreferencePolicyUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await PreferencesService(db).update_policy(user_id, data)


@router.get("/policy/history", response_model=list[UserPreferencePolicyVersionResponse])
async def get_preference_policy_history(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await PreferencesService(db).policy_history(user_id)


@router.post("/policy/rollback", response_model=UserPreferencePolicyVersionResponse)
async def rollback_preference_policy(
    data: UserPreferencePolicyRollbackRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    try:
        return await PreferencesService(db).rollback_policy(user_id, data.version)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
