"""Health and lightweight operational visibility routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.services.job_service import get_active_task_count, get_job_status_counts

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health")
async def health_check():
    """System health check."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@router.get("/health/ops")
async def operational_health(db: AsyncSession = Depends(get_db)):
    """Return non-secret operational state for local and deployment checks."""
    database_profile = "sqlite" if settings.DATABASE_URL.startswith("sqlite") else "server"
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "auth_required": settings.AUTH_REQUIRED,
        "database_profile": database_profile,
        "jobs": {
            "active_in_process": get_active_task_count(),
            "persisted_by_status": await get_job_status_counts(db),
        },
    }
