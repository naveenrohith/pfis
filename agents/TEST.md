# TEST Agent

Use TEST for every behavior-changing task.

## Active Test Harness

- Test root: `tests/pytest`
- Config: `pytest.ini`
- Default command from repo root:

```powershell
pytest
```

For targeted validation:

```powershell
pytest tests/pytest/test_parser_regression.py
pytest tests/pytest/test_jobs_pipeline.py
pytest tests/pytest/test_auth_security.py
```

## Test Expectations

- Parser changes require email input samples and exact expected extraction output.
- API changes require status-code, auth/ownership, happy-path, and failure-path coverage.
- Service changes require deterministic unit or integration tests.
- Security changes require negative tests.
- Dashboard-only changes should be manually verified in a browser when feasible.

## Determinism Rules

- Do not call real Gmail, Google OAuth, or external networks in tests.
- Use fixtures and in-memory/test databases.
- Avoid sleeps unless testing job polling and keep them bounded.
- Do not rely on test execution order.
- Do not leave persistent local database state behind.

## Required Review

If tests cannot run, report:

- Command attempted
- Exact blocker or failing dependency
- Whether code was still statically reviewed

