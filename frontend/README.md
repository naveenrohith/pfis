# PFIS Frontend (React + TypeScript + Vite)

A professional, component-based rewrite of the PFIS dashboard. Replaces the
legacy ~2,000-line vanilla-JS dashboard with a structured React application.

## Stack

- **React 18 + TypeScript** — typed, component-driven UI.
- **Vite** — fast dev server and production build.
- **Tailwind CSS** — utility styling with a token-based design system.
- **shadcn-style UI primitives** — local, owned components (`src/components/ui`).
- **TanStack Query** — server state, caching, and invalidation.
- **Recharts** — category and trend charts.
- **lucide-react** — icons.
- **Light / dark theme** — toggle with system-preference default.

## Commands

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxies /api -> http://127.0.0.1:8000)
npm run build    # type-check + bundle into dist/
npm run preview  # preview the production build
npm run test     # Vitest + Testing Library
npm run lint     # ESLint
npm run format   # Prettier
```

Run the FastAPI backend separately (see the root `README.md`).

## How it is served

`npm run build` emits to `frontend/dist`. FastAPI serves that build at
`/dashboard` (with SPA fallback). If the build is absent, FastAPI falls back to
the legacy static dashboard, so the app keeps working before the first build.

The Vite `base` is `/dashboard/`, so built assets resolve under
`/dashboard/assets/*` when served by the backend.

## Structure

```
src/
  main.tsx                 Entry point
  app/                     App shell: providers, layout, header, nav, theme toggle
  components/
    ui/                    Design-system primitives (Button, Card, Input, Dialog, …)
    theme/                 ThemeProvider (light/dark)
    SectionTitle.tsx
  features/
    auth/                  AuthContext + AuthScreen (login/register/Google/demo)
    workspace/             Month/year context, query hooks, sync pipeline
    overview/              Hero metrics + command center + activity log
    inbox/                 Email list + sync status
    insights/             Category + trend charts, merchants, recurring
    budgets/               Budget board + create/edit modal
    review/                Review queue + detail + bulk actions
    transactions/          Explorer with filters, grouping, drill-down, exports
  lib/                     api client, session, types, formatters, colors, utils
  styles/                  Tailwind entry + design tokens (light/dark)
  test/                    Vitest setup
```

## Design system

Colors are HSL CSS variables in `src/styles/index.css`, exposed to Tailwind via
`tailwind.config.js`. Light and dark palettes are defined under `:root` and
`.dark`. Components consume semantic tokens (`bg-card`, `text-muted-foreground`,
`border-border`, `bg-primary`, `text-success`, …) so theming is consistent.

## Feature parity

This app reaches parity with the legacy dashboard: authentication
(login/register/Google/demo), month navigation, the sync pipeline with live job
polling and an activity log, overview metrics, inbox, insights with charts,
budgets CRUD, the review queue with bulk actions, and the transactions explorer
with filters, drill-down, and CSV/HTML report export — plus a new light/dark
theme and accessibility (live regions, keyboard-dismissible dialogs, labelled
controls).
