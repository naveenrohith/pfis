# Premium Workspace Privacy Review

Status: passed for the deterministic premium workspace scope.

## Data used

- Guidance reads user-scoped transaction, budget, recurring-charge, anomaly, goal, and forecast aggregates.
- Dashboard preferences store layout version, widget ids/order/sizes, theme, density, favorites, onboarding goal, and stable dismissed-guidance ids.
- Accounts store user-owned account labels, masked identifiers, asset/liability classification, currency, and manual dated balances.
- Transfers store two auditable transaction legs joined by a random transfer id.

## Data not collected

- Guidance does not call a hosted LLM.
- Raw coach queries, raw email bodies, OAuth tokens, secrets, merchant-level telemetry, and credentials are not persisted or logged by the new services.
- Net worth does not infer bank balances, market prices, or investment valuations.

## Controls verified

- Every new route resolves authenticated user scope; ownership-isolation tests cover preferences and financial data.
- Guidance supports only an allowlisted deterministic grammar and returns examples for unsupported requests.
- Recommendation state changes presentation only and never mutates financial records.
- Balance history is append-only and unique per account/date.
- Transfers are atomic, remain visible in the ledger, and are excluded from income/spend aggregates.
- API contracts are additive and retain existing transaction filter names alongside the new descriptive aliases.

Separate reviews are required before bank aggregation, market pricing, OCR, cancellation, money movement, household collaboration, hosted AI, or product analytics are introduced.
