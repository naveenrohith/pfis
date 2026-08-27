import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, Link2, Mail, RefreshCw } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { useToast } from '@/components/ui/Toast';
import { SectionTitle } from '@/components/SectionTitle';
import { useAuth } from '@/features/auth/AuthContext';
import {
  queryKeys,
  useAutoSyncStatus,
  useEmails,
  useSyncStatus,
} from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { api, ApiError } from '@/lib/api';
import { formatTime } from '@/lib/format';

export function InboxSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const emails = useEmails();
  const syncStatus = useSyncStatus();
  const autoSync = useAutoSyncStatus();
  const { running, liveConnected, runSync, gmailConnectUrl } = useSync();
  const { scrollTo } = useDashboardUi();
  const [disconnectOpen, setDisconnectOpen] = useState(false);

  const latest = syncStatus.data?.latest_status;
  const disconnected =
    autoSync.error instanceof ApiError && autoSync.error.status === 404;
  const requiresReconnect = autoSync.data?.status === 'paused' && Boolean(autoSync.data.error);
  const statusVariant =
    latest === 'completed'
      ? 'success'
      : latest === 'failed'
        ? 'danger'
        : latest === 'running'
          ? 'info'
          : 'default';
  const disconnect = useMutation({
    mutationFn: () => api.disconnectGmail(user!.id),
    onSuccess: async (result) => {
      setDisconnectOpen(false);
      await queryClient.invalidateQueries({ queryKey: queryKeys.autoSyncStatus(user!.id) });
      if (result.provider_revocation === 'revoked') {
        notify('Gmail disconnected and provider access revoked', 'success');
      } else {
        notify(
          'Gmail disconnected locally. Review Google Account permissions because provider revocation could not be confirmed.',
          'error',
        );
      }
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

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
                {liveConnected ? 'Live updates' : 'Polling updates'}
              </Badge>
              {(requiresReconnect || disconnected) && gmailConnectUrl ? (
                <ButtonLink variant="outline" size="sm" href={gmailConnectUrl}>
                  <Link2 aria-hidden="true" className="mr-1 h-3.5 w-3.5" />
                  {requiresReconnect ? 'Reconnect Gmail' : 'Connect Gmail'}
                </ButtonLink>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={runSync}
                  disabled={running || autoSync.isLoading}
                >
                  <RefreshCw
                    aria-hidden="true"
                    className={`mr-1 h-3.5 w-3.5 ${running ? 'animate-spin' : ''}`}
                  />
                  {running ? 'Syncing' : 'Sync now'}
                </Button>
              )}
            </div>
          }
        />
      ) : null}

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
                icon={<Mail />}
                title="No emails yet"
                description="Run a sync to ingest your financial emails."
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
            <div
              className={`rounded-lg border p-3 text-sm ${
                requiresReconnect
                  ? 'border-warning/30 bg-warning/10 text-foreground'
                  : 'border-border bg-muted/40 text-muted-foreground'
              }`}
              role={requiresReconnect ? 'alert' : undefined}
            >
              {requiresReconnect ? (
                <span className="flex items-start gap-2">
                  <AlertTriangle
                    aria-hidden="true"
                    className="mt-0.5 h-4 w-4 shrink-0 text-warning"
                  />
                  <span>
                    Gmail access needs to be renewed once. After reconnecting, PFIS resumes
                    automatic sync every {Math.round((autoSync.data?.interval_seconds ?? 300) / 60)}{' '}
                    minutes.
                  </span>
                </span>
              ) : autoSync.data?.enabled ? (
                `Auto-sync is ${autoSync.data.status} every ${Math.round(autoSync.data.interval_seconds / 60)} minute(s).`
              ) : emails.data?.unprocessed_total ? (
                `${emails.data.unprocessed_total} email(s) are waiting to be processed into transactions.`
              ) : (
                'All synced emails have been processed.'
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {autoSync.data ? (
                <Button variant="danger" size="sm" onClick={() => setDisconnectOpen(true)}>
                  Disconnect Gmail
                </Button>
              ) : disconnected && gmailConnectUrl ? (
                <ButtonLink variant="outline" size="sm" href={gmailConnectUrl}>
                  <Link2 aria-hidden="true" className="h-3.5 w-3.5" />
                  Connect Gmail
                </ButtonLink>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>
      <Dialog
        open={disconnectOpen}
        onClose={() => {
          if (!disconnect.isPending) setDisconnectOpen(false);
        }}
        title="Disconnect Gmail?"
        description="PFIS will stop future inbox access and ask Google to revoke the grant."
      >
        <p className="text-sm leading-6 text-muted-foreground">
          Already synced emails, transactions, and their evidence stay in PFIS. You can manage
          those records separately from this connection.
        </p>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button
            data-dialog-initial-focus
            variant="ghost"
            onClick={() => setDisconnectOpen(false)}
            disabled={disconnect.isPending}
          >
            Keep connected
          </Button>
          <Button
            variant="danger"
            onClick={() => disconnect.mutate()}
            disabled={disconnect.isPending}
          >
            {disconnect.isPending ? 'Disconnecting…' : 'Disconnect Gmail'}
          </Button>
        </div>
        {disconnect.error ? (
          <p role="alert" className="mt-3 text-sm font-bold text-danger">
            {disconnect.error.message}
          </p>
        ) : null}
      </Dialog>
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
