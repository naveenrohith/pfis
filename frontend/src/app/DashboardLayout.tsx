import { lazy, Suspense } from 'react';
import { Header } from './Header';
import { SectionNav } from './SectionNav';
import { DashboardUiProvider, useDashboardUi } from './DashboardUiContext';
import { TodayExperience } from '@/features/today/TodayExperience';
import { useDashboardPreferences } from '@/features/workspace/queries';
import { cn } from '@/lib/utils';

const QuickAddDialog = lazy(() =>
  import('@/features/transactions/QuickAddDialog').then((module) => ({
    default: module.QuickAddDialog,
  })),
);
const ActivityExperience = lazy(() =>
  import('@/features/activity/ActivityExperience').then((module) => ({
    default: module.ActivityExperience,
  })),
);
const PlanExperience = lazy(() =>
  import('@/features/plan/PlanExperience').then((module) => ({
    default: module.PlanExperience,
  })),
);
const InsightsExperience = lazy(() =>
  import('@/features/insights/InsightsExperience').then((module) => ({
    default: module.InsightsExperience,
  })),
);
const DataExperience = lazy(() =>
  import('@/features/data/DataExperience').then((module) => ({
    default: module.DataExperience,
  })),
);
const CustomizeDashboardDialog = lazy(() =>
  import('@/features/personalization/CustomizeDashboardDialog').then((module) => ({
    default: module.CustomizeDashboardDialog,
  })),
);
function DashboardWorkspace() {
  const { activeWorkspace, quickAddOpen, setQuickAddOpen, customizeOpen, setCustomizeOpen } =
    useDashboardUi();
  const preferences = useDashboardPreferences();

  return (
    <div
      className={cn(
        'grid min-h-screen bg-background lg:grid-cols-[88px_minmax(0,1fr)]',
        preferences.data?.density === 'compact' && 'dashboard-compact',
      )}
    >
      <a
        href="#workspace-content"
        className="sr-only z-50 rounded-md bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to workspace content
      </a>
      <SectionNav />
      <div className="min-w-0 pb-24 lg:pb-0">
        <Header />
        <main
          id="workspace-content"
          tabIndex={-1}
          className="mx-auto w-full max-w-[1320px] px-4 py-8 sm:px-6 lg:px-10 lg:py-12"
        >
          {activeWorkspace === 'today' ? (
            <section id="overview" className="animate-fade-in scroll-mt-24">
              <TodayExperience />
            </section>
          ) : activeWorkspace === 'activity' ? (
            <Suspense
              fallback={
                <div
                  role="status"
                  aria-label="Loading Activity"
                  className="h-96 animate-soft-pulse rounded-xl bg-muted"
                />
              }
            >
              <ActivityExperience />
            </Suspense>
          ) : (
            <Suspense
              fallback={
                <div
                  role="status"
                  aria-label={`Loading ${activeWorkspace}`}
                  className="h-96 animate-soft-pulse rounded-xl bg-muted"
                />
              }
            >
              {activeWorkspace === 'plan' ? <PlanExperience /> : null}
              {activeWorkspace === 'insights' ? <InsightsExperience /> : null}
              {activeWorkspace === 'data' ? <DataExperience /> : null}
            </Suspense>
          )}
        </main>
      </div>
      <Suspense fallback={null}>
        {quickAddOpen ? <QuickAddDialog open onClose={() => setQuickAddOpen(false)} /> : null}
        {customizeOpen ? (
          <CustomizeDashboardDialog open onClose={() => setCustomizeOpen(false)} />
        ) : null}
      </Suspense>
    </div>
  );
}

export function DashboardLayout() {
  return (
    <DashboardUiProvider>
      <DashboardWorkspace />
    </DashboardUiProvider>
  );
}
