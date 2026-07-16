# Report 9: Maintainability Review

## Executive Summary

PFIS maintainability is good for its current size. The codebase has clear folder names, docs, tests, and focused modules. Maintainability will decline if orchestration logic keeps growing inside `pipeline.py`, route modules continue to accumulate rendering logic, and frontend migration remains unresolved.

## Maintainability Strengths

- Route, service, model, schema, parser, Gmail, and static asset concerns are separated.
- Docs explain architecture, parser behavior, data model, security, testing, workflows, and extension patterns.
- Test names map to product capabilities.
- Quality tools are centralized in `pyproject.toml`.
- The parser contract is explicit through `ParseResult`.
- Security and observability helpers are reusable.

## Maintainability Risks

| Issue | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Pipeline orchestration density | High | Harder parser changes | `_process_email_batch` contains many concerns | Extract named stages |
| Route-owned report presentation | Medium | Harder report changes | `reports.py` embeds full HTML/CSS string | Move to templates |
| Mixed frontend assets | Medium | Developer confusion | static dashboard and Svelte app coexist | Document primary UI and migration path |
| Non-blocking mypy | Low now, Medium later | Type drift | CI continues on mypy errors | Tighten type gates by module over time |
| Domain concepts remain service-centric | Medium later | Growth pressure | services package contains multiple domains | Introduce domain packages only when tests support it |

## Readability Review

Naming is generally clear. The main readability issue is not unclear variable names; it is responsibility density. Long functions that perform multiple workflow stages are harder to review and harder to test. Refactoring should focus on workflow seams, not cosmetic renaming.

## Testability Review

PFIS is testable because tests already exist for major behavior. The next improvement is to make individual pipeline stages testable without requiring a full raw-email-to-transaction batch.

Recommended test units:

- email classification
- parser selection
- parse result validation
- merchant inference
- merchant normalization
- transaction creation and duplicate detection
- parse failure recording
- retry behavior

## Documentation Quality

Documentation quality is above average for an MVP. The docs should remain the source of truth. Future code changes should update docs when they change:

- API contracts
- parser rules
- data model
- security behavior
- testing commands
- deployment assumptions

## Recommended Solution

1. Keep module names boring and domain-aligned.
2. Extract responsibilities only when it improves tests or reduces real complexity.
3. Add architecture decision records for major changes.
4. Keep docs synchronized with code changes.
5. Tighten type checking gradually by selecting stable modules first.

## Validation Strategy

- Review cyclomatic and function-size hotspots with Ruff or targeted static analysis.
- Run `make check`.
- Add tests before extracting high-risk services.
- Review docs and tests in the same PR as behavior changes.

## Rollback Strategy

Maintainability refactors should be behavior-preserving. If the behavior changes unintentionally, revert the refactor and keep the new tests that identify the intended behavior.

