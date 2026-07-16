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
- Resolve exact `UserMerchantRule` matches before consulting the shared merchant catalog.
- Keep learned aliases and category preferences user scoped; ordinary correction flows never
  mutate global `Merchant` rows.
- Return explainable resolution metadata: source, confidence, rule id, and resolver version.
- Shared aliases use exact matching. Conservative canonical-name containment remains a lower-
  confidence fallback; unrestricted alias substring matching is not allowed.

