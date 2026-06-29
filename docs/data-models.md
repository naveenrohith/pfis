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

Transaction creation is represented by `backend/app/schemas/transaction.py`. Required fields are amount, transaction type, and transaction date. Optional fields include merchant, category, account last4, reference ID, confidence, and source email.

## Pipeline Stats

Pipeline endpoints return stats with counts for total unprocessed, parsed success, parsed failed, stored, duplicates, low confidence, skipped non-transaction, and per-email results.

## Report Data

Reports and dashboard workflows depend on monthly summary, category breakdown, top merchants, daily trend, recurring payments, and insight cards.

