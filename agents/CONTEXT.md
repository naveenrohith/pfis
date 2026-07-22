# PFIS Project Context

PFIS is the Personal Finance Intelligence System. It ingests financial emails, parses transaction data, stores normalized records, and exposes dashboard, insights, budget, and report workflows.

## Current Shape

```
backend/
  app/
    main.py                 FastAPI app, middleware, route registration, dashboard serving
    config.py               Pydantic settings loaded from backend/.env and root .env
    database.py             async SQLAlchemy engine, session factory, metadata creation
    security.py             JWT, password hashing, Fernet token encryption, ownership helpers
    rate_limit.py           slowapi limiter
    api/routes/             FastAPI routers
    models/                 SQLAlchemy ORM models
    schemas/                Pydantic request/response schemas
    services/               Gmail, parser, transaction, insights, jobs, seed services
    static/                 dashboard HTML/CSS/JS
  alembic/                  database migrations
tests/pytest/               active pytest suite
docs/                       PFIS architecture and workflow source of truth
agents/                     agent workflow instructions
```

## Core Product Workflow

1. User authenticates or runs local/demo mode.
2. Gmail OAuth connects an account, or demo sync injects realistic sample emails.
3. Raw emails are stored for traceability and re-processing.
4. Email filter classifies transaction, OTP, promotion, statement, or ignore.
5. Parser registry selects a bank-specific parser or generic fallback.
6. Parser extracts amount, transaction type, merchant, date, account last4, reference ID, and confidence.
7. Merchant normalizer maps aliases and category defaults.
8. Transaction service deduplicates by fingerprint and stores transaction rows.
9. Insights, budgets, reports, and dashboard render financial intelligence.

## Important Files

- App startup: `backend/app/main.py`
- Settings: `backend/app/config.py`
- Auth and ownership: `backend/app/security.py`
- Database setup: `backend/app/database.py`
- Parser pipeline: `backend/app/services/parser/pipeline.py`
- Parser registry: `backend/app/services/parser/registry.py`
- Transaction service: `backend/app/services/transaction_service.py`
- Gmail sync: `backend/app/services/gmail/sync_service.py`
- Dashboard: canonical React/Vite source in `frontend/`; FastAPI serves `frontend/dist`
- Tests: `tests/pytest/`

## Non-Negotiables

- User-scoped data must never leak across users.
- OAuth and Gmail tokens must be encrypted at rest and never logged.
- Raw emails are retained so parser improvements can reprocess history.
- Parser accuracy is more important than UI polish.
- Every parser or dedup change needs regression coverage.
- API route behavior must remain documented.

