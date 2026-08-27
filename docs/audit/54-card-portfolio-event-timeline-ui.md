# Card portfolio event-timeline UI review

Status: `PASS_WITH_RISKS`

## Scope

The Cards portfolio-upcoming response already returned a dated `events`
collection, but the UI previously surfaced only `next_event` and one summary
per card. The portfolio panel now offers a native disclosure containing the
retained events in date order, with event type, date-relative position, source
kind, lifecycle status, confidence, amount, and bounded reason evidence.

Observed issuer events remain visually distinct from planned or estimated
events. Risk signals are called out without turning a forecast into issuer
truth, and the timeline explicitly does not schedule, submit, reserve, or
confirm payments. The compact per-card state and shared attention summary are
unchanged for quick scanning.

## Verification

- `CardPortfolioUpcomingPanel.test.tsx`: dated event disclosure, source/status/
  confidence evidence, risk count, reason-code copy, and single-card/error
  states.
- `CardsSection.test.tsx`: portfolio panel remains integrated with the Cards
  workspace alongside payment plan, spend routing, projection, and runway
  surfaces.
- Frontend lint, full tests, production build, and desktop financial-roadmap
  browser verification are run with this slice.

## Residual risks

The timeline is only as complete as the backend's retained issuer, ledger,
calendar, and forecast evidence. It does not add provider coverage, improve
forecast calibration, infer missing refunds, or perform payment optimization.
Representative cohorts, matured outcomes, provider freshness, and staging
task-success evidence remain release gates.
