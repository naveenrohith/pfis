# PFIS API Reference

All application routes are mounted under `/api`. Authentication is optional in
local/demo mode (`AUTH_REQUIRED=false`); when required, send a bearer token.
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
| `POST` | `/api/auth/register` | `RegisterRequest` | — | `201` | `409` | `AuthTokenResponse` (rate 5/min) |
| `POST` | `/api/auth/login` | `LoginRequest` | — | `200` | `401,403` | `AuthTokenResponse` (rate 10/min) |
| `GET` | `/api/auth/me` | — | — | `200` | `401` | `AuthMeResponse` (auth required) |
| `GET` | `/api/auth/google/login` | — | — | `302` | `500` | Redirect to Google consent |
| `GET` | `/api/auth/google/callback` | — | `code, state` | `200` (HTML) | `400,403,500` | Completes OAuth, sets session |

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
| `GET` | `/api/auth/gmail/callback` | `code, state` | `200` | `400,500` | `{status, message, gmail_account_id, user_id}` |

Operations router (`/api/gmail`):

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/gmail/sync` | `user_id`, `max_results` (1–5000, def 500) | `200` | `404,500` | `{status, stats}` |
| `GET` | `/api/gmail/status` | `user_id` | `200` | — | `{latest_status, runs[]}` (latest 5 runs) |
| `GET` | `/api/gmail/emails` | `user_id`, `processed?` (bool), `limit` (1–100, def 20), `offset` (≥0) | `200` | — | `{total, all_total, processed_total, unprocessed_total, applied_filter, emails[]}` |
| `POST` | `/api/gmail/demo-sync` | `user_id` | `200` | — | `{status, mode, stats}` (injects sample emails, no OAuth) |

## Pipeline

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/pipeline/process` | `user_id`, `limit` (1–200, def 50) | `200` | `500` | `{status, stats}` (parse → normalize → categorize → dedup → store) |

## Transactions

| Method | Path | Body | Query / Path | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/transactions/` | `TransactionCreate` | — | `201` | `409` | `TransactionResponse` (auto-dedup) |
| `GET` | `/api/transactions/` | — | `user_id`, `month?` (1–12), `year?` (2020–2030), `category_id?`, `limit` (1–200, def 50), `offset` (≥0) | `200` | — | `list[TransactionResponse]`; header `X-Total-Count` |
| `GET` | `/api/transactions/summary` | — | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | — | `TransactionSummary` |
| `PATCH` | `/api/transactions/bulk-update` | `BulkTransactionUpdate` | `user_id` | `200` | — | `BulkTransactionUpdateResponse` |
| `GET` | `/api/transactions/{txn_id}` | — | `txn_id` | `200` | `404` | `TransactionResponse` |
| `PATCH` | `/api/transactions/{txn_id}` | `TransactionUpdate` | `txn_id` | `200` | `404,409` | `TransactionResponse` (correction learning) |
| `DELETE` | `/api/transactions/{txn_id}` | — | `txn_id` | `204` | `404` | — |

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
| `GET` | `/api/insights/` | `user_id`, `month?` (1–12, def current), `year?` (2020–2030, def current) | `200` | `{meta, insights, daily_trend, recurring}` |

## Reports

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/reports/export/csv` | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | CSV stream; `Content-Disposition` attachment |
| `GET` | `/api/reports/monthly` | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | Printable HTML report |

## Jobs

Async job submissions return `202 Accepted` with a `JobResponse`; poll the job
by id for status. Submissions are rate-limited to 5/min.

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/jobs/demo-sync-pipeline` | `user_id`, `limit` (1–200, def 50) | `202` | — | `JobResponse` |
| `POST` | `/api/jobs/gmail-sync-pipeline` | `user_id`, `max_results` (1–5000, def 500), `limit` (1–5000, def 500), `sync_all` (bool) | `202` | — | `JobResponse` |
| `POST` | `/api/jobs/retry-parse-failures` | `user_id`, `limit` (1–200, def 20) | `202` | — | `JobResponse` |
| `GET` | `/api/jobs/{job_id}` | — | `200` | `404` | `JobResponse` |

---

Keep this file updated whenever paths, query parameters, response headers, or
response shapes change. Route source lives in `backend/app/api/routes`.

