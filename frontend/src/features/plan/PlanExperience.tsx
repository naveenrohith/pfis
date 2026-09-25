import { Suspense, type ReactNode } from 'react';
import { ArrowRight, ChevronRight } from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { PageIntro, WorkspaceContextBar } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { useFinancialHorizon } from '@/features/workspace/queries';
import { lazyWithRetry } from '@/lib/lazyWithRetry';
import { formatCurrency, formatDate } from '@/lib/format';
import type { FinancialHorizonResponse } from '@/lib/types';
import { TemporalEvidencePanel } from './TemporalEvidencePanel';
import {
  PLAN_STAGES,
  planNavigationForView,
  planSectionForNavigation,
  planViewFromSection,
  type PlanNavigationId,
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

const STEP_COPY: Record<
  PlanStageId,
  {
    title: string;
    detailLabel: string;
    actionLabel: string;
    actionTarget: PlanView;
  }
> = {
  spend: {
    title: 'Can I spend?',
    detailLabel: 'Review Cash Plan readiness',
    actionLabel: 'Review Safe to spend',
    actionTarget: 'cash-plan',
  },
  stand: {
    title: 'Where do I stand?',
    detailLabel: 'Review position evidence',
    actionLabel: 'Review position',
    actionTarget: 'networth',
  },
  coming: {
    title: 'What’s coming?',
    detailLabel: 'Review commitments and dues',
    actionLabel: 'Review commitments',
    actionTarget: 'obligations',
  },
  change: {
    title: 'What could change?',
    detailLabel: 'Review outlook and scenarios',
    actionLabel: 'Review outlook',
    actionTarget: 'analytics',
  },
  protect: {
    title: 'Protect & plan',
    detailLabel: 'Review budgets, goals, and household plans',
    actionLabel: 'Review budgets and goals',
    actionTarget: 'budgets',
  },
};

export function PlanExperience() {
  const { activeSection, scrollTo } = useDashboardUi();
  const view = planViewFromSection(activeSection);
  const activeStage = planNavigationForView(view);
  const horizon = useFinancialHorizon(30);
  const stepStates = buildPlanStepStates(horizon.data, horizon.isLoading, horizon.isError);

  return (
    <div className="space-y-6">
      <PageIntro
        eyebrow="Plan"
        title="Move through the decision before opening the details."
        description="PFIS orders planning from safe-to-spend readiness through position, commitments, forecast, and protection so every panel answers the next financial question."
      />

      <WorkspaceContextBar label="Plan journey" className="sticky top-24 z-20 lg:top-[5.75rem]">
        <PlanStepNavigator
          activeStage={activeStage}
          onNavigate={(stage) => scrollTo(planSectionForNavigation(stage), 'push')}
        />
      </WorkspaceContextBar>

      <ol className="space-y-4" aria-label="Plan decision journey">
        {PLAN_STAGES.map((stage, index) => {
          const copy = STEP_COPY[stage.id];
          const state = stepStates[stage.id];
          const isOpen = isStageOpen(stage.id, view);
          return (
            <li key={stage.id}>
              <PlanJourneyStep
                stage={stage.id}
                stepNumber={index + 1}
                title={copy.title}
                description={stage.description}
                detailLabel={copy.detailLabel}
                headline={state.headline}
                badge={state.badge}
                isOpen={isOpen}
                action={
                  <Button
                    type="button"
                    variant={isOpen ? 'secondary' : 'outline'}
                    size="sm"
                    onClick={() => scrollTo(copy.actionTarget, 'push')}
                  >
                    {copy.actionLabel}
                    <ArrowRight aria-hidden="true" className="h-4 w-4" />
                  </Button>
                }
                onOpen={() => scrollTo(copy.actionTarget, 'push')}
              >
                <Suspense fallback={<PlanSkeleton label={copy.detailLabel} />}>
                  <PlanStepDetail stage={stage.id} view={view} onNavigate={scrollTo} />
                </Suspense>
              </PlanJourneyStep>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function PlanStepNavigator({
  activeStage,
  onNavigate,
}: {
  activeStage: PlanNavigationId;
  onNavigate: (stage: PlanNavigationId) => void;
}) {
  return (
    <nav aria-label="Plan decision steps" className="w-full">
      <ol className="grid grid-cols-2 gap-2 min-[360px]:grid-cols-5">
        {PLAN_STAGES.map((stage, index) => {
          const isActive = stage.id === activeStage;
          return (
            <li key={stage.id} className="min-w-0">
              <ButtonLink
                href={`#${stage.destination}`}
                aria-current={isActive ? 'step' : undefined}
                variant={isActive ? 'primary' : 'outline'}
                size="sm"
                className="w-full min-w-0 justify-start px-2 text-left min-[360px]:justify-center min-[360px]:text-center"
                onClick={(event) => {
                  event.preventDefault();
                  onNavigate(stage.id);
                }}
              >
                <span className="money-value shrink-0 text-[0.7rem] opacity-75">{index + 1}</span>
                <span className="truncate text-xs sm:hidden">{stage.shortLabel}</span>
                <span className="hidden truncate text-xs sm:inline">{stage.label}</span>
              </ButtonLink>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function PlanJourneyStep({
  stage,
  stepNumber,
  title,
  description,
  headline,
  badge,
  detailLabel,
  isOpen,
  action,
  onOpen,
  children,
}: {
  stage: PlanStageId;
  stepNumber: number;
  title: string;
  description: string;
  headline: string;
  badge: { label: string; variant: 'success' | 'warning' | 'danger' | 'info' | 'outline' };
  detailLabel: string;
  isOpen: boolean;
  action: ReactNode;
  onOpen: () => void;
  children: ReactNode;
}) {
  const titleId = `plan-step-${stage}-title`;
  return (
    <article
      id={stage === 'coming' ? 'obligations' : stage === 'protect' ? 'budgets' : undefined}
      className="scroll-mt-[8rem] rounded-2xl border border-border/70 bg-card/80 p-4 shadow-sm lg:scroll-mt-[9rem] sm:p-5"
      aria-labelledby={titleId}
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="money-value inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-xs font-extrabold text-primary">
              {stepNumber}
            </span>
            <h2 id={titleId} className="text-xl font-extrabold tracking-[-0.035em] text-pretty">
              {title}
            </h2>
            <Badge variant={badge.variant}>{badge.label}</Badge>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
          <p className="mt-3 max-w-3xl text-base font-extrabold leading-7 text-foreground">
            {headline}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 lg:justify-end">{action}</div>
      </div>

      <details
        open={isOpen}
        className="mt-4 border-t border-border/65 pt-3"
        onToggle={(event) => {
          if (event.currentTarget.open && !isOpen) onOpen();
        }}
      >
        <summary className="focus-ring flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 rounded-md py-2 text-sm font-bold text-muted-foreground hover:text-foreground">
          <span>{detailLabel}</span>
          <ChevronRight aria-hidden="true" className="h-4 w-4" />
        </summary>
        <div className="pt-4">{isOpen ? children : null}</div>
      </details>
    </article>
  );
}

function PlanStepDetail({
  stage,
  view,
  onNavigate,
}: {
  stage: PlanStageId;
  view: PlanView;
  onNavigate: (section: string, historyMode?: 'push' | 'replace') => void;
}) {
  if (stage === 'spend') {
    return (
      <div id="cash-plan" className="scroll-mt-[8rem] lg:scroll-mt-[9rem]">
        <FinancialPositionSection view="cash-plan" />
        <PlanningEquationDisclosure />
      </div>
    );
  }
  if (stage === 'stand') {
    return (
      <div id="networth" className="scroll-mt-[8rem] lg:scroll-mt-[9rem]">
        <NetWorthSection embedded />
      </div>
    );
  }
  if (stage === 'coming') {
    return <ComingDetails view={view} onNavigate={onNavigate} />;
  }
  if (stage === 'change') {
    return (
      <div id="analytics" className="scroll-mt-[8rem] lg:scroll-mt-[9rem]">
        <div className="mb-4 flex flex-wrap justify-end gap-2 border-b border-border/65 pb-3">
          <Button type="button" variant="outline" onClick={() => onNavigate('budgets', 'push')}>
            Budgets and spending limits <ChevronRight aria-hidden="true" className="h-4 w-4" />
          </Button>
        </div>
        <AnalyticsSection embedded />
      </div>
    );
  }
  return <ProtectDetails view={view} onNavigate={onNavigate} />;
}

function ComingDetails({
  view,
  onNavigate,
}: {
  view: PlanView;
  onNavigate: (section: string, historyMode?: 'push' | 'replace') => void;
}) {
  return (
    <div className="space-y-5">
      <CommitmentDetailLinks onNavigate={(section) => onNavigate(section, 'push')} />
      {view === 'cards' ? (
        <div id="cards" className="scroll-mt-[8rem] lg:scroll-mt-[9rem]">
          <CardsSection hideIntro />
        </div>
      ) : view === 'liabilities' ? (
        <div id="liabilities" className="scroll-mt-[8rem] lg:scroll-mt-[9rem]">
          <FinancialPositionSection view="liabilities" />
        </div>
      ) : (
        <>
          <RoadmapExtensionsSection view="obligations" />
          <details className="border-t border-border/65 pt-3">
            <summary className="focus-ring cursor-pointer rounded-md py-2 text-sm font-bold text-muted-foreground hover:text-foreground">
              Review dated events and follow-ups
            </summary>
            <div className="pt-3">
              <TemporalEvidencePanel />
            </div>
          </details>
        </>
      )}
    </div>
  );
}

function ProtectDetails({
  view,
  onNavigate,
}: {
  view: PlanView;
  onNavigate: (section: string, historyMode?: 'push' | 'replace') => void;
}) {
  return (
    <div className="space-y-5">
      <nav
        aria-label="Protection and planning details"
        className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border/65 pb-4"
      >
        <Button type="button" variant="outline" size="sm" onClick={() => onNavigate('analytics', 'push')}>
          Scenario outlook <ChevronRight aria-hidden="true" className="h-4 w-4" />
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => onNavigate('obligations', 'push')}>
          Payoff and safety checks <ChevronRight aria-hidden="true" className="h-4 w-4" />
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => onNavigate('household', 'push')}>
          Household plans <ChevronRight aria-hidden="true" className="h-4 w-4" />
        </Button>
      </nav>
      {view === 'household' ? (
        <div id="household" className="scroll-mt-[8rem] lg:scroll-mt-[9rem]">
          <RoadmapExtensionsSection view="household" />
        </div>
      ) : (
        <BudgetsSection embedded />
      )}
    </div>
  );
}

function CommitmentDetailLinks({ onNavigate }: { onNavigate: (section: string) => void }) {
  return (
    <nav
      aria-label="Commitment detail"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-border/65 pb-4"
    >
      <Button type="button" variant="outline" size="sm" onClick={() => onNavigate('cards')}>
        Card accounts <ChevronRight aria-hidden="true" className="h-4 w-4" />
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={() => onNavigate('liabilities')}>
        All liabilities <ChevronRight aria-hidden="true" className="h-4 w-4" />
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={() => onNavigate('obligations')}>
        Bills and subscriptions <ChevronRight aria-hidden="true" className="h-4 w-4" />
      </Button>
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

function buildPlanStepStates(
  horizon: FinancialHorizonResponse | undefined,
  loading: boolean,
  error: boolean,
): Record<PlanStageId, { headline: string; badge: { label: string; variant: 'success' | 'warning' | 'danger' | 'info' | 'outline' } }> {
  if (loading) {
    return {
      spend: loadingState('Checking Cash Plan readiness'),
      stand: loadingState('Checking position evidence'),
      coming: loadingState('Checking dated commitments'),
      change: loadingState('Checking forecast evidence'),
      protect: loadingState('Checking planning evidence'),
    };
  }
  if (error || !horizon) {
    return {
      spend: unavailableState('Safe-to-spend status is unavailable until the horizon refreshes.'),
      stand: unavailableState('Position status is unavailable until the horizon refreshes.'),
      coming: unavailableState('Upcoming commitments are unavailable until the horizon refreshes.'),
      change: unavailableState('Forecast status is unavailable until the horizon refreshes.'),
      protect: unavailableState('Planning evidence is unavailable until the horizon refreshes.'),
    };
  }

  const currency = horizon.current_position.currency;
  const safeToSpend = horizon.current_position.safe_to_spend;
  const readiness = humanizeReason(horizon.current_position.cash_plan_readiness ?? 'not_ready');
  const verifiedNet = horizon.current_position.verified.net;
  const provisionalNet = horizon.current_position.provisional.net;
  const firstEvent = horizon.events[0];
  const firstRisk = horizon.risk_signals[0];
  const staleSources = horizon.source_health.find((source) => source.status !== 'fresh');

  return {
    spend: {
      headline:
        safeToSpend == null
          ? `PFIS needs ${readiness} before it can name safe-to-spend money.`
          : `Safe-to-spend is ${formatCurrency(safeToSpend, currency)} on the server-owned Cash Plan basis.`,
      badge: statusBadge(horizon.status, safeToSpend == null ? 'Evidence needed' : 'Ready'),
    },
    stand: {
      headline: `Verified net position is ${formatCurrency(verifiedNet, currency)}; provisional position is ${formatCurrency(provisionalNet, currency)} until evidence settles.`,
      badge: horizon.current_position.account_count
        ? { label: `${horizon.current_position.account_count} accounts`, variant: 'info' }
        : { label: 'No accounts', variant: 'warning' },
    },
    coming: {
      headline: firstEvent
        ? `${firstEvent.label} is the next dated item on ${formatDate(firstEvent.date)}.`
        : 'No dated commitment, card due, or liability event is exposed for this horizon.',
      badge: horizon.events.length
        ? { label: `${horizon.events.length} dated`, variant: 'warning' }
        : { label: 'Clear', variant: 'success' },
    },
    change: {
      headline: horizon.lowest_projected_point
        ? `The forecast low point is ${formatCurrency(horizon.lowest_projected_point.expected_balance, currency)} on ${formatDate(horizon.lowest_projected_point.date)}.`
        : horizon.lowest_projected_point_unavailable_reason ||
          'PFIS needs more forecast evidence before naming what could change.',
      badge: statusBadge(horizon.status, horizonStatusLabel(horizon.status)),
    },
    protect: {
      headline: firstRisk
        ? `${firstRisk.label}: ${firstRisk.detail}`
        : staleSources
          ? `${sourceLabel(staleSources.source)} evidence is ${humanizeReason(staleSources.status)} and should be reviewed before relying on protection plans.`
          : horizon.missing_evidence[0]
            ? `PFIS still needs ${humanizeReason(horizon.missing_evidence[0])} to strengthen reserves, goals, scenarios, and payoff planning.`
            : 'Protection and planning evidence is current; review budgets, reserves, goals, and scenario choices before changing course.',
      badge: firstRisk
        ? { label: firstRisk.severity === 'danger' ? 'Risk' : 'Watch', variant: firstRisk.severity === 'danger' ? 'danger' : 'warning' }
        : { label: 'Plan ready', variant: 'success' },
    },
  };
}

function isStageOpen(stage: PlanStageId, view: PlanView) {
  return planNavigationForView(view) === stage;
}

function loadingState(label: string) {
  return { headline: `${label}.`, badge: { label: 'Loading…', variant: 'outline' as const } };
}

function unavailableState(headline: string) {
  return { headline, badge: { label: 'Unavailable', variant: 'warning' as const } };
}

function statusBadge(status: FinancialHorizonResponse['status'], readyLabel: string) {
  if (status === 'healthy') return { label: readyLabel, variant: 'success' as const };
  if (status === 'deficit') return { label: 'Deficit', variant: 'danger' as const };
  if (status === 'attention' || status === 'stale') return { label: 'Attention', variant: 'warning' as const };
  return { label: 'Evidence needed', variant: 'outline' as const };
}

function horizonStatusLabel(status: FinancialHorizonResponse['status']) {
  const labels: Record<FinancialHorizonResponse['status'], string> = {
    healthy: 'Clear',
    attention: 'Attention',
    deficit: 'Deficit',
    low_data: 'Evidence needed',
    stale: 'Stale evidence',
  };
  return labels[status];
}

function sourceLabel(source: string) {
  return humanizeReason(source);
}

function humanizeReason(reason: string) {
  return reason.replace(/[_-]+/g, ' ');
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
