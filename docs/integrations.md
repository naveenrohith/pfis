# PFIS Integrations

## Gmail

PFIS integrates with Gmail through Google OAuth and Gmail API clients. Real Gmail calls must not run in tests.

Gmail is the first source connector. Future connectors should produce a
connector-neutral `SourceRecord` from `backend/app/services/connectors/` and
feed the same classify -> parse -> normalize -> dedup -> store pipeline instead
of creating a parallel transaction path.

## Database

Local development uses SQLite through async SQLAlchemy. Production design should remain PostgreSQL-compatible.

## Dashboard

The dashboard is static HTML/CSS/JS served by FastAPI. It consumes `/api` routes and should not bypass backend ownership rules.

## External Dependencies

Primary dependencies are listed in `backend/requirements.txt`. New dependencies require a clear need, tests, and documentation.
