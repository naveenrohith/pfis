# PFIS Repository Standards

This document defines where PFIS code belongs and which files are allowed in
version control. It is the source of truth for repository hygiene alongside the
root `AGENTS.md` workflow.

## Source ownership

| Area | Owns | Does not own |
| --- | --- | --- |
| `backend/app/api/routes/` | HTTP contracts, auth dependencies, response mapping | Business rules or direct presentation markup |
| `backend/app/models/` | SQLAlchemy persistence entities | Request/response contracts |
| `backend/app/schemas/` | Pydantic API contracts | Database queries or side effects |
| `backend/app/services/` | Domain workflows, integrations, parsing, and persistence coordination | Route registration or frontend state |
| `frontend/src/app/` | Application shell, navigation, providers, and layout | Feature-specific business UI |
| `frontend/src/components/` | Reusable presentational primitives and composed shared components | Feature data fetching or route-specific copy |
| `frontend/src/features/<domain>/` | A cohesive product capability and its UI | Cross-feature design primitives |
| `frontend/src/lib/` | API client, types, formatting, and small framework-agnostic helpers | React feature components |
| `tests/pytest/` | Backend and API coverage | Browser or visual assertions |
| `frontend/e2e/` | Browser, accessibility, and visual-regression coverage | Unit-level component behavior |
| `docs/` | Durable product, architecture, API, and operational guidance | Generated reports or transient notes |

## Placement rules

- Extend an existing domain module before creating a new top-level folder.
- Keep FastAPI routes thin; add reusable domain behavior to a service.
- Keep React capabilities feature-local. Promote a component to `components/`
  only when at least two features need the same stable interface.
- Co-locate a React unit test with the component it protects; keep end-to-end
  tests in `frontend/e2e/`.
- Add an Alembic migration for every persisted-model change and update the
  affected API/data-model documentation in the same change.
- Do not move active files merely for naming symmetry. A move must reduce an
  actual ownership ambiguity and retain test coverage.

## Repository hygiene

The following are local or generated artifacts and must never be committed:

- Python caches, coverage files, test scratch directories, virtual environments,
  and local SQLite databases.
- Node modules, Vite builds, TypeScript build-info files, Playwright reports,
  Lighthouse reports, and temporary logs.
- `.env` files, OAuth credentials, user data exports, and backups.

The application has one dashboard delivery path: `frontend/` is the canonical
React and Vite product surface. `backend/app/static/` contains retired dashboard
source retained temporarily for reference and is not served by FastAPI. Delete it
only in a dedicated cleanup after verifying that no unique business behavior remains.

## Required checks before integration

Run the checks proportionate to the change before merging:

```powershell
.\.venv\Scripts\python.exe -m ruff check backend/app tests
.\.venv\Scripts\python.exe -m black --check backend/app tests
.\.venv\Scripts\python.exe -m pytest

Push-Location frontend
npm run lint
npm test
npm run build
npm run quality:bundle
Pop-Location
```

Run the relevant Playwright coverage for workflow, visual, accessibility, or
responsive changes. Run Lighthouse through `npm run quality:lighthouse` when a
release-like local server is available.
