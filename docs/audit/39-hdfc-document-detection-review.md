# HDFC digital document detection review

## Scope

PFIS already had value extraction and a general statement detector, but an
uploading client could not ask for a small, stable HDFC document contract before
choosing an account. This slice adds a pure HDFC document detector and the
read-only `POST /api/statements/hdfc/detect` PDF preflight.

## Detection contract

The detector takes issuer evidence only from the first three document lines,
then returns only issuer, document kind, reviewed format,
importability, stable reason, matched signal names, and detector version. It
does not return source text, card/account suffixes, balances, dates, or marker
fragments. It recognizes:

- a complete reviewed HDFC credit-card document: issuer, card identity, total
  due, billing period, duplicate marker, domestic ledger, date/time, and
  transaction-description signals;
- a complete HDFC deposit table: issuer, account statement, account identity,
  narration, reference, withdrawal, deposit, and closing-balance signals; and
- mixed card/deposit signatures as `ambiguous`, never choosing an importer.

Non-HDFC documents return `unknown`/`unsupported_issuer`; HDFC-branded but
incomplete layouts return `unknown`/`unrecognized_hdfc_layout`. A reviewed card
points to `/api/statements/hdfc/upload`; a reviewed HDFC deposit points to the
account-aware `/api/statements/import/upload`. Unreviewed formats have no import
endpoint.

## Safety and persistence

The PDF route retains the existing 10 MB, `%PDF`, and unencrypted gates. It
prefers embedded text and can use bounded local OCR when configured; it reads
bytes and rendered pages only in memory, never calls a value extractor, and does
not create rejection telemetry, statement imports, statement rows,
transactions, balance snapshots, or durable review artifacts. The existing
legacy text and PDF import routes are unchanged.

## Verification

- Pure detector tests cover reviewed card, reviewed deposit, non-HDFC,
  HDFC-notification, and mixed-product ambiguity.
- API tests cover redaction/no persistence plus non-PDF, encrypted, and
  unavailable/empty-text rejection behavior; OCR unit tests cover rendering,
  engine absence, and page limits.
- Focused HDFC/statement regression: 56 passed, 28 deselected.
- Full backend regression: 546 passed, 2 skipped.
- Ruff passes for backend, tests, and scripts; mypy passes for 159 backend
  source files; worktree inventory reports 354 assigned packets and no
  unassigned changes.

## Remaining scale gap

This is still a document-classification contract, not arbitrary issuer support.
OCR is a bounded local text-recovery aid, not a confidence-free parser:
encrypted PDFs, low-quality OCR, unfamiliar HDFC layouts, and other bank
formats remain review-only. Provider-backed issuer truth and representative
cohort evidence remain external release gates.
