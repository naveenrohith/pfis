"""Security regressions for the canonical React dashboard serving boundary."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

app_main = importlib.import_module("app.main")


async def test_dashboard_rejects_encoded_filesystem_traversal(client, tmp_path, monkeypatch):
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<main>PFIS React</main>", encoding="utf-8")
    (tmp_path / "private.env").write_text("SECRET_KEY=must-not-leak", encoding="utf-8")
    monkeypatch.setattr(app_main, "FRONTEND_DIST", frontend_dist)
    monkeypatch.setattr(app_main, "SPA_INDEX", frontend_dist / "index.html")

    traversal_paths = (
        "/dashboard/%2e%2e/private.env",
        "/dashboard/%2e%2e%5cprivate.env",
        "/dashboard/nested/%2e%2e/%2e%2e/private.env",
    )
    for path in traversal_paths:
        response = await client.get(path)
        assert response.status_code == 404
        assert "must-not-leak" not in response.text


async def test_dashboard_serves_only_contained_files_or_spa_index(client, tmp_path, monkeypatch):
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text("<main>PFIS React</main>", encoding="utf-8")
    (frontend_dist / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_main, "FRONTEND_DIST", frontend_dist)
    monkeypatch.setattr(app_main, "SPA_INDEX", frontend_dist / "index.html")

    asset = await client.get("/dashboard/manifest.webmanifest")
    assert asset.status_code == 200
    assert asset.text == "{}"

    client_route = await client.get("/dashboard/plan/budgets")
    assert client_route.status_code == 200
    assert client_route.text == "<main>PFIS React</main>"
    assert client_route.headers["cache-control"].startswith("no-store")


async def test_dashboard_returns_service_unavailable_without_react_build(
    client, tmp_path, monkeypatch
):
    missing_index = tmp_path / "dist" / "index.html"
    monkeypatch.setattr(app_main, "SPA_INDEX", missing_index)

    response = await client.get("/dashboard")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "internal_error"
    assert "dashboard-revamp" not in response.text


def test_production_startup_requires_react_build(tmp_path, monkeypatch):
    monkeypatch.setattr(app_main, "settings", SimpleNamespace(is_production=True))
    monkeypatch.setattr(app_main, "SPA_INDEX", tmp_path / "missing" / "index.html")

    with pytest.raises(RuntimeError, match="canonical React build"):
        app_main.ensure_production_frontend_build()


async def test_api_responses_disable_browser_caching(client):
    response = await client.get("/api/categories/")

    response.raise_for_status()
    assert response.headers["cache-control"] == "no-store"
