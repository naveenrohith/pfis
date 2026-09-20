"""Pure matching policy coverage for controlled evidence comparisons."""

from decimal import Decimal

from app.services.transaction_matching import (
    is_fuel_evidence,
    is_fuel_surcharge_amount_match,
    merchant_evidence_matches,
    merchant_key,
    merchants_match,
)


def test_transaction_matching_covers_empty_exact_suffix_and_evidence_paths():
    assert merchant_key("  HDFC BANK / POS 123 ")
    assert merchants_match("Amazon India", "Amazon India") is True
    assert merchants_match("Amazon India", "Amazon") is True
    assert merchants_match("abcd", "abc") is False
    assert merchants_match("", "Amazon") is False
    assert merchant_evidence_matches("Amazon India", [None, "Amazon India"]) is True
    assert merchant_evidence_matches("Amazon India", [None, "Different merchant"]) is False
    assert is_fuel_evidence("PETROL", None) is True
    assert is_fuel_evidence("grocery", None) is False
    assert is_fuel_surcharge_amount_match(Decimal("0"), Decimal("100")) is False
    assert is_fuel_surcharge_amount_match(Decimal("110"), Decimal("100")) is False
    assert is_fuel_surcharge_amount_match(Decimal("102"), Decimal("100")) is True
