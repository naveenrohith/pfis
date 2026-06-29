# PFIS Parser

Parser code lives in `backend/app/services/parser`.

## Components

- `base_parser.py`: `BaseParser`, `ParseResult`, transaction type enum.
- `bank_parsers.py`: bank-specific and generic parsers.
- `registry.py`: sender/bank routing.
- `patterns.py`: shared extraction patterns.
- `pipeline.py`: batch processing from raw email to transaction.

## Parser selection

`registry.py` routes each email to a bank-specific parser based on the sender.
When the sender is unknown or no bank parser matches, the **`GenericParser`**
fallback runs so that processing degrades gracefully instead of failing.

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
- Add regression tests for every parser change.
- Keep raw email available for reprocessing.

