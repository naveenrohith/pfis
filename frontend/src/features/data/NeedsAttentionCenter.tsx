import {
  AlertTriangle,
  CheckCircle2,
  FileSearch,
  Landmark,
  RefreshCw,
  Wifi,
  Wrench,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import {
  useAutoSyncStatus,
  useBalanceProviderStatus,
  useDepositStatementReviewItems,
  useOperationalHealth,
  useStatementAnalysisReviews,
  useSyncStatus,
} from '@/features/workspace/queries';
import { formatDate, formatTime } from '@/lib/format';

type AttentionSeverity = 'warning' | 'danger' | 'info';

interface AttentionItem {
  key: string;
  title: string;
  detail: string;
  severity: AttentionSeverity;
  action: ReactNode;
  icon: typeof AlertTriangle;
}

const STALE_SYNC_AFTER_MS = 24 * 60 * 60 * 1000;

const severityVariant: Record<AttentionSeverity, 'warning' | 'danger' | 'info'> = {
  warning: 'warning',
  danger: 'danger',
  info: 'info',
};

export function NeedsAttentionCenter({
  running,
  gmailConnectUrl,
  runSync,
  onNavigate,
}: {
  running: boolean;
  gmailConnectUrl: string | null;
  runSync: () => void;
  onNavigate: (target: string) => void;
}) {
  const syncStatus = useSyncStatus();
  const autoSync = useAutoSyncStatus();
  const statementReviews = useStatementAnalysisReviews();
  const depositReviews = useDepositStatementReviewItems();
  const providerStatus = useBalanceProviderStatus();
  const operationalHealth = useOperationalHealth();

  const items: AttentionItem[] = [];
  const auto = autoSync.data;
  const latestSyncStatus =
    syncStatus.data?.latest_status ?? syncStatus.data?.runs?.[0]?.status ?? undefined;

  if (autoSync.isSuccess && auto === null) {
    items.push({
      key: 'gmail-disconnected',
      title: 'Connect Gmail to restore automatic imports',
      detail: 'PFIS has no connected inbox source for new transaction emails.',
      severity: 'danger',
      icon: Wifi,
      action: gmailConnectUrl ? (
        <ButtonLink href={gmailConnectUrl} size="sm">
          Connect Gmail
        </ButtonLink>
      ) : (
        <Button size="sm" variant="outline" onClick={() => onNavigate('inbox')}>
          Review connections
        </Button>
      ),
    });
  } else if (auto?.status === 'paused' || auto?.connection_status === 'reauthorization_required') {
    items.push({
      key: 'gmail-reauthorize',
      title: 'Reconnect Gmail before the next sync',
      detail: auto.error || 'Google needs a fresh authorization before PFIS can import mail.',
      severity: 'danger',
      icon: Wifi,
      action: gmailConnectUrl ? (
        <ButtonLink href={gmailConnectUrl} size="sm">
          Reconnect Gmail
        </ButtonLink>
      ) : (
        <Button size="sm" variant="outline" onClick={() => onNavigate('inbox')}>
          Review connections
        </Button>
      ),
    });
  } else if (auto?.last_synced_at && isStale(auto.last_synced_at)) {
    items.push({
      key: 'sync-stale',
      title: 'Refresh stale inbox data',
      detail: `Last successful sync was ${formatDate(auto.last_synced_at)} at ${formatTime(
        auto.last_synced_at,
      )}.`,
      severity: 'warning',
      icon: RefreshCw,
      action: (
        <Button size="sm" onClick={runSync} disabled={running}>
          {running ? 'Syncing…' : 'Sync now'}
        </Button>
      ),
    });
  } else if (latestSyncStatus && ['failed', 'error'].includes(latestSyncStatus)) {
    items.push({
      key: 'sync-failed',
      title: 'Retry the latest sync',
      detail: 'The most recent inbox sync did not complete cleanly.',
      severity: 'warning',
      icon: RefreshCw,
      action: (
        <Button size="sm" onClick={runSync} disabled={running}>
          {running ? 'Syncing…' : 'Sync now'}
        </Button>
      ),
    });
  }

  const pendingStatementReviews =
    statementReviews.data?.filter((item) => item.status === 'pending_review').length ?? 0;
  if (pendingStatementReviews > 0) {
    items.push({
      key: 'statement-layout-review',
      title: 'Review saved statement layouts',
      detail: `${pendingStatementReviews} redacted statement ${
        pendingStatementReviews === 1 ? 'artifact needs' : 'artifacts need'
      } an explicit import decision.`,
      severity: 'warning',
      icon: FileSearch,
      action: (
        <Button size="sm" variant="outline" onClick={() => onNavigate('statements')}>
          Review statements
        </Button>
      ),
    });
  }

  const depositReviewCount = depositReviews.data?.length ?? 0;
  if (depositReviewCount > 0) {
    items.push({
      key: 'deposit-rail-review',
      title: 'Classify bank statement rows',
      detail: `${depositReviewCount} ${
        depositReviewCount === 1 ? 'row needs' : 'rows need'
      } a payment rail before import.`,
      severity: 'warning',
      icon: FileSearch,
      action: (
        <Button size="sm" variant="outline" onClick={() => onNavigate('statements')}>
          Review rows
        </Button>
      ),
    });
  }

  const provider = providerStatus.data;
  if (provider && provider.status !== 'ready') {
    items.push({
      key: 'provider-readiness',
      title: 'Check provider balance readiness',
      detail: provider.next_step || 'Provider evidence is not ready for account positions yet.',
      severity: provider.status === 'blocked' || provider.status === 'overdue' ? 'danger' : 'info',
      icon: Landmark,
      action: (
        <ButtonLink href="#networth" size="sm" variant="outline">
          Review accounts
        </ButtonLink>
      ),
    });
  }

  const health = operationalHealth.data;
  if (health && (health.status !== 'healthy' || health.data_warnings.length > 0)) {
    items.push({
      key: 'operational-health',
      title: health.status === 'needs_repair' ? 'Repair diagnostics' : 'Review data health notes',
      detail:
        health.status_reasons[0] ||
        health.data_warnings[0] ||
        'A diagnostic check needs attention.',
      severity: health.status === 'needs_repair' ? 'danger' : 'warning',
      icon: Wrench,
      action: (
        <Button size="sm" variant="outline" onClick={() => onNavigate('pipeline')}>
          Open diagnostics
        </Button>
      ),
    });
  }

  const loading =
    syncStatus.isLoading ||
    autoSync.isLoading ||
    statementReviews.isLoading ||
    depositReviews.isLoading ||
    providerStatus.isLoading ||
    operationalHealth.isLoading;

  return (
    <Card
      className="border border-border/70 shadow-sm"
      aria-labelledby="needs-attention-title"
      role="region"
    >
      <CardContent className="grid gap-4 p-5 sm:p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-warning">
              Recovery centre
            </p>
            <h2 id="needs-attention-title" className="mt-1 text-xl font-extrabold">
              Needs attention
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              One queue for source health, sync freshness, statement review, and provider
              readiness. Each item has a single recovery action.
            </p>
          </div>
          <Badge variant={items.length ? 'warning' : 'success'}>
            {items.length ? (
              <AlertTriangle aria-hidden="true" className="h-3.5 w-3.5" />
            ) : (
              <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />
            )}
            {items.length ? `${items.length} to review` : 'Clear'}
          </Badge>
        </div>

        {loading && items.length === 0 ? (
          <div role="status" aria-label="Checking recovery queue…" className="space-y-3">
            <div className="h-4 w-56 animate-soft-pulse rounded bg-muted" />
            <div className="h-16 animate-soft-pulse rounded-xl bg-muted/70" />
          </div>
        ) : items.length ? (
          <ul className="divide-y divide-border/65 rounded-xl border border-border/70">
            {items.map((item) => {
              const Icon = item.icon;
              return (
                <li
                  key={item.key}
                  className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="mt-0.5 rounded-lg bg-muted p-2 text-muted-foreground">
                      <Icon aria-hidden="true" className="h-4 w-4" />
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-extrabold">{item.title}</p>
                        <Badge variant={severityVariant[item.severity]}>{item.severity}</Badge>
                      </div>
                      <p className="mt-1 text-sm leading-5 text-muted-foreground">
                        {item.detail}
                      </p>
                    </div>
                  </div>
                  <div className="shrink-0">{item.action}</div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="rounded-xl border border-success/25 bg-success/[0.035] p-4 text-sm leading-6 text-muted-foreground">
            No recovery work is queued. Data sources, statements, and provider evidence are either
            healthy or not yet configured for this workspace.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function isStale(value: string): boolean {
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) && Date.now() - timestamp > STALE_SYNC_AFTER_MS;
}
