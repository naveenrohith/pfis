# Card daily-path and hard-limit runway UI review

Status: `PASS_WITH_RISKS`

## Scope

The Cards workspace now consumes the daily path already emitted by the
next-statement projection service. The panel plots central utilization from
tomorrow through the projected statement close, marks known dated payments and
charges, and preserves a day-by-day semantic table containing projected balance
ranges, utilization, target status, hard-limit status, and event labels.

The runway readout keeps user utilization targets separate from the observed
credit limit. It reports the first target and hard-limit pressure dates and
states that the path is a PFIS estimate rather than an issuer schedule, live
available-credit value, decline prediction, or payment outcome.

## Verification

- `CardDailyPathPanel.test.tsx`: dated path rendering, event markers, target and
  hard-limit pressure, evidence table, estimate boundary, and unavailable state.
- `CardsSection.test.tsx`: Cards workspace integration covers the new path panel
  alongside the existing forecast and utilization-history surfaces.
- Frontend lint, full tests, production build, and the desktop financial-roadmap
  browser flow are run with this slice.

## Residual risks

The panel depends on the deterministic backend path and its current/seasonal
pace evidence. It is not a calibrated probability distribution, issuer
available-credit feed, payment optimizer, or card-decline predictor. Provider
pending-authorizations, representative cohorts, matured backtests, and staging
UX evidence remain release gates.
