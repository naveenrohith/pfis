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

      <ProductBoundaryCard />
      <OperationalStatusCard onNavigate={scrollTo} />

      <WorkspaceContextBar
        label="Data views"
        description="Connect, recover, and tune the evidence pipeline."
      >
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
          <Tabs
            ariaLabel="Data views"
            value={view}
            onValueChange={(value) => scrollTo(value)}
            options={[
              { value: 'inbox', label: 'Connections' },
              { value: 'statements', label: 'Statements' },
              { value: 'pipeline', label: 'Diagnostics' },
              { value: 'settings', label: 'Preferences & data' },
            ]}
            className="w-full max-w-full sm:w-auto sm:max-w-max"
          />
          <p className="px-1 text-xs text-muted-foreground sm:px-0">
            {status.data?.latest_status
              ? `Last run: ${status.data.latest_status}`
              : 'No completed sync run yet'}
          </p>
        </div>
      </WorkspaceContextBar>

      <div id={view} className="animate-fade-in scroll-mt-[10.5rem] lg:scroll-mt-[11.5rem]">
        <Suspense fallback={<DataSkeleton label={view} />}>
          {view === 'inbox' ? <InboxSection embedded /> : null}
          {view === 'pipeline' ? <PipelineHealthSection embedded /> : null}
          {view === 'statements' ? <StatementImportSection /> : null}
          {view === 'settings' ? (
            <div className="space-y-6">
              <IntelligenceReadinessPanel />
              <FinancialDaySettings />
              <RawEmailRetentionSettings />
              <TemporalHistoryBackfillSettings />
              <DataExportSettings />
              <AccountDeletionSettings />
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
