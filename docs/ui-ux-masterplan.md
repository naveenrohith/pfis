# PFIS UI/UX Masterplan

PFIS is evolving from a long dashboard into a financial decision workspace. The canonical React UI groups
features by the decisions users are trying to make while preserving existing section hashes and API contracts.

## Quiet-ledger overhaul record

The September 2026 overhaul is implemented on `codex/pfis-uiux-overhaul`, branched from
`chore/pfis-phased-integration`. The current integration branch remains the source of truth for financial
behavior; the main branch was used only as the visual shell reference.

The phase commits are intentionally reviewable:

| Phase | Commit | Scope |
|---|---|---|
| Quiet-ledger shell | `a643a0f` · `ui: restore quiet ledger shell` | Slim rail, concise header, flat Plan labels, calmer spacing |
| Plan Cards | `08151b9` · `ui: make plan cards first-class` | Flat Plan views, Cards decision workspace, progressive disclosure, typed observation client |
| Financial workspaces | `e7e33d9` · `ui: simplify financial workspaces` | Today, Activity, Insights, and Data & settings hierarchy |

The implementation keeps the existing `DashboardSectionId` values and section hashes, including
`#cards`, `#liabilities`, `#household`, `#obligations`, `#networth`, `#analytics`, and `#budgets`.
No new frontend framework, hosted component runtime, analytics processor, provider, migration, or financial
calculation rule was introduced.

### External component and source register

The following research queries and sources were reviewed for interaction patterns. They are references for
PFIS primitives, not instructions to copy catalog blocks into the product.

| Query / source | License or access note | Adoption decision |
|---|---|---|
| `accessible collapsible finance dashboard sidebar mobile sheet` | PFIS-local design research | Adapted into the existing rail and five-tab mobile navigation; hashes and keyboard behavior remain PFIS-owned. |
| `shadcn card workspace tabs progressive disclosure` | Official [shadcn MCP documentation](https://ui.shadcn.com/docs/mcp); registry discovery only | Retain existing Base UI/Radix-compatible PFIS primitives and adapt the existing `Tabs`, `Dialog`, `PageIntro`, and disclosure patterns. No registry package was added. |
| `credit card financial dashboard utilization runway evidence` | PFIS product-domain research | Used to organize existing card read models as position → utilization → runway → evidence; no new calculation rule was added. |
| `accessible tabs disclosure dialog focus restoration` | PFIS accessibility research plus the local dialog implementation | Use native disclosures and existing focus-managed dialogs; verify keyboard, escape, focus restoration, reduced motion, and no sticky-header clipping. |
| `quiet finance dashboard activity ledger insights ranked drivers` | PFIS visual hierarchy research | Applied to Today, Activity, Insights, and Data surfaces; no generic dashboard grid was introduced. |
| [21st repository](https://github.com/serafimcloud/21st) | Repository license reviewed as MIT | Reference only for isolated interaction ideas. No hosted 21st runtime, catalog block, or copied dependency was added. |
| [21st hosted MCP setup](https://github.com/21st-dev/magic-mcp/blob/main/llms-install.md) | Requires external authentication/API key | Not configured or used. PFIS does not depend on hosted design tooling at runtime. |
| [Annnimate 21st alternatives](https://annnimate.com/alternatives/21st-dev) | Catalog/comparison page; no component license adopted | Not used as a code or dependency source. Core dashboard motion remains restrained PFIS motion. |
| [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md) | Public guideline document | Used as a final review checklist for responsive behavior, forms, motion, accessibility, and performance; no code copied. |

### Cards contract decision

The existing `POST /accounts/{account_id}/card-observations` route accepts issuer/connector observations and
requires connector provenance and a complete coverage envelope. The frontend now exposes a typed
`createCardPositionObservation` client method for that contract, but the visible “Record verified position”
dialog deliberately uses the existing manual `POST /accounts/{account_id}/balances` route. This keeps a
user-entered value labelled user-observed instead of incorrectly presenting it as issuer-confirmed. Successful
saves alone invalidate the card overview, forecast, due-runway, utilization, and account-position queries.

### Current gate status

The integrated gate completed locally on 2026-09-17:

- `npm run lint`: passed.
- `npm run test`: 38 files and 95 tests passed.
- `npm run build`: passed; `npm run quality:bundle`: passed (92.8 KB initial-route gzip, 47 lazy chunks).
- `npm run test:e2e:ci`: 26 passed and 10 intentional project skips across 360px, 768px, and 1440px light/dark projects. The run covered keyboard navigation, hash deep links, axe serious/critical checks, reduced motion, responsive overflow, and the flat Plan labels.
- Visual baselines: 6 passed after regenerating the intentional Today quiet-ledger shell snapshots for light/dark mobile, tablet, and desktop.
- `npm run quality:lighthouse`: passed all configured assertions across three runs against the local release-like host at `/dashboard/`.

The separate staging/release-host approval remains an operational follow-up. Pushing the branch is a separate
authorized action.

## Workspace Model

| Workspace | Sections | User outcome |
|---|---|---|
| Today | Financial Horizon, one priority action, up to three supporting signals | Understand the month and choose the next safe action |
| Activity | Transactions, Review, Timeline | Inspect the ledger and resolve uncertainty |
| Plan | Safe to spend, Position, Cards, Commitments, Outlook, Budgets | Move from current position to deliberate financial choices |
| Insights | Drivers, Categories, Merchants | Explain what changed and rank the evidence behind it |
| Data & settings | Connections, Statements, Preferences & privacy, Diagnostics | Control sources, privacy, recovery, and technical health |

Desktop navigation uses a persistent workspace sidebar. Mobile navigation uses five persistent bottom tabs plus
a global quick-add action.
Existing hashes such as `#review` and `#transactions` activate the owning workspace before scrolling to the
requested section.

## MCP Workflow

The project configures the official shadcn registry MCP server in `.vscode/mcp.json`. Start it from VS Code's
MCP controls before component research. Codex users can configure the same server in their user-level Codex
configuration as documented by [shadcn/ui](https://ui.shadcn.com/docs/mcp).

MCP is a development-time discovery tool. Registry results must pass PFIS accessibility, dependency,
performance, privacy, and maintenance review before adoption. Never copy a block directly into production.

### Component Decision Record

| Need | MCP query | Initial decision | Rationale |
|---|---|---|---|
| Grouped dashboard navigation | `accessible collapsible finance dashboard sidebar mobile sheet` | Adapt | PFIS needs its own workspace and hash compatibility model; use registry behavior as a reference |
| Core Button, Card, Input, Badge, Skeleton, Toast | `dashboard UI primitives accessible states` | Retain | Existing typed primitives already use PFIS tokens and accessible states |
| Dialog focus management | `Shadcn dialog focus trap focus restoration React` | Implemented locally | Dialog now traps focus, restores the trigger, locks background scroll, and uses labelled semantics without adding a dependency |
| Mobile workspace navigation | `Shadcn accessible dashboard mobile navigation` | Implemented locally | Five stable workspaces remain visible while existing hashes keep working |
| Transaction table | `Shadcn responsive data table pagination mobile` | Implemented with TanStack Table | Sorting, filtering, pagination, responsive rows, and keyboard review use the existing PFIS primitives |
| Chart explanations and alternatives | `WCAG compliant dashboard chart tooltip` | Implemented locally | Charts now include concise summaries, native explanatory disclosures, and expandable data tables without adding a dependency |
| Command palette | `accessible cmdk application navigation` | Implemented with cmdk | Global navigation, search, sync, quick add, month, and theme actions share one keyboard surface |
| Personalization | `keyboard sortable dashboard widgets` | Implemented with dnd-kit | Widget visibility, supported sizes, ordering, density, and theme persist per user |
| Financial day setting | Existing labelled Input, Card, Button, and Toast primitives | Retain | A native timezone datalist, inline validation, and boundary preview meet the focused settings need without another dependency or custom combobox |
| Gmail disconnect | Existing Dialog, Button, and Toast primitives | Retain | The destructive flow defaults focus to Keep connected, states retained evidence before confirmation, and reports unconfirmed provider revocation without another dependency |
| Portable data copy | Existing Card, Button, Toast, and semantic list primitives | Retain | The settings surface previews included groups—including immutable forecast and recommendation decisions/outcomes—permanent secret exclusions, schema version, manifest verification, and secure-storage risk before one deliberate download action |
| Recommendation decision | Existing Button, icon-action, Toast, and evidence text primitives | Retain | “Use this action,” snooze, and “Not relevant” preserve one calm recommendation hierarchy while recording explicit user intent; no engagement score, celebratory motion, or extra card grid is added |
| Recommendation outcome review | Existing Card, Badge, Button, and semantic section primitives | Retain | Accepted actions return in one evidence log with their captured baseline, four plain-language outcome choices, and the measured directional change; the answer is explicitly final and no engagement score or celebratory motion is introduced |
| Source-email retention | Existing Card, SelectField, Dialog, Button, and Toast primitives | Retain | The control distinguishes content from lineage, explains unresolved-evidence deferral, and confirms irreversible shorter-policy changes with the safe action focused first |
| Account deletion | Existing Card, Input, Dialog, Button, and Toast primitives | Retain | The flow states private deletion versus shared tombstone retention, requires recent login and exact account-specific typing, focuses Keep my account first, and gives a concrete reauthentication recovery path |
| Data Confidence evidence | Existing Card, Badge, Button, and semantic description-list primitives | Retain | The evidence ledger distinguishes observed coverage, freshness, parsing quality, unresolved conflicts, and a source register; every weak row routes to the relevant recovery workspace without adding a gauge, page, dependency, or request |
| Historical evidence recovery | Existing Card, Badge, Button, and Toast primitives | Retain | Data & settings offers preview/capture for a forward-only temporal baseline, clearly separating evidence recovery from financial-data mutation or false historical reconstruction |
| Intelligence readiness | Existing Card, Badge, Button, Skeleton, and disclosure primitives | Retain | Data & settings shows user-scoped evidence gates and recovery paths without collapsing representative release proof into a misleading score |
| Operational status | Existing Card, Badge, Button, and status primitives | Retain | Data & settings separates service health from provider-coverage warnings and routes each issue to the appropriate recovery workspace without exposing internal counters |
| Automatic statement intake | Existing FinancialHero, Select, Button, Badge, file input, and semantic status primitives | Adapt | The Statements workspace now reads the PDF before account selection and exposes a source → recognized product → ledger destination evidence chain. Unsupported layouts remain read-only; supported card/deposit profiles route to compatible owned accounts without adding a dependency. |

| Next-statement card forecast | Existing FinancialHero, semantic section, description-list, and financial typography primitives | Adapt | Cards separates issuer due, current position, and a pace-based next-statement estimate. The estimate exposes historical calibration, planned-payment and scheduled-EMI evidence, range, confidence, next action, and missing-evidence states without adding a gauge, live-data claim, or dependency. |
| Card daily trajectory and hard-limit runway | Existing semantic section, compact SVG plot, disclosure, and evidence-table primitives | Adapt | Cards now makes the backend daily path inspectable from tomorrow through projected close, marking known dated events, utilization-target pressure, and separate hard-limit runway states while retaining a full table fallback and explicit estimate boundaries. |
| Single-card payment scenarios | Existing semantic comparison table, description-list, Badge, and financial typography primitives | Adapt | Cards now compares minimum-due and total-due targets against the same conservative funding path, credits existing payment intentions without calling them settled, and keeps all outcomes read-only. |
| Card utilization history | Existing semantic section, compact SVG plot, evidence table, and financial typography primitives | Adapt | Cards now places issuer-statement anchors beside a bounded settled-ledger roll-forward. The visual uses one quiet line with distinct point treatments, a target guide, and an expandable evidence table so estimates cannot be mistaken for issuer truth. |
| Card portfolio upcoming state | Existing semantic section, description-list, disclosure, and financial typography primitives | Adapt | Cards now composes the next dated obligation across two or more cards while keeping issuer dues aggregate-only, per-card evidence visible, and estimated outstanding explicitly non-live. |
| Card portfolio event timeline | Existing native disclosure, semantic ordered list, time, and evidence primitives | Adapt | Cards now lets users inspect every retained multi-card event—not only the first shared attention—sorted by date with source kind, lifecycle status, confidence, amount, and reason evidence while remaining read-only. |
| Card portfolio payment plan | Existing semantic comparison table, description-list, disclosure, and financial typography primitives | Adapt | Cards now compares minimum-due and total-due targets against shared conservative funding paths, preserves existing planned intentions, and keeps the result explicitly read-only. |
| Hypothetical card spend routing | Existing Card, Input, Select, Button, Badge, and semantic comparison-table primitives | Adapt | Cards now previews where one hypothetical purchase would land across active cards, ranking target/headroom and explicit user-entered reward evidence without authorizing a transaction or claiming issuer economics. |
| Durable statement analysis review | Existing semantic section, disclosure, status, and evidence-table primitives | Adapt | Statements now exposes a user-triggered, redacted analysis artifact for unfamiliar card or bank layouts. Product detection, bounded row previews, rails, reconciliation evidence, and confidence remain review-only; account mapping and ledger import stay separate explicit actions. |
| Deposit rail review | Existing Card, Select, Button, Badge, and semantic status primitives | Adapt | Statements keeps ambiguous bank rows review-only until the user assigns an explicit UPI, debit-card, ATM, or transfer rail; unsupported rows can be held outside the ledger. |
| Deposit rail review | Existing semantic list, Select, Button, Badge, and evidence primitives | Retain | Statements now surfaces unresolved bank rows with account/period context and requires an explicit UPI, debit-card, ATM, or transfer choice before import; users can hold a row outside the ledger without guessing. |

## Delivery Tracker

- [x] Quiet-ledger shell phase: slim rail, concise header, and stable five-destination navigation.
- [x] Flat Plan phase: Cards is a first-class destination with compatible legacy section helpers.
- [x] Cards phase: decision-led first viewport, progressive disclosure, typed connector client, and user-observed position dialog.
- [x] Financial workspaces phase: Today, Activity, Insights, and Data & settings hierarchy aligned to the quiet-ledger model.
- [x] Integrated overhaul gate: full lint, test, build, bundle, e2e, accessibility, responsive, visual, and release-like performance checks.
- [x] Audit current React shell and reusable primitives.
- [x] Configure official shadcn MCP discovery for VS Code.
- [x] Establish MCP adoption rules and the initial decision record.
- [x] Group existing features into task-oriented workspaces.
- [x] Preserve section-hash and cross-feature navigation behavior.
- [x] Complete dialog and mobile workspace-menu focus management.
- [x] Redesign Home around position, attention, and the highest-priority recommendation.
- [x] Complete contextual-help and chart accessibility review.
- [x] Consolidate Insights as historical evidence and Analytics as forward-looking outlook.
- [x] Add premium visual tokens, self-hosted Inter, reduced-motion-aware microinteractions, skeletons, and empty/error states.
- [x] Add five-tab mobile navigation, quick add, command palette, and responsive TanStack transaction table.
- [x] Add deterministic guidance briefs, allowlisted questions, evidence, stable recommendations, and dismissal state.
- [x] Add versioned cross-device dashboard preferences, keyboard widget reordering, and goal-led onboarding.
- [x] Add manual asset/liability accounts, append-only balances, true net worth, and atomic linked transfers.
- [x] Add account identity confidence, evidence trail, and lifecycle history to the Plan surface.
- [x] Add the cash-pocket workflow: bank-to-cash ATM transfers plus account-linked manual cash spending without duplicate spend.
- [x] Add a statement-backed card activity centre for deterministic duplicate, high-value, and pending-reversal signals.
- [x] Add transaction notes, tags, and evidence-preserving split allocations in Activity → Review.
- [x] Add Playwright, axe, multi-viewport browser flows, and visual snapshot specifications.
- [x] Phase 9: enforce bundle budgets and add the release-host Lighthouse/visual-baseline gate.
- [ ] Phase 9 operations: approve Lighthouse and visual baselines on the staging/release host.
- [x] Phase 10: ship the evidence-labelled Money Horizon.
- [x] Phase 11: ship the deterministic, non-mutating Scenario Studio.
- [x] Phase 12: persist the user's in-app financial briefing rhythm.
- [x] Add an owned IANA timezone and a visible Data & settings financial-day boundary.
- [x] Add an owned Gmail disconnect with provider revocation, retained-data disclosure, and an audit event.
- [x] Add a versioned portable data copy with a visible manifest contract and explicit secret exclusions.
- [x] Add owned source-email retention with lineage-preserving redaction, durable sweeps, and an irreversible-change confirmation.
- [x] Add owned account deletion with recent authentication, connector revocation, complete private erasure, session revocation, and auditable shared-household tombstones.
- [x] Centralize recurring knowledge with cadence, lifecycle, confidence, evidence, and rulesets.
- [x] Split Monthly Stability from Data Confidence and consolidate the Today briefing response.
- [x] Replace opaque Data Confidence with a versioned evidence breakdown and exact remediation for every weak dimension.
- [x] Add an observed-source register with explicit partial/unknown completeness states and recovery actions.
- [x] Add a forward-only historical evidence baseline recovery action with explicit non-reconstruction copy.
- [x] Add a user-scoped intelligence-readiness gate view for source, temporal, forecast, recommendation, anomaly, and release evidence.
- [x] Add a visible cross-source reconciliation-quality gate with review, statement, and verified-balance evidence.
- [x] Add settlement-aware bank/card position estimates with observed-versus-estimated proof, pending impact, and cutoff reasons.
- [x] Add the Plan daily bank/card balance path with dated movement, uncertainty bands, source IDs, and fail-closed anchor/review states.
- [x] Add automatic card-versus-deposit statement preflight, compatible account routing, and a reconciliation receipt without retaining PDF bytes.
- [x] Add visible merchant pattern evidence and a user-controlled Learned Rules ledger.
- [x] Add an explainable next-statement card balance/utilisation projection with uncertainty, confidence, evidence, and fail-closed recovery states.
- [x] Add a dated daily card trajectory with known events, utilization-target pressure, and hard-limit runway evidence.
- [x] Add a read-only single-card minimum-vs-total payment-scenario comparison with lower-band funding coverage.
- [x] Add a visible card utilization-history view that keeps issuer statements separate from the bounded settled-ledger estimate and provides an accessible evidence table.
- [x] Add a multi-card upcoming-state view that aggregates only known issuer dues and preserves per-card evidence states.
- [x] Add a dated multi-card event timeline that exposes all retained upcoming evidence with source, status, confidence, and non-action boundaries.
- [x] Add a read-only multi-card minimum-vs-total payment-plan comparison with shared funding-path coverage.
- [x] Add a read-only hypothetical card spend-routing preview with utilization, hard-limit, and explicit reward evidence.
- [x] Add a durable redacted statement-analysis review artifact for unfamiliar card and bank layouts without mutating accounts or the ledger.
- [x] Add explicit deposit-statement rail review before importing UPI, debit-card, ATM, or transfer rows.
- [x] Add explicit bank-statement rail review actions for unresolved UPI, debit-card, ATM, and transfer rows.
- [ ] Phase 13 gate: complete privacy, provider, consent, and cost review before connected accounts or analytics.

The locked scope, research evidence, exit criteria, and phase sequencing are documented in
[ui-ux-next-level-roadmap.md](ui-ux-next-level-roadmap.md).

## Release Gates

- Frontend lint, unit tests, and production build pass.
- No serious or critical automated accessibility violations once the accessibility harness is added.
- Target Lighthouse Performance 90+, Accessibility 95+, LCP at most 2.5s, INP below 200ms, and CLS below 0.1.
- All primary workspaces operate by keyboard at 360px, 768px, and desktop widths.
- Private dashboard pages remain outside public SEO and structured-data work.
- Initial-route JavaScript must remain at or below 100 KB gzip; lazy feature chunks must remain below 130 KB gzip.

## Dependency and Motion Policy

PFIS remains React, Vite, Tailwind 3, React Query, Recharts, Lucide, its current
theme provider, toast system, and accessible primitives. The premium workspace
adds only the approved foundational libraries: Inter variable font, Motion,
cmdk, React Hook Form, Zod/resolvers, TanStack Table, and dnd-kit. Motion is
limited to 120–240 ms fades, small translations, progress, and direct feedback;
`prefers-reduced-motion` disables non-essential movement. Particles, 3D,
parallax, heavy glassmorphism, and decorative animation remain excluded.
