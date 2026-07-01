# PFIS developer commands.
# Usage: make <target>  (requires GNU make; on Windows install via choco/scoop or run the
# underlying commands directly).

PY ?= python

.PHONY: start install lint format format-check typecheck test cov check precommit

start:          ## Prepare frontend/backend and start PFIS locally
	$(PY) scripts/start.py

install:        ## Install dev + runtime dependencies
	$(PY) -m pip install -r backend/requirements-dev.txt

lint:           ## Run ruff lint
	ruff check backend/app tests

format:         ## Auto-format with black + ruff fixes
	ruff check --fix backend/app tests
	black backend/app tests

format-check:   ## Verify formatting without writing changes
	black --check backend/app tests

typecheck:      ## Run mypy (non-blocking baseline)
	mypy backend/app

test:           ## Run the pytest suite
	$(PY) -m pytest -q

cov:            ## Run tests with coverage report
	$(PY) -m pytest --cov --cov-report=term-missing

check: lint format-check test  ## Run the full local gate (lint + format + tests)

precommit:      ## Install git pre-commit hooks
	pre-commit install
