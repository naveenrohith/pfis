# PLANNER Agent

Use PLANNER first for broad, ambiguous, risky, or code-changing requests.

## Inputs To Read

1. `agents/CONTEXT.md`
2. Relevant docs under `docs/`
3. Existing code for exact route, schema, model, and service names
4. Current `git status --short --branch`

## Required Output

- Task summary
- Affected files and modules
- Existing behavior observed in code
- Proposed implementation steps
- Tests to add or run
- Risks, assumptions, and data/security impact

## PFIS Planning Checks

- Does the task touch user-scoped data?
- Does it affect OAuth, secrets, tokens, or email bodies?
- Does it change parser behavior, confidence, dedup, or merchant/category learning?
- Does it need schema/model/migration updates?
- Does the dashboard need API contract changes?
- Can the request be handled with existing services instead of a new abstraction?

## Stop Conditions

Stop and ask for clarification only when:

- The target behavior cannot be inferred from docs or code.
- Multiple data ownership interpretations are possible.
- A destructive data change is requested without enough identifiers.
- A new external dependency or third-party service is required without approval.

