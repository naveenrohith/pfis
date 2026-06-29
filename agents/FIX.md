# FIX Agent

Use FIX only after REVIEW finds concrete issues or tests fail.

## Fix Rules

- Fix the smallest cause of the issue.
- Do not rewrite unrelated code.
- Preserve user changes in the dirty worktree.
- Add or adjust tests for the failure when practical.
- Re-run the most relevant validation after the fix.

## Common PFIS Fix Patterns

- Missing ownership check: add `resolve_user_scope` for user-id inputs or `ensure_user_owns_resource` for loaded rows.
- Parser regression: add a sample case, adjust the narrowest regex or parser branch, and keep confidence explainable.
- Duplicate transaction bug: inspect `TransactionService` fingerprint construction before changing route code.
- Blocking async path: isolate sync SDK calls with an async-safe wrapper.
- Unsafe frontend rendering: escape the server value at the insertion point.
- Missing doc update: update the narrowest relevant file in `docs/`.

