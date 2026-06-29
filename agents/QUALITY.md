# QUALITY Agent

Use QUALITY after TEST and before REVIEW for any non-trivial change. Its job is to keep PFIS small, readable, and free of redundant code/files.

## Responsibilities

- Detect dead files, generated artifacts, and unused legacy scripts.
- Identify duplicated logic that should live in shared helpers or services.
- Check for stale imports, unreachable branches, unused variables, and copied code.
- Verify touched files follow existing PFIS structure and naming.
- Confirm docs do not contain stale references from other projects.
- Keep cleanup recommendations scoped and safe.

## Required Checks

Run the cheapest relevant checks first:

```powershell
git status --short --branch
git ls-files | rg "(__pycache__|\\.pyc$|\\.db$|\\.db-journal$|dashboard\\.css$|dashboard\\.js$)"
rg -n "TODO|FIXME|copy-paste|Vendor\\s+Invoice|Spring\\s+Boot|Java\\s+21|com[.]siemens|U\\s*B\\s*M|repeat[_-]until[_-]found" agents docs .github backend tests
pytest
```

Use targeted commands when full pytest is too slow or blocked:

```powershell
pytest tests/pytest/test_parser_regression.py
pytest tests/pytest/test_api_regression.py
pytest tests/pytest/test_auth_security.py
```

## Deletion Rules

Delete without asking only when the file is clearly generated or already outside the active workflow:

- `__pycache__/`
- `*.pyc`
- `.pytest_cache/`
- `*.db-journal`
- obsolete dashboard files that are no longer referenced
- legacy verification scripts when equivalent pytest coverage exists

Ask before deleting when:

- The file is tracked source code.
- The file may contain unique business logic.
- The file is a migration, fixture, sample dataset, or documentation with unclear ownership.

## Refactor Rules

- Prefer deleting dead code over commenting it out.
- Prefer moving duplicated helpers into `backend/app/utils/` or an existing service.
- Do not introduce a new abstraction unless it removes real duplication.
- Keep refactors separate from behavior changes when possible.
- Preserve tests before and after cleanup.

## Output

QUALITY must report:

- Files removed or kept
- Duplication/dead-code findings
- Checks run
- Any cleanup intentionally deferred
