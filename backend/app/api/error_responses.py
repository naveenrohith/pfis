"""Stable JSON error responses shared by the HTTP API."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability import request_id_ctx


def error_response(
    request: Request,
    status_code: int,
    *,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    """Return the additive error envelope used by API clients."""
    request_id = request_id_ctx.get() or request.headers.get("X-Request-ID", "-")
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id,
            }
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normalize expected HTTP failures without exposing server-side details."""
    code = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        429: "rate_limited",
    }.get(exc.status_code, "internal_error" if exc.status_code >= 500 else "request_failed")

    if exc.status_code >= 500:
        return error_response(
            request,
            exc.status_code,
            code=code,
            message="Internal server error",
        )

    detail = exc.detail
    return error_response(
        request,
        exc.status_code,
        code=code,
        message=detail if isinstance(detail, str) else "Request failed",
        details=None if isinstance(detail, str) else detail,
    )


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return validation failures in the same error envelope."""
    return error_response(
        request,
        422,
        code="validation_error",
        message="Request validation failed",
        details=exc.errors(),
    )
