# PFIS Security Lab

The security lab is a disposable local assessment environment for PFIS. It
uses generated accounts and financial records, a separate PostgreSQL database,
a loopback-only HTTPS proxy, and an internal scanner network. It does not use
production credentials or real Gmail connections. The lab proxy applies the
production HSTS policy so TLS checks exercise the deployed header behavior.

## Prepare and operate the lab

Run these commands from the repository root:

```text
python scripts/security.py prepare --lightweight
python scripts/security.py lab start --lightweight
python scripts/security.py verify-boundaries
python scripts/security.py run --profile passive --wait
python scripts/security.py console
```

`prepare --lightweight` prepares PFIS and passive ZAP for routine checks.
`prepare --extended` adds pinned Nuclei, Nmap, and testssl images without
downloading Greenbone feeds. Plain `prepare` prepares all seven tools and
Greenbone feeds. Lab startup applies Alembic migrations, seeds synthetic users
and records, starts the loopback HTTPS endpoint, exports its local CA, and
verifies lab identity.

Generated owner, member, and viewer credentials live under the ignored
`.security-local/` directory. Keep it private. The loopback console displays a
pairing code that expires after five minutes. Operator sessions use an HttpOnly
cookie, exact Origin and Host checks, and CSRF tokens. Security findings and
reports use a separate local SQLite database; reports are retained for 30 days
by default.

```text
python scripts/security.py lab status
python scripts/security.py status
python scripts/security.py findings
python scripts/security.py run --profile baseline --wait
python scripts/security.py run --profile application --wait
python scripts/security.py run --profile frontend --wait
python scripts/security.py run --profile infrastructure --wait
python scripts/security.py run --profile exploit-validation --wait
python scripts/security.py run --profile full --wait
python scripts/security.py cancel <run-id>
python scripts/security.py report <run-id>
python scripts/security.py lab reset
```

CLI and console share targets, profiles, findings, and run state. Assessments
run one at a time across processes. Reset is rejected while an assessment owns
the process lock. `lab reset` removes only current-generation resources and
leaves local credentials and evidence available for reuse.

## Registered tools and boundaries

| Tool | Registered use | Important limit |
|---|---|---|
| OWASP ZAP 2.17.0 | Passive API checks, a separate dashboard crawl, and an authenticated API assessment | The active API scan uses a committed five-path operation allowlist because the full PFIS OpenAPI document is too large for a bounded run. It pins the spec server to the lab, rejects external references, trusts only the exported lab CA, and disables updates. |
| Nuclei 3.11.1 | Reviewed PFIS HTTP/TLS templates with a five-request-per-second limit | Code templates, automatic updates, and Interactsh callbacks are disabled. Version 3.10.0 or later is required for [GHSA-jpf4-98qj-qr67](https://github.com/projectdiscovery/nuclei/security/advisories/GHSA-jpf4-98qj-qr67). |
| Nmap 7.97 | Registered target port and service inventory using a fixed NSE allowlist | Scans only registered lab targets and ports. |
| testssl.sh 3.2.4 | HTTPS protocol, cipher, and certificate checks | Private-CA observations are contextualized rather than treated as public certificate defects. |
| Greenbone Community | Infrastructure assessment after feed readiness | Image, feed age, enabled VT families, and reachable services limit coverage; readiness must be recorded. |
| sqlmap 1.10 | Positive and negative controls against the isolated SQL injection fixture | PFIS endpoints are assessed only when evidence supports bounded validation. |
| Metasploit Framework 6.5.5 image digest | Fixed vsftpd module validation against the isolated Metasploitable fixture | A derived image removes the upstream Ruby/Nmap file capabilities and setuid helper, then runs UID/GID 1000 with a read-only root, no added capabilities, and `no-new-privileges`. The binary reports `6.5.5-dev`; no arbitrary module paths or targets are accepted. The fixture uses TCP 21 and restarts before and after every attempt; it is never a PFIS target. |

Images and scanner templates are digest or revision pinned. Greenbone runs
separately because of its memory use. Feed update services disconnect before
scans. Scanner containers have no Docker socket, host bind, or internet route;
the scanner network is internal. Scope checks reject arbitrary URLs and
redirects.

Profiles are `baseline` (Nmap, TLS, passive ZAP, Nuclei), `application`
(authenticated ZAP, 22 synthetic-user boundary checks, Nuclei),
`frontend` (passive crawl from `/dashboard`),
`infrastructure` (Greenbone), `exploit-validation` (fixture-only sqlmap and
Metasploit), and `full` (sequential profiles with fixture resets). Coverage
distinguishes completed, no findings, not applicable, authentication failure,
timeout, cancellation, and incomplete execution. Missing tools, failed scans,
and missing controls never count as a pass. Fixture-control findings remain
separate from PFIS findings.

The authenticated ZAP API scan loads a reviewed HTTP Sender script scoped to
`https://pfis.test`. It mirrors only the synthetic `__Host-pfis-csrf` cookie into
`X-CSRF-Token` and runs a fixed empty transaction mutation afterward. The scan
fails unless PFIS returns its expected validation response (`422`) with the
session-bound token; neither token value is written to findings or logs.

## CI pipeline

The existing PFIS workflow also runs on pushes to `codex/pfis-security-lab`;
its backend, frontend, PostgreSQL, and dependent browser regression jobs remain
in place. `Security Lab` runs on that branch and on pull requests targeting
`main`. It checks pinned actionlint, controller and adapter tests, the separate
console build and Firefox/axe suite, and a fresh HTTPS lab with authenticated
boundary checks, passive ZAP, and the separate `/dashboard` crawl. Manual
dispatch can run Nmap, TLS, passive and authenticated ZAP, the frontend crawl,
and reviewed Nuclei profiles sequentially. Greenbone and
exploit validation remain in the full local profile because feed and destructive
fixture stages need a dedicated resource envelope.

Security jobs have read-only repository permissions, generated lab credentials,
bounded timeouts, and no production secrets. They upload sanitized reports and
structured events for seven days, then clean only their labelled lab
generation. The aggregate result fails if a required job fails, is cancelled,
or is unexpectedly skipped. GitHub status is unverified until an authorized
push runs the workflows; a local pass does not establish a remote pass.

## Troubleshooting and recovery

- If a scanner is missing or its digest differs, rerun the appropriate
  `prepare` mode and inspect `python scripts/security.py lab status`.
- If HTTPS readiness fails, restart only the current generation and confirm its
  exported CA is present before retrying authenticated ZAP.
- The next coordinator marks interrupted work as interrupted and cleans only
  run-labelled containers; it never replays an assessment.
- If cleanup reports a live assessment lock, wait for that run or cancel it
  before resetting the lab.
- Greenbone requires prepared feeds and disconnected feed-egress. Missing
  readiness blocks the scan.
- Never report a fixture control as a PFIS finding. Confirmed critical/high
  PFIS findings require a regression test, a fix, and a rescan. Document lower
  severity observations and coverage gaps in the assessment report.
