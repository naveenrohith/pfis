# PFIS Integrations

## Gmail

PFIS integrates with Gmail through Google OAuth and Gmail API clients. Real Gmail calls must not run in tests.

Gmail is the first source connector. Future connectors should produce a
connector-neutral `SourceRecord` from `backend/app/services/connectors/` and
feed the same classify -> parse -> normalize -> dedup -> store pipeline instead
of creating a parallel transaction path.

Gmail sync now runs through the connector-driven ingestion path:

1. `GmailConnector` fetches backfill or incremental records from Gmail.
2. The connector returns `SourceRecord` values plus cursor and metrics data.
3. `IngestionCoordinator` persists eligible source records into `RawEmail`.
4. Domain events and WebSocket sync events expose progress to the dashboard.
5. The parser pipeline remains the only owner of transaction extraction and storage.

The legacy Gmail sync functions remain compatibility wrappers over this
coordinator so existing API routes and jobs keep the same public behavior.

## Classification

Source classification is connector-neutral. The Gmail `email_filter` module is a
compatibility facade over `services/classification`, which returns classification
type, confidence, matched signals, and a reason. Categories include transaction,
statement, OTP, promotion, investment, salary, refund, failed payment,
subscription, loan, and ignore.

## Connector Audit Events

Connector lifecycle and sync operations write non-secret audit events. These
events record connect, token refresh, sync started, sync completed, and sync
failed states without storing tokens or full source bodies.

## Database

Local development uses SQLite through async SQLAlchemy. Production design should remain PostgreSQL-compatible.

## Dashboard

The dashboard is static HTML/CSS/JS served by FastAPI. It consumes `/api` routes and should not bypass backend ownership rules.

## External Dependencies

Primary dependencies are listed in `backend/requirements.txt`. New dependencies require a clear need, tests, and documentation.
