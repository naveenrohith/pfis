# Issuer-neutral credit-card import review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10

## Scope

PFIS previously recognized non-HDFC credit-card statements and produced a
bounded analysis preview, but every such document stopped at
`recognized_not_supported`. This slice adds one deliberately narrow,
write-enabled profile: `generic-credit-card-tabular-v1`.

## Contract and safety gates

The pure extractor accepts only a de-identified pipe-delimited table that
proves a masked card suffix, statement date and billing period, payment due
date, total/minimum due, credit limit, opening liability, and explicit debit,
credit, and running-balance columns. Every row must contain exactly one
positive direction, fall inside the billing period, and satisfy the cent-exact
liability equation `opening + debits - credits = balance after`. The final
balance must equal total amount due.

Debit wording is classified conservatively as purchase, fee, tax, or interest.
Credits must explicitly say payment, refund/reversal, or cashback; unknown
credits reject the entire import rather than silently becoming payments. EMI
component evidence is reused from the reviewed HDFC classifier without
inventing tenure or rates. Source currency and masked suffix are checked again
against the selected active, user-owned credit-card account before persistence.

The existing HDFC importer and the strict generic bank/deposit importer retain
their own gates. Unreviewed PDFs, low-quality OCR, unfamiliar tables, mixed
card/bank signatures, missing direction, and ambiguous events remain durable
review evidence only. OCR is only a text-recovery input; no provider
assumptions or arbitrary issuer support is claimed by this profile.

## Persistence and API behavior

The automatic text/PDF import routes dispatch a supported generic-card
detection to the shared card statement persistence path. It creates one
`StatementImport` with issuer `GENERIC` and extractor version
`generic-credit-card-tabular-v1`, a verified statement-date liability snapshot,
source lines, and only explicitly safe card transactions. Card payments remain
`needs_review` until a bank leg is chosen. Fingerprint retries return the
existing owned statement; a fingerprint selected for another account is
rejected rather than reusing the wrong statement.

## Verification

- Pure extractor/detector and HDFC regressions: 31 passed.
- Generic-card integration covers detection, import, event classification,
  payment review state, suffix/currency checks, and idempotent retry.
- HDFC statement/import regressions: 18 passed, 31 deselected.
- Full backend suite: 559 passed, 2 skipped.
- Ruff and targeted mypy checks are clean.

## Remaining scale gap

Representative cohorts for major issuers, provider-backed current balances, and
cross-account funding optimization are still release gates. The local OCR
fallback is bounded and available only where the host runtime is provisioned;
it does not replace a new reviewed layout profile with its own fixtures and
reconciliation tests.

Verdict: `PASS_WITH_RISKS` for the strict issuer-neutral card-table importer.
