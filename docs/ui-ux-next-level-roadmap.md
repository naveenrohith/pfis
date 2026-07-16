# PFIS Next-Level Product Roadmap

Status: locked for implementation on `modernization/phases-0-8`  
Scope: phases 9-12 are approved for implementation; phase 13 remains gated research.

## Product thesis

PFIS should become a calm financial decision instrument, not a larger dashboard. A user opening the product
after a sync should be able to answer three questions in order:

1. What is my financial position now?
2. What is likely to happen before month end?
3. What single change would improve that outcome?

The signature interaction is **Money Horizon**: an evidence-labelled runway from the observed position to a
deterministic month-end forecast, followed by a small scenario studio for testing a change. It uses PFIS's own
ledger and rules; it does not imply bank-grade certainty or invent scheduled dates that the data cannot support.

## Research findings and decisions

| Evidence | Product lesson | PFIS decision |
|---|---|---|
| [Monarch Recurring](https://www.monarchmoney.com/features/recurring) presents bills and subscriptions as a calendar/list with reminders | Forward visibility is more useful when commitments are visible in time | Represent recurring commitments in the horizon, but label them as a reserve until PFIS has reliable due dates |
| [Copilot Cash Flow](https://help.copilot.money/en/articles/9682232-cash-flow-tab-overview) connects income, spending, net income, and drill-down | A forecast must remain traceable to source figures | Keep observed, calculated, and forecast values visibly distinct and retain assumption details |
| [Copilot Recurrings](https://help.copilot.money/en/articles/3760068-creating-recurrings) uses expected schedules | Exact scheduling depends on sufficient recurring evidence | Do not fabricate bill dates from weak recurrence data |
| [YNAB plan templates](https://support.ynab.com/en_us/creating-a-plan-template-ByZJZx_R9) combine targets and scheduled transactions | Planning becomes actionable when users can test explicit changes | Add deterministic controls for flexible-spend reduction, recurring reduction, and expected income |
| [Plaid recurring transaction docs](https://plaid.com/docs/api/products/transactions/) recommend substantial history and separate product access | Connected-data features introduce history, consent, security, cost, and vendor constraints | Keep aggregation and exact recurring schedules out of phases 9-12; require a separate architecture decision |
| [Core Web Vitals](https://web.dev/articles/vitals) defines field targets of LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1 at the 75th percentile | Premium quality needs measurable release gates | Enforce bundle budgets in CI and provide a repeatable Lighthouse release audit; defer RUM until privacy review |

## Design intent

- **Who:** a time-poor individual checking PFIS after sync or before making a spending decision.
- **Job:** understand the next 30 days and test one realistic adjustment.
- **Feel:** calm, precise, private, and consequential.
- **Visual language:** ledger ink, jade, coral, settlement blue, intelligence indigo, restrained depth, and
  information density driven by hierarchy rather than borders.
- **Motion:** 120-240 ms direct feedback only; deterministic numbers animate only after explicit action and all
  non-essential motion respects reduced-motion preferences.
- **Anti-patterns:** KPI walls, calendar theatre, generic chat prompts, speculative predictions, celebratory
  gamification, and new component libraries without a demonstrated product need.

## Phase 9 - Release confidence

Goal: make the new experience safe to ship repeatedly.

Deliverables:

- A production bundle budget check: initial-route JavaScript <= 100 KB gzip and lazy chunks <= 130 KB gzip.
- A checked-in Lighthouse configuration for the built dashboard with Performance >= 90 and Accessibility >= 95.
- CI enforcement for deterministic build and bundle gates; Lighthouse remains a release-environment gate because
  authenticated data and backend timing cannot be represented faithfully by a static CI shell.
- Documented Core Web Vitals targets and a release checklist for desktop and mobile visual baselines.
- No financial values, questions, account identifiers, or interaction events sent to telemetry.

Exit criteria: lint, unit tests, build, bundle budget, accessibility flows, and release audit instructions pass.

Run the release audit against a release-like FastAPI host after building the frontend:
`$env:PFIS_LIGHTHOUSE_URL='https://staging.example/dashboard/'; npm run quality:lighthouse`.
The URL defaults to the local `http://127.0.0.1:8000/dashboard/` host. Reports stay under
`frontend/artifacts/lighthouse` and are not uploaded.

## Phase 10 - Money Horizon

Goal: make the home experience forward-looking without overstating certainty.

Deliverables:

- Replace the historical-looking hero graph with a runway that relates today's net position, projected spend,
  recurring reserve, expected range, and projected month-end position.
- Label values as **Observed**, **Calculated**, or **Forecast**.
- Make the forecast range and deterministic assumptions available without leaving the surface.
- Use sentence-level financial storytelling: what changed, what remains, and the current risk.
- Preserve Daily Brief and ranked recommendation as the next layer, not competing hero widgets.

Exit criteria: the month-end outcome and its evidence are understandable without reading a chart legend; the
surface works at 360 px, keyboard-only, reduced motion, and high zoom.

## Phase 11 - Deterministic Scenario Studio

Goal: turn insight into a reversible decision preview.

Deliverables:

- A user-scoped `POST /api/analytics/scenario` endpoint based on the existing projection rules.
- Three explicit inputs: trim flexible spend, reduce recurring costs, and add expected income.
- No ledger mutation: the response is a preview containing baseline, adjusted outcome, effective adjustments,
  assumptions, data-through date, and ruleset version.
- Server-side clamping prevents reductions larger than the relevant projected amount.
- A focused Decision Studio in Analytics that compares baseline and scenario month-end position and explains the
  delta in plain language.

Exit criteria: ownership, validation, clamping, determinism, and non-mutation tests pass; the UI has one clear
preview action and never describes a scenario as guaranteed.

## Phase 12 - Financial rhythm

Goal: make PFIS feel proactive while keeping the user in control.

Deliverables:

- Persist an in-app briefing cadence of daily, weekly, or monthly in dashboard preferences.
- Use the selected cadence for the deterministic brief endpoint and explain the setting in Customize.
- Keep recommendations ranked by consequence and evidence; do not introduce notification spam or external
  delivery in this phase.
- No behavioral analytics and no engagement-maximizing mechanics.

Exit criteria: cadence persists per user, remains backward compatible, and changes the requested brief period.

## Phase 13 - Connected financial picture (gated)

This phase is intentionally not authorized for implementation yet. Before selecting a provider or writing code,
PFIS needs a separate review covering consent UX, data minimization, refresh and deletion semantics, credential
boundaries, regional availability, vendor pricing, transaction-history requirements, incident handling, and
fallback behavior. Product analytics/RUM follows the same gate.

## Implementation sequence

1. Establish phase 9 budgets and release documentation.
2. Build Money Horizon from existing projection contracts.
3. Add and test the scenario API, then add the lazy-loaded Decision Studio.
4. Add the preference migration and wire briefing cadence end to end.
5. Run backend and frontend quality gates, browser flows, responsive review, Lighthouse where the release
   environment is available, and a final accessibility/design audit.

## Success measures

- A user can state the expected month-end position and biggest risk after one screen.
- A scenario can be previewed in under 30 seconds without changing financial records.
- Forecast numbers always expose assumptions, freshness, and ruleset provenance.
- Initial-route JavaScript stays within 100 KB gzip.
- Release audits target Performance 90+, Accessibility 95+, LCP <= 2.5 s, INP <= 200 ms, and CLS <= 0.1.
- No phase adds financial telemetry or an external data processor without a separate privacy decision.
