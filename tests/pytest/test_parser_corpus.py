"""Data-driven regression coverage for the sanitized parser corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.services.parser.registry import get_parser_registry

CORPUS_PATH = Path(__file__).resolve().parents[1] / "parser_corpus" / "transaction_alerts.json"


def _load_cases() -> list[dict]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert corpus["version"] == 1
    return corpus["cases"]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_sanitized_parser_corpus(case: dict):
    result = get_parser_registry().parse_email(case["sender"], case["subject"], case["body"])
    expected = case["expected"]

    assert result.bank == expected["bank"]
    assert result.amount == expected["amount"]
    assert result.transaction_type is not None
    assert result.transaction_type.value == expected["transaction_type"]
    assert result.merchant_raw == expected["merchant_raw"]
    assert result.confidence_score >= expected["min_confidence"]

    for field in ("account_last4", "payment_method"):
        if field in expected:
            assert getattr(result, field) == expected[field]
