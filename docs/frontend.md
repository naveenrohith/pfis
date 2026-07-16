# PFIS Frontend Ownership

PFIS has two frontend code paths during the migration window:

- Canonical UI: React + TypeScript + Vite app under `frontend/`. Its production
  build (`frontend/dist`) is served by FastAPI at `/dashboard`.
- Fallback UI: the legacy static dashboard under `backend/app/static`, served at
  `/dashboard` only when no React build is present.

The React app is the canonical product UI. The legacy static dashboard remains a
safety fallback so the app keeps working before the first `npm run build`.
Backend API changes must keep both paths working until the legacy dashboard is
removed.

## React App Rules

- Source lives in `frontend/src` (feature-based folders under `features/`).
- Reuse the typed API client in `src/lib/api.ts`; do not add frontend-only data
  paths or duplicate aggregation that belongs in backend services.
- Keep API calls aligned with `docs/api-reference.md`.
- Preserve accessibility: live regions for toasts, keyboard-dismissible dialogs,
  labelled controls, and visible focus states.
- `npm run build`, `npm run test`, and `npm run lint` must pass; CI enforces all
  three (`.github/workflows/ci.yml`, `frontend` job).
- Group product features through the workspace model in `docs/ui-ux-masterplan.md`.
- Preserve existing section hashes when reorganizing navigation or cross-feature actions.
- Use the official shadcn MCP server for component research, but retain existing PFIS primitives
  when they already meet accessibility and interaction requirements.
- Keep the initial route below 100 KB gzip and each lazy feature chunk below 130 KB gzip.
- Use the persisted dashboard preference contract for widget order, visibility, supported sizes,
  density, theme, onboarding, and dismissed deterministic guidance.

## Premium Workspace Stack

The canonical UI retains React, Vite, Tailwind 3, React Query, Recharts, Lucide,
PFIS theme/toast providers, and the existing primitives. Approved additions are
Inter variable font, Motion, cmdk, React Hook Form, Zod/resolvers, TanStack
Table, and dnd-kit. Feature-heavy dialogs and workspaces are lazy loaded.

Run `npm run test:e2e` for Playwright and axe checks after the full app is
available. Coverage targets 360 px, 768 px, and desktop widths in light and dark
themes; update snapshots intentionally with `npm run test:e2e:update`.

## Serving & Cutover

- `frontend/dist` is gitignored; CI builds it and FastAPI serves it at
  `/dashboard` (Vite `base` is `/dashboard/`).
- Local developers should use the repository-root launcher (`run.ps1`,
  `run.bat`, or `python scripts/start.py`) for the standard full-app workflow;
  it installs dependencies when needed, builds `frontend/dist`, runs migrations,
  and starts FastAPI. The launcher requires Python 3.13+ and Node.js/npm 22+ on
  `PATH`.
- When the React app is verified in production use, the legacy static dashboard
  under `backend/app/static` can be removed; document the removal in the same
  change and drop the FastAPI fallback branch in `main.py`.

## Legacy Static Dashboard

- Retained only as the no-build fallback.
- Do not invest in new features here; new UI work goes in the React app.
