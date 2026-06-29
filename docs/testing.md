# PFIS Testing

## Test Root

`pytest.ini` points to `tests/pytest`.

Run all tests:

```powershell
pytest
```

Run targeted suites:

```powershell
pytest tests/pytest/test_auth_security.py
pytest tests/pytest/test_parser_regression.py
pytest tests/pytest/test_jobs_pipeline.py
pytest tests/pytest/test_budgets.py
pytest tests/pytest/test_reports.py
```

## Requirements

- Parser changes need sample emails and expected extraction assertions.
- API changes need success, validation, and ownership tests.
- Security changes need negative tests.
- Job/sync changes must not call real Gmail in tests.
- Tests must be deterministic and isolated.

