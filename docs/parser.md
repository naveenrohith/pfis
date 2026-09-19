# PFIS Parser

Parser code lives in `backend/app/services/parser`.

## Sanitized parser corpus

The regression corpus is stored in `tests/parser_corpus/`. It contains synthetic
notification formats and expected extractions; never add raw emails, complete
account numbers, personal addresses, or live reference IDs. Every parser-format
fix must add or update a corpus case and pass `tests/pytest/test_parser_corpus.py`.

The corpus has separate transaction-extraction and source-classification sets.
`python scripts/evaluate_parser_corpus.py` produces a deterministic, content-addressed
version 2 report with:

- exact and per-field extraction accuracy;
- per-class precision, recall, F1, macro recall, weighted F1, classification
  accuracy, institution recognition, and a confusion matrix;
- generic-fallback rate and fallback accuracy;
- confidence calibration error and Brier score;
- per-format and parser-version cohorts;
- per-institution case/format counts, dedicated-parser coverage, and
  evidence-based `verified`, `supported`, `best_effort`, or `unsupported` tiers;
- explicit evidence cohorts. Unlabelled cases are `synthetic_fixture`; only
  `sanitized_production` or `production_safe` cases contribute to the
  representative release gate, which also requires minimum case, format, and
  institution coverage;
- an independent cohort-manifest status. Representative cases are release
  eligible only when a manifest pins the corpus fingerprint, lists opaque case
  IDs, and attests de-identification plus independent review; stale or malformed
  manifests fail closed;
- a SHA-256 corpus fingerprint and an optional prior-report regression check.

The corpus scorer fails below 95% exact transaction/classification accuracy,
95% macro classification recall, or 98% accuracy for represented critical
fields. It also prevents the corpus from shrinking below 50 extraction and 50
classification cases. The strict `intelligence_release_gate.py` additionally
requires the representative cohort thresholds before promotion; `--baseline
<report.json>` rejects comparable metric drops.

The manifest is intentionally separate from the corpus so changing a fixture
label cannot silently promote it. Its minimal shape is:

```json
{
  "version": 1,
  "corpus_fingerprint": "<sha256 from the scorer report>",
  "cases": [
    {"id": "opaque-case-id", "cohort": "sanitized_production"}
  ],
  "attestation": {
    "deidentified": true,
    "reviewed": true,
    "reviewer_id": "privacy-review-ticket",
    "reviewed_at": "2026-08-02T00:00:00Z"
  }
}
```

Run `python scripts/evaluate_parser_corpus.py --cohort-manifest
<manifest.json> --output <report.json>` after the manifest has been reviewed.
A support tier is evidence, not marketing: fewer than five passing cases remains
`best_effort`; `supported` also requires at least two distinct formats and 80%
dedicated-parser coverage; and `verified` requires at least 20 cases across
three formats at 98% accuracy with at least 95% dedicated-parser coverage.
Declared sources with no corpus evidence are explicitly `unsupported`.

Runtime parser events retain the non-secret source institution beside parser
name/version. Operational health compares seven-day source cohorts with the
preceding seven days and raises sample-guarded failure/fallback drift signals.
This detects routing or layout degradation without putting source email content,
merchant names, amounts, or account identifiers into health responses.

## Components

- `base_parser.py`: `BaseParser`, `ParseResult`, transaction type enum.
- `bank_parsers.py`: bank-specific and generic parsers.
- `registry.py`: sender/bank routing.
- `patterns.py`: shared extraction patterns.
- `pipeline.py`: batch processing from raw email to transaction.

## Parser selection

`registry.py` routes each email to an institution-aware parser based on the
sender. HDFC, SBI, ICICI, Axis, and Kotak alerts have dedicated account/card
patterns; Paytm, PhonePe, Google Pay, Amazon Pay, Razorpay, and LazyPay use a
shared digital-payment parser for stable receipt/counterparty language. When
the sender is unknown or no supported format matches, the **`GenericParser`**
fallback runs so that processing degrades gracefully instead of failing.
Telemetry still records the parser name/version and fallback bit; dedicated
routing is not treated as `supported` or `verified` until representative
cohorts clear the corpus gates.

## Confidence

Confidence is explainable:

- amount: 40 points
- merchant: up to 30 points
- date: 20 points
- transaction type: 10 points

Valid parse requires amount and transaction type. Results below the
low-confidence threshold (see `docs/constants-reference.md`) are flagged for
review rather than auto-accepted.

## Rules

- Prefer bank-specific patterns over broad generic regex.
- Do not silently drop failed parses; record `ParseFailure`.
- Do not relabel parsed money to make it fit a user ledger. A source-currency
  mismatch is retained with failure code `ledger_currency_mismatch` and no
  transaction is posted.
- Add regression tests for every parser change.
- Keep raw email available for reprocessing.
- Keep payment direction, payment rail, linked funding account, and card event separate.
  In particular, `debited` establishes direction only, never a debit-card rail.

## HDFC statement extractor

Statement recognition now runs as a pure pre-persistence step in
`backend/app/services/statement_detection.py`. The text and PDF
preflight APIs return only institution, product type, format candidate,
support status, named evidence codes, and detected activity rails; they never
return or retain statement text, account suffixes, balances, or PDF bytes.

### HDFC digital document preflight

`POST /api/statements/hdfc/detect` is a value-free classifier for an unencrypted
PDF. Embedded text is preferred; when the optional local OCR runtime is enabled,
the route renders a bounded page set in memory before calling
`detect_hdfc_statement_document`, which takes issuer evidence only from
the first three document lines (so a later HDFC counterparty cannot relabel an
ICICI statement) and requires the complete HDFC
credit-card signal set (issuer, card identity, total due, billing period,
duplicate marker, domestic ledger, date/time, and transaction description) or
the complete HDFC deposit table cluster (issuer, account statement, account
identity, narration, reference, withdrawal, deposit, and closing balance).
It returns a stable document kind, reviewed format, importability, reason code,
and matched signal names. It never calls a value extractor, chooses an account,
or writes telemetry/ledger data. Mixed card/deposit signatures are ambiguous;
non-HDFC documents and incomplete HDFC layouts fail closed.

Only the reviewed HDFC credit-card signature is `supported`; marker-compatible
but unreviewed card layouts are `recognized_not_supported` and cannot use the
automatic importer. HDFC deposit-account column clusters are generally
`recognized_not_supported`; official HDFC material names date, narration,
withdrawal, deposit, and closing balance, but recognition is not permission to
write. One de-identified, pipe-delimited profile (`hdfc-deposit-pipe-v1`) is
write-enabled. Its extractor requires a masked account
suffix, statement period, opening balance, the exact seven-column header, valid
dates, exactly one withdrawal or deposit per row, and cent-exact reconciliation
of every closing balance. It classifies only explicit UPI, POS/debit-card, ATM,
or NEFT/IMPS/RTGS narration. Other rows remain review evidence and do not enter
the ledger. The fixture proves the public column contract, not broad production
layout coverage; new layouts require reviewed de-identified samples and new
regression tests. Unknown or mixed signatures fail closed as `unsupported` or
`ambiguous`.

The direct HDFC card text endpoint also retains a compact de-identified fixture
profile for API regression coverage. It is accepted only when the complete
statement date, billing period, due date, due/minimum-due, and credit-limit
facts are present; marker-only or unfamiliar text is rejected before extraction.

An issuer-neutral `generic-deposit-tabular-v1` profile is also write-enabled
when a non-HDFC bank statement proves the same minimum evidence: a masked
account suffix, statement period, opening balance, explicit debit/credit and
balance columns, and cent-exact reconciliation for every row. Pipe-delimited
and fixed-width rows are accepted only when their column order is unambiguous;
blank or zero debit/credit pairs, date/period drift, balance drift, missing
identity, and unsupported single-amount layouts fail closed. Explicit UPI,
debit-card, ATM, and transfer narrations can create transactions; unknown rails
remain durable `needs_review` source lines. The selected owned bank account must
be active, confirmed, suffix-matched, and currency-compatible before persistence.

An issuer-neutral `generic-credit-card-tabular-v1` profile is write-enabled for
one reviewed pipe-delimited card export family. It requires a masked card
suffix, statement date and billing period, due/minimum-due/payment-date facts,
credit limit, opening liability, explicit debit/credit columns, and a
cent-exact `opening + debits - credits = balance after` chain whose final
balance equals total amount due. Debit rows are classified as purchases,
fees, taxes, or interest only from explicit wording; credit rows must say
payment, refund/reversal, or cashback, and unknown credits fail closed. The
selected active credit-card account must be suffix- and currency-compatible.
Non-HDFC PDFs and other generic card tables remain recognized evidence or
review artifacts until a representative de-identified layout is reviewed; the
profile is not a claim of arbitrary issuer coverage.

Merchant resolver version 3 separates the immutable raw descriptor from an
explainable identity candidate. Deterministic preprocessing removes payment and
issuer wrappers, controlled location suffixes, and explicit reference tokens
before user rules and the shared merchant catalog run. Explicit user rules
outrank shared logic, and a canonical catalog name outranks conflicting legacy
shared aliases regardless of row order. Sentence-like prose, newsletters, and
issuer boilerplate resolve to `Unknown` unless controlled counterparty evidence
is present.

HDFC alert extraction recognizes issuer-specific counterparty shapes including
gateway-prefixed card descriptors (`RAZ*Merchant`), debit-card acquirer prefixes,
UPI-credit names printed after the VPA, and the explicit `From Merchant` field
on refund/reversal alerts. HDFC alert parser version 4 treats ATM withdrawal
locations as movement evidence rather than merchant identity, requires `ATM` as
a word rather than a substring inside a UPI handle, and does not mistake the
standard service-charges footer for a fee event. Unknown senders require an explicit
money-movement phrase; a topical use of “purchase” in a study or newsletter is
not sufficient. Historical repair preserves meaningful reviewed/user-rule
identities and quarantines only source-proven non-transactions while retaining
the raw email evidence.

Travel itineraries and planned-maintenance notices with example amounts are
classified as non-transactions. Historical semantic repair runs independently
from merchant repair, preserves field-specific user corrections, and updates
only rails/card events/statuses supported by explicit parser evidence.

HDFC statement parsing emits EMI component evidence independently from the
merchant: conversion purchase/credit, processing fee/reversal, principal,
interest, tax, and pre-closure components. Issuer loan keys and observed
instalment numbers are retained where printed.

`backend/app/services/hdfc_statement_extractor.py` is a dedicated extractor for
one reviewed, unencrypted HDFC credit-card statement layout. It verifies the
issuer marker, billing-period fields, and masked card suffix before persistence.
Encrypted, malformed, unfamiliar-layout, low-quality OCR, and wrong-card files
are rejected with a reviewable plain-language reason; OCR output is never a
write permission by itself.

The extractor emits:

- statement/period/due dates and official previous due, credits, purchases,
  finance charges, total/minimum due, credit limit, available credit, and
  available cash limit;
- domestic ledger lines with direction and a separate card event: purchase,
  payment, refund, cashback, fee, tax, interest, or reversal;
- extractor version and document fingerprint provenance.

Matching precedence is deterministic:

1. An issuer reference matches first.
2. Otherwise card identity, exact amount, direction, controlled merchant
   normalization, and a ±3-calendar-day posting window must agree.
3. Exactly one candidate may auto-match. Zero candidates import an eligible
   purchase/refund; multiple or conflicting candidates go to review.
4. Card payments remain review evidence until the paying bank account is known.

The reverse path applies when Gmail arrives after a statement: the same
controlled comparison attaches the source email to the statement-created
transaction and creates the match instead of a second ledger event. An
ambiguous reverse match creates no new transaction and remains reviewable.
