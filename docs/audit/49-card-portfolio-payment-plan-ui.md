# Card portfolio payment-plan UI review

Status: `PASS_WITH_RISKS`

## Scope

The Cards workspace now consumes the existing read-only portfolio payment-plan
contract when two or more active cards are present. The panel compares:

- issuer minimum-due and total-due targets;
- additional cash required after existing recorded payment intentions;
- lower-band coverage and at-risk cards;
- shared funding paths, conservative cash gaps, and first shortfall dates;
- per-card due, funding-account, and runway evidence.

The panel does not schedule, submit, reserve, or confirm a payment. It keeps
the distinction between issuer targets, user-recorded intentions, and forecast
coverage visible in the primary comparison table and expandable per-card table.

## Verification

- `CardPortfolioPaymentPlanPanel.test.tsx`: target comparison, funding-path evidence, per-card disclosure, single-card suppression, and refresh-error state.
- `CardsSection.test.tsx`: Cards workspace integration remains covered.
- Frontend lint, full tests, and production build are run with this slice.

## Residual risks

The panel depends on the existing backend payment-plan and funding-forecast
contracts. It is not a payment optimizer and does not model issuer settlement
timing, rewards, fees, or provider live balances. Provider, representative
cohort, hosted operations, and staging UX evidence remain release-owner gates.
