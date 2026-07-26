"""Shared pytest fixtures for PFIS integration and regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.database as database_module
import app.main as main_module
import app.services.auto_sync_service as auto_sync_service_module
import app.services.job_service as job_service_module
from app.api.routes import ws as ws_routes_module
from app.config import get_settings
from app.database import Base, get_db, normalize_async_database_url
from app.main import app
from app.services.seed_service import run_seeds


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides) -> None:
    settings = get_settings()
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value, raising=False)
        monkeypatch.setattr(main_module.settings, key, value, raising=False)


@pytest_asyncio.fixture
async def test_session_factory(monkeypatch: pytest.MonkeyPatch):
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres",
    )
    normalized_url = normalize_async_database_url(database_url)
    schema_name = f"pfis_test_{uuid.uuid4().hex}"
    admin_engine = create_async_engine(normalized_url, pool_pre_ping=True)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    await admin_engine.dispose()

    engine = create_async_engine(
        normalized_url,
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": schema_name}},
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    _patch_settings(
        monkeypatch,
        AUTH_REQUIRED=False,
        DEBUG=False,
        DEMO_USER_PASSWORD="demo12345",
        SECRET_KEY="pytest-secret-key-long-enough-32-bytes",
        TOKEN_ENCRYPTION_KEY="",
        GOOGLE_ALLOWED_EMAILS=[],
    )
    main_module.limiter.reset()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await run_seeds(session)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(database_module, "engine", engine, raising=False)
    monkeypatch.setattr(database_module, "AsyncSessionLocal", session_factory, raising=False)
    monkeypatch.setattr(main_module, "AsyncSessionLocal", session_factory, raising=False)
    monkeypatch.setattr(job_service_module, "AsyncSessionLocal", session_factory, raising=False)
    monkeypatch.setattr(ws_routes_module, "AsyncSessionLocal", session_factory, raising=False)
    monkeypatch.setattr(
        auto_sync_service_module, "AsyncSessionLocal", session_factory, raising=False
    )

    # Invalidate normalizer merchant cache for test isolation
    from app.services.parser.normalizer import invalidate_merchant_cache

    invalidate_merchant_cache()

    try:
        yield session_factory
    finally:
        app.dependency_overrides.clear()
        main_module.limiter.reset()
        invalidate_merchant_cache()
        await engine.dispose()
        cleanup_engine = create_async_engine(normalized_url, pool_pre_ping=True)
        try:
            async with cleanup_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        finally:
            await cleanup_engine.dispose()


@pytest_asyncio.fixture
async def client(test_session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.fixture
def auth_required(monkeypatch: pytest.MonkeyPatch):
    _patch_settings(monkeypatch, AUTH_REQUIRED=True)
    yield
