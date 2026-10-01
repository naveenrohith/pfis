export type RunState = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
export type FindingState = 'candidate' | 'confirmed' | 'false_positive' | 'fixed_pending_rescan' | 'resolved';

export interface LabStatus {
  generation: string;
  project: string;
  https_url: string;
  synthetic_data: boolean;
  docker_context: string;
  containers: Array<{ Names: string; Status: string }>;
  scanner_network_internal: boolean | null;
}

export interface ToolStatus {
  id: string;
  version: string;
  image: string;
  capabilities: string[];
  digest_pinned: boolean;
  ready: boolean;
  status: string;
  detail: string;
}

export interface AssessmentRun {
  id: string;
  generation: string;
  commit_sha: string;
  profile: string;
  state: RunState;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  summary: string | Record<string, unknown>;
}

export interface Finding {
  fingerprint: string;
  title: string;
  severity: string;
  confidence: string;
  target_id: string;
  endpoint: string;
  tool: string;
  evidence: Array<{ tool: string; value: string; observed_at: string }>;
  reproduction: string;
  status: FindingState;
  first_seen: string;
  last_seen: string;
}

export interface ReportRef {
  id: string;
  profile: string;
  state: RunState;
  created_at: string;
  finished_at?: string | null;
}

export interface ConsoleData {
  lab: LabStatus | null;
  tools: ToolStatus[];
  runs: AssessmentRun[];
  findings: Finding[];
  reports: ReportRef[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function requestJson<T>(
  path: string,
  options: RequestInit = {},
  csrfToken?: string,
): Promise<T> {
  if (!path.startsWith('/security-api/')) throw new Error('Invalid local API path');
  const method = (options.method ?? 'GET').toUpperCase();
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    if (!csrfToken) throw new Error('The local operator session needs to be paired again.');
    headers.set('X-CSRF-Token', csrfToken);
  }
  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: 'same-origin',
    cache: 'no-store',
    redirect: 'error',
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(body?.detail ?? `Local security API returned ${response.status}.`, response.status);
  }
  return (await response.json()) as T;
}

export async function downloadReport(runId: string): Promise<void> {
  if (!/^[a-f0-9]{32}$/.test(runId)) throw new Error('Report ID is invalid.');
  const response = await fetch(`/security-api/reports/${runId}`, {
    credentials: 'same-origin',
    cache: 'no-store',
    redirect: 'error',
  });
  if (!response.ok) throw new ApiError('Report could not be downloaded.', response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `pfis-security-${runId}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
