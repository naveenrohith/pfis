"""Unit tests for deduplication fingerprinting and merchant-alias parsing.

These cover business-critical, pure logic with no database dependency so they
act as a fast safety net around the parser/transaction consolidation work.
"""

from datetime import date

from app.models.category import parse_merchant_aliases
from app.services.transaction_service import TransactionService

fingerprint = TransactionService.compute_fingerprint


def _base():
    return {
        "user_id": "user-1",
        "amount": 450.0,
        "transaction_date": date(2026, 5, 5),
        "merchant": "Swiggy",
        "reference_id": "REF123",
        "account_last4": "1234",
    }


def test_fingerprint_is_deterministic():
    assert fingerprint(**_base()) == fingerprint(**_base())


def test_fingerprint_differs_per_user():
    a = fingerprint(**_base())
    other = _base()
    other["user_id"] = "user-2"
    assert fingerprint(**other) != a


def test_fingerprint_merchant_is_case_and_whitespace_insensitive():
    a = fingerprint(**_base())
    variant = _base()
    variant["merchant"] = "  SWIGGY  "
    assert fingerprint(**variant) == a


def test_fingerprint_none_merchant_uses_unknown_sentinel():
    none_merchant = _base()
    none_merchant["merchant"] = None
    unknown_merchant = _base()
    unknown_merchant["merchant"] = "unknown"
    assert fingerprint(**none_merchant) == fingerprint(**unknown_merchant)


def test_fingerprint_changes_with_each_field():
    base = _base()
    a = fingerprint(**base)
    for field, new_value in [
        ("amount", 451.0),
        ("transaction_date", date(2026, 5, 6)),
        ("merchant", "Zomato"),
        ("reference_id", "REF999"),
        ("account_last4", "5678"),
    ]:
        variant = _base()
        variant[field] = new_value
        assert fingerprint(**variant) != a, f"fingerprint should change when {field} changes"


def test_fingerprint_account_last4_optional_defaults_consistently():
    without = {k: v for k, v in _base().items() if k != "account_last4"}
    explicit_empty = _base()
    explicit_empty["account_last4"] = None
    assert fingerprint(**without) == fingerprint(**explicit_empty)


def test_parse_aliases_valid_json():
    assert parse_merchant_aliases('["SWIGGY", "SWIGGY INDIA"]') == ["SWIGGY", "SWIGGY INDIA"]


def test_parse_aliases_handles_none_and_empty():
    assert parse_merchant_aliases(None) == []
    assert parse_merchant_aliases("") == []


def test_parse_aliases_handles_malformed_json():
    assert parse_merchant_aliases("{not json") == []


def test_parse_aliases_ignores_non_string_and_non_list():
    assert parse_merchant_aliases('["OK", 5, null, "GOOD"]') == ["OK", "GOOD"]
    assert parse_merchant_aliases('{"a": 1}') == []
