"""Shared pytest fixtures for PFIS integration and regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import app.database as database_module
import app.main as main_module
import app.services.job_service as job_service_module
from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.services.seed_service import run_seeds


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides) -> None:
    settings = get_settings()
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value, raising=False)
        monkeypatch.setattr(main_module.settings, key, value, raising=False)


@pytest_asyncio.fixture
async def test_session_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "pfis-test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    _patch_settings(
        monkeypatch,
        AUTH_REQUIRED=False,
        DEBUG=False,
        DEMO_USER_PASSWORD="demo12345",
        SECRET_KEY="pytest-secret-key-long-enough-32-bytes",
        TOKEN_ENCRYPTION_KEY="",
    )

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

    try:
        yield session_factory
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(test_session_factory):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.fixture
def auth_required(monkeypatch: pytest.MonkeyPatch):
    _patch_settings(monkeypatch, AUTH_REQUIRED=True)
    yield