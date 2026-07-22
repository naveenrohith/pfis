# PFIS Frontend Ownership

PFIS has one canonical frontend: the React + TypeScript + Vite app under
`frontend/`. Its production build (`frontend/dist`) is served by FastAPI at
`/dashboard`.

The retired dashboard under `backend/app/static` is not served. When the React
build is unavailable, local requests receive `503` and production startup fails
closed. Backend API changes need to support only the typed React client.

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
- Production images must include `frontend/dist/index.html`; startup validates it
  before database initialization or background scheduler startup.

## Retired Static Dashboard

- Retained temporarily as reference while its unique behavior is audited.
- It is not routed or authenticated by FastAPI. Do not add features to it.
