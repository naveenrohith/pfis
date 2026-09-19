# Card spend-routing preview UI review

Status: `PASS_WITH_RISKS`

## Scope

The Cards workspace now exposes the existing read-only
`POST /api/cards/portfolio/spend-routing` contract as a hypothetical purchase
preview. A signed-in user supplies an amount, an optional category, and one of
the backend's explicit priorities: utilization safety, rewards, or balanced.
The result preserves the backend ranking and makes each option's current and
projected utilization, target and hard-limit headroom, reward evidence, source,
confidence, and status visible in a semantic comparison table.

The panel is deliberately a preview. It does not schedule or authorize a
purchase, reserve cash, create a transaction, alter a payment plan, or claim
that an issuer will award a reward. Missing or review-state evidence remains
visible instead of being converted into a recommendation.

## Verification

- `CardSpendRoutingPanel.test.tsx`: explicit payload submission, recommendation
  rendering, evidence labels, reward caveat, and empty-card suppression.
- `CardsSection.test.tsx`: Cards workspace integration remains covered.
- Frontend lint, full tests, production build, and the desktop financial-roadmap
  browser flow are run with this slice.

## Residual risks

The panel depends on the existing backend evidence hierarchy and user-entered
reward rules. It is not an issuer catalogue, fee/interest calculator, payment
optimizer, or authorization surface. Provider cohort calibration, reward and
fee verification, hosted operations, and staging UX evidence remain release
gates.
