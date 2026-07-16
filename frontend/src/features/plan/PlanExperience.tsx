import { lazy, Suspense } from 'react';
import { HeartPulse, Plus } from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Tabs } from '@/components/ui/Tabs';
import { useWorkspaceSnapshot } from '@/features/workspace/queries';

const AnalyticsSection = lazy(() =>
  import('@/features/analytics/AnalyticsSection').then((module) => ({
    default: module.AnalyticsSection,
  })),
);
const BudgetsSection = lazy(() =>
  import('@/features/budgets/BudgetsSection').then((module) => ({
    default: module.BudgetsSection,
  })),
);
const NetWorthSection = lazy(() =>
  import('@/features/accounts/NetWorthSection').then((module) => ({
    default: module.NetWorthSection,
  })),
);

type PlanView = 'analytics' | 'networth' | 'budgets';

export function PlanExperience() {
  const { activeSection, scrollTo, setQuickAddOpen } = useDashboardUi();
  const workspace = useWorkspaceSnapshot();
  const health = workspace.data?.financial_health;
  const view: PlanView =
    activeSection === 'networth' || activeSection === 'budgets' ? activeSection : 'analytics';

  return (
    <div className="space-y-8">
      <PageIntro
        eyebrow="Plan"
        title="Give the month a direction."
        description="Turn your current position into a practical outlook, guardrails, and goals you can act on."
        action={
          <div className="flex flex-wrap items-center gap-2">
            {health ? (
              <Badge variant={health.monthly_stability >= 70 ? 'success' : 'warning'}>
                <HeartPulse className="h-3.5 w-3.5" /> Stability {health.monthly_stability}
              </Badge>
            ) : null}
            <Button variant="outline" onClick={() => setQuickAddOpen(true)}>
              <Plus className="h-4 w-4" /> Add movement
            </Button>
          </div>
        }
      />

      <Tabs
        ariaLabel="Plan views"
        value={view}
        onValueChange={(value) => scrollTo(value)}
        options={[
          { value: 'analytics', label: 'Outlook & goals' },
          { value: 'networth', label: 'Position' },
          { value: 'budgets', label: 'Budgets' },
        ]}
        className="max-w-max"
      />

      <div id={view} className="animate-fade-in scroll-mt-28">
        <Suspense fallback={<PlanSkeleton label={view} />}>
          {view === 'analytics' ? <AnalyticsSection embedded /> : null}
          {view === 'networth' ? <NetWorthSection embedded /> : null}
          {view === 'budgets' ? <BudgetsSection embedded /> : null}
        </Suspense>
      </div>
    </div>
  );
}

function PlanSkeleton({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-label={`Loading ${label}`}
      className="h-80 animate-soft-pulse rounded-xl bg-muted"
    />
  );
}
