# Card portfolio upcoming-state UI review

Status: `PASS_WITH_RISKS`

## Scope

The Cards workspace now shows a shared next-state panel when at least two active
credit cards are present. It composes the existing portfolio endpoint without
inventing a combined live balance:

- known issuer total dues are summed and marked partial when a card lacks due evidence;
- the earliest dated event keeps its source, status, amount, and confidence;
- each card remains visible with its own state, due value, and next-event evidence;
- review, missing-event, and estimated-position states remain explicit rather than being collapsed into a green/amber score.

The panel is read-only and does not submit payments, reserve cash, or claim
cross-issuer available credit.

## Verification

- `CardPortfolioUpcomingPanel.test.tsx`: multi-card composition, explicit issuer-only caveat, single-card suppression, and refresh-error state.
- `CardsSection.test.tsx`: Cards workspace integration remains covered.
- Frontend lint, full tests, and production build are run with this slice.

## Residual risks

The panel depends on the existing backend portfolio contract and its issuer,
ledger, and forecast evidence. It does not calibrate event confidence or add a
new provider source. Full browser/hosted verification and representative
multi-card cohort evidence remain release-owner gates.
