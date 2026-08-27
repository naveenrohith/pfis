"""Lightweight request-scoped observability helpers.

Provides a correlation id that is attached to every log record and surfaced on
responses via the ``X-Request-ID`` header. It also keeps a bounded, privacy-safe
in-process request snapshot for health probes and deployment metrics. The
snapshot deliberately contains no query strings, user identifiers, or source
content and is an operational aid rather than a replacement for hosted metrics.
"""

from __future__ import annotations

import logging
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime
from threading import Lock
from typing import Any

# Default "-" so log records emitted outside a request still format cleanly.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_LATENCY_BUCKETS_MS = (50, 100, 250, 500, 1000, 2000, 5000)
_MAX_LATENCY_SAMPLES = 2048
_MAX_ROUTE_METRICS = 256


class RequestMetrics:
    """Bounded process-local request metrics with stable, low-cardinality labels."""

    def __init__(self) -> None:
        self.started_at = datetime.now(UTC)
        self._lock = Lock()
        self._requests_total = 0
        self._responses_4xx = 0
        self._responses_5xx = 0
        self._slow_requests = 0
        self._latencies_ms: deque[float] = deque(maxlen=_MAX_LATENCY_SAMPLES)
        self._routes: dict[str, dict[str, Any]] = {}

    def record(self, *, method: str, route: str, status_code: int, duration_ms: float) -> None:
        """Record one request using a route template, never a raw URL."""

        route_key = route if route.startswith("/") else "unmatched"
        with self._lock:
            self._requests_total += 1
            if 400 <= status_code < 500:
                self._responses_4xx += 1
            if status_code >= 500:
                self._responses_5xx += 1
            if duration_ms >= 1000:
                self._slow_requests += 1
            self._latencies_ms.append(max(duration_ms, 0.0))

            route_metrics = self._routes.get(route_key)
            if route_metrics is None:
                if len(self._routes) >= _MAX_ROUTE_METRICS:
                    route_key = "other"
                    route_metrics = self._routes.setdefault(route_key, _new_route_metrics())
                else:
                    route_metrics = _new_route_metrics()
                    self._routes[route_key] = route_metrics
            route_metrics["requests"] += 1
            route_metrics["errors_4xx"] += int(400 <= status_code < 500)
            route_metrics["errors_5xx"] += int(status_code >= 500)
            route_metrics["slow_requests"] += int(duration_ms >= 1000)
            route_metrics["total_duration_ms"] = round(
                route_metrics["total_duration_ms"] + max(duration_ms, 0.0), 3
            )
            for boundary in _LATENCY_BUCKETS_MS:
                if duration_ms <= boundary:
                    route_metrics["latency_buckets"][str(boundary)] += 1
                    break
            else:
                route_metrics["latency_buckets"]["+Inf"] += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe aggregate snapshot suitable for health tooling."""

        with self._lock:
            latencies = sorted(self._latencies_ms)
            routes = {
                route: {
                    **metrics,
                    "latency_buckets": dict(metrics["latency_buckets"]),
                    "average_duration_ms": (
                        round(metrics["total_duration_ms"] / metrics["requests"], 2)
                        if metrics["requests"]
                        else 0.0
                    ),
                }
                for route, metrics in sorted(self._routes.items())
            }
            snapshot = {
                "started_at": self.started_at.isoformat(),
                "uptime_seconds": round(
                    max((datetime.now(UTC) - self.started_at).total_seconds(), 0.0), 3
                ),
                "requests_total": self._requests_total,
                "errors_4xx": self._responses_4xx,
                "errors_5xx": self._responses_5xx,
                "slow_requests": self._slow_requests,
                "latency_sample_count": len(latencies),
                "latency_ms": {
                    "p50": _percentile(latencies, 0.50),
                    "p95": _percentile(latencies, 0.95),
                    "max": round(latencies[-1], 2) if latencies else 0.0,
                },
                "routes": routes,
            }
        return snapshot


def _new_route_metrics() -> dict[str, Any]:
    return {
        "requests": 0,
        "errors_4xx": 0,
        "errors_5xx": 0,
        "slow_requests": 0,
        "total_duration_ms": 0.0,
        "latency_buckets": {str(boundary): 0 for boundary in _LATENCY_BUCKETS_MS} | {"+Inf": 0},
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * percentile)))
    return round(values[index], 2)


request_metrics = RequestMetrics()


class RequestIdFilter(logging.Filter):
    """Inject the current request id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def install_request_id_logging() -> None:
    """Attach the request-id filter to all root logging handlers.

    Applied at the handler level so every record the handler emits — including
    those from third-party loggers — carries a ``request_id`` attribute and the
    log format never raises a missing-key error.
    """
    flt = RequestIdFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(flt)
