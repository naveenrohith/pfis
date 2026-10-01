# PFIS Security Lab Assessment — 2026-10-01

## Outcome

The disposable PFIS lab completed baseline, frontend, authenticated application,
infrastructure, and exploit-control assessments. All required scans report
complete coverage, and there are **no confirmed critical or high findings on
the PFIS target**. The two high-severity observations from exploit validation
are expected positive controls on the isolated SQL injection and Metasploitable
fixtures; both are tagged as controls and excluded from PFIS findings.

No scanner-confirmed PFIS application vulnerability was found. A separate
dependency audit found vulnerable PyJWT records on the starting revision; the
branch upgrades the pin and its repeat audit is clean. The scan also identified
a medium TLS grade of B for the local HTTPS endpoint and informational
observations caused by the private lab certificate, expected negative API
probes, and literal placeholder query parameters. Their dispositions are below.

## Scope and lab identity

- Branch: `codex/pfis-security-lab`, created from `origin/main` at
  `f755c3b9ccf47961822ba95ecbb70ee7aa47b533`.
- Assessment source revision: `13a0468cc28cfa78ff0d0e6c4a8927379d54d906`.
  The later `0ed281c0854cc485ccaebc6043bcecc62a9bce06` change only added
  pre- and post-run restarts for disposable exploit fixtures. The application
  source did not change between those revisions. Boundary verification and the
  successful exploit-control rerun were performed on `0ed281c`.
- Lab generation: `634d40a0bac6`; synthetic users and financial records only;
  HTTPS target `https://localhost:8443` / registered scanner host `pfis.test`.
- Scanner containers had no host bind mounts or Docker socket. The scanner
  network was internal, Greenbone feed egress was disconnected before scanning,
  credentials were generated for this lab, and demo login was disabled during
  the application assessment.
- Provider behavior was covered by the existing mocked Google/Gmail contract
  tests; no live Google account or production provider was contacted.

The complete image, source, template, and Greenbone feed digests are recorded in
the local ignored receipt `.security-local/image-receipt.json` and archived
`.security-local/reports/greenbone-feed-receipt.json`. The local sanitized JSON
reports are under `.security-local/reports/` and are intentionally not committed.

## Scanner versions and coverage

| Tool | Version / source | Assessment use |
|---|---|---|
| OWASP ZAP | 2.17.0 | Passive baseline, authenticated OpenAPI/API assessment, separate frontend crawl |
| Nuclei | 3.11.1 | Reviewed HTTP/TLS templates; code templates, automatic updates, and external callbacks disabled |
| Nmap | 7.97 | TCP top-1,000 inventory and service versions using the committed NSE allowlist |
| testssl.sh | 3.2.4 | HTTPS protocol, cipher, and certificate checks |
| Greenbone Community | Community feed; OSPD OpenVAS 22.10.5 | Full-and-fast scan of the registered PFIS lab target after feed readiness |
| sqlmap | 1.10 at `ea8c6bdb63a3b2da1584f328836eb0d28116f7c4` | Positive control against the isolated in-memory SQL injection fixture |
| Metasploit Framework | 6.5.5-dev from pinned 6.5.5 image | Fixed vsftpd module against the isolated Metasploitable fixture; transient session closed by cleanup |

Nuclei meets the plan's 3.10.0 minimum. Its source image is pinned to the
reviewed 3.11.1 digest. Greenbone uses the official Community stack and
generation-specific feed receipts; coverage applies only to scanner-reachable
lab services and the feed content available in that run. Nmap's TCP top-port
and script allowlists do not establish UDP or full production network coverage.

## Assessment run ledger

| Profile | Run ID | Source revision | Result |
|---|---|---|---|
| Baseline | `8fbd67a9470a72ef1e2b318a77a511ec` | `13a0468` | Complete; Nmap 2 observations, testssl 6, passive ZAP 2, Nuclei 0; no critical/high |
| Frontend | `85656c4ba06885f396f10bfcdfca78c4` | `13a0468` | Complete; ZAP 2 observations; no critical/high |
| Application | `e47da68eafde87467c438ca979acdc42` | `13a0468` | Complete; all 22 fixed boundary checks passed, authenticated ZAP 52 observations, Nuclei 0; no critical/high |
| Infrastructure | `25dadc443902752100cdbe23379eec2c` | `13a0468` | Complete; Greenbone scanned the registered target for 554.7 seconds; no findings |
| Exploit validation | `2fc25f28c7b31f7d478276fd849cbe2a` | `0ed281c` | Complete; SQLMap and Metasploit positive controls detected; controls only |
| CI passive wrapper | `c6c757299d5319739dd23e03a4c3c9f7` | `0ed281c` | Complete; no critical/high; sanitized CI artifact created |
| CI frontend wrapper | `74a7161d1d70544fbbc7351830a30f14` | `0ed281c` | Complete; no critical/high; sanitized CI artifact created |

Two earlier failed runs were retained as failure evidence rather than counted as
passes:

- Greenbone run `6021d76126e077b5c2ea93974fc8a1d7` on `f1c794a` failed closed
  because the manager already held a target with the fixed name. Commit
  `13a0468` added exact generation, host, port-list, task, scanner, and
  configuration validation before reusing manager objects. The successful
  infrastructure run above verifies the retry path; active or mismatched
  objects still fail closed.
- Exploit run `6bcdded555eddad1b4f2a6d92a0c7959` on `13a0468` had a SQLMap
  fixture connection timeout while Metasploit's control passed. The fixture was
  long-lived and logged client disconnects. Commit `0ed281c` restarts both
  disposable exploit fixtures before and after each probe. The successful
  exploit-validation run above confirms both controls after that change.

### Starting-revision triage

Two preliminary runs against `f755c3b` are preserved for comparison but are
not counted as final branch coverage:

- Application run `55d7fa84619b9d11ce7fa5ff68d4ecef` was incomplete: the
  synthetic owner login check failed, and ZAP/Nuclei did not produce complete
  coverage. The subsequent final application run completed all 22 fixed
  boundary checks and produced no authentication-boundary finding. The earlier
  login record is resolved; the run remains failed evidence.
- Baseline run `7a7a037831f6db26a1b6246503eb23d1` parsed four high/critical
  testssl observations from the generated private-CA certificate. The final
  branch baseline run classified the equivalent private-CA observations as
  informational. Those four earlier certificate records are triaged as false
  positives for PFIS production scope; the medium TLS grade B remains a
  candidate for staging retest.

The findings database retains these run histories and triage notes. Earlier
failure or out-of-scope certificate observations are not silently treated as
passing scans.

## Findings and disposition

### PFIS application

- **Critical/high:** none confirmed.
- **Authentication and ownership:** 22 fixed checks passed across private-user,
  household-role, unauthenticated, session, CSRF, and cross-user boundaries.
- **Authenticated ZAP:** 52 scan observations; no critical/high. The local
  finding store deduplicates repeated observations, so its exported record
  count is not the same as the per-run observation count.
- **Nuclei:** no matching findings from the reviewed HTTP/TLS templates.
- **Informational client errors:** 41 ZAP observations were expected 4xx
  responses from deliberately invalid or unauthorized probes. They are not
  evidence of a leak or cross-user access.
- **`user_id` in URLs:** five informational ZAP observations contain the literal
  placeholder `user_id` in generated requests to transactions, accounts,
  statement import, and CSV export routes. The evidence contains no real user
  identifier or credential. Keep these as a privacy/logging review candidate;
  confirm production logs and referrer policy before closing them.
- **SPA content type:** low ZAP observations for `/` and `/dashboard` were
  triaged as false positives because these routes intentionally return the SPA
  document as `text/html`.
- **CSRF cookie:** the low “Cookie No HttpOnly Flag” observation on login was
  triaged as a false positive for the script-readable double-submit CSRF
  cookie. The session cookie remains HttpOnly, and CSRF boundary checks passed.

### Deployment and TLS

- Nmap found only the expected Caddy HTTP/HTTPS listeners on TCP 80 and 443;
  no unexpected service was identified in the registered top-1,000 TCP scan.
- testssl reported an **overall grade B (medium)**. Keep this as an open TLS
  hardening candidate for review; this assessment did not establish that the
  grade is only caused by the lab CA.
- Informational certificate observations (incomplete chain, no CRL/OCSP URI,
  and a short-lived intermediate) describe the generated private-CA lab
  certificate. They do not establish a production certificate defect. Retest
  a public staging endpoint with its actual certificate before production
  release.
- testssl also reported that its optional local GOST engine was unavailable.
  This is a scanner capability notice, not a PFIS vulnerability.
- Greenbone completed its full-and-fast scan with complete coverage and no
  findings on the registered target.

### Dependency audit

- Auditing the exact `origin/main` requirements manifest on 2026-10-01 found
  **13 vulnerability records for PyJWT 2.13.0**. Official maintainer advisories
  mark 2.13.0 affected and list fixes in 2.14.0, including a high-severity JWK
  BOM bypass and a critical asymmetric-key detection bypass
  ([GHSA-r6x4-923q-g947](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-r6x4-923q-g947),
  [GHSA-ffc3-869f-jxw9](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-ffc3-869f-jxw9)).
- Commit `529f55e` updates the pin to PyJWT 2.15.1. Re-running `pip-audit` on
  the branch requirements manifest reported no known vulnerabilities. The
  machine-readable base and branch receipts are preserved at
  `.security-local/reports/base-pip-audit.json` and
  `.security-local/reports/branch-pip-audit.json`.
- PFIS currently calls `jwt.decode` with the single allowed algorithm HS256
  and a raw configured secret. The reviewed mixed-algorithm/JWK bypass
  preconditions were not present in that call path, so no exploit of PFIS token
  handling was confirmed. The dependency update removes the affected package
  versions regardless.

### Isolated exploit controls

SQLMap confirmed the intentionally injectable in-memory fixture; Metasploit's
fixed training module reported a shell on the registered Metasploitable
fixture. Both findings have `control=true` and target IDs other than `pfis-web`.
The Metasploit session was closed during cleanup, and the fixture restarted.
Neither tool was used to exploit PFIS: no applicable confirmed PFIS injection
or Metasploit finding justified that step.

## Local pipeline verification

Local equivalents for both workflows passed on the branch:

- Pinned actionlint 1.7.12 validated `.github/workflows/ci.yml` and
  `.github/workflows/security.yml`.
- Backend: Ruff, Black (347 files), mypy (193 sources), Python dependency audit
  (no known vulnerabilities), parser/release-gate evaluations, 32 operational
  smoke tests, and **1,160 tests passed at 85.29% branch coverage** (85% gate).
- PostgreSQL: migrations through `060_pref_policy_versions`, migration parity,
  and both runtime contract tests passed on an ephemeral database.
- Existing frontend: `npm ci`, npm audit (0 vulnerabilities), lint, **162 tests
  across 50 files**, production build, and bundle budget passed. Initial-route
  bundle was 99.2 KB gzip; 49 lazy chunks were checked.
- Browser regression: **51 passed, 15 skipped**. The skipped cases are the
  expected non-desktop repetitions of three desktop-only tests; six visual
  tests are excluded by the CI command's `@visual` filter.
- Security controller: Ruff, Black, mypy, and **59 controller, adapter,
  parser, dependency, recovery, cancellation, scope, and fixture tests** passed.
- Security console: lint, 2 component tests, separate production build,
  50.0 KB gzip bundle budget, and Firefox/axe E2E (2 passed) passed.
- Security CI wrapper: 22 boundary checks, passive ZAP, and the separate
  frontend ZAP profile completed with complete coverage and no critical/high.

The latest observed existing GitHub `CI` run on the base branch was run
`36117696867` on `f755c3b`, with conclusion `success`. **No workflow has run on
`codex/pfis-security-lab` yet:** the branch has not been pushed. GitHub pipeline
status for this branch remains unverified until an authorized push triggers it.

The plan-time local baseline receipts on `f755c3b` recorded exit code 1 for
`pip-audit` and backend pytest coverage. A later audit of the exact base
requirements manifest reproduced the dependency failure and identified the
PyJWT findings above. The coverage receipt retained only an output hash, so its
baseline failure cause is unavailable; the branch full backend suite passed at
85.29%. The successful GitHub base-branch result and local planning-run results
are retained here as separate evidence.

## Remaining coverage limits

- This assessment covered the disposable synthetic lab only, not a deployed
  production host, public PKI, or live Google/Gmail provider.
- The TLS grade B and placeholder `user_id` URL observations remain review
  items. Confirm against the intended production TLS configuration and logging
  policy.
- Greenbone coverage is constrained by its Community feed, available VT
  families, and scanner-reachable services. The assessment does not claim
  exhaustive production or UDP coverage.
- GitHub Actions branch results are unverified until a push is authorized and
  completed; all checks recorded above are local results.

## Post-assessment CLI hardening

The integrated code review found that a one-shot `security run` command could
return while its daemon worker still owned the assessment. The CLI now waits
for a terminal result by default; Ctrl+C requests cancellation and waits for
executor and fixture cleanup before returning. A subprocess regression test
covers both normal completion and interrupt cleanup. This runner fix does not
change the PFIS application code or the historical scanner results above. It
is recorded in commit `36a41b8` and was verified with the security regression
suite after the scan revisions listed above.
