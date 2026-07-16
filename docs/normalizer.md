# PFIS Normalizer

Merchant normalization lives in `backend/app/services/parser/normalizer.py`.

## Responsibilities

- Map raw merchant names to normalized names.
- Match aliases from `Merchant.aliases`.
- Return default category when available.
- Infer merchants from full email text when parser extraction is weak.
- Cache merchant rows briefly to avoid repeated table scans.

## Rules

- Invalidate merchant cache after merchant table mutations.
- Do not treat generic transfer labels as strong merchants.
- Preserve user corrections as learning signals.

