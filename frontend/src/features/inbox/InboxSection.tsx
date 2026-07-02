import { Mail, RefreshCw, ArrowRight } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useAutoSyncStatus, useEmails, useSyncStatus } from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { formatTime } from '@/lib/format';

export function InboxSection() {
  const emails = useEmails();
  const syncStatus = useSyncStatus();
  const autoSync = useAutoSyncStatus();
  const { running, liveConnected, retrySync } = useSync();
  const { scrollTo } = useDashboardUi();

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
              <RefreshCw className={`mr-1 h-3.5 w-3.5 ${running ? 'animate-spin' : ''}`} />
              Retry
            </Button>
          </div>
        }
      />

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
                Open transactions <ArrowRight className="ml-1 h-3.5 w-3.5" />
              </Button>
            </div>

            {emails.isLoading ? (
              <div className="grid gap-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-16" />
                ))}
              </div>
            ) : !emails.data?.emails.length ? (
              <EmptyState icon={<Mail />} title="No emails yet" description="Run a sync to ingest your financial emails." />
            ) : (
              <div className="grid max-h-[28rem] gap-2 overflow-y-auto pr-1">
                {emails.data.emails.map((email, i) => (
                  <div
                    key={email.id ?? i}
                    className={`rounded-lg border-l-4 border border-border bg-card p-3 transition-colors hover:bg-muted/30 ${
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
              {autoSync.data?.enabled
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
