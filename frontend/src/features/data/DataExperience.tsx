import { lazy, Suspense } from 'react';
import { RefreshCw, SlidersHorizontal, Wifi } from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Tabs } from '@/components/ui/Tabs';
import { useSync } from '@/features/workspace/SyncContext';
import { useSyncStatus } from '@/features/workspace/queries';

const InboxSection = lazy(() =>
  import('@/features/inbox/InboxSection').then((module) => ({ default: module.InboxSection })),
);
const PipelineHealthSection = lazy(() =>
  import('@/features/pipeline/PipelineHealthSection').then((module) => ({
    default: module.PipelineHealthSection,
  })),
);

type DataView = 'inbox' | 'pipeline';

export function DataExperience() {
  const { activeSection, scrollTo, setCustomizeOpen } = useDashboardUi();
  const { running, liveConnected, retrySync } = useSync();
  const status = useSyncStatus();
  const view: DataView = activeSection === 'pipeline' ? 'pipeline' : 'inbox';

  return (
    <div className="space-y-8">
      <PageIntro
        eyebrow="Data & settings"
        title="Know where every number came from."
        description="Manage connections, inspect processing health, recover failures, and tune your workspace."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={liveConnected ? 'success' : 'default'}>
              <Wifi className="h-3.5 w-3.5" /> {liveConnected ? 'Live connection' : 'Fallback mode'}
            </Badge>
            <Button variant="outline" onClick={() => setCustomizeOpen(true)}>
              <SlidersHorizontal className="h-4 w-4" /> Preferences
            </Button>
            <Button onClick={retrySync} disabled={running}>
              <RefreshCw className={`h-4 w-4 ${running ? 'animate-spin' : ''}`} />
              {running ? 'Syncing' : 'Sync now'}
            </Button>
          </div>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Tabs
          ariaLabel="Data views"
          value={view}
          onValueChange={(value) => scrollTo(value)}
          options={[
            { value: 'inbox', label: 'Connections' },
            { value: 'pipeline', label: 'Diagnostics' },
          ]}
          className="max-w-max"
        />
        <p className="text-xs text-muted-foreground">
          {status.data?.latest_status
            ? `Last run: ${status.data.latest_status}`
            : 'No completed sync run yet'}
        </p>
      </div>

      <div id={view} className="animate-fade-in scroll-mt-28">
        <Suspense fallback={<DataSkeleton label={view} />}>
          {view === 'inbox' ? <InboxSection embedded /> : null}
          {view === 'pipeline' ? <PipelineHealthSection embedded /> : null}
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
