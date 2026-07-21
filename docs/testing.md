# PFIS Testing

## Test Root

`pytest.ini` points to `tests/pytest`.

Run all tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Audit pinned backend and frontend dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip_audit -r backend\requirements.txt
Set-Location frontend
npm audit --audit-level=high
```

Run targeted suites:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_auth_security.py
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_parser_regression.py
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_jobs_pipeline.py
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_budgets.py
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_reports.py
```

In the managed Windows environment, set the test temp directory to a writable
path if the default user temp directory is blocked:

```powershell
New-Item -ItemType Directory -Force .test-run | Out-Null; $env:TEMP=(Resolve-Path .test-run).Path; $env:TMP=(Resolve-Path .test-run).Path; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .test-run\pytest
```

## Requirements

- Parser changes need sample emails and expected extraction assertions.
- API changes need success, validation, and ownership tests.
- Security changes need negative tests.
- Job/sync changes must not call real Gmail in tests.
- Tests must be deterministic and isolated.

## Browser Regression

The functional Playwright suite runs in CI after backend and frontend validation:

```powershell
Set-Location frontend
npm run test:e2e:ci
```

CI starts an isolated FastAPI process, seeds the demo identity, and runs functional,
responsive, keyboard, and axe coverage in Chromium. Visual tests are tagged
`@visual`; run the complete suite against the fixed clock and inspect every diff
before updating snapshots:

```powershell
npm run test:e2e
npm run test:e2e:update
```

Never update a visual baseline solely to make CI green. Confirm that changed copy,
financial meaning, hierarchy, and responsive layout are intentional first.
