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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Import all models so SQLAlchemy Base.metadata registers them before create_all()
import app.models  # noqa: F401
from app.api.routes import (
    auth,
    budgets,
    categories,
    health,
    insights,
    jobs,
    pipeline,
    reports,
    transactions,
    users,
)
from app.api.routes.gmail import auth_router as gmail_auth_router
from app.api.routes.gmail import gmail_router
from app.config import get_settings
from app.database import AsyncSessionLocal, close_db, init_db
from app.observability import install_request_id_logging, request_id_ctx
from app.rate_limit import limiter
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
    await init_db()
    logger.info("✅ Database initialized")

    # Seed default data
    async with AsyncSessionLocal() as db:
        await run_seeds(db)

    base_url = _startup_base_url()
    logger.info(f"✅ PFIS v{settings.APP_VERSION} ready at {base_url}")
    logger.info(f"📖 API docs at {base_url}/docs")

    yield

    # Shutdown
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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["X-Total-Count", "X-Request-ID"],
)


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

# Built React SPA (frontend/dist). Served at /dashboard when present; the legacy
# static dashboard remains a fallback so the app still works before a build.
FRONTEND_DIST = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
SPA_INDEX = FRONTEND_DIST / "index.html"
SPA_AVAILABLE = SPA_INDEX.exists()
if SPA_AVAILABLE and (FRONTEND_DIST / "assets").exists():
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
app.include_router(transactions.router, prefix="/api")
app.include_router(categories.router, prefix="/api")

# Phase 1: Gmail routes
app.include_router(gmail_auth_router, prefix="/api")
app.include_router(gmail_router, prefix="/api")

# Phase 2+3: Pipeline routes
app.include_router(pipeline.router, prefix="/api")

# Phase 5: Insights routes
app.include_router(insights.router, prefix="/api")

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
    """Serve the PFIS dashboard.

    Prefers the built React SPA (frontend/dist); falls back to the legacy static
    dashboard when the SPA has not been built yet.
    """
    target = SPA_INDEX if SPA_AVAILABLE else STATIC_DIR / "dashboard.html"
    response = FileResponse(str(target), media_type="text/html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/dashboard/{path:path}")
async def serve_dashboard_spa(path: str):
    """SPA fallback: serve a built asset if it exists, else the SPA index.

    Enables client-side routing under /dashboard without 404s. Only active when
    the React build is present.
    """
    if SPA_AVAILABLE:
        candidate = FRONTEND_DIST / path
        if path and candidate.is_file():
            return FileResponse(str(candidate))
        response = FileResponse(str(SPA_INDEX), media_type="text/html")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response
    raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
