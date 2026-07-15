# UI/UX Agent

Use this guide for PFIS React shell, navigation, component, accessibility, and visual-system work.

## Product Direction

- Treat PFIS as a financial decision workspace: position, explanation, attention, and next action.
- Keep the React/Vite app under `frontend/` canonical; do not add features to the legacy static fallback.
- Organize features by user task rather than exposing backend or parser structure in primary navigation.
- Preserve section hashes when changing navigation so existing links and cross-feature actions keep working.

## MCP Component Research

- Use the official shadcn registry MCP server configured in `.vscode/mcp.json` for discovery.
- Search for a component only after identifying a concrete PFIS interaction or accessibility need.
- Record the query, candidate, source, decision, and rationale in `docs/ui-ux-masterplan.md`.
- Treat registry output as reference code. Adapt it to PFIS tokens, types, privacy boundaries, and tests.
- Retain an existing PFIS primitive when it already meets the behavioral requirement.
- Do not add a dependency or install a block solely for visual similarity.

## Acceptance Gates

- Keyboard operation, visible focus, accessible naming, light/dark themes, and mobile behavior.
- No financial values, merchant names, raw email content, or transaction identifiers in telemetry.
- Frontend lint, tests, and production build pass.
- New navigation and dialogs receive interaction tests; major layouts receive browser verification.
- Bundle or runtime cost is measured for new foundational dependencies.
