# Statement Analysis Preview Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: read-only statement analysis attached to the statement detector for
reviewed HDFC profiles and recognized generic bank/card table shapes.

## Outcome

PFIS now does more than label a non-card document. The detection response can
return a bounded analysis object with date range, debit/credit totals, observed
rails, balance evidence, and a small redacted row preview. The analysis is
strictly additive: `support_status` still controls every import route, and no
statement, transaction, balance observation, fingerprint, or audit row is
created.

Reviewed HDFC deposit statements use the existing extractor and expose a
cent-exact reconciled result. Reviewed HDFC card statements expose classified
card-event totals. Generic bank tables are parsed only when the date, debit,
credit, and balance columns are explicit; ambiguous directions and undisclosed
opening balances remain partial evidence. Generic card rows remain partial
unless a credit/debit marker is present; only the separately reviewed
`generic-credit-card-tabular-v1` contract is write-enabled.

## Evidence

- Five pure analysis tests cover reviewed deposit reconciliation, generic HDFC
  and ICICI rows, generic card direction uncertainty, and signature-only
  fallback.
- Statement-detection API regressions prove the analysis is present for generic
  and HDFC read-only candidates while no source text or masked suffix is
  returned and no persistence occurs.
- The analysis preview is capped at 25 rows, descriptions are length-bounded and
  redact account-like numeric tokens, and parser failure falls back to
  `signature_only` without changing detection or import behavior.

## Residual risks

1. Unreviewed generic layouts are evidence-only and are not a substitute for a
   reviewed issuer extractor or a representative statement cohort. The strict
   generic card profile intentionally supports one de-identified pipe family.
2. Generic rows without an explicit opening balance cannot prove a complete
   running-balance chain, even when individual debit/credit columns parse.
3. The preview is intentionally not a full ledger; pagination, user-selected
   review, and provider-backed statement coverage remain future work.

Verdict: `PASS_WITH_RISKS` for the bounded read-only analysis surface and the
separately reviewed strict generic-card importer. Arbitrary issuer PDFs remain
outside the write gate; scanned PDFs are eligible only when the optional local
OCR runtime recovers enough text for the same strict profiles.
