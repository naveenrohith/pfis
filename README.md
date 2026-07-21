# PFIS — Personal Finance Intelligence System

PFIS ingests financial emails, parses transaction data into structured records,
deduplicates and categorizes them, and surfaces insights, budgets, and reports
through a dashboard.

- **Backend:** FastAPI (Python 3.13), async SQLAlchemy, SQLite locally.
- **Frontend:** React + TypeScript + Vite under `frontend/` (see its README). Built
  output is served by FastAPI at `/dashboard`. FastAPI does not serve the retired
  static dashboard when the React build is missing.
- **Docs:** `docs/` is the source of truth (architecture, data model, API, parser, security).

## Quick start

From the repository root, run one command:

Prerequisites: Python 3.13+ and Node.js/npm 22+ available on `PATH`.

```powershell
# Windows PowerShell. If script execution is blocked, use Command Prompt: run
.\run.ps1
```

```cmd
:: Windows Command Prompt
run
```

```bash
# macOS/Linux or any shell with Python + Node available
python scripts/start.py
```

The launcher creates `.venv` if needed, installs backend dependencies when
requirements changed, creates `backend/.env` from the example if missing,
installs frontend dependencies when needed, builds the React dashboard, applies
local Alembic migrations, and starts FastAPI.

Then open:

- Dashboard: http://127.0.0.1:8000/dashboard
- API docs: http://127.0.0.1:8000/docs

### Optional manual startup

Use this only when you want to run each step yourself for debugging:

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -r backend/requirements-dev.txt
copy backend\.env.example backend\.env    # Windows, if missing
# cp backend/.env.example backend/.env     # macOS/Linux, if missing
cd frontend && npm install && npm run build && cd ..
cd backend && alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Developer commands

With `make` (or run the underlying commands directly — see the `Makefile`):

| Command | Purpose |
| --- | --- |
| `make start` | Prepare frontend/backend and start PFIS locally |
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
