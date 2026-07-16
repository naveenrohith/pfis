# PFIS Architecture

PFIS is a FastAPI personal-finance backend with a React dashboard served by FastAPI. It turns financial emails into structured transactions and insights.

## Layers

1. API routes in `backend/app/api/routes`
2. Service layer in `backend/app/services`
3. Knowledge Engine in `backend/app/services/knowledge`
4. Parser pipeline in `backend/app/services/parser`
5. ORM models in `backend/app/models`
6. Pydantic schemas in `backend/app/schemas`
7. React dashboard source in `frontend/`
8. Built dashboard assets served by FastAPI from `frontend/dist`
9. Tests in `tests/pytest`

## Core Pipeline

```
Gmail/demo raw email
  -> email classification
  -> parser registry
  -> ParseResult
  -> user-scoped merchant resolution
  -> category assignment
  -> transaction deduplication
  -> transaction storage
  -> knowledge rules (evidence, cadence, confidence, provenance)
  -> financial intelligence (stability, forecast, recommendations)
  -> premium workspace, reports
```

Connector-driven ingestion now sits before raw email storage:

```
Connector
  -> SourceRecord
  -> classification engine
  -> RawEmail persistence
  -> domain events
  -> parser pipeline
```

## Module Boundaries

- Route modules validate HTTP inputs and call services.
- `TransactionService` owns transaction create/update/delete, dedup, correction learning, and summaries.
- The global `Merchant` catalog is curated shared reference data. Explicit user corrections are
  stored as `UserMerchantRule` rows and take precedence during resolution without mutating other
  users' merchant behavior.
- Merchant resolution records its source, confidence, matching rule, and resolver version on the
  transaction so later intelligence remains explainable.
- `services/knowledge` owns reusable evidence contracts, versioned rulesets, and recurring-stream
  lifecycle analysis. Insights, merchants, forecasts, guidance, and workspace recommendations must
  consume this service instead of implementing competing recurrence heuristics.
- Recurring knowledge groups only user-owned debit ledger entries with the same account, normalized
  merchant, and currency. It separates cadence confidence from amount confidence and exposes
  `candidate`, `early`, `mature`, `missed`, and `inactive` lifecycle states.
- `IntelligenceService` separates Monthly Stability (financial behavior) from Data Confidence
  (coverage and classification quality). Review cleanliness never raises Monthly Stability.
- `WorkspaceService` is the authoritative premium briefing read model. It includes projection,
  month comparison, stability/data confidence, recurring commitments, evidence, and ranked actions
  so the Today workspace does not issue overlapping analytics requests.
- Parser modules extract transaction data only; they do not write database rows directly.
- Gmail sync stores raw email and sync metadata; processing happens through parser pipeline.
- Connector implementations fetch source records only; the ingestion coordinator owns sync orchestration, audit records, retry handling, and domain events.
- Security helpers own JWT decoding, optional auth, user-scope resolution, and resource ownership checks.

## Extension Points

- New bank format: add or update a parser and registry mapping.
- New API capability: add schema, service behavior, route, docs, tests.
- New dashboard feature: add backend contract first, then frontend rendering.
- New data source: produce raw records compatible with the parser pipeline.

## Frontend Direction

The React/Vite app under `frontend/` is the canonical UI. FastAPI serves its production build at `/dashboard`; the legacy static dashboard under `backend/app/static` remains only as a no-build fallback. See `docs/frontend.md`.
