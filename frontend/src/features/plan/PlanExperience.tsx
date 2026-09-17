import { Suspense } from 'react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro } from '@/components/system';
import { Tabs } from '@/components/ui/Tabs';
import { lazyWithRetry } from '@/lib/lazyWithRetry';
import { TemporalEvidencePanel } from './TemporalEvidencePanel';
import {
  PLAN_NAV_ITEMS,
  planNavigationForView,
  planSectionForNavigation,
  planViewFromSection,
  type PlanNavigationId,
  type PlanView,
} from './PlanModel';

const AnalyticsSection = lazyWithRetry(
  () =>
    import('@/features/analytics/AnalyticsSection').then((module) => ({
      default: module.AnalyticsSection,
    })),
  'plan-analytics',
);
const BudgetsSection = lazyWithRetry(
  () =>
    import('@/features/budgets/BudgetsSection').then((module) => ({
      default: module.BudgetsSection,
    })),
  'plan-budgets',
);
const NetWorthSection = lazyWithRetry(
  () =>
    import('@/features/accounts/NetWorthSection').then((module) => ({
      default: module.NetWorthSection,
    })),
  'plan-position',
);
const FinancialPositionSection = lazyWithRetry(
  () =>
    import('@/features/plan/FinancialPositionSection').then((module) => ({
      default: module.FinancialPositionSection,
    })),
  'plan-financial-position',
);
const CardsSection = lazyWithRetry(
  () => import('@/features/plan/CardsSection').then((module) => ({ default: module.CardsSection })),
  'plan-cards',
);
const RoadmapExtensionsSection = lazyWithRetry(
  () =>
    import('@/features/plan/RoadmapExtensionsSection').then((module) => ({
      default: module.RoadmapExtensionsSection,
    })),
  'plan-roadmap-extensions',
);

export function PlanExperience() {
  const { activeSection, scrollTo } = useDashboardUi();
  const view = planViewFromSection(activeSection);
  const navigation = planNavigationForView(view);

  return (
    <div className="space-y-7">
      <PageIntro
        eyebrow="Plan"
        title="Give the month a direction."
        description="Start with what is safe today, then move through position, cards, commitments, and the choices that shape what comes next."
      />

      <div className="sticky top-[5.75rem] z-20 -mx-4 bg-background/95 px-4 py-2 backdrop-blur sm:-mx-6 sm:px-6 lg:top-[6.5rem] lg:-mx-10 lg:px-10">
        <Tabs
          ariaLabel="Plan views"
          value={navigation}
          onValueChange={(value) => {
            if (PLAN_NAV_ITEMS.some((item) => item.id === value)) {
              scrollTo(planSectionForNavigation(value as PlanNavigationId));
            }
          }}
          options={PLAN_NAV_ITEMS.map(({ id, label }) => ({ value: id, label }))}
          className="w-full max-w-full sm:w-auto sm:max-w-max"
        />
      </div>

      <div id={view} className="animate-fade-in scroll-mt-[10.5rem] lg:scroll-mt-[11.5rem]">
        <PlanViewContext view={view} onNavigate={scrollTo} />
        <Suspense fallback={<PlanSkeleton label={view} />}>
          {view === 'cash-plan' ? (
            <>
              <FinancialPositionSection view="cash-plan" />
              <PlanningEquationDisclosure />
              <TemporalEvidencePanel />
            </>
          ) : null}
          {view === 'networth' ? <NetWorthSection embedded /> : null}
          {view === 'liabilities' || view === 'cards' ? (
            <DebtWorkspace view={view} />
          ) : null}
          {view === 'obligations' || view === 'household' ? (
            <RoadmapExtensionsSection view={view} />
          ) : null}
          {view === 'analytics' ? <AnalyticsSection embedded /> : null}
          {view === 'budgets' ? <BudgetsSection embedded /> : null}
        </Suspense>
      </div>
    </div>
  );
}

function PlanningEquationDisclosure() {
  return (
    <details className="border-t border-border/65 pt-4 text-sm">
      <summary className="focus-ring cursor-pointer rounded-md py-2 font-bold text-muted-foreground hover:text-foreground">
        How PFIS calculates safe to spend
      </summary>
      <div className="mt-3 flex flex-col gap-2 text-muted-foreground sm:flex-row sm:items-center sm:gap-3">
        <p className="font-extrabold text-foreground">
          Verified position − confirmed commitments − approved reserves = safe to spend
        </p>
        <p className="text-xs leading-5">
          Estimates stay labelled when evidence is incomplete.
        </p>
      </div>
    </details>
  );
}

type PlanViewContextProps = {
  view: PlanView;
  onNavigate: (section: string) => void;
};

function PlanViewContext({ view, onNavigate }: PlanViewContextProps) {
  const navigation = planNavigationForView(view);
  const commitmentDetails = [
    { id: 'obligations', label: 'Bills & safeguards' },
    { id: 'liabilities', label: 'All liabilities' },
    { id: 'household', label: 'Household' },
  ] as const;

  return (
    <div className="mb-5 flex flex-col gap-3 border-b border-border/65 pb-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
          Plan view
        </p>
        <p className="mt-1 text-sm font-extrabold tracking-[-0.01em]">
          {PLAN_NAV_ITEMS.find((item) => item.id === navigation)?.label}
          <span className="ml-2 font-medium text-muted-foreground">
            {navigation === 'obligations'
              ? 'Bills, liabilities, and household plans in one place.'
              : 'One decision surface, with supporting evidence below.'}
          </span>
        </p>
      </div>
      {navigation === 'obligations' ? (
        <nav
          aria-label="Commitment details"
          className="flex max-w-full flex-wrap items-center gap-1"
        >
          {commitmentDetails.map((detail) => {
            const active = detail.id === view;
            return (
              <button
                key={detail.id}
                type="button"
                aria-current={active ? 'page' : undefined}
                className={`focus-ring min-h-10 rounded-md px-2.5 text-xs font-bold transition-colors ${
                  active
                    ? 'bg-secondary text-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                }`}
                onClick={() => onNavigate(detail.id)}
              >
                {detail.label}
              </button>
            );
          })}
        </nav>
      ) : null}
    </div>
  );
}

function DebtWorkspace({ view }: { view: 'liabilities' | 'cards' }) {
  return view === 'cards' ? <CardsSection /> : <FinancialPositionSection view="liabilities" />;
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
