# PFIS Data Shapes

> **Scope:** API/Pydantic request and response shapes exchanged over HTTP.
> For the persisted SQLAlchemy data model, see [data_model.md](data_model.md).

## ParseResult

```json
{
  "amount": 450.0,
  "currency": "INR",
  "transaction_type": "debit",
  "merchant_raw": "SWIGGY",
  "date": "2026-05-05",
  "account_last4": "1234",
  "reference_id": "123456789",
  "bank": "HDFC",
  "parser_version": 1,
  "merchant_source": "exact",
  "confidence_score": 0.9
}
```

## Transaction Create

Transaction creation is represented by `backend/app/schemas/transaction.py`. Required fields are amount, transaction type, and transaction date. Optional fields include merchant, category, account last4, reference ID, confidence, and source email. Merchant resolution also carries an additive source, confidence, user-rule id, and resolver version contract; manual clients may omit these fields and retain the existing defaults.

## Pipeline Stats

Pipeline endpoints return stats with counts for total unprocessed, parsed success, parsed failed, stored, duplicates, low confidence, skipped non-transaction, and per-email results. Per-email parser results include parser-facing metadata such as bank, parser version, confidence, merchant source, and whether the generic parser fallback handled the email.

## Report Data

Reports and dashboard workflows depend on monthly summary, category breakdown, top merchants, daily trend, recurring payments, and insight cards.

## Knowledge and Financial Intelligence Shapes

Calculated knowledge uses a common envelope vocabulary: signal kind, observed/calculated/forecast
status, confidence, data sufficiency, sample size, ruleset key/version, safe aggregate evidence,
assumptions, and data-through date. The first shared implementation is recurring-stream knowledge.

Recurring items expose merchant, occurrences, average amount, monthly equivalent, cadence,
cadence and amount confidence, combined confidence, lifecycle status, last observed date, optional
next expected date, data sufficiency, ruleset version, and aggregate evidence. They never expose raw
email bodies or connector credentials.

`FinancialHealthScore` now represents two distinct concepts: `monthly_stability` measures cash-flow
behavior, budget pressure when budgets exist, recurring burden, and spending volatility;
`data_confidence` measures parse/merchant confidence, review completeness, and historical coverage.
The legacy `score` field equals `monthly_stability` for compatibility.
