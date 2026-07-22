"""Tests for cross-cutting endpoints: health, correlation id, categories, users."""

from .helpers import create_user


async def test_health_endpoint_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert "status" in response.json()


async def test_readiness_endpoint_checks_database(client):
    response = await client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "reachable"}


async def test_operational_health_exposes_safe_runtime_state(client):
    response = await client.get("/api/health/ops")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["environment"] == "local"
    assert body["database_profile"] == "sqlite"
    assert body["jobs"]["active_in_process"] >= 0
    assert set(body["jobs"]["persisted_by_status"]) == {
        "queued",
        "running",
        "completed",
        "failed",
    }
    assert "sync" in body
    assert "audit_events" in body["sync"]


async def test_request_id_header_is_added(client):
    response = await client.get("/api/health")
    assert response.headers.get("X-Request-ID")
    timing = response.headers.get("Server-Timing", "")
    assert timing.startswith("app;dur=")
    assert float(timing.removeprefix("app;dur=")) >= 0


async def test_request_id_header_is_echoed_when_supplied(client):
    response = await client.get("/api/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers.get("X-Request-ID") == "trace-abc-123"


async def test_categories_list_is_seeded(client):
    response = await client.get("/api/categories/")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) > 0


async def test_user_create_list_and_get(client):
    user = await create_user(client)
    user_id = user["id"]

    fetched = await client.get(f"/api/users/{user_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == user_id

    listed = await client.get("/api/users/")
    assert listed.status_code == 200
    assert any(u["id"] == user_id for u in listed.json())


async def test_user_get_unknown_returns_404(client):
    response = await client.get("/api/users/does-not-exist")
    assert response.status_code == 404
