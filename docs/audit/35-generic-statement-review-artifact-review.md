# Generic Statement Review Artifact Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: durable review-first handling for recognized or ambiguous statement formats

## Outcome

The detector and bounded analyzer now have an explicit persistence boundary for
formats that are not yet safe to import:

- `POST /api/statements/review/text` accepts statement text and
  `POST /api/statements/review/upload` extracts a digital PDF in memory;
- the service stores only detection metadata, a per-user fingerprint, and the
  existing redacted, bounded `StatementAnalysisResponse` JSON payload;
- `GET /api/statements/review` and `GET /api/statements/review/{review_id}`
  return owned artifacts for account/layout review; and
- no account foreign key, source text, PDF bytes, transaction, statement row, or
  balance observation is created by this path.

Exact reviewed profiles are marked `ready_to_import` as a recommendation for the
separate write-enabled import route. Generic, ambiguous, unfamiliar, or
signature-only analyses remain `pending_review`. Per-user fingerprints make
retries idempotent while preventing cross-user reads.

## Evidence

- `tests/pytest/test_financial_position.py::test_statement_analysis_review_persists_redacted_generic_evidence_without_import`
  verifies redaction, idempotence, list/detail ownership, and zero imports.
- `test_statement_pdf_detection_identifies_product_before_account_selection`
  also exercises the PDF review upload path and confirms the artifact is durable.
- Alembic revision `054_statement_analysis_reviews` matches the new ORM table.
- Focused pytest, Ruff, and mypy pass for the slice.

## Residual risks

1. The artifact is evidence, not an adapter: a new issuer/layout still needs a
   reviewed extractor and explicit account mapping before import.
2. Stored JSON is bounded to the analyzer preview; it intentionally cannot
   reconstruct every source row or prove a complete statement.
3. There is no mutation endpoint to mark an artifact reviewed or attach an
   account yet; the current workflow keeps mapping/import as a separate explicit
   action to avoid accidental ledger writes.
4. Provider-backed samples, representative cohorts, and browser capture remain
   release gates.

Verdict: `PASS_WITH_RISKS` for the durable generic-statement review boundary.
