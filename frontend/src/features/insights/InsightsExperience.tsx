import { lazy, Suspense } from 'react';
import { ArrowUpRight, Sparkles } from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Tabs } from '@/components/ui/Tabs';
import { useSummary } from '@/features/workspace/queries';

const InsightsSection = lazy(() =>
  import('@/features/insights/InsightsSection').then((module) => ({
    default: module.InsightsSection,
  })),
);
const CategoryIntelligenceSection = lazy(() =>
  import('@/features/categories/CategoryIntelligenceSection').then((module) => ({
    default: module.CategoryIntelligenceSection,
  })),
);
const MerchantIntelligenceSection = lazy(() =>
  import('@/features/merchants/MerchantIntelligenceSection').then((module) => ({
    default: module.MerchantIntelligenceSection,
  })),
);

type InsightsView = 'insights' | 'categories' | 'merchants';

export function InsightsExperience() {
  const { activeSection, scrollTo } = useDashboardUi();
  const summary = useSummary();
  const view: InsightsView =
    activeSection === 'categories' || activeSection === 'merchants' ? activeSection : 'insights';
  const leadingCategory = summary.data?.category_breakdown?.[0];

  return (
    <div className="space-y-8">
      <PageIntro
        eyebrow="Insights"
        title="See what is really driving the month."
        description="Move from totals to causes: the categories, merchants, days, and recurring patterns behind your position."
        action={
          <div className="flex flex-wrap items-center gap-2">
            {leadingCategory ? (
              <Badge variant="info">
                <Sparkles className="h-3.5 w-3.5" /> Leading: {leadingCategory.name}
              </Badge>
            ) : null}
            <Button variant="outline" onClick={() => scrollTo('transactions')}>
              Open ledger <ArrowUpRight className="h-4 w-4" />
            </Button>
          </div>
        }
      />

      <Tabs
        ariaLabel="Insight views"
        value={view}
        onValueChange={(value) => scrollTo(value)}
        options={[
          { value: 'insights', label: 'Drivers' },
          { value: 'categories', label: 'Categories' },
          { value: 'merchants', label: 'Merchants' },
        ]}
        className="max-w-max"
      />

      <div id={view} className="animate-fade-in scroll-mt-28">
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
