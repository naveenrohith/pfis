# Sprint 8 — Product task success

**Status:** PASS_WITH_RISKS  
**Scope:** make grounded financial answers usable at the moment a person needs to decide.

## Implemented

- Added typed frontend contracts for `plan`, `evidence`, `uncertainty`, `confidence`, and
  `temporal_scope` returned by `POST /api/guidance/query`.
- Added an evidence-and-limits treatment to Ask PFIS. Each answer can now show its ordered
  query plan, human-readable source/cutoff citations, confidence state, selected-period scope,
  and known limits. Unsupported questions use the same surface to explain why PFIS stopped.
- Added an `aria-live="polite"` result region, explicit decorative-icon labels, visible keyboard
  focus for example questions, touch-friendly example controls, and locale-aware confidence/date
  formatting.
- Added a deterministic interaction test covering the grounded answer, source cutoff, limits, and
  explainable plan.
- Updated the API reference so the response contract is discoverable outside the TypeScript app.

## Verification

| Check | Result |
|---|---|
| GuidanceSection focused test | 3 passed |
| Frontend unit suite | 29 files / 74 tests passed |
| Frontend lint | passed |
| Production build | passed |
| Bundle budget | passed; initial route 92.4 KB gzip |
| Web Interface Guidelines review | no new actionable findings in the changed result surface |

## Product task gate

Repository evidence now supports a transparent answer flow: ask → classify → cite sources → state
uncertainty → offer a bounded next action. The implementation is ready for a browser task-success
cohort, but the cohort itself has not been run in this environment. Before promotion, run the
existing Playwright/axe flows at 360px, 768px, and desktop widths with representative supported,
unsupported, stale-position, and empty-evidence cases. Record completion rate, time-to-first-answer,
refusal comprehension, keyboard success, and serious accessibility findings; do not infer the gate
from unit tests alone.

## Remaining risks

- Browser-hosted task success and Lighthouse/visual approval remain external gates.
- Connected-provider freshness and real account coverage are still outside fixture-backed tests.
- Confidence is an evidence label, not a claim that the answer is financially correct for every
  future provider state.

