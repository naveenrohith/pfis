# PFIS Debugging

PFIS does not use a separate debug-store subsystem. Debugging is done through logs, sync records, parse failures, raw emails, and tests.

Use:

- `SyncRun` for Gmail sync stats.
- `ParseFailure` for parser dead-letter records.
- `BackgroundJob` for async job state.
- pytest failures for regression evidence.

Do not log secrets or full raw email bodies.

