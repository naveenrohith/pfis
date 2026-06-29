# Extending PFIS

## Add A Bank Parser

1. Add parser logic in `backend/app/services/parser/bank_parsers.py`.
2. Add sender/bank detection if needed in Gmail email filter code.
3. Register the parser in `ParserRegistry`.
4. Add sample emails and parser regression tests.
5. Update `docs/parser.md`.

## Add An API Feature

1. Define or update Pydantic schemas.
2. Add service logic.
3. Add route handler.
4. Add tests for auth, ownership, success, and failure paths.
5. Update `docs/api-reference.md` and `docs/workflows.md`.

## Add A Data Model

1. Add SQLAlchemy model fields.
2. Add migration when required.
3. Update seed/test fixtures.
4. Update `docs/data_model.md`.

