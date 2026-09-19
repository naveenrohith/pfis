# Card Upcoming-State Timeline Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: composed next-event and next-state read model for one credit card

## Outcome

`GET /api/cards/{account_id}/upcoming-state` composes existing card evidence
without creating a second ledger or inventing provider events. It returns one
typed state and a bounded timeline containing:

- issuer-stated payment due dates;
- user-planned card payments and manual card calendar events;
- estimated next statement close and dated scheduled/recurring projection events;
- estimated utilization-target or hard-limit breach dates; and
- pending refunds that may change the future balance but are not settled credit.

The state prioritizes hard-limit pressure, then utilization-target pressure,
then a near-term issuer due, and otherwise reports monitoring or a fail-closed
evidence state. Events preserve source kind, status, confidence, and reason
codes. A missing projection does not suppress explicit due or user-intention
events.

## Evidence

- The focused API regression verifies a planned payment is the next event,
  issuer due remains present, and unavailable projection evidence is explicit.
- The service is read-only and reuses `CardOverviewResponse`; it does not create
  transactions, payment intents, calendar rows, statement rows, or provider
  observations.
- Ruff, mypy, and the focused endpoint test pass.

## Residual risks

1. The timeline is deterministic composition, not a calibrated probability
   model. Forecast event dates inherit the projection's uncertainty limitations.
2. The endpoint does not confirm payment settlement, issuer holds, or live
   available credit; a future UI must preserve those labels.
3. The current event envelope is intentionally bounded to 30 items and does not
   yet include arbitrary external bill sources outside the card overview.
4. Provider-backed issuer refresh, representative cohorts, and browser capture
   remain release gates rather than personal-account feature proof.

Verdict: `PASS_WITH_RISKS` for the composed card upcoming-state surface.
