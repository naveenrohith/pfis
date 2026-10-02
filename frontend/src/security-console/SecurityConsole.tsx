import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  ApiError,
  downloadReport,
  requestJson,
  type AssessmentRun,
  type ConsoleData,
  type Finding,
  type FindingState,
  type ReportRef,
  type ToolStatus,
} from './api';

type View = 'lab' | 'runs' | 'findings' | 'reports';
const VIEWS: Array<{ id: View; label: string; caption: string }> = [
  { id: 'lab', label: 'Lab', caption: 'Scope and tools' },
  { id: 'runs', label: 'Runs', caption: 'Coverage history' },
  { id: 'findings', label: 'Findings', caption: 'Evidence and triage' },
  { id: 'reports', label: 'Reports', caption: 'Local exports' },
];
const STATES: FindingState[] = ['candidate', 'confirmed', 'false_positive', 'fixed_pending_rescan', 'resolved'];
const INITIAL_DATA: ConsoleData = { lab: null, tools: [], runs: [], findings: [], reports: [] };

export function SecurityConsole() {
  const [view, setView] = useState<View>('lab');
  const [paired, setPaired] = useState(false);
  const [csrfToken, setCsrfToken] = useState('');
  const [code, setCode] = useState('');
  const [data, setData] = useState<ConsoleData>(INITIAL_DATA);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [dark, setDark] = useState(false);

  const refresh = useCallback(async () => {
    if (!csrfToken) return;
    setRefreshing(true);
    try {
      const [lab, tools, runs, findings, reports] = await Promise.all([
        requestJson<ConsoleData['lab']>('/security-api/lab'),
        requestJson<{ tools: ToolStatus[] }>('/security-api/tools'),
        requestJson<AssessmentRun[]>('/security-api/runs'),
        requestJson<Finding[]>('/security-api/findings'),
        requestJson<ReportRef[]>('/security-api/reports'),
      ]);
      setData({ lab, tools: tools.tools, runs, findings, reports });
      setError('');
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setPaired(false);
        setCsrfToken('');
        setError('Your local operator session expired. Pair the console again.');
      } else {
        setError(cause instanceof Error ? cause.message : 'The local security API is unavailable.');
      }
    } finally {
      setRefreshing(false);
    }
  }, [csrfToken]);

  useEffect(() => {
    let alive = true;
    void requestJson<{ csrf_token: string }>('/security-api/session')
      .then((session) => {
        if (!alive) return;
        setCsrfToken(session.csrf_token);
        setPaired(true);
      })
      .catch(() => {
        if (alive) setPaired(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (paired && csrfToken) void refresh();
  }, [paired, csrfToken, refresh]);

  const hasActiveRun = useMemo(
    () => data.runs.some((run) => run.state === 'queued' || run.state === 'running'),
    [data.runs],
  );

  useEffect(() => {
    if (!paired || !hasActiveRun) return undefined;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [paired, hasActiveRun, refresh]);

  async function pair(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/security-api/pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
        redirect: 'error',
        body: JSON.stringify({ code }),
      });
      const result = (await response.json().catch(() => ({}))) as { csrf_token?: string; detail?: string };
      if (!response.ok || !result.csrf_token) throw new Error(result.detail ?? 'Pairing code was not accepted.');
      setCsrfToken(result.csrf_token);
      setPaired(true);
      setCode('');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Pairing failed.');
    } finally {
      setBusy(false);
    }
  }

  async function startRun(profileId: string) {
    setBusy(true);
    try {
      await requestJson('/security-api/runs', {
        method: 'POST',
        body: JSON.stringify({ profile_id: profileId }),
      }, csrfToken);
      setView('runs');
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Assessment could not be started.');
    } finally {
      setBusy(false);
    }
  }

  async function cancelRun(runId: string) {
    setBusy(true);
    try {
      await requestJson(`/security-api/runs/${runId}/cancel`, { method: 'POST' }, csrfToken);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Cancellation could not be requested.');
    } finally {
      setBusy(false);
    }
  }

  async function triage(finding: Finding, nextStatus: FindingState) {
    setBusy(true);
    try {
      await requestJson(`/security-api/findings/${finding.fingerprint}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: nextStatus, note: '' }),
      }, csrfToken);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Finding status could not be updated.');
    } finally {
      setBusy(false);
    }
  }

  async function rescan(finding: Finding) {
    setBusy(true);
    try {
      await requestJson(`/security-api/findings/${finding.fingerprint}/rescan`, { method: 'POST' }, csrfToken);
      setView('runs');
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Rescan could not be started.');
    } finally {
      setBusy(false);
    }
  }

  async function resetLab() {
    if (!window.confirm('Reset the disposable lab and erase its synthetic financial records?')) return;
    setBusy(true);
    try {
      await requestJson('/security-api/lab/reset', { method: 'POST' }, csrfToken);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The lab could not be reset.');
    } finally {
      setBusy(false);
    }
  }

  if (!paired) {
    return (
      <main className={`security-app ${dark ? 'dark' : ''}`}>
        <div className="pair-card">
          <div className="security-wordmark" aria-label="PFIS Security Lab">PFIS <span>SECURITY</span></div>
          <p className="eyebrow">LOCAL OPERATOR ACCESS</p>
          <h1>Pair this console</h1>
          <p className="pair-copy">Enter the one-time code printed by <code>python scripts/security.py console</code>.</p>
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          <form onSubmit={pair} className="pair-form">
            <label htmlFor="pairing-code">Local pairing code</label>
            <input
              id="pairing-code"
              name="pairing-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              required
            />
            <button className="button-primary" type="submit" disabled={busy || code.length !== 6}>
              {busy ? 'Pairing…' : 'Open local console'}
            </button>
          </form>
          <p className="pair-footnote">The code expires after five minutes. This console accepts loopback connections only.</p>
        </div>
      </main>
    );
  }

  const latestRun = data.runs[0];
  const readyCount = data.tools.filter((tool) => tool.ready).length;

  return (
    <div className={`security-app ${dark ? 'dark' : ''}`}>
      <header className="security-header">
        <a className="security-brand" href="#lab" onClick={() => setView('lab')} aria-label="PFIS Security Lab home">
          <span className="brand-mark">P</span>
          <span className="brand-copy"><strong>PFIS</strong><small>Security lab</small></span>
        </a>
        <div className="header-scope" role="status">
          <span className="scope-dot" aria-hidden="true" />
          <span><strong>Local scope locked</strong><small>Registered targets · synthetic data</small></span>
        </div>
        <button
          className="theme-button"
          type="button"
          onClick={() => setDark((value) => !value)}
          aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
          aria-pressed={dark}
        >
          {dark ? 'Light' : 'Dark'}
        </button>
      </header>

      <div className="security-layout">
        <aside className="security-rail" aria-label="Security console sections">
          <p className="rail-label">ASSESSMENT</p>
          <nav>
            {VIEWS.map((item, index) => (
              <button
                type="button"
                className={`rail-link ${view === item.id ? 'is-current' : ''}`}
                aria-current={view === item.id ? 'page' : undefined}
                onClick={() => setView(item.id)}
                key={item.id}
              >
                <span className="rail-index">0{index + 1}</span>
                <span className="rail-label-copy"><strong>{item.label}</strong><small>{item.caption}</small></span>
              </button>
            ))}
          </nav>
          <div className="rail-footer">
            <span className="rail-led" aria-hidden="true" />
            <span>Controller on loopback</span>
          </div>
        </aside>

        <main className="security-main">
          <div className="page-intro">
            <div>
              <p className="eyebrow">APPLICATION ASSURANCE · LOCAL ONLY</p>
              <h1>{VIEWS.find((item) => item.id === view)?.label ?? 'Security lab'}</h1>
              <p className="page-subtitle">Follow the evidence from a registered boundary through reproduction, remediation, and rescan.</p>
            </div>
            <button className="button-quiet" type="button" onClick={() => void refresh()} disabled={refreshing}>
              {refreshing ? 'Refreshing…' : 'Refresh evidence'}
            </button>
          </div>

          <div className="scope-banner">
            <div className="scope-banner-mark" aria-hidden="true">◎</div>
            <div><strong>Scope is fixed to this disposable PFIS lab.</strong><span>Only registered targets and profiles can be assessed. Scanner traffic stays on an internal Docker network.</span></div>
            <span className="scope-tag">SYNTHETIC</span>
          </div>

          {error && <p className="notice notice-error" role="alert">{error}</p>}

          {view === 'lab' && (
            <LabView
              data={data}
              latestRun={latestRun}
              readyCount={readyCount}
              busy={busy}
              onRun={startRun}
              onReset={resetLab}
            />
          )}
          {view === 'runs' && <RunsView runs={data.runs} busy={busy} onCancel={cancelRun} />}
          {view === 'findings' && <FindingsView findings={data.findings} busy={busy} onTriage={triage} onRescan={rescan} />}
          {view === 'reports' && <ReportsView reports={data.reports} />}
        </main>
      </div>
    </div>
  );
}

function LabView({
  data,
  latestRun,
  readyCount,
  busy,
  onRun,
  onReset,
}: {
  data: ConsoleData;
  latestRun?: AssessmentRun;
  readyCount: number;
  busy: boolean;
  onRun: (profileId: string) => void;
  onReset: () => void;
}) {
  const lab = data.lab;
  const isReady = Boolean(lab?.containers.length && lab.scanner_network_internal);
  return (
    <section aria-labelledby="lab-overview-title">
      <div className="overview-grid">
        <article className="overview-card overview-primary">
          <div className="card-kicker"><span className={`state-orb ${isReady ? 'orb-ready' : ''}`} />LAB STATE</div>
          <h2 id="lab-overview-title">{isReady ? 'Ready for a bounded run' : 'Lab needs preparation'}</h2>
          <p>{isReady ? 'PFIS is served over the private HTTPS proxy. The scanner network is isolated from the database and host routes.' : 'Prepare the pinned images, then start the disposable lab from the developer CLI.'}</p>
          <div className="primary-meta">
            <div><span>Target origin</span><strong>{lab?.https_url ?? 'https://localhost:8443'}</strong></div>
            <div><span>Lab generation</span><strong className="mono">{lab?.generation ?? 'Not created'}</strong></div>
          </div>
        </article>
        <article className="overview-card readiness-card">
          <div className="card-kicker">TOOL READINESS</div>
          <strong className="readiness-number">{readyCount}<span> / 7</span></strong>
          <p>scanner integrations ready</p>
          <div className="readiness-meter" aria-label={`${readyCount} of 7 scanners ready`}>
            <span style={{ width: `${(readyCount / 7) * 100}%` }} />
          </div>
          <small>Unavailable and incomplete tools stay visible in coverage.</small>
        </article>
        <article className="overview-card run-card">
          <div className="card-kicker">LATEST RUN</div>
          <strong className="run-profile">{latestRun?.profile ?? 'No assessments yet'}</strong>
          <RunStatePill state={latestRun?.state ?? 'interrupted'} empty={!latestRun} />
          <p>{latestRun ? `Commit ${latestRun.commit_sha.slice(0, 8)} · ${formatDate(latestRun.created_at)}` : 'Start with the baseline profile to inventory HTTPS, ports, and passive findings.'}</p>
        </article>
      </div>

      <div className="section-heading">
        <div><p className="eyebrow">REGISTERED PROFILES</p><h2>Choose an assessment</h2></div>
        <span className="soft-pill">One run at a time</span>
      </div>
      <div className="profile-grid">
        <ProfileCard
          number="01"
          name="Baseline"
          description="Nmap service inventory, testssl.sh posture, passive ZAP, and reviewed Nuclei checks."
          tools="NMAP · TESTSSL · ZAP · NUCLEI"
          disabled={busy || !isReady}
          onRun={() => onRun('baseline')}
        />
        <ProfileCard
          number="02"
          name="Application"
          description="OpenAPI assessment and authenticated application boundaries using synthetic identities."
          tools="ZAP · PFIS SECURITY TESTS · NUCLEI"
          disabled={busy || !isReady}
          onRun={() => onRun('application')}
        />
        <ProfileCard
          number="03"
          name="Infrastructure"
          description="Greenbone assessment after its community feeds have loaded and readiness is verified."
          tools="GREENBONE COMMUNITY"
          disabled={busy || !isReady}
          onRun={() => onRun('infrastructure')}
        />
        <ProfileCard
          number="04"
          name="Exploit validation"
          description="Bounded sqlmap and reviewed Metasploit validation against isolated training fixtures."
          tools="SQLMAP · METASPLOIT"
          disabled={busy || !isReady}
          onRun={() => onRun('exploit-validation')}
        />
      </div>

      <div className="bottom-grid">
        <section className="tool-panel" aria-labelledby="tools-title">
          <div className="section-heading compact-heading"><div><p className="eyebrow">PINNED INTEGRATIONS</p><h2 id="tools-title">Scanner versions</h2></div></div>
          <ul className="tool-list">
            {data.tools.map((tool) => <ToolRow tool={tool} key={tool.id} />)}
            {data.tools.length === 0 && <li className="empty-row">Readiness is checked when the local lab is available.</li>}
          </ul>
        </section>
        <section className="lab-identity-panel" aria-labelledby="identity-title">
          <div className="section-heading compact-heading"><div><p className="eyebrow">BOUNDARY CHECK</p><h2 id="identity-title">Lab identity</h2></div></div>
          <dl className="identity-list">
            <div><dt>Data class</dt><dd>{lab?.synthetic_data ? 'Synthetic financial records' : 'Unverified'}</dd></div>
            <div><dt>Scanner network</dt><dd>{lab?.scanner_network_internal ? 'Internal · egress disabled' : 'Not verified'}</dd></div>
            <div><dt>Lab services</dt><dd>{lab?.containers.length ?? 0} generation-labelled containers</dd></div>
            <div><dt>Docker context</dt><dd>{lab?.docker_context ?? 'Not available'}</dd></div>
          </dl>
          <button className="button-danger-quiet" type="button" onClick={onReset} disabled={busy || !lab}>
            Reset synthetic lab
          </button>
        </section>
      </div>
    </section>
  );
}

function ProfileCard({
  number,
  name,
  description,
  tools,
  disabled,
  onRun,
}: {
  number: string;
  name: string;
  description: string;
  tools: string;
  disabled: boolean;
  onRun: () => void;
}) {
  return (
    <article className="profile-card">
      <div className="profile-card-top"><span className="profile-number">{number}</span><span className="profile-tools">{tools}</span></div>
      <h3>{name}</h3>
      <p>{description}</p>
      <button className="profile-run" type="button" disabled={disabled} onClick={onRun}>
        Start profile <span aria-hidden="true">↗</span>
      </button>
    </article>
  );
}

function ToolRow({ tool }: { tool: ToolStatus }) {
  return (
    <li className="tool-row">
      <div className="tool-avatar" aria-hidden="true">{tool.id.slice(0, 2).toUpperCase()}</div>
      <div className="tool-name"><strong>{tool.id}</strong><small>{tool.version} · {tool.capabilities.slice(0, 2).join(', ')}</small></div>
      <span className={`tool-state ${tool.ready ? 'tool-ready' : ''}`}>{tool.ready ? 'Ready' : 'Not ready'}</span>
      {!tool.ready && <small className="tool-warning">{tool.detail || (tool.digest_pinned ? 'Readiness check required' : 'Pin unavailable')}</small>}
    </li>
  );
}

function RunsView({ runs, busy, onCancel }: { runs: AssessmentRun[]; busy: boolean; onCancel: (id: string) => void }) {
  return (
    <section aria-labelledby="runs-title">
      <div className="section-heading"><div><p className="eyebrow">EXECUTION HISTORY</p><h2 id="runs-title">Assessments</h2></div><span className="soft-pill">Serial execution</span></div>
      {runs.length === 0 ? <EmptyState title="No runs recorded" copy="A run captures the branch commit, lab generation, tool outcomes, and coverage gaps." /> : (
        <div className="table-frame">
          <table className="security-table">
            <caption className="sr-only">Assessment runs and their execution state</caption>
            <thead><tr><th scope="col">Profile</th><th scope="col">State</th><th scope="col">Commit</th><th scope="col">Started</th><th scope="col">Coverage</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{runs.map((run) => <tr key={run.id}>
              <td><strong>{run.profile}</strong><small className="mono row-subtext">{run.id.slice(0, 12)}</small></td>
              <td><RunStatePill state={run.state} /></td>
              <td className="mono">{run.commit_sha.slice(0, 8)}</td>
              <td>{formatDate(run.started_at ?? run.created_at)}</td>
              <td><CoverageSummary summary={run.summary} /></td>
              <td>{run.state === 'queued' || run.state === 'running' ? <button className="button-danger-quiet" onClick={() => onCancel(run.id)} disabled={busy}>Cancel</button> : null}</td>
            </tr>)}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function FindingsView({
  findings,
  busy,
  onTriage,
  onRescan,
}: {
  findings: Finding[];
  busy: boolean;
  onTriage: (finding: Finding, nextStatus: FindingState) => void;
  onRescan: (finding: Finding) => void;
}) {
  if (findings.length === 0) return <EmptyState title="No PFIS findings yet" copy="Fixture control results stay separate. PFIS observations appear here with their tool, target, endpoint, and sanitized evidence." />;
  return (
    <section aria-labelledby="findings-title">
      <div className="section-heading"><div><p className="eyebrow">EVIDENCE AND TRIAGE</p><h2 id="findings-title">PFIS observations</h2></div><span className="soft-pill">{findings.length} finding{findings.length === 1 ? '' : 's'}</span></div>
      <div className="finding-list">
        {findings.map((finding) => (
          <article className="finding-card" key={finding.fingerprint}>
            <div className="finding-main">
              <span className={`severity severity-${finding.severity}`}>{finding.severity}</span>
              <div className="finding-heading"><h3>{finding.title}</h3><p>{finding.target_id} <span aria-hidden="true">·</span> {finding.endpoint}</p></div>
              <span className="confidence">{finding.confidence} confidence</span>
            </div>
            <details className="finding-evidence">
              <summary>Evidence trail <span>{finding.tool} · {finding.evidence.length} observation{finding.evidence.length === 1 ? '' : 's'}</span></summary>
              <div className="evidence-body">
                {finding.evidence.map((entry, index) => <blockquote key={`${entry.tool}-${entry.observed_at}-${index}`}>
                  <small>{entry.tool} · {formatDate(entry.observed_at)}</small>
                  <p>{entry.value}</p>
                </blockquote>)}
                {finding.reproduction && <p className="reproduction"><strong>Reproduction:</strong> {finding.reproduction}</p>}
              </div>
            </details>
            <div className="finding-actions">
              <label htmlFor={`state-${finding.fingerprint}`}>Triage state</label>
              <select
                id={`state-${finding.fingerprint}`}
                value={finding.status}
                onChange={(event) => onTriage(finding, event.target.value as FindingState)}
                disabled={busy}
              >
                {STATES.map((state) => <option value={state} key={state}>{formatState(state)}</option>)}
              </select>
              <button className="button-quiet" type="button" onClick={() => onRescan(finding)} disabled={busy}>Rescan</button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ReportsView({ reports }: { reports: ReportRef[] }) {
  return (
    <section aria-labelledby="reports-title">
      <div className="section-heading"><div><p className="eyebrow">LOCAL RETENTION · 30 DAYS</p><h2 id="reports-title">Assessment reports</h2></div><span className="soft-pill">JSON attachments</span></div>
      {reports.length === 0 ? <EmptyState title="Reports will appear here" copy="Completed, failed, interrupted, and cancelled runs retain a sanitized JSON report for 30 days." /> : (
        <div className="report-list">
          {reports.map((report) => <article className="report-row" key={report.id}>
            <div className="report-mark" aria-hidden="true">R</div>
            <div className="report-copy"><strong>{report.profile} assessment</strong><small>{report.id} · {formatDate(report.created_at)}</small></div>
            <RunStatePill state={report.state} />
            <button className="button-quiet" type="button" onClick={() => void downloadReport(report.id)}>Download JSON</button>
          </article>)}
        </div>
      )}
    </section>
  );
}

function CoverageSummary({ summary }: { summary: AssessmentRun['summary'] }) {
  const parsed = typeof summary === 'string' ? safeJson(summary) : summary;
  const coverage = Array.isArray(parsed.coverage) ? parsed.coverage as Array<{ status?: string }> : [];
  const completed = coverage.filter((item) => item.status === 'completed' || item.status === 'no_findings').length;
  return <span className={parsed.coverage_complete === false ? 'coverage-gap' : ''}>{coverage.length ? `${completed}/${coverage.length} tools` : 'Preparing'}</span>;
}

function RunStatePill({ state, empty = false }: { state: AssessmentRun['state']; empty?: boolean }) {
  return <span className={`run-state state-${state} ${empty ? 'state-empty' : ''}`}>{empty ? '—' : formatState(state)}</span>;
}

function EmptyState({ title, copy }: { title: string; copy: string }) {
  return <div className="empty-state"><span className="empty-rule" /><h3>{title}</h3><p>{copy}</p></div>;
}

function safeJson(value: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === 'object' && parsed !== null ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function formatState(value: string) {
  return value.replaceAll('_', ' ');
}

function formatDate(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}
