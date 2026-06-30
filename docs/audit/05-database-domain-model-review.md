# Report 5: Database and Domain Model Review

## Executive Summary

PFIS has a useful domain model for its current product shape. It models users, Gmail accounts, raw emails, transactions, categories, merchants, budgets, sync runs, parse failures, user corrections, background jobs, and OAuth state. The most important next step is to separate local/demo schema behavior from production schema control and strengthen constraints, migrations, and ownership guarantees.

## Current Model Evidence

- `docs/data_model.md` lists the main persistence entities and storage rules.
- `backend/app/models/transaction.py` stores transaction amount, type, merchant fields, category, date, account suffix, reference id, confidence, review flag, parser version, fingerprint, and source email id.
- `backend/app/models/email.py` models Gmail accounts and raw emails.
- `backend/app/models/sync.py` models sync runs, parse failures, user corrections, background jobs, and OAuth state.
- `backend/app/models/category.py` models categories, merchants, and budgets.
- `backend/alembic/versions/001_baseline.py` provides a migration baseline.

## Strengths

- Raw email retention supports traceability and reprocessing.
- `Transaction.fingerprint` gives a deduplication anchor.
- `ParseFailure` creates a dead-letter style workflow for parser misses.
- `UserCorrection` captures feedback for future normalization.
- Indexes exist for common transaction access patterns, including user/date, user/type/category, and user/review.
- Gmail tokens can be stored encrypted through security helpers.
- Budget and category concepts are already part of the model.

## Weaknesses and Risks

| Issue | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| SQLite default is local-first | High for production | Concurrency, operations | `config.py` defaults to `sqlite+aiosqlite:///./pfis.db` | Use PostgreSQL or another managed database for shared production |
| Startup create-all can bypass migration discipline | Medium | Schema drift | `init_db()` calls `Base.metadata.create_all` | Reserve create-all for local/demo and require Alembic elsewhere |
| Constraints are mostly ORM-driven | Medium | Data integrity | Transaction fields rely on ORM definitions and enum mapping | Add DB-level constraints where data correctness matters |
| Fingerprint uniqueness may need policy review | Medium | False duplicates or missed duplicates | Dedup uses user, amount, date, merchant, ref id, account suffix | Track duplicate decisions and allow explicit overrides |
| Domain boundaries are still table-centric | Low | Long-term modeling | Models live in shared package | Keep until complexity justifies bounded contexts |

## Domain Model Assessment

The model supports the current product well:

- ingestion: `GmailAccount`, `RawEmail`, `SyncRun`
- extraction quality: `ParseFailure`, `parser_version`, `confidence_score`
- finance domain: `Transaction`, `Category`, `Merchant`, `Budget`
- user feedback: `UserCorrection`
- async workflow: `BackgroundJob`
- security flow: `OAuthState`, `User`

The next domain evolution should focus on source abstraction. Gmail is currently a source-specific path. Future SMS, PDF, bank API, or manual import flows should produce source records compatible with the parser pipeline rather than creating parallel transaction paths.

## Recommended Solution

1. Document local/demo versus production database modes.
2. Treat Alembic as mandatory outside local demo.
3. Add explicit DB constraints for critical fields as production hardening.
4. Add duplicate review/override workflow before aggressive connector expansion.
5. Add source-type metadata when non-Gmail connectors are introduced.

## Migration Guidance

- Keep current model names stable while the product is MVP-stage.
- Add migrations for each schema change.
- Backfill derived fields through tested scripts.
- Avoid destructive migrations until raw source records and exports are verified.

## Validation Strategy

- `pytest tests/pytest/test_dedup_fingerprint.py`
- `pytest tests/pytest/test_budgets.py`
- `pytest tests/pytest/test_jobs_pipeline.py`
- Migration review through Alembic scripts.
- Manual schema inspection for new indexes and constraints.

## Rollback Strategy

Every production schema change should have a reversible migration or a documented restore path. For high-risk data changes, export affected rows first, apply changes in a transaction where possible, and verify counts before and after.

