# PFIS UI/UX Redesign Plan

**Status:** Approved implementation plan; implementation in progress.
**Branch:** `codex/ui-ux-redesign`, created from the clean `main` HEAD (`0662ed3`).
**Scope:** Frontend experience and presentation. This document does not authorize changes to financial calculations, stored data, backend contracts, or provider behavior.

## 1. Objective

Make PFIS easier to understand during a quick financial check-in and more coherent during deeper planning. A user should be able to identify their current position, understand what changed, distinguish observed facts from estimates and forecasts, and find one useful next action without scanning a wall of panels.

The redesign follows the existing PFIS direction in `docs/ui-ux-product-experience.md` and `docs/ui-ux-design-system-v2.md`: Quiet Horizon, decision before data, one dominant idea per view, progressive disclosure, a recognizable Financial Horizon, and evidence available when needed. This plan addresses implementation drift and newly visible composition problems; it does not restart the visual identity or replace the existing React/Vite stack.

## 2. Evidence and root causes

The supplied screenshots and read-only code review point to five connected causes:

1. **Feature accumulation:** each new analysis or evidence capability is appended to an existing page, so a screen increasingly resembles a catalog of features.
2. **No single owner for a financial fact:** the same card due, balance, or forecast is repeated in a hero, summary strip, tab, chart, and evidence block without each appearance clearly serving a different task.
3. **Backend state is too visible:** states such as `needs_anchor`, `observed_partial`, confidence, coverage, and ruleset version appear beside user decisions instead of being translated into a clear explanation and recovery action.
4. **Navigation has accumulated layers:** workspace navigation, Plan tabs, card tabs, local disclosures, and long scrolling content can all appear in one journey. Plan’s visible six destinations also conflict with its existing four-stage model.
5. **Charts have no enforced shared grammar:** shared `ChartFrame` exists, but current charts also use independent Recharts and SVG implementations. The card daily-path copy promises an uncertainty band that the rendered graph does not currently show.

These causes compound. Reducing borders or changing a component library alone will not resolve duplicate facts, uncertain page ownership, or conflicting chart semantics.

## 3. Product and compatibility boundaries

### Keep stable

- Five global destinations: Today, Activity, Plan, Insights, and Data & settings.
- Existing API and calculation behavior, including observed-versus-estimated distinctions, forecast assumptions, currency handling, and user confirmation boundaries.
- Existing navigation hashes and cross-feature routes. Map old hashes to their new destination and relevant view; do not break bookmarks or internal actions.
- PFIS’s Quiet Horizon visual direction, semantic finance colors, Base UI behavior primitives, TanStack Table, Recharts, Lucide, Motion, React Hook Form, and Zod.
- Privacy boundaries: no financial amounts, merchant names, transaction identifiers, account details, or email content in telemetry.

### Change through this work

- Page hierarchy, navigation grouping inside workspaces, content ownership, terminology, density, repeated-record presentation, chart composition, responsive behavior, and progressive disclosure.
- Frontend presentation selectors/view models where a shared translation of existing API states is needed. Do not mutate or reinterpret the underlying financial facts.

### Explicitly out of scope

- Backend, database, API, provider, forecasting, financial-health, or recommendation-rule changes unless prototype validation reveals a specific missing capability. Any such gap becomes a separate reviewed decision.
- Replacing the application framework or adding a complete visual component system.
- Removing capabilities simply to shorten pages. Every current capability must remain reachable in a task-appropriate place.

## 4. Proposed information architecture

Retain the five global destinations. Simplify local navigation around user tasks, while preserving direct links to existing sections.

| Destination | Primary user question | First-level content | Secondary detail |
|---|---|---|---|
| **Today** | What is my position, and what should I do next? | Financial Horizon, one priority action, up to three supporting signals, meaningful change | Evidence, forecast assumptions, and action history under the existing Today / Actions route |
| **Activity** | Where did money move, and what needs checking? | Transaction ledger and review queue | Timeline, recurring activity, merchant/category drill-down, transaction source details |
| **Plan** | Where am I heading, and what can I change? | Safe to spend; Position; Commitments; Outlook | Cards as account detail under Commitments; Budgets and goals under Outlook; calculation evidence |
| **Insights** | What patterns explain the change? | One conclusion and its supporting trend or ranked drivers | Category, merchant, anomaly, calibration, and forecast detail |
| **Data & settings** | Is my data connected and usable? | Source health and the next required repair | Connections, statements/imports, privacy, preferences, diagnostics, technical evidence |

The recommended Plan navigation aligns the existing four-stage model in `PlanModel.ts`: Safe to spend, Position, Commitments, and Outlook. Cards becomes a contextual account-detail workspace reachable from Position and Commitments; Budgets becomes a control within Outlook. Validate the wording and discoverability with a lightweight card sort and task test before implementation. Do not promote Cards to a global destination. `#cards` and `#budgets` remain direct entry points; `#cards` opens Plan → Commitments → the selected card detail, and `#budgets` opens Plan → Outlook → Budgets. Every other legacy hash must retain the exact current target from `workspaceNavigation.ts` unless a reviewed decision documents a user-evidenced remapping.

When a card is open, use a clear breadcrumb/back context instead of showing the Plan stage tabs and a second full tab bar simultaneously. Proposed card task views are **Now**, **Pay**, **Activity**, and **Evidence**. Keep the selected card and local view in URL state so direct links and browser back/forward restore the view.

Recommendation follow-up should leave the Today overview’s main scroll. Keep it discoverable under Today / Actions (`#recommendations`) so it remains attached to the recommendation lifecycle rather than being confused with transaction review.

### Navigation-depth rule

Aim for: global destination → one local view → optional evidence detail. Avoid tabs inside tabs and nested accordions. Use a page split when two areas support different tasks; use a disclosure only for supplemental facts a subset of users needs.

## 5. Shared financial language and state presentation

The application must preserve source truth while reducing the number of concepts users must learn. Do not create one universal status enum: source basis, evidence health, decision readiness, and action lifecycle describe different things and must stay orthogonal. Use shared typed presentation mappings instead of letting every feature invent its own labels.

| Independent axis | Values to present | UI responsibility |
|---|---|---|
| **Basis** | Issuer-stated; provider-observed; user-observed; PFIS estimate; user-planned | Identify where the value came from and what it represents |
| **Evidence health** | Current; stale; incomplete; needs review; missing | Explain whether the supporting evidence can be relied on and why |
| **Decision readiness** | Ready; action needed; waiting for evidence; monitor | State whether the user can proceed, must act, or should wait |
| **Action lifecycle** | Suggested; chosen; snoozed; not relevant; outcome recorded | Show where a recommendation or follow-up stands |

For each important amount, show its basis and effective/as-of date. Add evidence-health context where it changes the decision. Keep technical source IDs, detailed confidence, coverage windows, and ruleset versions in evidence detail and Data & settings.

Backend statuses remain available in detailed evidence and Data & settings. Do not collapse separate axes into one confidence score or relabel a user-entered value as issuer-verified. Missing or stale evidence must fail closed: no safe-to-spend or payment-runway calculation may silently fall back to zero or appear ready because an amount is absent. Preserve the last valid amount and mark its age when the existing calculation permits it. A central mapping requires exhaustive tests for every supported source/status pair before screens consume it.

Terminology corrections to include in the first semantic-safety slice:

- “Official statement position” → **Statement amount due**. A statement due is not a current card position.
- “Record verified position” → **Record observed balance**. The current manual flow records user-observed evidence.
- “Live” → **Connected** or **Last synced [time]**, unless a defined live-data service-level agreement supports “live.”
- “Statement-backed plan” → **Ready to use** or **Evidence current** only when the underlying source supports that description.

## 6. Page redesign specifications

### Today

- Keep one PageIntro, one Financial Horizon, and one dominant priority action.
- Put the conclusion and relevant as-of context before supporting numbers.
- Retain no more than three supporting signals and a short “what changed” list.
- Remove the full recommendation outcome log from the overview; surface a compact pending count/link to Today / Actions.
- Put recommendation evidence and trade-offs behind a clearly named, single disclosure or detail view.
- Preserve separate loading, low-data, stale-sync, partial-error, and deficit narratives; do not render a wall of identical skeletons.

### Plan: Available now

- Separate first-time setup from the ready-to-use planning view.
- Present the required inputs as a short, staged task: funding account → observed balance → next confirmed income date.
- Show only the next useful input; explain why it is required in one sentence.
- After calculation, replace the setup emphasis with one result, its basis/date, the next commitment or risk, and a visible “Edit inputs” path.
- Keep detailed assumptions and evidence available on demand. Do not repeat the same flexible-money result in a second equal-weight metric strip.

### Plan: Accounts & balances

- Lead with one net-worth/current-position statement and an explicit as-of/basis label.
- Show unresolved account identities and provider connection problems as concise, actionable notices.
- Keep the account list as compact rows, grouped by asset/liability where that helps scanning.
- Place history below the current position and use the shared time-series chart grammar.
- Move connection setup and mapping operations to Data & settings; retain a clear route to repair.

### Plan: Commitments and Cards

- Lead with the next due item or the most material risk; use a chronological/prioritized list for repeated obligations.
- Each row should answer: what, how much, when, source/basis, and what action is available.
- Preserve separate statement due, current outstanding, estimated position, and payment runway. Do not aggregate across currencies or incomplete card coverage as if totals were complete.
- For a selected card, show a compact decision summary once, then one primary trajectory and the next action. Put issuer calculation, source records, event history, utilization details, and alternate payment scenarios in separate purposeful views or evidence detail.
- Use the card-local task views **Now**, **Pay**, **Activity**, and **Evidence** as prototype candidates. Keep card selection and active view URL-addressable and make browser back/forward restore them.
- Never label a statement due as current outstanding, or a user-entered observation as issuer-verified. If the source or coverage is incomplete, state that next to the affected decision.
- Review whether portfolio-level and per-card panels can share a single event/commitment model without hiding per-account context.

### Plan: Outlook & goals

- Use one month-end/outlook narrative with a chart only when it clarifies the time path or uncertainty.
- Keep scenario inputs close to their before/after result and label every result as a preview.
- Organize budgets and goals around user changes and progress, not a collection of equal metric cards.
- Keep data sufficiency and model calibration subordinate to the conclusion, with a direct explanation link.

### Insights

- Start with a sentence stating what changed and the comparison period.
- Show one primary visualization per view, followed by a ranked contribution list and linked evidence.
- Separate historical observations from forecasts and recurring candidates.
- Keep calibration samples and technical anomaly adjudication in a clearly secondary detail path.
- Replace a long all-in-one article with task-specific views for Drivers, Categories, and Merchants, while retaining context between them.

### Activity and Review

- Keep the transaction experience ledger-first: searchable/filterable rows, responsive mobile row treatment, and selected-record detail.
- Make review a focused queue with a clear current item, source evidence, proposed value, correction controls, and progress through the queue.
- Keep timeline and recurring-activity context secondary to transactions/review.
- Reuse the existing TanStack Table and interaction patterns where they serve this task; do not create another table framework.

### Data & settings

- Make source status understandable at a glance: connected, needs attention, or unavailable, with a specific next action.
- Group statement import, connections, privacy/preferences, and diagnostics by the user task.
- Keep parser, ruleset, coverage, and recovery evidence accessible here without making it the language of the daily financial experience.
- Avoid presenting operational counts or readiness percentages without explaining what decision they support.

## 7. Shared visual and interaction system

- Use one destination introduction and one dominant composition per view.
- Use surfaces by purpose: financial narrative, action, interpreted insight, chart, form, or selected detail. Use ledger/list rows for repeated records; do not wrap every record in a bordered card.
- Keep one primary action per view. Secondary actions should not compete in weight or placement.
- Keep financial amounts aligned with tabular numerals and consistent currency/date formatting.
- Use semantic color for financial meaning and interaction; labels must carry state meaning without color alone.
- Review the 52px large PageIntro treatment and sticky workspace bars against long-scroll pages, smaller laptop heights, zoom, and mobile. Ensure sticky layers never hide section headings, focus, or anchor targets.
- Preserve 44px minimum touch targets, safe-area spacing, visible keyboard focus, reduced-motion behavior, light/dark themes, and accessible control names.
- Do not add a library unless a specific interaction cannot be delivered accessibly with the current stack. Record the need, alternatives, bundle cost, maintenance, license, and mobile behavior first.

## 8. Chart grammar

Every chart must answer a named user question before a chart type is selected. Use the existing `ChartFrame` as the intended shared composition or document why a chart needs a specialized frame.

| Data relationship | Preferred treatment | PFIS-specific rule |
|---|---|---|
| Change over time | Line/area only when a continuous time path matters | Label observed, estimated, and forecast segments; mark their boundary and show uncertainty when the text claims it |
| Category/merchant ranking | Sorted horizontal bars or a compact ranked list | Show amount and comparison/delta directly; no donut by default |
| Actual vs target | Direct comparison/bar or annotated threshold | Name the target and unit; do not rely on color alone |
| Scenario comparison | Baseline and scenario values with a clear delta | State that it is a reversible preview, not a guaranteed outcome |
| Sparse/incomplete series | Honest empty/partial-state summary | Never connect missing values in a way that implies observed continuity |

Shared chart requirements:

- Conclusion-led title; subtitle includes measure, period, and basis.
- Axes and labels include units; dates remain legible at phone widths.
- Direct annotations sit beside the event they describe and do not overlap the data.
- Legends explain observed/estimated/forecast meaning, not merely line colors.
- Tooltips supplement labels; important meaning is visible without hover.
- Provide a concise text summary and structured data alternative for decision-relevant charts.
- Keyboard and touch interaction expose the same detail; contrast and non-color cues are checked.
- Validate resizing and long currency labels. No clipped axes, overlapping lines, hidden event markers, or misleading interpolation.

### Current chart inventory and intended treatment

| Current surface | User question | Redesign treatment |
|---|---|---|
| Position → net-worth history (`NetWorthSection`) | How has the recorded position changed? | One currency-labelled historical line, explicit snapshot basis and as-of context, legible dates, and an expandable table; do not imply investment-market valuation. |
| Insights → daily observed-spend trend (`InsightsSection`) | When did observed debit spend change? | One conclusion-led observed-series chart with period and currency units, sparse date ticks, non-hover summary, and a table of dates/amounts/counts. |
| Cards → daily path (`CardDailyPathPanel`) | What could happen to utilization before statement close? | Keep the central estimate and event/target/limit cues; render the balance uncertainty range as a band when the matching credit-limit anchor exists. If it does not, state that limitation and keep the exact amount range in the table. |
| Cards → utilization history (`CardUtilizationHistoryPanel`) | What is issuer evidence versus the current ledger estimate? | Separate issuer statement anchors from the estimated continuation at a marked basis boundary; never draw one unqualified line across the source change. Keep the target guide, summary, and evidence table. |
| Outlook / budgets / payment scenarios | What changes under a plan or scenario? | Retain direct labelled comparisons and text ranges; do not add decorative charts where a compact before/after comparison answers the question more clearly. |

The repository already has a `ChartFrame` and Recharts/SVG implementations. Reuse the existing stack; make the frame carry the chart question, measure/period/basis, summary, and data alternative, while specialist renderers own marks, units, and uncertainty. Do not add a chart dependency.

## 9. Delivery sequence and proof gates

The work should proceed in vertical slices. These are sequence estimates of scope, not calendar promises.

### Phase 0 — Baseline and inventory

**Scope:** shell, Today, Activity/Review, Plan, Insights, Data & settings; existing URLs, hashes, tests, and design contracts.

**Work:** capture current light/dark screenshots at 360px, 768px, and 1440px; inventory every visible section and action; map duplicate facts to a canonical owner; list all hashes and cross-feature routes; record current build/bundle and browser gate results.

**Exit:** an agreed screen inventory, before-state, compatibility map, and no unresolved question about the existing behavior that the redesign must preserve.

### Phase 1 — Task research and IA validation

**Work:** test the five core journeys already defined in `docs/ui-ux-product-experience.md`: daily check-in, explain a change, review uncertain activity, adjust a plan, and repair data trust. Use a small formative usability round with time-poor users; include first-time and returning users. Card-sort Plan labels and test whether Cards belongs beside or within Commitments.

**Proof:** record task completion, time to find the answer/action, wrong turns, and whether participants can distinguish source facts from estimates and forecasts. Update the proposed IA only from observed confusion; keep this document marked proposed until the grouping decision is recorded.

**Exit:** approved sitemap, page questions, content ownership map, and terminology/state presentation table.

### Phase 2 — Screen prototypes and chart review

**Work:** create desktop and mobile low/high-fidelity prototypes for Today, Activity/Review, all Plan tasks, Insights, and Data & settings. Prototype populated, empty, low-data, stale, loading, and error states. Use realistic but sanitized financial examples. Test long amounts, dates, narrow widths, dark mode, keyboard order, and sticky behavior.

**Proof:** moderated task walkthroughs plus chart comprehension questions. Review the proposed primary chart on Cards and the Financial Horizon with observed, estimated, and forecast states. Resolve the uncertainty-band mismatch by making the visual and explanation agree.

**Exit:** reviewed prototypes, final local navigation model, chart specifications, and annotated implementation notes.

### Phase 3 — Semantic safety and shared presentation contracts

**Scope:** financial terminology in Today/Cards, `frontend/src/components/system/FinancialPrimitives.tsx`, shared chart utilities, and a small financial-state presentation module with focused tests.

**Work:** correct misleading labels; implement four independent presentation axes; standardize PageIntro, hero, action, insight, row, disclosure, loading/error, and ChartFrame usage. Centralize labels and metadata for provider, user-entered, statement, ledger estimate, forecast, and unavailable states. Add chart formatting and accessible-summary conventions. Retain specialist primitives where appropriate.

**Exit:** each source/status mapping is tested; missing/stale states cannot render a false-ready zero; misleading financial labels are corrected; one representative chart passes keyboard, responsive, and text-alternative review; no new library is required without an approved decision record.

### Phase 4 — Shell and Today

**Scope:** `frontend/src/app/`, `TodayExperience.tsx`, `FinancialHorizon`, recommendation presentation/follow-up.

**Work:** tune global/local navigation depth and sticky behavior; compose the Today overview around the horizon and one action; cap supporting signals; move action history to Today / Actions while keeping its old hash. Show a compact count/link or the single most urgent follow-up, not every accepted item as a long card.

**Exit:** daily check-in is understandable in ten seconds on a typical laptop; priority action and evidence remain clear on mobile; all existing Today links work.

### Phase 5 — Activity and Review

**Scope:** `frontend/src/features/activity/`, transactions, review, timeline, recommendation-action history placement.

**Work:** deliver ledger-first browsing and a focused review queue; keep mobile detail usable; move secondary timeline/recurring detail behind clear local navigation. Keep recommendation-action outcomes separate from transaction corrections while retaining direct navigation from Today.

**Exit:** users can find a transaction, inspect its source, correct/review it, and continue the queue with keyboard or pointer without losing context.

### Phase 6 — Plan, in three independently reviewable slices

1. **Available now and Accounts & balances:** staged setup, result state, account position and net-worth history.
2. **Commitments and Cards:** prioritized due items, card position, statement facts, payment runway, primary trajectory, detail evidence.
3. **Outlook & goals:** month horizon, budgets/goals, reversible scenario comparison.

**Exit:** each slice has one clear user question; values appear once per view unless a second appearance has a distinct comparison or action purpose; basis/date are visible; incomplete coverage is explicit; old hashes land in the correct new view; card-local URL state supports direct links and browser back/forward.

### Phase 7 — Insights and shared charts

**Scope:** `InsightsExperience`, `InsightsSection`, `AnalyticsSection`, `NetWorthSection`, `CardDailyPathPanel`, `CardUtilizationHistoryPanel`, and shared chart helpers.

**Work:** apply chart grammar, align evidence tables, separate observations from projections, and split views according to the research-approved tasks. Remove contradictory copy/visuals and redundant chart-summary panels.

**Exit:** representative time-series, category-rank, target, and scenario charts pass the chart criteria above at 360/768/1440px and in light/dark mode.

### Phase 8 — Data & settings, integration, and release review

**Scope:** `DataExperience` and its source, statement, privacy, preference, and diagnostics views; all redesigned routes.

**Work:** simplify source recovery journeys, verify every financial state routes to the right repair action, run accessibility/responsive/browser/performance checks, and review before/after screenshots with the same data and viewport.

**Exit:** all current capabilities remain reachable, hash compatibility passes, mobile navigation does not cover content/focus, no visual chart defects remain, privacy rules hold, and the existing lint/test/build/e2e/visual/bundle/Lighthouse gates pass.

## 10. Acceptance criteria

### Comprehension and hierarchy

- On Today, a user can identify current position, what changed, and the next action within ten seconds on a typical laptop.
- Every view has one explicit primary question, one dominant composition, and no competing equal-weight hero surfaces.
- A user can correctly identify whether a shown amount is provider/issuer observed, user-entered, calculated from ledger activity, or projected, and can find its as-of date.
- Statement amount due, current outstanding, available credit, and safe-to-spend remain distinct values with distinct labels.
- A missing/stale amount never becomes a false-ready zero in safe-to-spend or payment-runway views.
- User-entered balances are never labelled “verified” or “issuer-stated.”
- No view repeats the same financial fact as multiple independent KPI panels without a distinct comparison purpose.
- Routine tasks need no more than one local view switch; evidence is discoverable and not nested in multiple hidden layers.

### Charts and layout

- Decision-relevant graphs include a visible conclusion, measure, period, basis, legible date/amount labels, and equivalent text/data access.
- Observed, estimated, and forecast segments are distinguishable without color alone; all stated ranges/bands are actually rendered.
- At 360px, 768px, and 1440px, no chart labels/lines/annotations overlap or clip, no page-level horizontal scrolling is introduced, and long currency values remain readable.
- Sticky navigation does not cover focused controls, headings, or hash targets; mobile bottom navigation respects safe areas and does not cover the page’s last action.

### Behavior and quality

- Keyboard operation, visible focus, accessible names, reduced motion, light/dark themes, and 200% zoom remain usable.
- Existing navigation hashes, query filters, keyboard shortcuts, search, and cross-feature actions continue to work or have documented aliases.
- `#cards` and `#budgets` open the correct contextual detail in the proposed four-stage Plan; browser back/forward restores the selected stage/card view.
- No financial computation, persisted data, user ownership, or API contract changes without a separate decision.
- No new dependency without a documented, tested product need and bundle/accessibility/maintenance review.
- Frontend lint, unit tests, production build, bundle budget, Playwright flows, Axe checks, visual snapshots, and release-like Lighthouse review pass before completion.
- Keep the established bundle ceilings: initial route at or below 100 KB gzip and lazy chunks at or below 130 KB gzip.

### Formative usability target

Use five moderated sessions as an initial formative round, not as a statistically representative study. For each core journey, target at least four of five participants completing without moderator hints and zero critical misunderstandings about an amount’s basis or whether a forecast is guaranteed. Any miss should produce a concrete revision and a retest of that task.

**Current validation limitation:** the supplied screenshots, code review, and product-owner approval informed this implementation, but no external participant sessions have been conducted. Automated browser and accessibility checks are engineering evidence only; they do not satisfy the five-session target or prove user comprehension. Per the product owner's direction, proceed with implementation and record the moderated study as follow-up rather than claiming it passed.

## 11. Key implementation files to revisit

| Area | Likely files |
|---|---|
| Shell and URL behavior | `frontend/src/app/DashboardLayout.tsx`, `SectionNav.tsx`, `Header.tsx`, `DashboardUiContext.tsx` |
| Shared primitives/charts | `frontend/src/components/system/FinancialPrimitives.tsx`, `frontend/src/components/ui/Tabs.tsx` |
| Today/actions | `frontend/src/features/today/TodayExperience.tsx`, `frontend/src/features/guidance/RecommendationFollowUp.tsx` |
| Plan structure/state | `frontend/src/features/plan/PlanExperience.tsx`, `PlanModel.ts`, `FinancialPositionSection.tsx`, `CardsSection.tsx`, `TemporalEvidencePanel.tsx` |
| Chart consumers | `frontend/src/features/plan/CardDailyPathPanel.tsx`, `CardUtilizationHistoryPanel.tsx`, `frontend/src/features/accounts/NetWorthSection.tsx`, `frontend/src/features/insights/InsightsSection.tsx`, `frontend/src/features/analytics/AnalyticsSection.tsx` |
| Other destinations | `frontend/src/features/activity/`, `frontend/src/features/data/` |
| Existing quality evidence | `frontend/e2e/`, feature tests, `frontend/package.json`, current UI/UX documentation |

Exact file scope will be refined after the approved prototypes; this list is a discovery map, not permission for a broad refactor.

## 12. Research basis

- PFIS product contract: [`docs/ui-ux-product-experience.md`](ui-ux-product-experience.md), [`docs/ui-ux-design-system-v2.md`](ui-ux-design-system-v2.md), [`docs/ui-ux-masterplan.md`](ui-ux-masterplan.md), and [`docs/ui-ux-revamp-roadmap.md`](ui-ux-revamp-roadmap.md).
- Nielsen Norman Group, [Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/): disclose the core task first, make secondary detail predictable, and validate the grouping with task analysis and testing.
- Nielsen Norman Group, [8 Design Guidelines for Complex Applications](https://www.nngroup.com/articles/complex-application-design/): reduce competition, connect primary information to supporting detail, and make genuinely important items salient.
- GOV.UK, [Data visualisation principles](https://brand.design-system.service.gov.uk/data/) and [Charts](https://brand.design-system.service.gov.uk/data/charts/): define the chart’s purpose and story, simplify labels, annotate without overlap, and avoid interactive charts when a static view can communicate the message.
- GOV.UK, [Task list](https://design-system.service.gov.uk/components/task-list/), [Details](https://design-system.service.gov.uk/components/details/), and [Accordion](https://design-system.service.gov.uk/components/accordion/): use action lists for real tasks, avoid hiding essential information, and avoid nested disclosure patterns.
- W3C WAI, [Tables tutorial](https://www.w3.org/WAI/tutorials/tables/) and [WCAG non-text contrast understanding](https://www.w3.org/WAI/WCAG21/Understanding/non-text-contrast.html): provide structured relationships and equivalent access to chart information.
- CFPB, [Consumer insights on managing spending](https://www.consumerfinance.gov/data-research/research-reports/consumer-insights-managing-spending/): participants described spending tools as potentially helpful for reducing uncertainty; treat this as motivation for clear, timely decisions, not proof that a particular PFIS layout will work without testing.
