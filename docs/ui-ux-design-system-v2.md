# PFIS Design System v2

Status: implemented foundation
Direction: Quiet Horizon
Primary sources: `frontend/src/styles/index.css`, `frontend/tailwind.config.js`, `frontend/src/components/ui`, and `frontend/src/components/system`

## Foundations

### Typography

- Manrope Variable is self-hosted through `@fontsource-variable/manrope`.
- Display headings use tight tracking and balanced wrapping.
- Money uses the `money-value` utility with tabular numerals.
- Labels remain sentence case unless a compact metadata context genuinely benefits from short tracking.

### Color roles

| Role | Light intent | Dark intent |
|---|---|---|
| Canvas / background | Warm statement paper | Deep green-black |
| Foreground / ledger ink | Near-black green ink | Warm off-white |
| Primary / jade | Trustworthy action and positive movement | Brighter jade for dark contrast |
| Danger / coral | Financial outflow and blocking error | Softer coral with dark foreground |
| Warning / amber | Attention and commitments | Warm high-contrast amber |
| Info / settlement blue | Evidence and linked data | Clear cool blue |
| Intelligence | PFIS explanation and forecast context | Brighter indigo-violet |

Category colors are visualization-only. Semantic colors are never the sole carrier of meaning.

### Spacing and shape

- Spacing follows a 4 px base with primary rhythm on 8 px increments.
- Radius tokens: 10 px compact, 14 px standard, and 20 px prominent.
- Full pills are reserved for compact statuses and appropriate toggles.
- Shadows are limited to `lift` and `float`; ordinary content grouping does not use elevation.

### Motion

- `fade-in`: 180 ms, small vertical translation.
- `soft-pulse`: loading feedback without a decorative gradient shimmer.
- All non-essential motion collapses under `prefers-reduced-motion`.

## Accessible behavior layer

Base UI is installed as the incremental behavior foundation. Current wrappers include:

- Dialog with modal focus containment, focus restoration, Escape handling, and scroll locking.
- Tabs with keyboard navigation and a shared selection indicator.
- Menu with roving focus and disabled/destructive states.
- Select with labels, typeahead, and accessible item state.
- Tooltip for supplementary visual labels only.

The existing native `Select` remains available for compatibility during migration. New composed screens should prefer `SelectField` unless native select behavior is intentionally required.

## Core component roles

### General primitives

- `Button`: primary, secondary, ghost, outline, danger, and link variants; default touch target is 44 px.
- `Input`, native `Select`, and `Label`: consistent 44 px field height and visible focus treatment.
- `Badge`: compact semantic status; not a decorative tag.
- `Card`: a neutral surface primitive without a mandatory border or shadow.
- `Skeleton` and `EmptyState`: compact and contextual; empty states accept a direct action.
- `Toast`: temporary outcome feedback, not required information.

### Financial product primitives

- `PageIntro`: destination orientation and one optional action.
- `FinancialHero`: the primary financial narrative surface.
- `ActionSurface`: one high-impact recommendation with an explicit CTA.
- `InsightSurface`: evidence-led insight with neutral, positive, attention, or intelligence tone.
- `LedgerRow`: dense, scannable activity with optional selection and detail disclosure.
- `ChartFrame`: title, accessible summary, visual chart, and optional data table.

## Composition rules

1. A page may have one `PageIntro` and one dominant composition.
2. Do not create a card simply to hold a heading and two values.
3. Use `ActionSurface` once in the first viewport unless the screen is explicitly an action queue.
4. Use `InsightSurface` for an interpreted conclusion, not a raw statistic.
5. Use `LedgerRow` or semantic table rows for repeated records; do not wrap every record in a card.
6. Charts require an accessible summary and a data alternative when they carry decision-relevant information.
7. Tooltips contain supplementary labels only. Important explanations stay inline or use a popover/dialog.

## Migration policy

- Existing screen components remain functional while destinations migrate.
- New destination work uses the v2 tokens and financial primitives.
- Visually obsolete card components are removed only after their final consumer has migrated.
- Base UI behavior is adopted one primitive at a time with tests; PFIS styling remains local.
- No registry component enters production without an explicit adopt/adapt/reject decision.

## Phase 3 exit gate

- [x] Light and dark semantic tokens implemented.
- [x] New typography, radius, depth, focus, money, and motion foundations implemented.
- [x] Button, field, select, tabs, menu, dialog, toast, badge, tooltip, skeleton, and empty-state foundations available.
- [x] Page heading, hero, insight, action, ledger row, and chart frame implemented.
- [x] Existing build and lint remain green after foundation integration.
- [x] Dialog behavior tests cover labeling, initial focus, focus containment, Escape, focus restoration, and scroll locking.

The system can now compose Today and Activity without one-off visual foundations.
