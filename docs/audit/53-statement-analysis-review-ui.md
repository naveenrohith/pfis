# Durable statement-analysis review UI review

Status: `PASS_WITH_RISKS`

## Scope

The Statements workspace now surfaces the existing durable statement-review
artifact contract for unfamiliar credit-card and bank/debit/UPI layouts. A
user explicitly saves a selected PDF for review; the client then lists only
the backend's detection metadata, bounded redacted line preview, observed
rails, confidence, and reconciliation evidence. Account mapping and ledger
import remain separate explicit actions.

The panel keeps recognized-but-unsupported and ambiguous products review-only.
It does not expose source text or PDF bytes, create a transaction, map an
account, or claim issuer settlement truth. Loading, failure, empty, and
success states are announced with semantic status/alert regions, while the
preview uses a disclosure and a responsive table.

## Verification

- `StatementAnalysisReviewPanel.test.tsx`: explicit save mutation, redacted
  artifact evidence, no-ledger caveat, and retained-artifact behavior without
  a new file selection.
- `StatementImportSection.test.tsx`: statement intake remains compatible with
  the review-artifact query surface and keeps import gating unchanged.
- Frontend lint, full tests, production build, and the desktop Statements
  browser flow are run with this slice.

## Residual risks

The review artifact is bounded evidence, not a universal extractor or account
linking decision. OCR/scanned PDFs, issuer-specific layouts, retention policy
calibration, privacy approval, representative statement cohorts, and explicit
operator mapping still require backend/provider/staging evidence before any
write-enabled import path is broadened.
