# PFIS Frontend Ownership

PFIS currently has two frontend code paths:

- Active UI: FastAPI-served static dashboard under `backend/app/static`.
- Migration UI: Svelte/Vite scaffold under `frontend/`.

The static dashboard is the canonical product UI until a later migration phase explicitly promotes the Svelte app. Backend API changes must keep the static dashboard working.

## Static Dashboard Rules

- Keep `/dashboard` served by FastAPI until cutover.
- Keep dashboard API contracts aligned with `docs/api-reference.md`.
- Do not redesign dashboard workflows as part of backend modernization phases.
- Validate report, job, sync, transaction, budget, and auth flows through existing endpoint tests before changing dashboard calls.

## Svelte Migration Rules

- Treat `frontend/` as migration work, not the active runtime.
- Port views incrementally with parity against the static dashboard.
- Reuse backend contracts rather than adding frontend-only data paths.
- Promote Svelte only after auth, sync, reports, budgets, review queue, accessibility, and build/deployment behavior reach parity.

## Cutover Criteria

Svelte can become canonical only when:

- `npm run build` succeeds in `frontend/`.
- The built app can be served or deployed with the same API base.
- Core dashboard workflows have test or manual validation evidence.
- Static dashboard retirement is documented in the same change.
