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
import pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import get_settings
from app.database import init_db, close_db, AsyncSessionLocal
from app.api.routes import health, users, transactions, categories
from app.api.routes.gmail import auth_router as gmail_auth_router, gmail_router
from app.api.routes import pipeline
from app.api.routes import insights
from app.api.routes import budgets
from app.api.routes import reports
from app.services.seed_service import run_seeds

# Import all models so SQLAlchemy Base.metadata registers them before create_all()
import app.models  # noqa: F401

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pfis")

settings = get_settings()


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

    logger.info(f"✅ PFIS v{settings.APP_VERSION} ready at http://localhost:8000")
    logger.info("📖 API docs at http://localhost:8000/docs")

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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (CSS, JS, assets)
STATIC_DIR = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Register routes
app.include_router(health.router, prefix="/api")
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
    """Serve the PFIS dashboard HTML."""
    return FileResponse(
        str(STATIC_DIR / "dashboard.html"),
        media_type="text/html",
    )
