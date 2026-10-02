# Gmail statement import: requirements and implementation plan

Status: implemented on `codex/gmail-statement-import` in [draft PR #10](https://github.com/naveenrohith/pfis/pull/10). Local verification and integrated review passed. All four CI jobs must pass on the final head before merge; merge requires approval.

CI repair: the first draft PR run failed the existing Python dependency audit on PyJWT 2.13.0. The initial pin update to 2.14.0 passed on September 30. The October 2 review run found the newly published PYSEC-2026-4141 advisory, so the final pin is 2.15.1, which includes the [upstream payload-parser security fix and padding compatibility repair](https://pyjwt.readthedocs.io/en/latest/changelog.html). Authentication regressions and all four CI jobs must pass before merge. This adds no new library or migration.

Implementation decisions: candidates use encrypted, user/mailbox/generation-bound `source_ref` values rather than browser-visible message IDs. References expire after 30 minutes. Discovery reads 20 messages and returns at most 100 attachments per page, with explicit partial-coverage fields. PDF passwords remain in component memory through detection and import; each server request downloads/decrypts again. Shared standard manual/Gmail import dispatch takes the user lock before fingerprint persistence. No migration or dependency change is required. Exact contracts are maintained in `docs/api-reference.md`, `docs/integrations.md`, and `docs/security.md`.

## Goal and first-release boundary

Let a user with a connected Gmail mailbox select a PDF statement attachment in
Data & settings → Statements, supply a PDF password if required, review the
detected document and destination account, and explicitly import it through
PFIS's existing statement pipeline. Keep manual upload available.

The first release is user-triggered. It does not scan every incoming attachment
in background jobs, store statement passwords, import email-linked bank portal
documents, expand supported issuer layouts, or treat email metadata as financial
proof. Those are separate product decisions.

## Verified starting point

- Gmail consent already requests `gmail.readonly`; Google documents that this
  scope permits fetching attachments through `users.messages.attachments.get`.
  `GmailConnector` currently turns a message into sender, subject, body, and
  received time only. `RawEmail` has no attachment fields. Existing transaction
  sync must remain independent of statement intake.
- Statement detection, review, and import are distinct endpoints under
  `backend/app/api/routes/financial_position.py`. Import supports only proven
  HDFC and strict generic card/deposit profiles, verifies an owned compatible
  account, and reconciles or reviews statement lines. Fingerprint retries are
  idempotent. Uploads have a 10 MB PDF limit and retain no source PDF.
- `statement_pdf_extractor.py` currently rejects encrypted PDFs. A password
  supplied in the UI does not work until this extractor and its callers change.
- `StatementImportSection.tsx` currently accepts a local file, detects it before
  account selection, and requires a separate import action. Extend this flow
  rather than creating another statement pipeline.
- `.github/workflows/ci.yml` has four jobs: `backend`, `frontend`, `postgres`,
  and `e2e`. The workflow runs for pull requests to `main` and pushes to `main`,
  not for a push to this feature branch alone.

## Proposed user journey

1. In Statements, choose **From Gmail** or **Upload PDF**. From Gmail is available
   only with an active, authorized Gmail connection. The disconnected and
   reauthorization states point to the existing connection flow.
2. On user request, search a bounded date window for messages with PDF
   attachments. Show received date, sender, safely truncated/redacted subject
   and filename, and size. Avoid email body previews and full account numbers.
   Paginate; never imply a capped result set is complete.
3. Select one attachment. The backend fetches it from the user's connected
   mailbox, checks its actual bytes and size, and runs detection in memory. If
   encrypted, prompt for its password and retry detection. Invalid passwords
   produce a recoverable error without exposing parser internals.
4. Show the existing detection and bounded analysis, then only compatible owned
   accounts. Unsupported or ambiguous layouts remain read-only or enter the
   existing explicit review flow. Do not infer account ownership from sender or
   filename.
5. The user explicitly imports a supported statement. Fetch the attachment
   again, compare its SHA-256 fingerprint with the detection result, decrypt in
   memory, and call the same import service used by manual upload. A mismatch
   requires fresh detection. Existing duplicate detection and line review apply.
6. Clear the password from component state after completion, cancellation, or
   source change. Never persist it in browser storage or server storage.

## Functional requirements and acceptance evidence

| ID | Requirement | Proof during implementation |
| --- | --- | --- |
| F1 | List PDF candidates only for the authenticated user's connected Gmail account; support bounded paging and clear incomplete coverage. | Mocked Gmail and route tests for ownership, pagination, empty and partial results. |
| F2 | Handle nested MIME parts, inline part data, and separate Gmail attachment IDs; reject non-PDF bytes and files above 10 MB before parsing. | Connector/service fixture tests including malformed and oversized attachments. |
| F3 | Detect unencrypted and password-protected PDFs without server-side retention of source bytes, extracted text, or password beyond the request. | Extractor and route tests for correct, absent, incorrect, and unsupported encryption; log/telemetry assertions. |
| F4 | Preserve detection → compatible account selection → explicit import, with no ledger write during search or detection. | API integration and UI interaction tests. |
| F5 | Import rechecks the reviewed fingerprint and reuses existing account, layout, atomicity, duplicate, and review gates. | Integration tests for mismatch, wrong owner, retry, conflict, rollback, and statement/email reconciliation. |
| F6 | Manual upload continues to work with the same current contract. | Existing upload regression tests plus a focused UI test for both source choices. |
| F7 | Connection expiry, provider outage, missing attachment, wrong password, and unsupported layout have actionable, privacy-safe recovery states. | Route tests and UI tests; browser regression for the user journey. |

## API and service design to validate before coding

Proposed routes (names are new and subject to API review):

- `GET /api/statements/gmail/candidates`: bounded query parameters and opaque
  pagination cursor; response contains display metadata plus Gmail message and
  attachment identifiers, with no bytes or email body.
- `POST /api/statements/gmail/detect`: message/attachment identifiers and
  optional password in the JSON body; returns the existing detection envelope
  plus document fingerprint and a password-required state. No persistence.
- `POST /api/statements/gmail/import`: identifiers, reviewed fingerprint, owned
  financial account ID, and optional password in the body; returns the existing
  statement import envelope. Import retains existing atomic transaction behavior.

Use a statement-attachment service alongside the Gmail connector for provider
search and retrieval. Share a single PDF extraction/detection/import boundary
with upload routes. Provider calls and PDF/OCR processing must not block the
async event loop. Reuse encrypted Gmail credentials, ownership helpers, and
connection-generation fencing. Avoid putting passwords, message identifiers,
or extracted content in URLs, exception details, logs, metrics, or audit payloads.
Bound candidate/fetch calls and password attempts to limit provider load and
online guessing without exposing whether a candidate belongs to another user.

Search should use a separate bounded Gmail query rather than advancing the
transaction sync history cursor. File names and MIME declarations are hints;
the downloaded bytes and statement detector remain the trust boundary. Use
stable, non-secret error codes and retry only transient provider failures.

No migration is expected for this first release: candidates are fetched on
demand, and existing statement records provide import idempotency. Reassess if
requirements later call for durable queues, saved passwords, or attachment
status tracking.

## Likely owning files

| Area | Existing files to change or extend |
| --- | --- |
| Gmail retrieval | `backend/app/services/connectors/gmail_connector.py` or a focused sibling service; `backend/app/api/routes/gmail.py` or focused statement routes |
| PDF and import boundary | `backend/app/services/statement_pdf_extractor.py`, `backend/app/api/routes/financial_position.py`, relevant schemas in `backend/app/schemas/financial_position.py` |
| UI and API client | `frontend/src/features/data/StatementImportSection.tsx`, `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`; reuse existing connection status and UI primitives |
| Backend tests | `tests/pytest/test_gmail_connector_contract.py`, `test_statement_pdf_extractor.py`, statement route/integration tests, plus focused attachment fixtures |
| Frontend tests | `StatementImportSection.test.tsx` and a browser regression under `frontend/e2e/` |
| Contracts | `docs/api-reference.md`, `docs/integrations.md`, `docs/workflows.md`, `docs/security.md`, and `docs/ui-ux-masterplan.md`; `docs/data_model.md` only if persistence changes |

Before frontend implementation, follow the repository's mandatory frontend
design, app principles, React performance, and web interface guidelines with
`agents/UI_UX.md` and `docs/ui-ux-masterplan.md`. Preserve PFIS's calm financial
workspace, keyboard operation, mobile behavior, visible focus, and restrained
motion. The source → detected product → owned account chain is the hierarchy.

## Ordered implementation and proof plan

1. **Confirm fixtures and contract.** Collect de-identified representative PDFs
   and metadata for the user's actual issuer/encryption variants. Finalize the
   date window, candidate display fields, errors, and request/response schemas.
   Proof: contract review against Gmail API and existing privacy policy.
2. **Provider retrieval.** Add read-only candidate search and one-attachment
   fetch with ownership, pagination, size, MIME, and failure controls. Proof:
   mocked Gmail tests, no live Gmail calls in CI.
3. **Password-aware extraction.** Add bounded in-memory decryption and explicit
   failure types; keep OCR and unsupported-layout gates intact. Proof: real
   de-identified encrypted PDF fixtures and extractor tests. Review dependency
   support before adding any package.
4. **Detection and import routes.** Reuse the existing statement service,
   fingerprint recheck, transaction boundary, and duplicate handling. Proof:
   route/integration tests across owners, retries, source changes, and partial
   failures; manual upload regression.
5. **Statements UI.** Add source choice and recoverable states without a new
   navigation destination. Proof: frontend lint, interaction tests, accessibility
   and responsive review, browser test with a mocked provider.
6. **Documentation and integrated review.** Update contracts and privacy docs,
   run the applicable quality and security checks, and inspect the full diff for
   account leakage, secret handling, import correctness, and operability.

Each slice stays on `codex/gmail-statement-import`. Do not push, open a PR, or
merge as part of this planning task.

## Release gate and rollback

When implementation is reviewable, run focused local tests first, then the
backend and frontend checks from CI. Open a pull request into `main` only after
authorization. The PR must show all four green jobs: backend lint/type/test and
quality gates; frontend lint/audit/test/build/bundle; PostgreSQL migration and
runtime; browser regression. The browser job depends on the first three. Inspect
artifacts and failures rather than treating a partially successful workflow as
merge-ready. Merge only after explicit review and authorization.

The feature should be additive and can be disabled or reverted without
rewriting imported statement data. Existing imported records remain subject to
the normal user ownership and deletion rules. If provider access or extraction
fails, the manual upload path remains the recovery path.

## Decisions and blockers to resolve before implementation

1. **Product scope:** Confirm user-triggered selection for the first release.
   Automatic imports of encrypted future mail would need a separate credential
   storage/consent design and should not be implied by this plan.
2. **Real examples:** Obtain safe, de-identified examples of the target banks'
   statement attachments and encryption methods. Existing import support does
   not guarantee those layouts are accepted.
3. **Search window:** Choose a default historical window and maximum results,
   with visible pagination/coverage. Proposed default: last 12 months, with an
   explicit older search rather than unbounded mailbox scanning.
4. **Provider readiness:** The connected Gmail grant must be valid in the target
   environment. The current `gmail.readonly` scope is sufficient for Google's
   attachment API; rollout may still depend on the app's existing Google OAuth
   verification and deployment configuration.

None is a known code-level impossibility. The sample/layout check is the main
unknown for the user's actual statements.

## Primary sources

- [Gmail message MIME part structure](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages)
- [Gmail attachment retrieval and accepted scopes](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments/get)
