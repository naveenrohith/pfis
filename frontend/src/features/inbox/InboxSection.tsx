import { useEffect, useState } from 'react';
import { AlertCircle, ArrowRight, CheckCircle2, Mail, RefreshCw, ShieldCheck } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useAutoSyncStatus, useEmails, useSyncStatus } from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useAuth } from '@/features/auth/AuthContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { formatTime } from '@/lib/format';
import { api } from '@/lib/api';

const GMAIL_ERROR_MESSAGES: Record<string, string> = {
  access_denied: 'Gmail access was not connected. Your PFIS workspace is still available.',
  consent_required: 'Gmail permission was not completed. You can try connecting again.',
  missing_code: 'Google did not return a connection code. Try connecting Gmail again.',
  gmail_scope_required:
    'Read-only Gmail permission is required to sync your inbox. Try connecting again and approve it.',
  gmail_account_conflict: 'This Gmail account could not be connected to this workspace.',
  gmail_account_mismatch:
    'A different Gmail account is already connected. Reconnect the existing account instead.',
  gmail_identity_invalid: 'Google could not verify the Gmail account. Try connecting again.',
  gmail_connection_forbidden:
    'Gmail connection was not allowed. Try again or contact your administrator.',
  provider_unavailable: 'Google is temporarily unavailable. Try connecting Gmail again shortly.',
  provider_rejected: 'Google did not complete the Gmail connection. You can try again.',
  gmail_connection_failed: 'PFIS could not complete the Gmail connection. Try again.',
};

type GmailNotice = { kind: 'success' | 'error'; message: string };

export function InboxSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const emails = useEmails();
  const syncStatus = useSyncStatus();
  const autoSync = useAutoSyncStatus();
  const { running, liveConnected, retrySync } = useSync();
  const { scrollTo } = useDashboardUi();
  const [notice, setNotice] = useState<GmailNotice | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const authResult = params.get('gmail_auth');
    const errorCode = params.get('gmail_error');

    if (authResult === 'success') {
      setNotice({ kind: 'success', message: 'Gmail is connected. Your inbox is ready to sync.' });
    } else if (errorCode) {
      setNotice({
        kind: 'error',
        message: GMAIL_ERROR_MESSAGES[errorCode] ?? 'Gmail connection could not be completed.',
      });
    }

    if (authResult || errorCode) {
      params.delete('gmail_auth');
      params.delete('gmail_error');
      const query = params.toString();
      window.history.replaceState(
        {},
        '',
        `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`,
      );
    }
  }, []);

  const disconnected = !autoSync.isLoading && !autoSync.isError && autoSync.data === null;
  const needsReauthorization = autoSync.data?.connection_status === 'reauthorization_required';
  const connectionDescription = autoSync.isLoading
    ? 'Checking the connection for this workspace…'
    : autoSync.isError
      ? 'PFIS could not confirm the Gmail connection. Try again shortly.'
      : needsReauthorization
        ? 'Gmail needs permission again before automatic sync can resume.'
        : disconnected
          ? 'Connect a Gmail account to import financial emails. PFIS requests read-only access separately from sign-in.'
          : 'Gmail is connected to this workspace. PFIS stores provider tokens encrypted and keeps mailbox data owner-scoped.';
  const connectionLabel = autoSync.isLoading
    ? 'Checking'
    : autoSync.isError
      ? 'Unavailable'
      : needsReauthorization
        ? 'Reconnect needed'
        : disconnected
          ? 'Not connected'
          : 'Connected';
  const connectionActionLabel =
    needsReauthorization || autoSync.data ? 'Reconnect Gmail' : 'Connect Gmail';

  const latest = syncStatus.data?.latest_status;
  const statusVariant =
    latest === 'completed'
      ? 'success'
      : latest === 'failed'
        ? 'danger'
        : latest === 'running'
          ? 'info'
          : 'default';

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Inbox"
          title="Email sync"
          description="Financial emails ingested and processed into transactions."
          action={
            <div className="flex items-center gap-2">
              <Badge variant={statusVariant}>{latest ? `Latest: ${latest}` : 'No sync yet'}</Badge>
              <Badge variant={liveConnected ? 'success' : 'default'}>
                {liveConnected ? 'Live' : 'Fallback'}
              </Badge>
              <Button variant="outline" size="sm" onClick={retrySync} disabled={running}>
                <RefreshCw
                  aria-hidden="true"
                  className={`mr-1 h-3.5 w-3.5 ${running ? 'animate-spin' : ''}`}
                />
                Retry
              </Button>
            </div>
          }
        />
      ) : null}

      {notice ? (
        <div
          role={notice.kind === 'error' ? 'alert' : 'status'}
          aria-live="polite"
          className={`mb-4 flex items-start gap-3 rounded-xl p-3.5 text-sm leading-5 ring-1 ${
            notice.kind === 'error'
              ? 'bg-danger/10 text-danger ring-danger/25'
              : 'bg-success/10 text-success ring-success/25'
          }`}
        >
          {notice.kind === 'error' ? (
            <AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <CheckCircle2 aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          <span>{notice.message}</span>
        </div>
      ) : null}

      <Card className="mb-4">
        <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
          <div className="flex min-w-0 items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
              <ShieldCheck aria-hidden="true" className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-bold">Gmail connection</h3>
                <Badge
                  variant={
                    needsReauthorization
                      ? 'warning'
                      : disconnected || autoSync.isError
                        ? 'default'
                        : 'success'
                  }
                >
                  {connectionLabel}
                </Badge>
              </div>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                {connectionDescription}
              </p>
            </div>
          </div>
          {user ? (
            <a
              href={api.gmailConnectUrl(user.id)}
              className="focus-ring inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-bold text-primary-foreground shadow-lift transition-[background-color,box-shadow,transform] duration-150 hover:bg-primary/90 active:translate-y-px"
            >
              {needsReauthorization ? (
                <RefreshCw aria-hidden="true" className="h-4 w-4" />
              ) : (
                <Mail aria-hidden="true" className="h-4 w-4" />
              )}
              {connectionActionLabel}
            </a>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardContent className="p-4 sm:p-5">
            <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted-foreground">
                {emails.data
                  ? `${emails.data.all_total} synced · ${emails.data.processed_total} processed · ${emails.data.unprocessed_total} waiting`
                  : 'Loading…'}
              </p>
              <Button variant="link" size="sm" onClick={() => scrollTo('transactions')}>
                Open transactions <ArrowRight aria-hidden="true" className="ml-1 h-3.5 w-3.5" />
              </Button>
            </div>

            {emails.isLoading ? (
              <div className="grid gap-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-16" />
                ))}
              </div>
            ) : !emails.data?.emails.length ? (
              <EmptyState
                icon={<Mail aria-hidden="true" />}
                title={disconnected ? 'Connect Gmail to start syncing' : 'No emails yet'}
                description={
                  disconnected
                    ? 'Connect your Gmail account to bring financial emails into this workspace.'
                    : 'Run a sync to ingest your financial emails.'
                }
                action={
                  disconnected && user ? (
                    <a
                      href={api.gmailConnectUrl(user.id)}
                      className="focus-ring inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-bold text-primary-foreground shadow-lift hover:bg-primary/90"
                    >
                      <Mail aria-hidden="true" className="h-4 w-4" />
                      Connect Gmail
                    </a>
                  ) : undefined
                }
              />
            ) : (
              <div className="grid max-h-[28rem] gap-2 overflow-y-auto pr-1">
                {emails.data.emails.map((email, i) => (
                  <div
                    key={email.id ?? i}
                    className={`rounded-lg border border-l-4 border-border bg-card p-3 transition-colors hover:bg-muted/30 ${
                      email.processed ? 'border-l-success' : 'border-l-warning'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="line-clamp-1 text-sm font-semibold">
                        {email.subject || '(no subject)'}
                      </p>
                      <Badge variant={email.processed ? 'success' : 'warning'}>
                        {email.processed ? 'Processed' : 'Waiting'}
                      </Badge>
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                      {email.sender} · {formatTime(email.received_at)}
                    </p>
                    {email.body_preview && (
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground/80">
                        {email.body_preview}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="grid gap-3 p-4 sm:p-5">
            <h3 className="font-bold">Sync overview</h3>
            <div className="grid grid-cols-2 gap-2">
              <Tile label="Synced" value={emails.data?.all_total ?? 0} />
              <Tile label="Processed" value={emails.data?.processed_total ?? 0} />
              <Tile label="Waiting" value={emails.data?.unprocessed_total ?? 0} />
              <Tile label="Runs" value={syncStatus.data?.runs.length ?? 0} />
            </div>
            <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
              {needsReauthorization
                ? 'Gmail needs to be reconnected before automatic sync can resume.'
                : disconnected
                  ? 'Connect Gmail to enable inbox sync and automatic processing.'
                  : autoSync.data?.enabled
                    ? `Auto-sync is ${autoSync.data.status} every ${Math.round(autoSync.data.interval_seconds / 60)} minute(s).`
                    : emails.data?.unprocessed_total
                      ? `${emails.data.unprocessed_total} email(s) are waiting to be processed into transactions.`
                      : 'All synced emails have been processed.'}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-muted/35 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-bold">{value}</p>
    </div>
  );
}
