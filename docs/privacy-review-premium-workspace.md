# Premium Workspace Privacy Review

Status: passed for the deterministic premium workspace scope.

## Data used

- Guidance reads user-scoped transaction, budget, recurring-charge, anomaly, goal, and forecast aggregates.
- Recurring knowledge reads only user-owned normalized ledger fields and returns aggregate cadence,
  amount, confidence, lifecycle, and freshness evidence.
- Dashboard preferences store layout version, widget ids/order/sizes, theme, density, favorites, onboarding goal, and stable dismissed-guidance ids.
- Financial rhythm stores only the selected in-app briefing cadence: daily, weekly, or monthly.
- Accounts store user-owned account labels, masked identifiers, asset/liability classification, currency, and manual dated balances.
- Transfers store two auditable transaction legs joined by a random transfer id.

## Data not collected

- Guidance does not call a hosted LLM.
- Raw coach queries, raw email bodies, OAuth tokens, secrets, merchant-level telemetry, and credentials are not persisted or logged by the new services.
- Net worth does not infer bank balances, market prices, or investment valuations.
- Scenario previews are calculated on request and are not persisted as financial records or behavioral events.
- Bundle and Lighthouse release checks inspect application assets and rendered quality; they do not transmit financial values or product-interaction telemetry.

## Controls verified

- Every new route resolves authenticated user scope; ownership-isolation tests cover preferences and financial data.
- Merchant corrections and exact descriptor rules remain user owned; they do not modify the shared merchant catalog or another user's normalization behavior.
- Users can list and delete their own learned merchant mappings. Rule identifiers are filtered by
  user ownership, and cross-user deletion returns not found.
- Forecast and stability surfaces distinguish observed, calculated, and forecast values; data
  confidence is not blended into financial stability.
- Guidance supports only an allowlisted deterministic grammar and returns examples for unsupported requests.
- Recommendation state changes presentation only and never mutates financial records.
- Scenario inputs are user-scoped, deterministically clamped to supported projection amounts, and never mutate ledger, goal, or preference data.
- Briefing cadence changes only the allowlisted deterministic brief period and does not enable email, push, or third-party delivery.
- Balance history is append-only and unique per account/date.
- Transfers are atomic, remain visible in the ledger, and are excluded from income/spend aggregates.
- API contracts are additive and retain existing transaction filter names alongside the new descriptive aliases.

Separate reviews are required before bank aggregation, market pricing, OCR, cancellation, money movement, household collaboration, hosted AI, or product analytics are introduced.
