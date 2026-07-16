# PFIS UI/UX Masterplan

PFIS is evolving from a long dashboard into a financial decision workspace. The canonical React UI groups
features by the decisions users are trying to make while preserving existing section hashes and API contracts.

## Workspace Model

| Workspace | Sections | User outcome |
|---|---|---|
| Home | Overview, Guidance, Recommendations | See monthly position, a deterministic brief, and next priorities |
| Understand | Timeline, Insights, Merchants, Categories | Explain what changed and why |
| Plan | Net Worth, Analytics, Budgets | Track owned balances and adjust future financial behavior |
| Act | Review, Transactions | Resolve uncertainty and inspect records |
| System | Inbox/Connectors, Pipeline Health | Operate ingestion and recover failures |

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

## Delivery Tracker

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
- [x] Add Playwright, axe, multi-viewport browser flows, and visual snapshot specifications.
- [x] Phase 9: enforce bundle budgets and add the release-host Lighthouse/visual-baseline gate.
- [ ] Phase 9 operations: approve Lighthouse and visual baselines on the staging/release host.
- [x] Phase 10: ship the evidence-labelled Money Horizon.
- [x] Phase 11: ship the deterministic, non-mutating Scenario Studio.
- [x] Phase 12: persist the user's in-app financial briefing rhythm.
- [x] Centralize recurring knowledge with cadence, lifecycle, confidence, evidence, and rulesets.
- [x] Split Monthly Stability from Data Confidence and consolidate the Today briefing response.
- [x] Add visible merchant pattern evidence and a user-controlled Learned Rules ledger.
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
