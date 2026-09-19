# Card utilization-history UI review

Status: `PASS_WITH_RISKS`

## Scope

The Cards workspace now consumes `GET /api/cards/{account_id}/utilization-history`
and exposes the evidence in the same decision surface as the statement due and
next-statement projection.

- Issuer statement anchors and settled-ledger estimates use different point
  treatments and explicit legend labels.
- The compact trend plot includes the user target guide when configured, while
  the text summary states the trend, delta, latest basis, peaks, and breach
  counts.
- An expandable semantic table provides date, basis, utilization, balance,
  status, and confidence for recent points.
- Empty, loading, and read failures each provide a concrete next step and never
  imply live available credit.

## Verification

- `CardUtilizationHistoryPanel.test.tsx`: trend plot, evidence table, empty
  state, and error state.
- `CardsSection.test.tsx`: Cards workspace integration.
- Frontend test suite: 31 files, 80 tests passed.
- `npm run lint`: passed.
- `npm run build`: passed.

## Residual risks

This is a read-only presentation of the existing backend contract. It does not
replace provider observations, calibrate the ledger estimate, or add a new
statement source. Full browser/hosted verification remains a release-owner
gate, as does provider and representative-cohort evidence.
