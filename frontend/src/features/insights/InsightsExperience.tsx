import { Suspense } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro, WorkspaceContextBar } from '@/components/system';
import { Button } from '@/components/ui/Button';
import { Tabs } from '@/components/ui/Tabs';
import { useSummary } from '@/features/workspace/queries';
import { lazyWithRetry } from '@/lib/lazyWithRetry';

const InsightsSection = lazyWithRetry(
  () =>
    import('@/features/insights/InsightsSection').then((module) => ({
      default: module.InsightsSection,
    })),
  'insights-overview',
);
const CategoryIntelligenceSection = lazyWithRetry(
  () =>
    import('@/features/categories/CategoryIntelligenceSection').then((module) => ({
      default: module.CategoryIntelligenceSection,
    })),
  'insights-categories',
);
const MerchantIntelligenceSection = lazyWithRetry(
  () =>
    import('@/features/merchants/MerchantIntelligenceSection').then((module) => ({
      default: module.MerchantIntelligenceSection,
    })),
  'insights-merchants',
);

type InsightsView = 'insights' | 'categories' | 'merchants';

export function InsightsExperience() {
  const { activeSection, scrollTo } = useDashboardUi();
  const summary = useSummary();
  const view: InsightsView =
    activeSection === 'categories' || activeSection === 'merchants' ? activeSection : 'insights';
  const leadingCategory = summary.data?.category_breakdown?.[0];

  return (
    <div className="space-y-6">
      <PageIntro
        eyebrow="Insights"
        title={leadingCategory ? `Start with ${leadingCategory.name}.` : 'See what is driving the month.'}
        description="Follow the largest measured driver to its ledger evidence, then review recurring and unusual patterns."
        action={
          <Button variant="outline" onClick={() => scrollTo('transactions')}>
            Open ledger <ArrowUpRight className="h-4 w-4" />
          </Button>
        }
      />

      <WorkspaceContextBar label="Insight views">
        <Tabs
          ariaLabel="Insight views"
          value={view}
          onValueChange={(value) => scrollTo(value)}
          options={[
            { value: 'insights', label: 'Drivers' },
            { value: 'categories', label: 'Categories' },
            { value: 'merchants', label: 'Merchants' },
          ]}
          className="w-full max-w-full sm:w-auto sm:max-w-max"
        />
      </WorkspaceContextBar>

      <div id={view} className="animate-fade-in scroll-mt-[10.5rem] lg:scroll-mt-[11.5rem]">
        <Suspense fallback={<InsightsSkeleton label={view} />}>
          {view === 'insights' ? <InsightsSection embedded /> : null}
          {view === 'categories' ? <CategoryIntelligenceSection embedded /> : null}
          {view === 'merchants' ? <MerchantIntelligenceSection embedded /> : null}
        </Suspense>
      </div>
    </div>
  );
}

function InsightsSkeleton({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-label={`Loading ${label}`}
      className="h-96 animate-soft-pulse rounded-xl bg-muted"
    />
  );
}
