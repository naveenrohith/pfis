# Sprint 2 - Provider/bank observation vertical review

Status: PASS_WITH_RISKS  
Verified: 2026-08-09  
Scope: provider-neutral consent, mapping, refresh, cursor, and observation ingestion

## Repository evidence

- `BalanceProviderConnectionService` owns pending/active/expired/revoked consent
  state and stores only a one-way consent-reference hash.
- `BalanceProviderMappingService` requires active consent, enforces one-to-one
  provider identity mapping, and audits map/unmap events without payloads.
- `BalanceSyncService` validates the requested account scope before writes,
  rejects duplicate source identities, resumes one opaque cursor, and marks
  missing/partial accounts incomplete.
- `RebitDepositConnector` is an injectable ReBIT FI-type adapter. Transport,
  consent, encryption, rate limits, and institution selection stay outside PFIS.
- Provider status is fail-closed: no registered transport means no refresh
  capability and no claim of a live amount.

Focused evidence:

```text
python -m pytest -q tests/pytest/test_balance_sync.py
9 passed
python -m pytest -q tests/pytest/test_rebit_deposit_connector.py
5 passed
```

The tests cover consent request/grant/expiry/revoke, idempotent refresh,
cursor resume, account mapping, duplicate source rejection, partial provider
coverage, and the ReBIT parser/transport seam.

## Unresolved promotion gate

This sprint cannot claim a live bank balance. No eligible Account Aggregator/FIU
partner, production consent callback, sandbox credentials, or institution cohort
is present in the repository. The next action is an external provider decision
with a named owner and approved secret-handling boundary. Until then, PFIS must
continue to label balances as observed-from-fixture, estimated, or unavailable;
the adapter seam is not a provider integration.

