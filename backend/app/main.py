"""
PFIS — Personal Finance Intelligence System
Main FastAPI Application

Phase 0: Foundation
- Database setup with full schema
- CRUD APIs for users, transactions, categories
- Deduplication via fingerprinting
- Monthly summary aggregations
- Seeded categories, merchants, and demo user
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, close_db, AsyncSessionLocal
from app.api.routes import health, users, transactions, categories
from app.api.routes.gmail import auth_router as gmail_auth_router, gmail_router
from app.api.routes import pipeline
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

# CORS (allow frontend in Phase 4)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": "PFIS",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/health",
    }
