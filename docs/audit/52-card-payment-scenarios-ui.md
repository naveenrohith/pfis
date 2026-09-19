# Single-card payment-scenarios UI review

Status: `PASS_WITH_RISKS`

## Scope

The Cards workspace now consumes the existing `payment_scenarios` envelope from
the card due-runway endpoint. It compares issuer minimum-due and total-due
targets using the same funding path and exposes planned-payment credit,
additional amount, effective hypothetical cash leaving, billed due remaining,
lower-band funding after, and coverage/gap state in a semantic table.

The panel is explicitly a read-only comparison. A planned intention is not
presented as settled, and no scenario schedules, submits, reserves, or confirms
a payment. Interest, fees, issuer settlement timing, and delinquency policy
remain outside the deterministic contract.

## Verification

- `CardPaymentScenarioPanel.test.tsx`: minimum/total comparison, planned-payment
  evidence, lower-band gap, status, caveat, and empty-scenario suppression.
- `CardsSection.test.tsx`: Cards workspace integration covers the payment
  comparison with the runway, projection, daily path, and utilization history.
- Frontend lint, full tests, production build, and the desktop financial-roadmap
  browser flow are run with this slice.

## Residual risks

The comparison depends on the existing funding forecast and issuer statement
targets. It is not a payment optimizer, fee/interest model, live bank balance,
issuer confirmation, or provider action. Provider settlement truth,
representative cohorts, matured outcomes, and staging UX evidence remain
release gates.
