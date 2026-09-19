# PFIS Data Shapes

> **Scope:** API/Pydantic request and response shapes exchanged over HTTP.
> For the persisted SQLAlchemy data model, see [data_model.md](data_model.md).

## ParseResult

```json
{
  "amount": 450.0,
  "currency": "INR",
  "transaction_type": "debit",
  "merchant_raw": "SWIGGY",
  "date": "2026-05-05",
  "account_last4": "1234",
  "reference_id": "123456789",
  "bank": "HDFC",
  "parser_version": 1,
  "merchant_source": "exact",
  "confidence_score": 0.9
}
```

## Transaction Create

Transaction creation is represented by `backend/app/schemas/transaction.py`. Required fields are amount, transaction type, and transaction date. Optional fields include merchant, category, account last4, reference ID, confidence, and source email. Merchant resolution also carries an additive source, confidence, user-rule id, and resolver version contract; manual clients may omit these fields and retain the existing defaults.

## Account identity

`FinancialAccount` responses include the current product identity plus an
evidence contract:

```jsonc
{
  "identity_status": "confirmed",
  "identity_confidence": 1.0,
  "identity_evidence": [
    {
      "source_type": "user_confirmation",
      "source_id": "account-id",
      "role": "identity_creation",
      "note": "A user created this account with an explicit institution and product type.",
      "observed_at": "2026-08-02T12:00:00Z"
    }
  ]
}
```

`unresolved` and `inferred` identities remain visible but are not promoted into
typed position/debt conclusions. `GET /api/accounts/{account_id}/identity-history`
returns immutable `AccountIdentitySnapshot` rows in capture order; these rows
contain masked identifiers only and retain deactivation history.

Account responses expose `latest_balance` from the latest verified observation;
`latest_observed_balance` separately reveals a newer provisional observation. The
account response now also exposes the same settlement-aware estimate as
`current_balance`, with `current_balance_as_of`, `current_balance_status`,
confidence, and reason codes so account lists update when eligible history
changes. The account-position response adds a transaction-derived estimate only
after a verified anchor. Both surfaces report settled movement, pending impact,
status, confidence, reason codes, and observation source/effective timestamps
rather than presenting the estimate as a live provider balance. Connector
observations can also carry a source record identity for retry-safe ingestion.
The card read model additionally separates the statement billed anchor from
post-statement `paid_since_statement` and signed `unbilled_activity`, so a
current outstanding amount can be explained without treating it as a live
issuer balance.

`GET /api/balance-provider/status` publishes the operational side of that
boundary: account mapping, source cadence, last successful observation, and
coverage state. Its `refresh_supported` flag remains false until a real
transport, consent lifecycle, and provider registry are configured.

`BalanceProviderConnection` is the durable, non-secret consent lifecycle for
that registry. It stores only provider type, status/expiry, refresh timestamps,
stable error codes, and a one-way consent-reference hash; the refresh job
requires an active connection and a registered factory.

`BalanceProviderAccountMapping` is the provider-scoped identity map for an
owned bank, card, loan, or investment account. It keeps an opaque provider
account ID separate from Gmail connector state, enforces one provider identity
per user/provider, and is the only mapping used by a provider refresh when a
registered provider is present. Legacy `FinancialAccount.connector_account_id`
values are accepted only as a read-only migration fallback for older fixtures;
new provider integrations must persist this mapping instead.

`CardPositionObservation` is the issuer-card companion to the generic balance
snapshot. It keeps current outstanding, billed due, pending amount, credit
limit, and available credit as independent append-only facts with source
identity, effective/retrieval timestamps, and coverage. Only current
outstanding feeds the liability position; the other fields are never derived
when a provider omits them.

Cash Plan consumes that same account-position read model. `estimated_balance` is
the current evidence, while `planning_balance` is set only when PFIS can safely
use it for flexible money. `needs_position_review` fails closed on pending,
unreviewed, or cutoff-ambiguous activity instead of subtracting commitments from
an unsafe spendable total.

Transaction lifecycle fields are also evidence, not alternate ledger entries:
`transaction_status` captures authorization/settlement state, while
`transaction_type` and `card_event` identify refunds and reversals. The temporal
timeline exposes pending, failed, refund, and reversal rows as typed
`transaction_lifecycle` events with exact transaction evidence. These events
retain the original amount and source ID, but never add a second spend or income
movement; source snapshots make the same contract available to historical-safe
evaluation.

Settled aggregates include only completed, posted, settled, succeeded, or
captured statuses. Pending, failed, declined, cancelled, and reversed rows
remain visible in Activity and temporal evidence but are excluded from settled
spend and income totals until a source record reports settlement.

Legacy rows can be enrolled in temporal history through the dry-run/apply
`/api/knowledge/history/backfill` contract. The supported sources are
transactions, financial-account identities, issuer statement lines, and card
payment intentions. The resulting snapshot timestamp is the first safe
knowledge time; it cannot be used as historical evidence for an earlier cutoff.

## Pipeline Stats

Pipeline endpoints return stats with counts for total unprocessed, parsed success, parsed failed, stored, duplicates, low confidence, skipped non-transaction, and per-email results. Per-email parser results include parser-facing metadata such as bank, parser version, confidence, merchant source, and whether the generic parser fallback handled the email.

## Report Data

Reports and dashboard workflows depend on monthly summary, category breakdown, top merchants, daily trend, recurring payments, and insight cards.

## Knowledge and Financial Intelligence Shapes

Calculated knowledge uses a common envelope vocabulary: signal kind, observed/calculated/forecast
status, confidence, data sufficiency, sample size, ruleset key/version, safe aggregate evidence,
assumptions, and data-through date. The first shared implementation is recurring-stream knowledge.

Recurring items expose merchant, occurrences, average amount, monthly equivalent, cadence,
cadence and amount confidence, combined confidence, lifecycle status, last observed date, optional
next expected date, data sufficiency, ruleset version, and aggregate evidence. They never expose raw
email bodies or connector credentials.

`FinancialHealthScore` now represents two distinct concepts: `monthly_stability` measures cash-flow
behavior, budget pressure when budgets exist, recurring burden, and spending volatility;
`data_confidence` measures parse/merchant confidence, review completeness, and historical coverage.
The legacy `score` field equals `monthly_stability` for compatibility.

It also carries a versioned observed-source register: Gmail history, owned-ledger
history, account identity, and ingestion processing each expose status, freshness,
counts, date range, completeness, limitations, and a recovery target. This is
coverage of records PFIS has observed, not a claim that a provider inbox or
external account universe is complete.
