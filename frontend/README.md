# PFIS Frontend (Svelte + Vite) — Migration Foundation

This directory is the in-progress migration of the dashboard from the single
~2,000-line vanilla-JS file (`backend/app/static/js/dashboard-revamp.js`) to a
component-based Svelte app built with Vite.

> **Status:** scaffold + API client + one ported view (`Overview`). The legacy
> static dashboard at `/dashboard` remains the served default and is fully
> functional. Nothing here changes the running app until the cutover step.

## Why Svelte

- Smallest runtime footprint of the mainstream options; compiles to plain JS.
- Auto-escapes interpolated values, preserving the XSS safety the legacy
  dashboard achieved manually via `escapeHtml()`.
- No virtual-DOM overhead — a good fit for a chart-heavy single-user dashboard.

(React or Vue are viable alternatives; the API client in `src/lib/api.js` is
framework-agnostic and can be reused if the framework choice changes.)

## Prerequisites

Node.js 18+ and npm. Node is **not** installed in the current environment, so
the scaffold has not yet been `npm install`ed or built here — do that locally:

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxies /api to http://127.0.0.1:8000)
npm run build    # outputs to frontend/dist/
```

Run the backend separately (see the root `README.md`).

## Structure

```
frontend/
  index.html              Vite entry HTML
  vite.config.js          Dev server + /api proxy + build config
  src/
    main.js               Mounts the App
    App.svelte            Shell (header + view)
    views/
      Overview.svelte     Ported metrics view (calls /transactions/summary)
    lib/
      api.js              Typed-ish API client (mirrors docs/api-reference.md)
      session.js          Versioned localStorage session (pfis.session.v3)
```

## Migration plan (remaining work)

1. Port views incrementally, reusing `src/lib/api.js`:
   hero/metrics → category analytics → review queue → budgets → reports.
2. Re-create accessibility features from the legacy dashboard
   (`aria-live` regions, `.sr-only` text, Escape-to-close, focus management).
3. Port auth/session flows (login, Google OAuth callback handling).
4. Keep Chart.js (or swap for a Svelte-friendly chart lib) for trend charts.

## Cutover

Once views reach parity:

1. `npm run build` to produce `frontend/dist/`.
2. Serve the built assets from FastAPI (e.g. mount `frontend/dist` and point the
   `/dashboard` route at the new `index.html`), or serve the SPA separately.
3. Remove the legacy `static/js/dashboard-revamp.js` and related files.

Each ported view should be validated against the legacy dashboard for visual and
behavioral parity before the cutover.
