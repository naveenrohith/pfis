# Guidance Card Upcoming-State Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: allowlisted Guidance access to the composed credit-card next-state timeline

## Outcome

Grounded Guidance now recognizes dated card-next-state questions, including:

- what happens next with a card;
- upcoming or next statement/payment timing;
- utilization forecast or target pressure; and
- credit-limit pressure or estimated breach language.

The new `card_upcoming_state` intent selects one active credit card, refuses to
combine multiple cards, and reads `CardUpcomingStateService`. The answer reports
the composed state, next dated event, source/status labels, bounded confidence,
and review actions. It uses `current_card_cycle` as its temporal scope and does
not create transactions, payment intents, calendar rows, or provider actions.

## Evidence

- `tests/pytest/test_premium_workspace.py::test_guidance_card_upcoming_state_uses_timeline_read_model`
  verifies intent classification, current-cycle scope, event date, source cutoff,
  and the no-payment safety statement.
- Existing `tests/pytest/test_card_upcoming_state.py` continues to cover the
  underlying timeline composition and fail-closed projection behavior.
- Ruff and mypy pass for the changed service and its timeline dependency.

## Residual risks

1. The classifier is intentionally phrase allowlisted; unsupported wording still
   receives the normal refusal rather than a generated answer.
2. Guidance selects one active card and asks the user to choose when several
   exist; a future UI may pass an explicit card identifier.
3. Event confidence is inherited from the underlying deterministic projection,
   not a calibrated probability or provider guarantee.
4. Provider-backed refresh, representative cohorts, and browser capture remain
   release gates.

Verdict: `PASS_WITH_RISKS` for the Guidance utilization of card next-state evidence.
