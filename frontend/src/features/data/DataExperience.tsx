import { Suspense } from 'react';
import { Link2, RefreshCw, SlidersHorizontal, Wifi } from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro, WorkspaceContextBar } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Tabs } from '@/components/ui/Tabs';
import { useSync } from '@/features/workspace/SyncContext';
import { useAutoSyncStatus, useSyncStatus } from '@/features/workspace/queries';
import { ApiError } from '@/lib/api';
import { lazyWithRetry } from '@/lib/lazyWithRetry';
import { AccountDeletionSettings } from './AccountDeletionSettings';
import { DataExportSettings } from './DataExportSettings';
import { FinancialDaySettings } from './FinancialDaySettings';
import { IntelligenceReadinessPanel } from './IntelligenceReadinessPanel';
import { OperationalStatusCard } from './OperationalStatusCard';
import { RawEmailRetentionSettings } from './RawEmailRetentionSettings';
import { ProductBoundaryCard } from './ProductBoundaryCard';
import { TemporalHistoryBackfillSettings } from './TemporalHistoryBackfillSettings';

const InboxSection = lazyWithRetry(
  () =>
    import('@/features/inbox/InboxSection').then((module) => ({ default: module.InboxSection })),
  'data-inbox',
);
const PipelineHealthSection = lazyWithRetry(
  () =>
    import('@/features/pipeline/PipelineHealthSection').then((module) => ({
      default: module.PipelineHealthSection,
    })),
  'data-pipeline',
);
const StatementImportSection = lazyWithRetry(
  () =>
    import('@/features/data/StatementImportSection').then((module) => ({
      default: module.StatementImportSection,
    })),
  'data-statements',
);

type DataView = 'inbox' | 'pipeline' | 'statements' | 'settings';

export function DataExperience() {
  const { activeSection, scrollTo, setCustomizeOpen } = useDashboardUi();
  const { running, liveConnected, runSync, gmailConnectUrl } = useSync();
  const status = useSyncStatus();
  const autoSync = useAutoSyncStatus();
  const view: DataView =
    activeSection === 'pipeline' || activeSection === 'statements' || activeSection === 'settings'
      ? activeSection
      : 'inbox';
  const requiresReconnect = autoSync.data?.status === 'paused' && Boolean(autoSync.data.error);
  const disconnected = autoSync.error instanceof ApiError && autoSync.error.status === 404;

  return (
    <div className="space-y-6">
      <PageIntro
        eyebrow="Data & settings"
        title="Know where every number came from."
        description="Manage connections, inspect processing health, recover failures, and tune your workspace."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={liveConnected ? 'success' : 'default'}>
              <Wifi aria-hidden="true" className="h-3.5 w-3.5" />{' '}
              {liveConnected ? 'Live updates' : 'Polling updates'}
            </Badge>
            <Button variant="outline" onClick={() => setCustomizeOpen(true)}>
              <SlidersHorizontal aria-hidden="true" className="h-4 w-4" /> Preferences
            </Button>
            {(requiresReconnect || disconnected) && gmailConnectUrl ? (
              <ButtonLink href={gmailConnectUrl}>
                <Link2 aria-hidden="true" className="h-4 w-4" />
                {requiresReconnect ? 'Reconnect Gmail' : 'Connect Gmail'}
              </ButtonLink>
            ) : (
              <Button onClick={runSync} disabled={running || autoSync.isLoading}>
                <RefreshCw
                  aria-hidden="true"
                  className={`h-4 w-4 ${running ? 'animate-spin' : ''}`}
                />
                {running ? 'Syncing' : 'Sync now'}
              </Button>
            )}
          </div>
        }
      />

      <WorkspaceContextBar label="Data views">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
          <Tabs
            ariaLabel="Data views"
            value={view}
            onValueChange={(value) => scrollTo(value)}
            options={[
              { value: 'inbox', label: 'Connections' },
              { value: 'statements', label: 'Statements' },
              { value: 'settings', label: 'Preferences & privacy' },
              { value: 'pipeline', label: 'Diagnostics' },
            ]}
            className="w-full max-w-full sm:w-auto sm:max-w-max"
          />
        </div>
      </WorkspaceContextBar>

      <div id={view} className="animate-fade-in scroll-mt-[10.5rem] lg:scroll-mt-[11.5rem]">
        <Suspense fallback={<DataSkeleton label={view} />}>
          {view === 'inbox' ? <InboxSection embedded /> : null}
          {view === 'pipeline' ? (
            <div className="space-y-6">
              <section
                aria-label="Latest diagnostic run"
                className="flex flex-col gap-2 rounded-xl border border-border/70 bg-card px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between sm:px-5"
              >
                <span className="font-extrabold">Diagnostics</span>
                <span className="text-muted-foreground">
                  {status.data?.latest_status
                    ? `Last run: ${status.data.latest_status}`
                    : 'No completed sync run yet'}
                </span>
              </section>
              <ProductBoundaryCard />
              <OperationalStatusCard onNavigate={scrollTo} />
              <IntelligenceReadinessPanel />
              <PipelineHealthSection embedded />
            </div>
          ) : null}
          {view === 'statements' ? <StatementImportSection /> : null}
          {view === 'settings' ? (
            <div className="space-y-6">
              <section aria-labelledby="preferences-title" className="space-y-4">
                <div>
                  <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
                    Preferences & privacy
                  </p>
                  <h2 id="preferences-title" className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
                    Tune the workspace and control your data.
                  </h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                    Everyday preferences stay separate from diagnostics. Export and deletion keep
                    their existing safeguards and confirmation steps.
                  </p>
                </div>
                <div className="grid gap-6 xl:grid-cols-2">
                  <FinancialDaySettings />
                  <RawEmailRetentionSettings />
                </div>
              </section>
              <section aria-labelledby="privacy-title" className="space-y-4">
                <div>
                  <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
                    Portability & deletion
                  </p>
                  <h2 id="privacy-title" className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
                    Keep control of your records.
                  </h2>
                </div>
                <div className="grid gap-6 xl:grid-cols-2">
                  <DataExportSettings />
                  <AccountDeletionSettings />
                </div>
              </section>
              <details className="rounded-xl border border-border/70 bg-card p-5 sm:p-6">
                <summary className="focus-ring cursor-pointer rounded text-base font-extrabold">
                  Advanced data maintenance
                </summary>
                <div className="mt-5">
                  <TemporalHistoryBackfillSettings />
                </div>
              </details>
            </div>
          ) : null}
        </Suspense>
      </div>
    </div>
  );
}

function DataSkeleton({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-label={`Loading ${label}`}
      className="h-80 animate-soft-pulse rounded-xl bg-muted"
    />
  );
}
