# PFIS developer commands.
# Usage: make <target>  (requires GNU make; on Windows install via choco/scoop or run the
# underlying commands directly).

PY ?= python

.PHONY: start install lint format format-check typecheck test cov check precommit restore-drill release-gate

start:          ## Prepare frontend/backend and start PFIS locally
	$(PY) scripts/start.py

install:        ## Install dev + runtime dependencies
	$(PY) -m pip install -r backend/requirements-dev.txt

lint:           ## Run ruff lint
	ruff check backend/app scripts tests

format:         ## Auto-format with black + ruff fixes
	ruff check --fix backend/app scripts tests
	black backend/app scripts tests

format-check:   ## Verify formatting without writing changes
	black --check backend/app scripts tests

typecheck:      ## Run the blocking mypy gate
	mypy backend/app scripts/release_gate.py scripts/postgres_restore_drill.py

test:           ## Run the pytest suite
	$(PY) -m pytest -q

cov:            ## Run tests with coverage report
	$(PY) -m pytest --cov --cov-report=term-missing

check: lint format-check typecheck test  ## Run the full local gate

precommit:      ## Install git pre-commit hooks
	pre-commit install

restore-drill:  ## Backup and verify restore into an explicitly disposable PostgreSQL database
	$(PY) scripts/postgres_restore_drill.py --source-url "$$DATABASE_URL" --restore-url "$$RESTORE_DATABASE_URL" --confirm-restore-database "$$RESTORE_DATABASE_NAME" --artifact-dir "$$RELEASE_EVIDENCE_DIR" --output "$$RELEASE_EVIDENCE_DIR/restore-evidence.json"

release-gate:   ## Verify owners, HTTPS, restore evidence, health, security headers, and load limits
	$(PY) scripts/release_gate.py --base-url "$$PFIS_PRODUCTION_URL" --restore-evidence "$$RELEASE_EVIDENCE_DIR/restore-evidence.json" --output "$$RELEASE_EVIDENCE_DIR/release-evidence.json"
