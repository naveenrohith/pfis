# Bounded statement OCR review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10

## Scope

Statement upload routes previously stopped at the embedded-text threshold, so
image-only card and bank PDFs could not reach the existing detector, review
artifact, or strict import profiles. This slice adds one shared in-memory
extractor, `statement_pdf_extractor.py`, used by all PDF detection, review, and
import routes.

## Runtime contract

Embedded PDF text remains the first choice. When `STATEMENT_OCR_ENABLED` is
true and the host exposes both PyMuPDF and the `tesseract` executable, the
extractor renders at most `STATEMENT_OCR_MAX_PAGES` pages at the configured DPI
and sends PNG bytes to Tesseract through stdin. Each page has an explicit
timeout. No temporary PDF, image, or OCR-text file is created, and the route
discards the request bytes after the operation.

OCR output is a recovery input, not a parser or an import permission. The same
issuer detector, generic statement detector, identity/suffix/currency checks,
event-direction rules, and cent-exact running-balance reconciliation still run
before any ledger write. Missing Tesseract/PyMuPDF, encrypted or unreadable
documents, page-limit violations, timeouts, non-zero OCR exits, and insufficient
text fail closed with a reviewable 4xx/5xx response; no partial persistence is
introduced.

## Verification

- Unit coverage proves embedded-text preference, in-memory page rendering and
  Tesseract stdin/stdout invocation, engine-unavailable failure, and page-limit
  failure.
- Upload detection coverage proves OCR-recovered generic card text reaches the
  existing classifier and strict format contract.
- Existing HDFC PDF transport, encryption, redaction, and no-persistence tests
  remain green.
- Full backend, Ruff, and mypy results are recorded in the delivery response.

## Remaining scale gap

OCR quality is not yet benchmarked against representative issuer cohorts and
only the English language pack is configured. Layout drift, low-resolution or
rotated scans, regional languages, and handwritten annotations remain review-
only until independently reviewed fixtures and quality thresholds exist. A
future provider-backed ingestion path must retain the same strict write gate;
external OCR services are out of scope for this local, privacy-preserving slice.

Verdict: `PASS_WITH_RISKS` for bounded local text recovery and fail-closed
integration with the existing statement intelligence pipeline.
