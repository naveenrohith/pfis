# PFIS UI/UX Revamp Roadmap

**Status:** Phases 0-8 implemented and verified on 2026-07-16
**Scope:** Frontend experience overhaul. Preserve backend business logic and existing API contracts unless a new approved interaction proves a narrowly scoped API gap.

## 1. Product Decision

### Product identity

PFIS is a **personal financial command center**. It turns fragmented financial activity into a clear, trustworthy daily plan.

PFIS is not primarily an expense tracker, admin dashboard, email client, parser console, generic analytics tool, or open-ended chatbot. Those capabilities support the command-center promise; they do not define the product.

### Primary user

The initial experience is designed for one financially aware but time-poor individual whose information is fragmented across transactions, financial emails, recurring commitments, and accounts. Household, advisor, organization, investment-management, tax-advice, and autonomous-money-management products are explicitly deferred.

### User questions PFIS must answer

1. What changed in my financial position?
2. Why did it change?
3. What needs my attention now?
4. What is the most useful action to take next?
5. Can I trust the underlying data and recommendation?

## 2. Experience Architecture

### Primary navigation

| Destination | Purpose | Current capabilities mapped here |
|---|---|---|
| Today | Establish position, explain the meaningful change, and present one priority | Overview, daily brief, recommendations |
| Activity | Explore evidence and recurring behavior | Transactions, timeline, merchant/category drill-down, recurring charges |
| Plan | Make intentional future decisions | Budgets, goals, net worth, cash-flow outlook |
| Insights | Explain historical drivers and forward-looking patterns | Analytics, category/merchant intelligence, forecasts |
| Data & settings | Configure data sources and recover operational issues | Accounts, Gmail sync, imports, pipeline health, preferences |

`System` is not a top-level personal-finance destination. Parser health, inbox source records, and other technical operations move into **Data & settings**, with technical detail progressively disclosed.

### Today: the core product moment

The first screen must work as a financial briefing, not a metric dashboard.

```text
Greeting and period context
  -> Financial position: one decisive headline and supporting amount
  -> AI coach: why this matters, grounded in evidence
  -> Priority action: one recommended next move
  -> Supporting pulse: at most three secondary measures
  -> Evidence: recent activity or a compact trend, available on demand
```

The above-the-fold experience must state the financial situation and the next action without requiring the user to interpret a grid of cards.

### Content hierarchy

- **Primary (about 60%)**: current position, meaningful change, and recommended action.
- **Secondary (about 30%)**: confidence, context, trend, and progress toward an outcome.
- **Detail (about 10%)**: raw metrics, filters, diagnostics, and historical evidence.

No item may appear in multiple home-screen collections unless each appearance has a distinct job. For example, a recommendation may appear as the single priority in Today and as detailed evidence in Insights, but not as three visually equivalent cards.

## 3. Visual Direction

### Intended character

- 70% Apple: quiet confidence, generous space, and natural feedback.
- 20% Linear: precise typography, compact controls, and excellent keyboard behavior.
- 10% Copilot Money: emotionally useful financial storytelling and purposeful colour.

PFIS should feel calm, personal, deliberate, and trustworthy. It must not resemble a Bootstrap or generic enterprise-admin dashboard.

### Non-negotiable design rules

1. Use whitespace and typographic hierarchy before borders, shadows, gradients, or colour.
2. A surface must have a job: hero, quiet panel, interactive row, data visual, or overlay. Do not wrap every item in a card.
3. Avoid nested-card stacks and repeated thin borders.
4. One screen has one dominant message and one primary action.
5. Finance colour is semantic, not decorative: income, outflow, savings, risk, recurring, information, and AI each have deliberate roles.
6. Charts lead with an insight or annotation. The visual is supporting evidence, not decoration.
7. Empty states are compact, reassuring, and actionable; never large blank containers with a short sentence.
8. Raw email bodies, parser diagnostics, and other technical content stay out of primary personal-finance flows.

### Design tokens v2

The design system will define tokens for:

- Typography: display value, headline, title, body, caption, metadata.
- Colour: canvas, surfaces, neutral scale, semantic financial states, chart series, and focus states.
- Spacing: 4/8-point scale.
- Radius and elevation: minimal, differentiated by surface purpose rather than applied everywhere.
- Motion: durations, easing, loading, reordering, success, and dismissal states.
- Charts: axis, grid, annotation, tooltip, comparison, and accessible data-table states.

## 4. Component and MCP Strategy

### Product-owned system

PFIS owns the visual language, tokens, composition, financial components, and content patterns. Component libraries may supply behavior or reference implementations; they do not dictate the product appearance.

### Approved foundation

- React, Vite, TypeScript, Tailwind, React Query, and existing API hooks.
- Motion for restrained feedback and layout movement.
- Lucide for the core icon language.
- TanStack Table for the transaction ledger engine.
- React Hook Form plus Zod for forms.
- cmdk for global search and commands.
- dnd-kit for deliberate personalization and reordering.
- Recharts for the initial chart system.
- Playwright and Axe for browser, visual, and accessibility verification.

### Curated discovery sources

| Source | Use | Constraint |
|---|---|---|
| shadcn registry MCP | Accessible primitives, patterns, and compatible registries | Search only after a concrete interaction is specified |
| Radix | Complex accessible behavior such as dialogs, menus, popovers, and selects | PFIS styles and content rules remain authoritative |
| Aceternity-compatible registry | Candidate visual or motion details | Never use it to define dashboard shell, navigation, or data density |
| Figma | Approved visual exploration and implementation handoff | Designs need explicit review before production code |
| Browser research | Inspect real product interaction patterns | Record the reason and PFIS adaptation; never copy a product wholesale |
| Context7 | Current technical documentation | Supports implementation only; it does not make product decisions |
| Playwright | Viewport checks, keyboard flows, and visual regression | Required for each major redesigned surface |

No library is adopted solely because it appears modern. Additions require a decision record covering interaction need, accessibility, dependency cost, mobile behavior, maintenance, and the PFIS visual adaptation.

### Explicitly deferred by default

- Next.js/platform migration, monorepo restructuring, auth replacement, and database migration.
- MUI, Ant, Mantine, DaisyUI, generic dashboard templates, or mixing full design systems.
- GSAP, Lottie, Three.js, React Three Fiber, particles, parallax, heavy glassmorphism, and decorative animated backgrounds.
- Tax advice, investment advice, voice control, autonomous money movement, referrals, affiliate systems, and broad marketing-site work.

## 5. Delivery Plan

### Phase 0: Protect the baseline (2-3 days)

- Inventory the current UI and preserve browser screenshots at desktop, tablet, and mobile widths.
- Separate reusable behavior from visually obsolete compositions.
- Confirm which existing routes, hashes, shortcuts, and query contracts must continue to work.
- Establish a safe commit/branch boundary before large frontend replacement work.

**Exit gate:** A documented before-state and a safe development boundary; no backend behavior is changed.

### Phase 1: Product experience definition (1 week)

- Produce the navigation map above with feature ownership.
- Write the Today information hierarchy and content rules.
- Map current sections into primary, secondary, moved, merged, or retired destinations.
- Define the first-ten-seconds experience and the core user journeys: check position, understand a change, review activity, plan an outcome, and repair data.

**Exit gate:** Product brief, information architecture, journey map, and content hierarchy are approved.

### Phase 2: Research and visual exploration (1 week)

- Research by design problem: financial briefing, ledger density, recommendation trust, planning, navigation, and empty states.
- Create PFIS decision records: adopt, adapt, or reject.
- Explore two to three visual directions in Figma or code; select one before component build-out.
- Verify current documentation and library APIs when a source is shortlisted.

**Exit gate:** A selected direction, a compact research library, and no unresolved visual-system decision.

### Phase 3: Design system v2 (1-2 weeks)

- Implement token foundations and representative visual states.
- Build only the initial primitives: button, field, select, tabs, menu, dialog, toast, badge, tooltip, empty state, section heading, hero, insight, action, ledger row, and chart frame.
- Introduce Storybook only when these primitives have approved variants worth maintaining.

**Exit gate:** The system can render a polished Today screen and an Activity ledger without one-off CSS.

### Phase 4: Prototype the new experience (1-2 weeks)

- Create approved desktop and mobile prototypes for Today, Activity, Plan, Insights, Review, and Data & settings.
- Validate information hierarchy, reading order, navigation, loading states, empty states, and failure states.
- Define responsive behavior before implementation rather than shrinking the desktop layout later.

**Exit gate:** Reviewed prototypes and implementation specifications for each primary flow.

### Phase 5: Build the new shell and Today (2 weeks)

- Implement the redesigned navigation shell and global command/search experience.
- Build Today as the first production-quality destination.
- Replace the card-grid home with a financial position hero, AI coach, priority action, and compact supporting evidence.

**Exit gate:** Today works with live data, keyboard navigation, light/dark themes, and the required viewports.

### Phase 6: Build Activity and Review (2 weeks)

- Replace transaction cards with a responsive, dense ledger and detail panel/drawer.
- Rebuild timeline as an activity stream rather than a stack of cards.
- Redesign review as a focused task flow, including a compact and useful all-clear state.

**Exit gate:** Search, filters, drill-down, correction actions, and empty states work without a generic-admin visual language.

### Phase 7: Build Plan, Insights, and Data & settings (2-3 weeks)

- Rebuild goals, budgets, net worth, cash-flow outlook, and health into a planning experience.
- Turn analytics into narrative insight plus evidence, with drill-down on demand.
- Move sync, email-source, import, parser health, and recovery operations into Data & settings.

**Exit gate:** Every original capability is reachable in the new model, with technical content appropriately de-emphasized.

### Phase 8: Finish, verify, and release (1-2 weeks)

- Add intentional microinteractions, skeletons, transitions, feedback, and polished empty states.
- Complete browser coverage, visual-regression review, and manual accessibility review.
- Measure performance and approve release visual baselines.
- Add privacy-safe product analytics only after defining the question each event answers.

**Exit gate:** Production build, lint, tests, browser flows, accessibility checks, responsive review, and visual approval are all green.

## 6. Ongoing Quality Bar

Every new or migrated experience must satisfy:

- A user can identify their current financial position and next action without interpreting a metric wall.
- The screen uses a clear reading order and no visually equivalent competing primary cards.
- Keyboard operation, visible focus, accessible names, contrast, and reduced motion are supported.
- Desktop, tablet, and mobile layouts are intentionally designed.
- Motion explains state change or hierarchy; it never exists merely to decorate.
- Financial data, merchant names, email content, transaction identifiers, and account details do not enter telemetry.
- New dependency, registry component, or MCP recommendation has an explicit decision record.

## 7. First Implementation Decision

The first implementation slice after the Phase 1-4 approval work is **Today**. It establishes the navigation shell, visual language, financial hero, AI coach, and recommendation model that the rest of PFIS will inherit.

## Appendix A: Phase 0 Boundary Audit (2026-07-16)

### Verified application boundary

- The canonical client is the React/Vite application under `frontend/`, served at `/dashboard` when built.
- The backend's static dashboard is a fallback only. New experience work must not be added to `backend/app/static`.
- Existing APIs already cover the first redesign phases: workspace/dashboard state, transactions, insights, analytics, budgets, accounts, deterministic guidance, preferences, Gmail sync/status, pipeline health, reports, and live dashboard updates.
- The existing app already has browser coverage for keyboard command access, quick add, transactions, dashboard personalization, reduced motion, Axe analysis, and desktop/tablet/mobile screenshots.

### Preserve as behavior and compatibility contracts

| Area | Preserve | Revamp implication |
|---|---|---|
| App providers | Authentication, workspace period, sync state, React Query, theme, toast | Keep the provider layer; change its presentation only |
| Data layer | `frontend/src/lib/api.ts`, shared types, workspace queries, live sync contracts | Do not duplicate API calls or move financial logic into components |
| Direct actions | Search/command access, sync, quick add, review and transaction actions, exports | Recompose actions into the new experience; do not remove working flows |
| URL compatibility | Existing section hashes and navigation helpers | Redirect or map legacy hashes while the new navigation rolls out |
| Quality checks | Playwright, Axe, existing unit tests, responsive snapshots | Refresh intended baselines only after review; retain interaction coverage |

### Replace as presentation architecture

- `DashboardLayout`, `Header`, `SectionNav`, and the workspace composition model.
- The generic card grammar: `StatCard`, `ActionCard`, `InsightCard`, `RecommendationCard`, `TimelineCard`, and most direct `Card` compositions.
- Current page headings and section order, which present collections of equally weighted panels rather than a single financial narrative.
- The styling and token layer in `frontend/src/styles/index.css`, while retaining accessibility and reduced-motion policies.
- Existing page-level layouts for Overview, Guidance, Recommendations, Timeline, Insights, Analytics, Transactions, Review, Inbox, Pipeline, Budgets, and Net Worth. Their data loading and actions remain useful; their visual composition is not the new contract.

### Relocate in the new information architecture

| Existing area | New destination | Reason |
|---|---|---|
| Overview, Guidance, Recommendations | Today | One briefing, one priority, evidence on demand |
| Transactions, Timeline, Merchants, Categories | Activity | A coherent evidence and recurring-behavior workflow |
| Budgets, Net Worth, Goals, cash-flow outlook | Plan | Future-oriented decisions rather than widgets |
| Insights and Analytics | Insights | Explanations, drivers, comparisons, and forecasts |
| Inbox, Gmail sync, Pipeline Health | Data & settings | Necessary operational capability, not a primary personal-finance moment |

### Current worktree risk and safe rule

The current branch contains a large mixed set of modified and untracked backend, frontend, test, documentation, migration, and configuration files. Do not reset, discard, or broadly reformat this worktree during the UI revamp.

Before Phase 5 implementation, create a deliberate branch/commit boundary that preserves the existing backend and current frontend behavior. Until then, roadmap, prototype, token, and isolated component work must be scoped carefully and reviewed against the existing visual baselines.
