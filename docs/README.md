# PFIS Documentation Index

This directory is the source of truth for PFIS agent and Copilot work.

## Core Docs

- [architecture.md](architecture.md) - system structure and module boundaries
- [data_model.md](data_model.md) - SQLAlchemy entities and persistence rules
- [data-models.md](data-models.md) - request/response and pipeline data shapes
- [workflows.md](workflows.md) - user, Gmail, parser, dashboard, report workflows
- [api-reference.md](api-reference.md) - route groups and API contracts
- [security.md](security.md) - auth, ownership, secrets, OAuth, frontend safety
- [testing.md](testing.md) - pytest strategy and validation commands
- [modernization-plan.md](modernization-plan.md) - phased modernization implementation tracker
- [deployment.md](deployment.md) - production-candidate deployment, backup, and health runbook
- [frontend.md](frontend.md) - canonical React/Vite workspace ownership and release gates
- [ui-ux-masterplan.md](ui-ux-masterplan.md) - workspace navigation, MCP component research, and UI/UX delivery gates
- [privacy-review-premium-workspace.md](privacy-review-premium-workspace.md) - premium workspace data-use and privacy approval

## Domain Docs

- [audit/README.md](audit/README.md) - enterprise modernization audit reports
- [parser.md](parser.md) - parser registry and extraction rules
- [normalizer.md](normalizer.md) - merchant/category normalization
- [integrations.md](integrations.md) - Gmail, OAuth, database, dashboard dependencies
- [constants-reference.md](constants-reference.md) - key config values and thresholds
- [extending.md](extending.md) - how to add parsers, routes, services, and UI features
- [adding-a-vendor.md](adding-a-vendor.md) - PFIS-compatible source/parser onboarding

## Not In Scope

PFIS does not use browser automation, captcha solving, DOM extraction, locator resolution, or automated MFA. Agents must not introduce those concepts unless the product scope changes.
