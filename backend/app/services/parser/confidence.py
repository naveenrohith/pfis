"""Parser confidence helpers for per-field and aggregate scoring."""

from __future__ import annotations

from app.services.parser.base_parser import ParseResult

CONFIDENCE_VERSION = 1


def score_parse_result(parse_result: ParseResult) -> ParseResult:
    """Populate per-field confidence and preserve the existing overall score."""
    parse_result.confidence_version = CONFIDENCE_VERSION
    parse_result.compute_confidence()
    return parse_result
