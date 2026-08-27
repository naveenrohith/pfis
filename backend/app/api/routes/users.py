"""
User Routes
CRUD endpoints for user management.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.user import (
    AccountDeletionRequest,
    AccountDeletionResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.security import (
    get_current_user,
    get_current_user_optional,
    normalize_email,
    resolve_user_scope,
)
from app.services.account_deletion_service import (
    delete_owned_account,
    has_recent_authentication,
)
from app.services.job_service import create_job, schedule_job

router = APIRouter(prefix="/users", tags=["Users"])
settings = get_settings()


@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a local fixture user; disabled when production auth is required."""
    if settings.is_production:
        raise HTTPException(status_code=404, detail="Not found")
    email = normalize_email(str(data.email))
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User with this email already exists")

    user = User(
        email=email,
        name=data.name,
        currency=data.currency,
        timezone=data.timezone,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/", response_model=list[UserResponse])
async def list_users(
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List all users."""
    if current_user is not None:
        return [current_user]
    if settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="Authentication required")
    result = await db.execute(select(User))
    return list(result.scalars().all())


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Get a user by ID."""
    user_id = resolve_user_scope(user_id, current_user)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: UserUpdate,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Update non-financial profile settings such as the financial timezone."""
    user_id = resolve_user_scope(user_id, current_user)
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    updates = data.model_dump(exclude_unset=True)
    retention_changed = (
        "raw_email_retention_days" in updates
        and updates["raw_email_retention_days"] != user.raw_email_retention_days
    )
    for field, value in updates.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    if retention_changed:
        job = await create_job(
            db,
            "raw_email_retention",
            user.id,
            payload={"batch_size": 500},
        )
        schedule_job(job.id)
    return user


@router.delete("/{user_id}", response_model=AccountDeletionResponse)
@limiter.limit("3/hour")
async def delete_user_account(
    request: Request,
    response: Response,
    user_id: str,
    data: AccountDeletionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Irreversibly remove private account data after recent authentication."""
    if user_id != current_user.id:
        raise HTTPException(status_code=403, detail="User scope mismatch")
    raw_session = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not await has_recent_authentication(db, raw_session):
        raise HTTPException(
            status_code=403,
            detail="Sign in again before deleting your account",
        )
    expected = f"DELETE {current_user.email}"
    if data.confirmation != expected:
        raise HTTPException(
            status_code=422,
            detail=f"Type {expected} to confirm account deletion",
        )

    result = await delete_owned_account(db, current_user)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/")
    response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")
    return result
