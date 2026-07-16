# Semantic Labeling

PFIS semantic labeling means transaction categorization and merchant normalization, not DOM labeling.

Relevant modules:

- `backend/app/services/parser/normalizer.py`
- `backend/app/services/transaction_service.py`
- `backend/app/models/category.py`

Rules:

- User corrections should improve future categorization.
- Unknown merchants should degrade gracefully to "Unknown" or "Others".
- Tests must cover category and merchant changes.

