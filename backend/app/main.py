"""
PFIS — Personal Finance Intelligence System
Main FastAPI Application

Phases 0-6:
- Database setup with full schema
- CRUD APIs for users, transactions, categories
- Gmail OAuth + Demo sync + Email filter
- Parsing engine with bank-specific parsers
- Processing pipeline with dedup, normalization, DLQ
- Dashboard UI with charts, corrections, month navigation
- Insights engine with trends, recurring detection, anomalies
- Reports, CSV export, and budget management
"""

import logging
import os
import pathlib
import sys
import uuid
from contextlib import asynccontextmanager

if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    backend_dir = pathlib.Path(__file__).resolve().parents[1]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

# Import all models so SQLAlchemy Base.metadata registers them before create_all().
# The alias avoids shadowing the FastAPI ``app`` instance for static type checkers.
from app import models as _models  # noqa: F401
from app.api.error_responses import (
    error_response,
    http_exception_handler,
    request_validation_exception_handler,
)
from app.api.routes import (
    accounts,
    ai,
    analytics,
    auth,
    budgets,
    categories,
    dashboard,
    guidance,
    health,
    insights,
    jobs,
    merchants,
    pipeline,
    preferences,
    reports,
    transactions,
    users,
    ws,
)
from app.api.routes.gmail import auth_router as gmail_auth_router
from app.api.routes.gmail import gmail_router
from app.config import get_settings
from app.database import AsyncSessionLocal, close_db, init_db
from app.observability import install_request_id_logging, request_id_ctx
from app.rate_limit import limiter
from app.security import validate_session_csrf
from app.services.auto_sync_service import start_auto_sync_scheduler, stop_auto_sync_scheduler
from app.services.job_service import recover_interrupted_jobs
from app.services.seed_service import run_seeds

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(request_id)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
install_request_id_logging()
logger = logging.getLogger("pfis")

settings = get_settings()


def _startup_base_url() -> str:
    """Return the local URL displayed in startup logs."""
    host = os.environ.get("PFIS_HOST", "localhost")
    port = os.environ.get("PFIS_PORT", "8000")
    display_host = "localhost" if host in {"0.0.0.0", "127.0.0.1"} else host
    return f"http://{display_host}:{port}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("🚀 Starting PFIS...")
    ensure_production_frontend_build()
    await init_db()
    logger.info("✅ Database initialized")

    # Seed default data
    async with AsyncSessionLocal() as db:
        await run_seeds(db)
        recovered_jobs = await recover_interrupted_jobs(db)
        if recovered_jobs:
            logger.warning("Marked %s interrupted background job(s) as failed", recovered_jobs)

    base_url = _startup_base_url()
    start_auto_sync_scheduler()
    logger.info(f"✅ PFIS v{settings.APP_VERSION} ready at {base_url}")
    logger.info(f"📖 API docs at {base_url}/docs")

    yield

    # Shutdown
    await stop_auto_sync_scheduler()
    await close_db()
    logger.info("👋 PFIS shutdown complete")


# Create app
app = FastAPI(
    title="PFIS — Personal Finance Intelligence System",
    description=(
        "Automated personal finance system that ingests transaction emails, "
        "parses them into structured data, and delivers actionable insights."
    ),
    version=settings.APP_VERSION,
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)


async def rate_limit_exception_handler(request, exc):
    return error_response(
        request,
        429,
        code="rate_limited",
        message="Rate limit exceeded",
    )


app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-CSRF-Token"],
    expose_headers=["X-Total-Count", "X-Request-ID"],
)


_CSRF_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/demo",
}


def _is_cross_site_mutation(request: Request) -> bool:
    """Reject browser mutations initiated outside the configured PFIS origins."""
    if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
        return True
    origin = request.headers.get("Origin")
    if not origin:
        return False
    allowed_origins = {
        str(request.base_url).rstrip("/"),
        *(configured.rstrip("/") for configured in settings.CORS_ORIGINS),
    }
    return origin.rstrip("/") not in allowed_origins


@app.middleware("http")
async def browser_csrf_middleware(request: Request, call_next):
    """Require a session-bound CSRF token for cookie-authenticated mutations."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and _is_cross_site_mutation(request):
        return error_response(
            request,
            403,
            code="cross_site_request_blocked",
            message="Cross-site request blocked.",
        )
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path not in _CSRF_EXEMPT_PATHS
        and "authorization" not in request.headers
    ):
        session_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
        if session_token:
            csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME, "")
            csrf_header = request.headers.get("X-CSRF-Token", "")
            if not csrf_cookie or csrf_cookie != csrf_header:
                return error_response(
                    request,
                    403,
                    code="csrf_failed",
                    message="Security check failed. Refresh the page and try again.",
                )
            async with AsyncSessionLocal() as db:
                if not await validate_session_csrf(session_token, csrf_header, db):
                    return error_response(
                        request,
                        403,
                        code="csrf_failed",
                        message="Security check failed. Sign in again and retry.",
                    )
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Apply a conservative browser security baseline to HTML and API responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
        "object-src 'none'; form-action 'self'; img-src 'self' data:; "
        "font-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self' ws: wss:"
    )
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def request_id_middleware(request, call_next):
    """Attach a correlation id to each request for traceable logging."""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    token = request_id_ctx.set(rid)
    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


# Static files (CSS, JS, assets)
STATIC_DIR = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Built React SPA (frontend/dist). The React workspace is the only dashboard
# implementation served by FastAPI; local Vite development remains available.
FRONTEND_DIST = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
SPA_INDEX = FRONTEND_DIST / "index.html"


def ensure_production_frontend_build() -> None:
    """Fail closed when a production image omits the canonical dashboard."""
    if settings.is_production and not SPA_INDEX.is_file():
        raise RuntimeError(
            "Production startup requires the canonical React build at "
            f"{SPA_INDEX}. Run the frontend production build before starting PFIS."
        )


if SPA_INDEX.exists() and (FRONTEND_DIST / "assets").exists():
    app.mount(
        "/dashboard/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="spa-assets",
    )

# Register routes
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(ws.router, prefix="/api")
app.include_router(transactions.router, prefix="/api")
app.include_router(categories.router, prefix="/api")

# Phase 1: Gmail routes
app.include_router(gmail_auth_router, prefix="/api")
app.include_router(gmail_router, prefix="/api")

# Phase 2+3: Pipeline routes
app.include_router(pipeline.router, prefix="/api")

# Phase 5: Insights routes
app.include_router(insights.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(merchants.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(analytics.goals_router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(guidance.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")

# Phase 6: Budget + Reports routes
app.include_router(budgets.router, prefix="/api")
app.include_router(reports.router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint — redirect to dashboard."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def serve_dashboard():
    """Serve the canonical React dashboard build."""
    if not SPA_INDEX.is_file():
        raise HTTPException(
            status_code=503,
            detail="Dashboard build is unavailable. Run the frontend production build.",
        )
    response = FileResponse(str(SPA_INDEX), media_type="text/html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/dashboard/{path:path}")
async def serve_dashboard_spa(path: str):
    """Serve contained build assets or the SPA index for client-side routes."""
    if not SPA_INDEX.is_file():
        raise HTTPException(status_code=404, detail="Not found")

    frontend_root = FRONTEND_DIST.resolve()
    normalized_path = path.replace("\\", "/")
    if ".." in pathlib.PurePosixPath(normalized_path).parts:
        raise HTTPException(status_code=404, detail="Not found")
    candidate = (frontend_root / normalized_path).resolve()
    if not candidate.is_relative_to(frontend_root):
        raise HTTPException(status_code=404, detail="Not found")
    if path and candidate.is_file():
        return FileResponse(str(candidate))

    response = FileResponse(str(SPA_INDEX), media_type="text/html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
