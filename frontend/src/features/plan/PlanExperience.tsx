import { Suspense } from 'react';
import { ArrowLeft, ChevronRight } from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro, WorkspaceContextBar } from '@/components/system';
import { Button } from '@/components/ui/Button';
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

const DETAIL_VIEWS = new Set<PlanView>(['cards', 'budgets', 'liabilities', 'household']);

const PAGE_COPY: Record<PlanView, { title: string; description: string }> = {
  'cash-plan': {
    title: 'Know what is safe before the next income.',
    description: 'Use an observed balance, confirmed commitments, and a confirmed income date.',
  },
  networth: {
    title: 'Know what you own and owe.',
    description: 'Review dated account positions and the evidence behind each total.',
  },
  obligations: {
    title: 'Prepare for what is due next.',
    description: 'Review confirmed commitments and open the account detail that needs attention.',
  },
  analytics: {
    title: 'Look ahead with room to adjust.',
    description: 'Explore the month outlook, then preview changes before deciding.',
  },
  cards: {
    title: 'Card accounts',
    description: 'Review what is due, the current position, and the evidence behind each card.',
  },
  budgets: {
    title: 'Budgets and goals',
    description:
      'Adjust monthly guardrails and review progress without mixing them into today’s cash.',
  },
  liabilities: {
    title: 'All liabilities',
    description: 'Review current obligations and the evidence attached to each account.',
  },
  household: {
    title: 'Household plans',
    description: 'Coordinate shared commitments and settlements with their ownership context.',
  },
};

export function PlanExperience() {
  const { activeSection, scrollTo } = useDashboardUi();
  const view = planViewFromSection(activeSection);
  const navigation = planNavigationForView(view);
  const isDetail = DETAIL_VIEWS.has(view);
  const parentSection = planSectionForNavigation(navigation);
  const pageCopy = PAGE_COPY[view];

  return (
    <div className="space-y-6">
      {isDetail ? (
        <PlanBreadcrumb view={view} parentSection={parentSection} onNavigate={scrollTo} />
      ) : null}
      <PageIntro
        eyebrow={isDetail ? `Plan · ${navigationLabel(navigation)}` : 'Plan'}
        title={pageCopy.title}
        description={pageCopy.description}
        className={isDetail ? 'gap-2' : undefined}
      />

      {!isDetail ? (
        <WorkspaceContextBar label="Plan stages" className="sticky top-24 z-20 lg:top-[5.75rem]">
          <Tabs
            ariaLabel="Plan stages"
            value={navigation}
            onValueChange={(value) => {
              if (PLAN_NAV_ITEMS.some((item) => item.id === value)) {
                scrollTo(planSectionForNavigation(value as PlanNavigationId), 'push');
              }
            }}
            options={PLAN_NAV_ITEMS.map(({ id, label }) => ({ value: id, label }))}
            className="w-full max-w-full sm:w-auto sm:max-w-max"
          />
        </WorkspaceContextBar>
      ) : null}

      <div
        id={view === 'cards' ? 'plan-cards' : view}
        className="animate-fade-in scroll-mt-[8rem] lg:scroll-mt-[9rem]"
      >
        <Suspense fallback={<PlanSkeleton label={pageCopy.title} />}>
          {view === 'cash-plan' ? (
            <>
              <FinancialPositionSection view="cash-plan" />
              <PlanningEquationDisclosure />
            </>
          ) : null}
          {view === 'networth' ? <NetWorthSection embedded /> : null}
          {view === 'cards' ? <CardsSection anchorId="cards" hideIntro /> : null}
          {view === 'liabilities' ? <FinancialPositionSection view="liabilities" /> : null}
          {view === 'obligations' ? (
            <>
              <CommitmentDetailLinks onNavigate={(section) => scrollTo(section, 'push')} />
              <RoadmapExtensionsSection view="obligations" />
              <details className="border-t border-border/65 pt-3">
                <summary className="focus-ring cursor-pointer rounded-md py-2 text-sm font-bold">
                  Review dated events and follow-ups
                </summary>
                <div className="pt-3">
                  <TemporalEvidencePanel />
                </div>
              </details>
            </>
          ) : null}
          {view === 'household' ? <RoadmapExtensionsSection view="household" /> : null}
          {view === 'analytics' ? (
            <>
              <div className="mb-4 flex justify-end border-b border-border/65 pb-3">
                <Button type="button" variant="outline" onClick={() => scrollTo('budgets', 'push')}>
                  Budgets and spending limits{' '}
                  <ChevronRight aria-hidden="true" className="h-4 w-4" />
                </Button>
              </div>
              <AnalyticsSection embedded />
            </>
          ) : null}
          {view === 'budgets' ? <BudgetsSection embedded /> : null}
        </Suspense>
      </div>
    </div>
  );
}

function navigationLabel(navigation: PlanNavigationId) {
  return PLAN_NAV_ITEMS.find((item) => item.id === navigation)?.label ?? 'Plan';
}

function PlanBreadcrumb({
  view,
  parentSection,
  onNavigate,
}: {
  view: PlanView;
  parentSection: string;
  onNavigate: (section: string) => void;
}) {
  const current = view === 'household' ? 'Household' : pageCopyForView(view);
  const parent = navigationLabel(planNavigationForView(view));

  return (
    <nav aria-label="Plan location" className="flex items-center gap-2 text-sm">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="-ml-2 min-h-11 px-2 text-muted-foreground"
        onClick={() => onNavigate(parentSection)}
      >
        <ArrowLeft aria-hidden="true" className="h-4 w-4" />
        Back to {parent}
      </Button>
      <ChevronRight aria-hidden="true" className="h-4 w-4 text-muted-foreground/70" />
      <span aria-current="page" className="font-bold text-foreground">
        {current}
      </span>
    </nav>
  );
}

function pageCopyForView(view: PlanView) {
  return view === 'cards' ? 'Cards' : view === 'budgets' ? 'Budgets' : 'All liabilities';
}

function CommitmentDetailLinks({ onNavigate }: { onNavigate: (section: string) => void }) {
  return (
    <nav
      aria-label="More commitment detail"
      className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border/65 pb-4"
    >
      <Button type="button" variant="outline" size="sm" onClick={() => onNavigate('cards')}>
        Card accounts <ChevronRight aria-hidden="true" className="h-4 w-4" />
      </Button>
      <details className="relative">
        <summary className="focus-ring flex min-h-11 cursor-pointer list-none items-center rounded-md px-2 text-sm font-bold text-muted-foreground hover:text-foreground">
          More commitment views
        </summary>
        <div className="absolute left-0 top-full z-20 mt-1 grid min-w-48 rounded-lg border border-border bg-card p-1 shadow-lift">
          <button
            type="button"
            className="focus-ring min-h-11 rounded px-3 text-left text-sm hover:bg-muted"
            onClick={() => onNavigate('liabilities')}
          >
            All liabilities
          </button>
          <button
            type="button"
            className="focus-ring min-h-11 rounded px-3 text-left text-sm hover:bg-muted"
            onClick={() => onNavigate('household')}
          >
            Household plans
          </button>
        </div>
      </details>
    </nav>
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
          Observed position − confirmed commitments − approved reserves = safe to spend
        </p>
        <p className="text-xs leading-5">Estimates stay labelled when evidence is incomplete.</p>
      </div>
    </details>
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
