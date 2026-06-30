# PFIS — Personal Finance Intelligence System

PFIS ingests financial emails, parses transaction data into structured records,
deduplicates and categorizes them, and surfaces insights, budgets, and reports
through a dashboard.

- **Backend:** FastAPI (Python 3.13), async SQLAlchemy, SQLite locally.
- **Frontend:** React + TypeScript + Vite under `frontend/` (see its README). Built
  output is served by FastAPI at `/dashboard`; the legacy static dashboard under
  `backend/app/static` remains a fallback until a build is present.
- **Docs:** `docs/` is the source of truth (architecture, data model, API, parser, security).

## Quick start

```bash
# 1. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux

# 2. Install dependencies (dev includes lint/format/type/test tooling)
pip install -r backend/requirements-dev.txt

# 3. Configure environment
copy backend\.env.example backend\.env    # Windows
# cp backend/.env.example backend/.env     # macOS/Linux
#   then set a unique SECRET_KEY (see the file for a generator one-liner)

# 4. Apply migrations
cd backend && alembic upgrade head && cd ..

# 5. Run the API + dashboard
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Build the frontend (React SPA)

```bash
cd frontend
npm install
npm run build      # emits frontend/dist, served by FastAPI at /dashboard
# npm run dev       # or run the Vite dev server on :5173 (proxies /api)
```

Then open:

- Dashboard: http://127.0.0.1:8000/dashboard
- API docs: http://127.0.0.1:8000/docs

## Developer commands

With `make` (or run the underlying commands directly — see the `Makefile`):

| Command | Purpose |
| --- | --- |
| `make test` | Run the pytest suite |
| `make cov` | Run tests with a coverage report |
| `make lint` | Ruff lint |
| `make format` | Auto-format (ruff --fix + black) |
| `make format-check` | Verify formatting without writing |
| `make typecheck` | Mypy (baseline, non-blocking) |
| `make check` | Lint + format-check + tests (local gate) |
| `make precommit` | Install git pre-commit hooks |

CI runs the same lint/format/type/test gate on every push and pull request
(`.github/workflows/ci.yml`).

## Project layout

```
backend/app/
  api/routes/        FastAPI routers (mounted under /api)
  models/            SQLAlchemy ORM models
  schemas/           Pydantic request/response shapes
  services/          Gmail sync, parser pipeline, transactions, insights, jobs
  static/            Served dashboard (HTML/CSS/JS)
  config.py          Settings   security.py  Auth/ownership   observability.py  Request-id logging
frontend/            React + TypeScript + Vite dashboard (built output served at /dashboard)
docs/                Source-of-truth documentation
tests/pytest/        Test suite
```

## Notes

- This configuration targets **local / single-user** use. Production hardening
  (containerization, Postgres, reverse proxy, secrets management) is intentionally
  out of scope for now.
- Never commit a real `.env`; never log secrets, tokens, OAuth codes, or full
  email bodies.
