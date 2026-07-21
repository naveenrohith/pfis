# PFIS API Reference

All application routes are mounted under `/api`. Authentication is optional in
local/demo mode (`AUTH_REQUIRED=false`). The browser uses an opaque `HttpOnly`
session cookie plus `X-CSRF-Token` for mutations; bearer JWTs remain supported
for API compatibility.
User-scoped routes accept a `user_id` and resolve the effective user via
`resolve_user_scope(user_id, current_user)`.

Common error codes: `400` bad state, `401` unauthenticated, `403` forbidden,
`404` not found, `409` conflict/duplicate, `500` server error.

## Health

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/health` | `{status, app, version}` |

## Auth

| Method | Path | Body | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/auth/register` | `RegisterRequest` | — | `201` | `409,422` | `AuthSessionResponse` + session/CSRF cookies (rate 5/min) |
| `POST` | `/api/auth/login` | `LoginRequest` | — | `200` | `401,403` | `AuthSessionResponse` + session/CSRF cookies (rate 10/min) |
| `POST` | `/api/auth/demo` | — | — | `200` | `404` | Isolated demo `AuthSessionResponse` (disabled in production; rate 10/min) |
| `POST` | `/api/auth/logout` | — | — | `200` | `403` | Revokes browser session; requires CSRF header |
| `GET` | `/api/auth/session` | — | — | `200` | `401` | Browser-safe session metadata; never returns a token |
| `GET` | `/api/auth/me` | — | — | `200` | `401` | `AuthMeResponse` (auth required) |
| `GET` | `/api/auth/google/login` | — | — | `307` | — | Redirect to identity-only Google consent |
| `GET` | `/api/auth/google/callback` | — | `code, state` | `303` | `400` | Verifies OIDC transaction, sets session, redirects to dashboard |

## Users

| Method | Path | Body | Path param | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/users/` | `UserCreate` | — | `201` | `409` | `UserResponse` |
| `GET` | `/api/users/` | — | — | `200` | — | `list[UserResponse]` (current user if authed, else all) |
| `GET` | `/api/users/{user_id}` | — | `user_id` | `200` | `404` | `UserResponse` |

## Gmail

Auth router (`/api/auth/gmail`):

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/auth/gmail/connect` | `user_id` | `302` | `500` | Redirect to Google consent |
| `GET` | `/api/auth/gmail/callback` | `code, state` | `303` | `400,500` | Stores encrypted connector tokens and redirects to dashboard |

Operations router (`/api/gmail`):

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/gmail/sync` | `user_id`, `max_results` (1–5000, def 500) | `200` | `404,500` | `{status, stats}` |
| `GET` | `/api/gmail/status` | `user_id` | `200` | — | `{latest_status, runs[]}` (latest 5 runs) |
| `GET` | `/api/gmail/emails` | `user_id`, `processed?` (bool), `limit` (1–100, def 20), `offset` (≥0) | `200` | — | `{total, all_total, processed_total, unprocessed_total, applied_filter, emails[]}` |
| `POST` | `/api/gmail/demo-sync` | `user_id` | `200` | — | `{status, mode, stats}` (injects sample emails, no OAuth) |

Auto-sync additions:

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/gmail/auto-sync` | `user_id` | `200` | `404` | Auto-sync settings, status, last sync, and cursor |
| `PATCH` | `/api/gmail/auto-sync` | `user_id` | `200` | `404,422` | Update auto-sync enabled state or interval |

## WebSocket

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/ws/sync` | `user_id`, `token?` | WebSocket | Sync events scoped by browser session cookie or compatibility bearer token |

Sync events include `sync_started`, `gmail_checked`, `emails_stored`,
`pipeline_started`, `transactions_updated`, `sync_completed`, and `sync_failed`.
When `AUTH_REQUIRED=true`, the optional `token` query value must identify the
same user as `user_id`.

## Pipeline

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/pipeline/process` | `user_id`, `limit` (1–200, def 50) | `200` | `500` | `{status, stats}` (parse → normalize → categorize → dedup → store) |

### GET `/api/pipeline/metrics`

Returns parser-pipeline health for a user/month:

- parse attempts
- transaction created count
- parse success rate
- average confidence
- fallback rate
- unknown merchant rate
- duplicate rate
- retry count
- DLQ size
- average parse time

Query parameters: `user_id`, optional `month`, optional `year`.

### GET `/api/pipeline/failures`

Lists parser DLQ items without raw email bodies. Query parameters:

- `user_id`
- `resolved` defaults to `false`
- `limit`
- `offset`

Each item includes failure stage/code, parser versions, retry metadata, subject/sender previews, and non-secret diagnostics.

### POST `/api/pipeline/failures/{failure_id}/retry`

Retries one unresolved parse failure for the scoped user.

Query parameters: `user_id`.

### POST `/api/pipeline/reprocess`

Replays retained raw emails. The default `dry_run: true` compares parser output without mutating transactions.

Query parameters: `user_id`.

JSON body:

```json
{
  "email_ids": ["optional-email-id"],
  "from_date": "2026-05-01",
  "to_date": "2026-05-31",
  "dry_run": true,
  "limit": 100
}
```

## Transactions

| Method | Path | Body | Query / Path | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/transactions/` | `TransactionCreate` | — | `201` | `409` | `TransactionResponse` (auto-dedup) |
| `GET` | `/api/transactions/` | — | `user_id`; optional `month`, `year`, `category_id`, `text`/`q`, `type`/`transaction_type`, `payment_method`, `review_state`/`reviewed`, `date_from`, `date_to`, `amount_min`, `amount_max`, `sort_field`/`sort`, `sort_direction`/`direction`; `limit`, `offset` | `200` | — | `list[TransactionResponse]`; header `X-Total-Count` |
| `GET` | `/api/transactions/summary` | — | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | — | `TransactionSummary` |
| `PATCH` | `/api/transactions/bulk-update` | `BulkTransactionUpdate` | `user_id` | `200` | — | `BulkTransactionUpdateResponse` |
| `GET` | `/api/transactions/{txn_id}` | — | `txn_id` | `200` | `404` | `TransactionResponse` |
| `PATCH` | `/api/transactions/{txn_id}` | `TransactionUpdate` | `txn_id` | `200` | `404,409` | `TransactionResponse` (correction learning) |
| `DELETE` | `/api/transactions/{txn_id}` | — | `txn_id` | `204` | `404` | — |

`TransactionCreate` also accepts an optional owned `financial_account_id`. Transfer
legs include `transfer_group_id` and `is_transfer=true`; they remain visible in the
ledger but are excluded from income, spending, budget, guidance, forecast, and
report aggregates.

`TransactionResponse` includes additive merchant provenance fields:
`merchant_resolution_source`, `merchant_resolution_confidence`,
`merchant_rule_id`, and `merchant_resolver_version`. Direct transaction-create
requests are recorded as `manual`; client-supplied provenance values are ignored.

## Guidance and Dashboard Preferences

| Method | Path | Query / Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/guidance/brief` | `user_id`, `period=daily|weekly|monthly`, optional `month`, `year` | `GuidanceBrief` with ruleset version, freshness, health changes, and ranked recommendations |
| `POST` | `/api/guidance/query` | `user_id`, `GuidanceQueryRequest` | `GuidanceQueryResult`; unsupported intents return examples instead of a generated answer |
| `PATCH` | `/api/guidance/{recommendation_id}/state` | `user_id`, state `active|dismissed|snoozed`, optional `snoozed_until` | Persisted recommendation state |
| `GET` | `/api/preferences/dashboard` | `user_id` | Versioned `DashboardPreferences`; deterministic defaults when missing |
| `PATCH` | `/api/preferences/dashboard` | `user_id`, partial preferences | Validated, user-owned preferences, including `briefing_cadence: daily|weekly|monthly` |
| `DELETE` | `/api/preferences/dashboard` | `user_id` | Reset defaults |

Guidance is deterministic and allowlisted. Supported intents cover period totals,
merchant/category spend, comparisons, recurring charges, and budget status. Raw
queries are neither persisted nor logged by the guidance service.

## Accounts, Balances, Net Worth, and Transfers

| Method | Path | Query / Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/accounts` | `user_id` | `list[FinancialAccount]` |
| `POST` | `/api/accounts` | `user_id`, `FinancialAccountCreate` | Created account |
| `PATCH` | `/api/accounts/{account_id}` | `user_id`, `FinancialAccountUpdate` | Updated owned account |
| `POST` | `/api/accounts/{account_id}/balances` | `user_id`, `BalanceSnapshotCreate` | Append-only balance snapshot; duplicate account/date returns `409` |
| `GET` | `/api/net-worth` | `user_id`, optional `as_of` | `NetWorthSeries`, calculated as latest assets minus latest liabilities |
| `POST` | `/api/transfers` | `user_id`, `TransferCreate` | Atomic debit/credit pair sharing a transfer identifier |

All account and preference routes resolve the authenticated user scope. Cross-user
resource access returns no data, and cross-currency transfers are rejected.

## Categories

| Method | Path | Success | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/categories/` | `200` | `list[CategoryResponse]` |

## Budgets

| Method | Path | Body | Query / Path | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/budgets/` | `BudgetCreate` | `user_id` | `201` | `409` | `{id, status}` |
| `GET` | `/api/budgets/` | — | `user_id` | `200` | — | `list[BudgetResponse]` |
| `PATCH` | `/api/budgets/{budget_id}` | `BudgetUpdate` | `budget_id` | `200` | `404` | `{id, monthly_limit, status}` |
| `DELETE` | `/api/budgets/{budget_id}` | — | `budget_id` | `204` | `404` | `{status}` |
| `GET` | `/api/budgets/track` | — | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | — | `list[BudgetTracker]` sorted by status |

## Insights

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/insights/` | `user_id`, `month?` (1–12, def current), `year?` (2020–2030, def current) | `200` | `{meta, insights, daily_trend, recurring_payments}`; recurring items include cadence, lifecycle, confidence, monthly equivalent, expected date, evidence, and ruleset |

## Dashboard

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/dashboard/workspace` | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | `WorkspaceResponse` |

`WorkspaceResponse` is an aggregate DTO for the Financial Decision Workspace,
composed from existing deterministic services (transactions, insights, budgets,
gmail status). It never contains raw email bodies, tokens, or secrets.

```jsonc
{
  "month": 7, "year": 2026,
  "snapshot": {
    "income": 0, "spend": 0, "savings": 0, "net_cash_flow": 0,
    "transaction_count": 0, "review_count": 0, "budget_risk_count": 0,
    "sync_status": "idle"
  },
  "timeline": [
    { "type": "income|subscription|bill|shopping|refund|spending",
      "label": "Merchant", "merchant": "Merchant", "category": "Food",
      "amount": 0, "direction": "in|out", "date": "2026-07-01", "confidence": 0.9 }
  ],
  "insights": [ { "type": "…", "icon": "🏷️", "title": "…", "description": "…", "severity": "info" } ],
  "recommendations": [
    { "type": "savings|recurring|budget|anomaly|review", "severity": "warning",
      "title": "…", "description": "…", "action_label": "Open review queue", "target": "review" }
  ],
  "review_summary": { "pending_count": 0, "low_confidence_count": 0, "avg_confidence": null },
  "sync_summary": { "latest_status": null, "last_synced_at": null, "processed_total": 0, "unprocessed_total": 0 },
  "projection": { "projected_net": 0, "confidence": 0.35, "data_sufficiency": "low", "evidence": [] },
  "month_comparison": { "spend_change_pct": null, "category_deltas": [] },
  "financial_health": { "monthly_stability": 0, "data_confidence": 0, "data_sufficiency": "low" },
  "recurring_commitments": []
}
```

The workspace endpoint is the authoritative Today briefing contract. Projection ranges use
historical variation when enough months exist, treat only mature recurring streams as confirmed
commitments, and label forecast confidence and assumptions. `financial_health.score` is retained
as a compatibility alias for `monthly_stability`; data quality is reported separately as
`data_confidence`. Missing budgets return `budget_adherence: null` and do not inflate stability.

## Merchant, Category, Analytics, Goals, and AI-ready Explanations

These endpoints extend the Financial Decision Workspace with Phase 2-4 read
models. They are deterministic and aggregate-only; they do not expose raw email
bodies, tokens, passwords, or connector secrets.

| Method | Path | Query / Body | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/merchants/` | `user_id`, `month`, `year` | `200` | `list[MerchantSummary]` with spend, trend, category, recurrence lifecycle/cadence/confidence, expected date, and data sufficiency |
| `GET` | `/api/merchants/learned-rules` | `user_id` | `200` | User-owned exact merchant mappings learned from explicit corrections |
| `DELETE` | `/api/merchants/learned-rules/{rule_id}` | `user_id` | `204` | Forget one user-owned learned mapping; another user's id returns `404` |
| `GET` | `/api/merchants/{merchant_key}` | `user_id`, `month`, `year` | `200` | `MerchantDetail` with aliases, default category, latest transactions |
| `PATCH` | `/api/merchants/{merchant_key}` | `user_id`, `month`, `year`, `MerchantUpdate` | `200` | Updated `MerchantDetail`; can apply normalized name/category to existing transactions |
| `GET` | `/api/categories/intelligence` | `user_id`, `month`, `year` | `200` | `CategoryIntelligenceResponse` with hierarchy, budget usage, MoM change, top merchants |
| `GET` | `/api/analytics/cash-flow` | `user_id`, `month`, `year` | `200` | Evidence-labelled projection with expected income, confirmed commitments, flexible spend, historical range, confidence, sufficiency, assumptions, and ruleset |
| `POST` | `/api/analytics/scenario` | `user_id`, `ScenarioRequest` | `200` | Non-mutating `ScenarioResponse` with baseline, adjusted outcome, effective capped adjustments, assumptions, freshness, and ruleset |
| `GET` | `/api/analytics/month-comparison` | `user_id`, `month`, `year` | `200` | `MonthComparison` with category deltas |
| `GET` | `/api/analytics/financial-health` | `user_id`, `month`, `year` | `200` | Monthly Stability and separate Data Confidence; retains `score` as a stability compatibility alias |
| `GET` | `/api/goals/` | `user_id`, `month`, `year` | `200` | `list[GoalResponse]` |
| `POST` | `/api/goals/` | `user_id`, `GoalCreate` | `201` | Created `GoalResponse` |
| `PATCH` | `/api/goals/{goal_id}` | `user_id`, `month`, `year`, `GoalUpdate` | `200` | Updated `GoalResponse` |
| `POST` | `/api/ai/explain` | `ExplainRequest` | `200` | `ExplainResponse` with summary, drivers, next actions, safety note |

Merchant edits are user scoped. `PATCH /api/merchants/{merchant_key}` creates
exact `UserMerchantRule` mappings for the selected user and, when
`apply_existing=true`, updates matching historical transactions atomically with
correction history, duplicate protection, and monthly-summary invalidation. It
does not mutate the shared `Merchant` catalog.

Two similar purchases are not sufficient evidence of recurrence. PFIS requires a recognizable
weekly, fortnightly, monthly, quarterly, or annual interval; 2 supported occurrences are `early`,
3 or more high-confidence occurrences can become `mature`, and late streams become `missed` or
`inactive`. Amount consistency contributes confidence but is not used as a cadence substitute.

`ScenarioRequest` accepts `month`, `year`, `flexible_spend_reduction`,
`recurring_reduction`, and `additional_income`. All adjustment amounts are
non-negative. The service reuses the cash-flow projection rules, caps reductions
to supported projected amounts, and never writes a transaction, goal, or
preference.

## Reports

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/reports/export/csv` | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | CSV stream; `Content-Disposition` attachment |
| `GET` | `/api/reports/monthly` | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | Printable HTML report |

## Jobs

Job enqueue endpoints accept an optional `Idempotency-Key` header. Repeating the
same key for the same user and job type returns the original durable job instead
of starting the financial workflow twice. Job responses include `attempt_count`
and `max_attempts`; `queued` may mean either newly accepted or waiting for a
bounded retry.

Async job submissions return `202 Accepted` with a `JobResponse`; poll the job
by id for status. Submissions are rate-limited to 5/min. Failed jobs keep
`error_message` populated and include `result.error_type` for stable operational
classification.

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/jobs/demo-sync-pipeline` | `user_id`, `limit` (1–200, def 50) | `202` | — | `JobResponse` |
| `POST` | `/api/jobs/gmail-sync-pipeline` | `user_id`, `max_results` (1–5000, def 500), `limit` (1–5000, def 500), `sync_all` (bool) | `202` | — | `JobResponse` |
| `POST` | `/api/jobs/retry-parse-failures` | `user_id`, `limit` (1–200, def 20) | `202` | — | `JobResponse` |
| `GET` | `/api/jobs/{job_id}` | — | `200` | `404` | `JobResponse` |

---

Keep this file updated whenever paths, query parameters, response headers, or
response shapes change. Route source lives in `backend/app/api/routes`.

## Error contract

Successful response bodies retain their endpoint-specific schema. API failures
use this stable envelope and also expose the same correlation value through
`X-Request-ID`:

```json
{
  "error": {
    "code": "not_found",
    "message": "Transaction not found",
    "details": null,
    "request_id": "trace-abc-123"
  }
}
```

Validation errors use `code: "validation_error"` and include Pydantic error
items in `details`; server errors return a generic message and do not expose
internal exception text.

## Health

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/health` | — | `200` | Basic liveness: status, app, version |
| `GET` | `/api/health/ops` | — | `200` | Non-secret operational posture and job counters |
