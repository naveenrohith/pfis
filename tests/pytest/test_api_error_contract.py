"""Regression tests for the stable API error envelope."""


async def test_not_found_uses_error_envelope_and_request_id(client):
    response = await client.get(
        "/api/users/does-not-exist", headers={"X-Request-ID": "error-contract-123"}
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "error-contract-123"
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "User not found",
            "details": None,
            "request_id": "error-contract-123",
        }
    }


async def test_validation_error_uses_error_envelope(client):
    response = await client.get("/api/transactions/summary?user_id=demo-user&month=13&year=2026")

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert body["message"] == "Request validation failed"
    assert body["details"]
    assert body["request_id"] == response.headers["X-Request-ID"]
