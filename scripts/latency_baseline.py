"""Measure PFIS critical-read latency without printing response bodies."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

MAX_P95_MS = 750.0
MAX_ERROR_RATE_PCT = 0.5
MIN_SAMPLES = 20


@dataclass(frozen=True)
class RouteSpec:
    name: str
    template: str
    path: str
    query: Mapping[str, str]


@dataclass(frozen=True)
class Sample:
    status_code: int | None
    duration_ms: float
    error: str | None = None


Transport = Callable[[str, Mapping[str, str], float], Sample]


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _url(base_url: str, path: str, query: Mapping[str, str]) -> str:
    base = base_url.rstrip("/") + "/"
    url = urljoin(base, path.lstrip("/"))
    if query:
        return f"{url}?{urlencode(query)}"
    return url


def build_routes(
    *,
    user_id: str,
    account_id: str,
    card_account_id: str,
    month: int,
    year: int,
) -> list[RouteSpec]:
    common = {"user_id": user_id}
    return [
        RouteSpec("net_worth", "/api/accounts/net-worth", "/api/accounts/net-worth", common),
        RouteSpec(
            "account_position",
            "/api/accounts/{account_id}/position",
            f"/api/accounts/{quote(account_id, safe='')}/position",
            common,
        ),
        RouteSpec(
            "card_due_runway",
            "/api/cards/{account_id}/due-runway",
            f"/api/cards/{quote(card_account_id, safe='')}/due-runway",
            common,
        ),
        RouteSpec(
            "workspace",
            "/api/dashboard/workspace",
            "/api/dashboard/workspace",
            {**common, "month": str(month), "year": str(year)},
        ),
        RouteSpec(
            "intelligence_readiness",
            "/api/analytics/intelligence-readiness",
            "/api/analytics/intelligence-readiness",
            common,
        ),
    ]


def default_transport(url: str, headers: Mapping[str, str], timeout: float) -> Sample:
    started = time.perf_counter()
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            status_code = int(response.status)
            error = None if status_code < 400 else f"http_{status_code}"
    except HTTPError as exc:
        status_code = int(exc.code)
        error = f"http_{status_code}"
    except (OSError, URLError, TimeoutError) as exc:
        status_code = None
        error = exc.__class__.__name__
    return Sample(
        status_code=status_code,
        duration_ms=(time.perf_counter() - started) * 1000,
        error=error,
    )


def percentile(values: Sequence[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil((percentile_value / 100) * len(ordered)) - 1)
    return round(ordered[min(index, len(ordered) - 1)], 2)


def summarize_samples(samples: Sequence[Sample]) -> dict[str, Any]:
    successful = [sample.duration_ms for sample in samples if sample.error is None]
    errors = len(samples) - len(successful)
    error_rate = (errors / len(samples) * 100) if samples else 100.0
    status_codes: dict[str, int] = {}
    for sample in samples:
        key = str(sample.status_code) if sample.status_code is not None else "transport_error"
        status_codes[key] = status_codes.get(key, 0) + 1
    return {
        "samples": len(samples),
        "successes": len(successful),
        "errors": errors,
        "error_rate_pct": round(error_rate, 3),
        "p50_ms": percentile(successful, 50),
        "p95_ms": percentile(successful, 95),
        "status_codes": status_codes,
    }


def measure_route(
    base_url: str,
    route: RouteSpec,
    *,
    samples: int,
    headers: Mapping[str, str],
    timeout: float,
    transport: Transport = default_transport,
) -> dict[str, Any]:
    url = _url(base_url, route.path, route.query)
    observed = [transport(url, headers, timeout) for _ in range(samples)]
    summary = summarize_samples(observed)
    return {"route": route.template, **summary}


def measure_baseline(
    base_url: str,
    routes: Sequence[RouteSpec],
    *,
    samples: int,
    headers: Mapping[str, str],
    timeout: float,
    transport: Transport = default_transport,
) -> dict[str, Any]:
    if samples < MIN_SAMPLES:
        raise ValueError(f"samples must be at least {MIN_SAMPLES}")
    route_results = {
        route.name: measure_route(
            base_url,
            route,
            samples=samples,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        for route in routes
    }
    failed_routes = [
        name
        for name, result in route_results.items()
        if result["error_rate_pct"] > MAX_ERROR_RATE_PCT
        or result["p95_ms"] is None
        or result["p95_ms"] > MAX_P95_MS
    ]
    return {
        "schema_version": "pfis-critical-read-latency-baseline-1",
        "generated_at": _iso_now(),
        "thresholds": {
            "max_p95_ms": MAX_P95_MS,
            "max_error_rate_pct": MAX_ERROR_RATE_PCT,
            "min_samples_per_route": MIN_SAMPLES,
        },
        "status": "failed" if failed_routes else "passed",
        "failed_routes": failed_routes,
        "routes": route_results,
    }


def _parse_header(raw: str) -> tuple[str, str]:
    name, separator, value = raw.partition("=")
    if not separator or not name.strip():
        raise ValueError("Headers must use NAME=VALUE")
    return name.strip(), value.strip()


def build_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "pfis-latency-baseline/1"}
    if args.bearer_token:
        headers["Authorization"] = f"Bearer {args.bearer_token}"
    if args.session_cookie_value:
        headers["Cookie"] = f"{args.session_cookie_name}={args.session_cookie_value}"
    for raw in args.header:
        name, value = _parse_header(raw)
        headers[name] = value
    return headers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="PFIS base URL, for example https://pfis.example.com")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--card-account-id")
    parser.add_argument("--month", type=int, default=datetime.now().month)
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--samples", type=int, default=MIN_SAMPLES)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--bearer-token")
    parser.add_argument("--session-cookie-name", default="__Host-pfis_session")
    parser.add_argument("--session-cookie-value")
    parser.add_argument("--header", action="append", default=[], metavar="NAME=VALUE")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        routes = build_routes(
            user_id=args.user_id,
            account_id=args.account_id,
            card_account_id=args.card_account_id or args.account_id,
            month=args.month,
            year=args.year,
        )
        result = measure_baseline(
            args.base_url,
            routes,
            samples=args.samples,
            headers=build_headers(args),
            timeout=args.timeout_seconds,
        )
    except ValueError as exc:
        print(f"latency-baseline-error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
