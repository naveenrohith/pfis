import { Suspense } from 'react';
import { HeartPulse, Plus } from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Tabs } from '@/components/ui/Tabs';
import { useWorkspaceSnapshot } from '@/features/workspace/queries';
import { lazyWithRetry } from '@/lib/lazyWithRetry';
import { cn } from '@/lib/utils';
import { TemporalEvidencePanel } from './TemporalEvidencePanel';
import {
  PLAN_STAGES,
  planStageForView,
  planViewFromSection,
  stageForId,
  type PlanStageId,
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
  const { activeSection, scrollTo, setQuickAddOpen } = useDashboardUi();
  const workspace = useWorkspaceSnapshot();
  const health = workspace.data?.financial_health;
  const view = planViewFromSection(activeSection);
  const stage = planStageForView(view);
  const stageDefinition = stageForId(stage);

  return (
    <div className="space-y-7">
      <PageIntro
        eyebrow="Plan"
        title="Decide what the money can safely do next."
        description="Follow the evidence in order: establish position, account for commitments, then choose the guardrails for what comes next."
        action={
          <div className="flex flex-wrap items-center gap-2">
            {health ? (
              <Badge variant={health.monthly_stability >= 70 ? 'success' : 'warning'}>
                <HeartPulse className="h-3.5 w-3.5" /> Stability {health.monthly_stability}
              </Badge>
            ) : null}
            <Button variant="outline" onClick={() => setQuickAddOpen(true)}>
              <Plus className="h-4 w-4" /> Record movement
            </Button>
          </div>
        }
      />

      <PlanningEquation />

      <div className="sticky top-[5.75rem] z-20 -mx-4 bg-background/95 px-4 py-2 backdrop-blur sm:-mx-6 sm:px-6 lg:top-[6.5rem] lg:-mx-10 lg:px-10">
        <Tabs
          ariaLabel="Planning decision stages"
          value={stage}
          onValueChange={(value) => {
            const destination = PLAN_STAGES.find((definition) => definition.id === value)?.destination;
            if (destination) scrollTo(destination);
          }}
          options={PLAN_STAGES.map(({ id, label }) => ({ value: id, label }))}
          className="w-full max-w-full sm:w-auto sm:max-w-max"
        />
      </div>

      <div id={view} className="animate-fade-in scroll-mt-[10.5rem] lg:scroll-mt-[11.5rem]">
        <PlanningStageContext
          stage={stage}
          stageDescription={stageDefinition.description}
          view={view}
          onNavigate={scrollTo}
        />
        <Suspense fallback={<PlanSkeleton label={view} />}>
          {view === 'cash-plan' ? (
            <>
              <FinancialPositionSection view="cash-plan" />
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

function PlanningEquation() {
  return (
    <section
      className="border-y border-border/70 py-4"
      aria-labelledby="planning-equation-title"
    >
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between lg:gap-8">
        <div className="min-w-0">
          <p
            id="planning-equation-title"
            className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground"
          >
            How PFIS builds the answer
          </p>
          <p className="mt-1 text-sm font-extrabold tracking-[-0.01em] sm:text-base">
            <span>Verified position</span>
            <span className="px-2 text-muted-foreground/60" aria-hidden="true">
              −
            </span>
            <span>confirmed commitments</span>
            <span className="px-2 text-muted-foreground/60" aria-hidden="true">
              −
            </span>
            <span>approved reserves</span>
            <span className="px-2 text-muted-foreground/60" aria-hidden="true">
              =
            </span>
            <span className="text-primary">safe to spend</span>
          </p>
        </div>
        <p className="max-w-md text-xs leading-5 text-muted-foreground lg:text-right">
          Every stage below answers one part of the same decision. Estimates stay labelled when
          evidence is incomplete.
        </p>
      </div>
    </section>
  );
}

type PlanningStageContextProps = {
  stage: PlanStageId;
  stageDescription: string;
  view: PlanView;
  onNavigate: (section: string) => void;
};

function PlanningStageContext({
  stage,
  stageDescription,
  view,
  onNavigate,
}: PlanningStageContextProps) {
  const tools =
    stage === 'commitments'
      ? [
          { id: 'obligations', label: 'Bills & safeguards' },
          { id: 'cards', label: 'Cards' },
          { id: 'liabilities', label: 'All liabilities' },
          { id: 'household', label: 'Household' },
        ]
      : stage === 'outlook'
        ? [
            { id: 'analytics', label: 'Forecast & scenarios' },
            { id: 'budgets', label: 'Budgets' },
          ]
        : [];

  return (
    <div className="mb-5 flex flex-col gap-3 border-b border-border/65 pb-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
          Current stage
        </p>
        <p className="mt-1 text-sm font-extrabold tracking-[-0.01em]">
          {stageForId(stage).label}
          <span className="ml-2 font-medium text-muted-foreground">{stageDescription}</span>
        </p>
      </div>
      {tools.length ? (
        <nav
          aria-label={`${stageForId(stage).label} views`}
          className="flex max-w-full flex-wrap items-center gap-1"
        >
          {tools.map((tool) => {
            const active = tool.id === view;
            return (
              <Button
                key={tool.id}
                type="button"
                size="sm"
                variant={active ? 'secondary' : 'ghost'}
                aria-current={active ? 'page' : undefined}
                className={cn('min-h-10 px-2.5 text-xs', !active && 'text-muted-foreground')}
                onClick={() => onNavigate(tool.id)}
              >
                {tool.label}
              </Button>
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
