# PFIS developer commands.
# Usage: make <target>  (requires GNU make; on Windows install via choco/scoop or run the
# underlying commands directly).

PY ?= python
WORKTREE_INVENTORY_OUTPUT ?= .test-run/worktree-inventory.json
MIGRATION_PARITY_OUTPUT ?= .test-run/migration-parity.json
PROMOTION_MANIFEST_OUTPUT ?= .test-run/promotion-manifest.json
PROMOTION_EVIDENCE_ROOT ?= release-evidence

.PHONY: start install lint format format-check typecheck intelligence-eval intelligence-scorecard promotion-manifest worktree-inventory migration-parity ops-contract anomaly-eval anomaly-evidence-export forecast-evidence-export balance-reconciliation-evidence-export recommendation-evidence-export intelligence-release-gate test cov check precommit restore-drill release-gate

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
	mypy backend/app scripts/release_gate.py scripts/postgres_restore_drill.py scripts/evaluate_parser_corpus.py scripts/evaluate_anomaly_quality.py scripts/export_anomaly_evidence.py scripts/export_forecast_evidence.py scripts/export_balance_reconciliation_evidence.py scripts/export_recommendation_evidence.py scripts/intelligence_release_gate.py scripts/intelligence_scorecard.py scripts/build_promotion_manifest.py scripts/check_migration_parity.py scripts/check_worktree_inventory.py

intelligence-eval:  ## Score parser/classifier truth corpora and enforce quality thresholds
	$(PY) scripts/evaluate_parser_corpus.py --baseline tests/parser_corpus/quality_baseline.json

intelligence-scorecard:  ## Emit the canonical product, workspace, readiness, and delivery score separation
	$(PY) scripts/intelligence_scorecard.py $(INTELLIGENCE_SCORECARD_ARGS)

promotion-manifest:  ## Assemble a hash-addressed, fail-closed promotion handoff
	$(PY) scripts/build_promotion_manifest.py --output "$(PROMOTION_MANIFEST_OUTPUT)" --evidence-root "$(PROMOTION_EVIDENCE_ROOT)" $(if $(SCORECARD_REPORT),--scorecard-report "$(SCORECARD_REPORT)",)

worktree-inventory:  ## Assign every changed file to an ordered integration packet
	$(PY) scripts/check_worktree_inventory.py --workspace . --output "$(WORKTREE_INVENTORY_OUTPUT)"

migration-parity:  ## Verify configured PostgreSQL databases share the repository Alembic head
	$(PY) scripts/check_migration_parity.py $(if $(MIGRATION_PARITY_DATABASE),--database "$(MIGRATION_PARITY_DATABASE)",) $(if $(MIGRATION_PARITY_OUTPUT),--output "$(MIGRATION_PARITY_OUTPUT)",)

ops-contract:      ## Verify health, observability, and release-control contracts
	$(PY) -m pytest tests/pytest/test_endpoints_smoke.py tests/pytest/test_release_gates.py -q

anomaly-eval:  ## Score adjudicated category/merchant anomaly signals
	$(PY) scripts/evaluate_anomaly_quality.py $(ANOMALY_EVIDENCE) $(ANOMALY_EVAL_ARGS)

anomaly-evidence-export:  ## Export protected aggregate anomaly labels without user/source identifiers
	$(PY) scripts/export_anomaly_evidence.py --output "$$ANOMALY_EVIDENCE"

forecast-evidence-export:  ## Export protected forecast backtests with keyed user hashes
	$(PY) scripts/export_forecast_evidence.py --output "$$FORECAST_EVIDENCE" $(if $(FORECAST_COHORT_MANIFEST),--cohort-manifest "$(FORECAST_COHORT_MANIFEST)",)

balance-reconciliation-evidence-export:  ## Export protected balance-reconciliation intervals with keyed cohort hashes
	$(PY) scripts/export_balance_reconciliation_evidence.py --output "$$BALANCE_RECONCILIATION_EVIDENCE" $(if $(BALANCE_RECONCILIATION_COHORT_MANIFEST),--cohort-manifest "$(BALANCE_RECONCILIATION_COHORT_MANIFEST)",)

recommendation-evidence-export:  ## Export privacy-safe recommendation effectiveness cohorts
	$(PY) scripts/export_recommendation_evidence.py --output "$$RECOMMENDATION_EVIDENCE"

intelligence-release-gate:  ## Strictly validate parser, balance, forecast, anomaly, and recommendation release evidence
	$(PY) scripts/intelligence_release_gate.py --strict $(INTELLIGENCE_RELEASE_ARGS)

test:           ## Run the pytest suite
	$(PY) -m pytest -q

cov:            ## Run tests with coverage report
	$(PY) -m pytest --cov --cov-report=term-missing

check: lint format-check typecheck intelligence-eval test  ## Run the full local gate

precommit:      ## Install git pre-commit hooks
	pre-commit install

restore-drill:  ## Backup and verify restore into an explicitly disposable PostgreSQL database
	$(PY) scripts/postgres_restore_drill.py --source-url "$$DATABASE_URL" --restore-url "$$RESTORE_DATABASE_URL" --confirm-restore-database "$$RESTORE_DATABASE_NAME" --artifact-dir "$$RELEASE_EVIDENCE_DIR" --output "$$RELEASE_EVIDENCE_DIR/restore-evidence.json"

release-gate:   ## Verify owners, HTTPS, restore evidence, health, security headers, and load limits
	$(PY) scripts/release_gate.py --base-url "$$PFIS_PRODUCTION_URL" --restore-evidence "$$RELEASE_EVIDENCE_DIR/restore-evidence.json" --output "$$RELEASE_EVIDENCE_DIR/release-evidence.json"
