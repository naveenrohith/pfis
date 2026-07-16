# PFIS Architecture

PFIS is a FastAPI personal-finance backend with a React dashboard served by FastAPI. It turns financial emails into structured transactions and insights.

## Layers

1. API routes in `backend/app/api/routes`
2. Service layer in `backend/app/services`
3. Parser pipeline in `backend/app/services/parser`
4. ORM models in `backend/app/models`
5. Pydantic schemas in `backend/app/schemas`
6. React dashboard source in `frontend/`
7. Built dashboard assets served by FastAPI from `frontend/dist`
8. Tests in `tests/pytest`

## Core Pipeline

```
Gmail/demo raw email
  -> email classification
  -> parser registry
  -> ParseResult
  -> merchant normalization
  -> category assignment
  -> transaction deduplication
  -> transaction storage
  -> insights, budgets, reports, dashboard
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
