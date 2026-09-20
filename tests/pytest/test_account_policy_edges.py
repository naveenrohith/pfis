"""Ownership, identity-evidence, and immutable account boundary coverage."""

import json
from datetime import date
from decimal import Decimal

import pytest
from app.models.account import FinancialAccount
from app.services.account_service import (
    _append_identity_evidence,
    _balance_kind_label,
    _expected_balance_kind,
    _parse_identity_evidence,
)

from tests.pytest.helpers import create_user


@pytest.mark.parametrize(
    ("account_type", "expected_kind"),
    [
        ("bank", "asset"),
        ("cash", "asset"),
        ("investment", "asset"),
        ("credit_card", "liability"),
        ("loan", "liability"),
        ("pay_later", "liability"),
        ("unknown", None),
    ],
)
def test_account_type_policy_maps_only_supported_products(
    account_type: str, expected_kind: str | None
):
    assert _expected_balance_kind(account_type) == expected_kind


def test_account_identity_evidence_parser_and_appender_are_deduplicated():
    assert _balance_kind_label("asset") == "assets"
    assert _balance_kind_label("liability") == "liabilities"
    assert _parse_identity_evidence(None) == []
    assert _parse_identity_evidence("not-json") == []
    assert _parse_identity_evidence(json.dumps({"not": "a list"})) == []
    assert _parse_identity_evidence(json.dumps([{"role": "kept"}, "ignored"])) == [{"role": "kept"}]

    account = FinancialAccount(
        user_id="user-1",
        institution_name="Evidence Bank",
        account_type="bank",
        balance_kind="asset",
        masked_number="****1234",
        currency="INR",
        identity_evidence_json="not-json",
    )
    _append_identity_evidence(
        account,
        source_type="test",
        source_id="source-1",
        role="identity",
        note="confirmed by test",
        status="confirmed",
        confidence=Decimal("0.8764"),
    )
    _append_identity_evidence(
        account,
        source_type="test",
        source_id="source-1",
        role="identity",
        note="confirmed by test",
    )
    evidence = json.loads(account.identity_evidence_json)
    assert len(evidence) == 1
    assert evidence[0]["source_id"] == "source-1"
    assert account.identity_status == "confirmed"
    assert account.identity_confidence == Decimal("0.876")


async def _account(client, user_id: str, suffix: str, *, account_type: str = "bank") -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Account Edge Bank",
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_account_link_rule_can_be_deactivated_reactivated_and_scoped(client):
    user = await create_user(client, "account-link-lifecycle")
    account = await _account(client, user["id"], "9501")
    create_url = f"/api/account-link-rules?user_id={user['id']}"
    payload = {
        "financial_account_id": account["id"],
        "evidence_kind": "masked_suffix",
        "evidence_value": "9501",
        "currency": "INR",
    }
    created = await client.post(create_url, json=payload)
    created.raise_for_status()
    rule = created.json()
    assert rule["is_active"] is True

    removed = await client.delete(f"/api/account-link-rules/{rule['id']}?user_id={user['id']}")
    assert removed.status_code == 204
    listed = await client.get(create_url)
    listed.raise_for_status()
    assert listed.json()[0]["is_active"] is False

    reactivated = await client.post(create_url, json=payload)
    reactivated.raise_for_status()
    assert reactivated.json()["id"] == rule["id"]
    assert reactivated.json()["is_active"] is True

    assert (
        await client.delete(f"/api/account-link-rules/missing?user_id={user['id']}")
    ).status_code == 404


async def test_account_identity_updates_are_retained_and_inactive_accounts_reject_rules(client):
    user = await create_user(client, "account-identity-lifecycle")
    account = await _account(client, user["id"], "9502")

    updated = await client.patch(
        f"/api/accounts/{account['id']}?user_id={user['id']}",
        json={"institution_name": "Refined Account Edge Bank", "masked_number": "****9503"},
    )
    updated.raise_for_status()
    assert updated.json()["institution_name"] == "Refined Account Edge Bank"
    assert updated.json()["identity_status"] == "confirmed"

    inactive = await client.patch(
        f"/api/accounts/{account['id']}?user_id={user['id']}", json={"is_active": False}
    )
    inactive.raise_for_status()
    assert inactive.json()["is_active"] is False
    blocked = await client.post(
        f"/api/account-link-rules?user_id={user['id']}",
        json={
            "financial_account_id": account["id"],
            "evidence_kind": "masked_suffix",
            "evidence_value": "9503",
            "currency": "INR",
        },
    )
    assert blocked.status_code == 422
    assert "active account" in blocked.json()["error"]["message"]

    history = await client.get(
        f"/api/accounts/{account['id']}/identity-history?user_id={user['id']}"
    )
    history.raise_for_status()
    assert len(history.json()) >= 3
    assert any(item["is_active"] is False for item in history.json())


async def test_account_balance_edges_reject_duplicate_dates_and_missing_connector_identity(client):
    user = await create_user(client, "account-balance-edges")
    account = await _account(client, user["id"], "9504")
    balance_url = f"/api/accounts/{account['id']}/balances?user_id={user['id']}"
    first = await client.post(
        balance_url,
        json={"amount": 1500, "as_of": date.today().isoformat(), "verified": True},
    )
    first.raise_for_status()
    duplicate = await client.post(
        balance_url,
        json={"amount": 1600, "as_of": date.today().isoformat(), "verified": True},
    )
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["error"]["message"]

    observation = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 1600,
            "as_of": date.today().isoformat(),
            "source": "connector",
            "verified": True,
        },
    )
    assert observation.status_code == 409
    assert "source_record_id" in observation.json()["error"]["message"]
