# PFIS Responsive Prototype Specification

Status: validated and ready for production implementation
Prototype entry: `frontend/prototype.html`
Implementation: `frontend/src/prototypes/PrototypeApp.tsx`
Captured baselines: `docs/prototypes/experience/`

## Prototype coverage

| Experience | Primary decision | Desktop composition | Mobile composition |
|---|---|---|---|
| Today | What is my position and what should I do? | Financial Horizon plus one action, then pulse and evidence | Single narrative column in the same priority order |
| Activity | Where did money move? | Dense ledger with persistent detail panel | Ledger rows; details move to a dedicated surface/drawer in production |
| Review | What is uncertain and how do I resolve it? | Queue plus focused evidence/correction panel | Queue followed by the selected item and reachable actions |
| Plan | Where am I heading and what can change it? | Projected outcome plus best move, then goals and position | Outcome, move, goals, and accounts stack in priority order |
| Insights | Which patterns explain the outcome? | Narrative driver chart plus interpreted evidence | Chart, interpretations, and next patterns stack without horizontal scrolling |
| Data & settings | Is PFIS connected and accurate? | Source status, accounts, and processing health | Compact status groups and settings sections; technical detail stays secondary |

## Responsive rules confirmed

- Desktop uses an 88 px destination rail and a constrained 1240 px content canvas.
- Mobile uses five persistent destinations and safe-area-aware bottom spacing.
- The selected destination is conveyed by icon, label, background, and `aria-current`.
- Headers reduce secondary controls before content hierarchy changes.
- Financial Horizon remains a single component on mobile.
- Repeated records use ledger rows; the page does not horizontally scroll.
- Review actions wrap and reorder for thumb reach without changing their meaning.
- Status badges remain content-sized on narrow screens.
- Charts expose a textual summary and a data-table disclosure.

## State specifications for production

The visual prototype shows representative populated states. Production screens must also implement:

### Today

- Healthy, attention, deficit, low-data, stale-sync, loading, partial error, and full error.
- The priority action may be absent only when PFIS can truthfully say no action is needed.

### Activity and Review

- No matching transactions, no activity in period, all-clear review, source unavailable, correction failure, and successful confirmation.
- Desktop detail panel becomes a dialog/drawer or dedicated inline section on narrow screens.

### Plan

- No accounts, no goals, insufficient forecast data, healthy projection, and goal completion.
- Forecast bands are labeled as estimates, never guarantees.

### Insights

- Insufficient comparison history, no dominant driver, category cleanup required, and forecast unavailable.
- Observed facts, calculations, and forecasts remain visually distinguishable.

### Data & settings

- Healthy, stale, syncing, recoverable failure, blocked source, and no source connected.
- Parser-level diagnostics remain behind an explicit technical disclosure.

## Validation

`frontend/scripts/capture-prototypes.mjs` produces repeatable desktop and mobile baselines for all six experiences.

`frontend/scripts/validate-prototypes.mjs` validates all six experiences at 1440 × 1000 and 390 × 844 for:

- serious and critical axe accessibility violations;
- accidental horizontal page overflow;
- reduced-motion rendering.

The final Phase 4 run passed all 12 screen/viewport combinations. Earlier failures led to design-system fixes for semantic contrast, ARIA list semantics, responsive min-width handling, and mobile navigation contrast.

## Phase 4 exit gate

- [x] Today, Activity, Review, Plan, Insights, and Data & settings prototypes exist in React.
- [x] Desktop and mobile baselines are captured.
- [x] Reading order and responsive composition are explicit.
- [x] Important empty, loading, stale, and failure states are specified.
- [x] No serious or critical axe violations remain in the prototypes.
- [x] No prototype has horizontal page overflow at the validated widths.
- [x] Production implementation can reuse the actual v2 primitives rather than recreating the prototype’s visual foundations.
