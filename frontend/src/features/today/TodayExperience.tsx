import {
  ArrowRight,
  Check,
  CircleAlert,
  Clock3,
  RefreshCw,
  Sparkles,
  TrendingDown,
  TrendingUp,
  WalletCards,
  X,
} from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ActionSurface,
  FinancialHero,
  InsightSurface,
  PageIntro,
} from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useAuth } from '@/features/auth/AuthContext';
import { RecommendationFollowUp } from '@/features/guidance/RecommendationFollowUp';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { queryKeys, useCashPlan, useWorkspaceSnapshot } from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatCurrency, formatDate, formatTime } from '@/lib/format';
import type { CashPlan, RecommendationConsequence, RecommendationDecision } from '@/lib/types';
import { cn } from '@/lib/utils';
import { buildTodayBriefCopy } from './todayCopy';

export function TodayExperience() {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const { scrollTo } = useDashboardUi();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const workspace = useWorkspaceSnapshot();
  const cashPlan = useCashPlan();
  const decisions = useQuery({
    queryKey: ['guidance', 'decisions', user?.id ?? 'signed-out'],
    queryFn: () => api.guidanceDecisions(user!.id),
    enabled: Boolean(user),
  });
  const { liveConnected, running } = useSync();
  const updateRecommendation = useMutation({
    mutationFn: ({
      recommendationId,
      state,
    }: {
      recommendationId: string;
      state: 'accepted' | 'not_relevant' | 'snoozed';
    }) => {
      if (!user) throw new Error('Sign in to update guidance');
      const snoozedUntil =
        state === 'snoozed'
          ? new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
          : undefined;
      const asOf = `${year}-${String(month).padStart(2, '0')}-01`;
      return api.setGuidanceState(user.id, recommendationId, state, snoozedUntil, asOf);
    },
    onSuccess: (_, variables) => {
      if (user) {
        queryClient.invalidateQueries({ queryKey: queryKeys.workspace(user.id, month, year) });
        queryClient.invalidateQueries({ queryKey: ['guidance', 'decisions', user.id] });
      }
      notify(
        variables.state === 'accepted'
          ? 'Action added to your decisions'
          : variables.state === 'snoozed'
            ? 'Guidance snoozed for 7 days'
            : 'Marked as not relevant',
        'success',
      );
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  if (workspace.isLoading && !workspace.data) return <TodaySkeleton />;

  if (workspace.isError && !workspace.data) {
    return (
      <div className="space-y-8">
        <PageIntro
          eyebrow="Financial brief"
          title="Your financial story could not be loaded."
          description="PFIS kept your workspace intact. Retry the live summary or open Activity to inspect the source records."
        />
        <EmptyState
          icon={<CircleAlert className="h-5 w-5" />}
          title="The summary is temporarily unavailable"
          description={(workspace.error as Error).message}
          action={
            <Button onClick={() => void workspace.refetch()}>
              <RefreshCw className="h-4 w-4" /> Retry summary
            </Button>
          }
        />
      </div>
    );
  }

  const currency = user?.currency ?? 'INR';
  const data = workspace.data;
  const snapshot = data?.snapshot;
  const projection = data?.projection;
  const financialHealth = data?.financial_health;
  const monthComparison = data?.month_comparison;
  const name = firstName(user?.name || user?.email || 'there');
  const netCashFlow = snapshot?.net_cash_flow ?? 0;
  const spend = snapshot?.spend ?? 0;
  const previousNet = monthComparison
    ? monthComparison.previous_income - monthComparison.previous_spend
    : null;
  const netMovement = previousNet === null ? null : netCashFlow - previousNet;
  const hiddenRecommendationIds = new Set(
    (decisions.data ?? [])
      .filter((decision: RecommendationDecision) => {
        if (['accepted', 'dismissed', 'not_relevant'].includes(decision.state)) return true;
        return (
          decision.state === 'snoozed' &&
          Boolean(decision.snoozed_until) &&
          new Date(decision.snoozed_until!).getTime() > Date.now()
        );
      })
      .map((decision: RecommendationDecision) => decision.recommendation_id),
  );
  const primaryAction = data?.recommendations.find(
    (recommendation) => !hiddenRecommendationIds.has(recommendation.id),
  );
  const actionConflicts = primaryAction?.conflicts ?? [];
  const actionGoals = primaryAction?.goal_links ?? [];
  const actionResolution = primaryAction?.resolution;
  const actionTarget = primaryAction?.target ?? 'insights';
  const healthScore = financialHealth?.monthly_stability;
  const recurringBurden = financialHealth?.recurring_burden;
  const evidence = (data?.insights ?? []).slice(0, 2);
  const lowData = financialHealth?.data_sufficiency === 'low';
  const transactionCount = snapshot?.transaction_count ?? 0;

  const { headline, summary } = buildTodayBriefCopy({
    transactionCount,
    netCashFlow,
    name,
    currency,
    recommendationTitle: primaryAction?.title,
  });

  return (
    <div className="space-y-8">
      <PageIntro
        eyebrow={`${greeting(user?.timezone ?? 'Asia/Kolkata')} · Financial brief`}
        title={
          lowData ? (
            headline
          ) : (
            <>
              {headline}{' '}
              <span className={netCashFlow >= 0 ? 'text-success' : 'text-coral'}>
                {netCashFlow >= 0 ? 'Your buffer is growing.' : 'Your spending is running ahead.'}
              </span>
            </>
          )
        }
        description={summary}
        action={
          <Badge variant={liveConnected ? 'success' : 'outline'}>
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                liveConnected ? 'bg-success' : 'bg-muted-foreground',
              )}
            />
            {running ? 'Syncing' : liveConnected ? 'Live' : 'Saved snapshot'}
          </Badge>
        }
      />

      {lowData ? (
        <div className="flex items-start gap-3 rounded-xl border border-warning/20 bg-warning/10 px-4 py-3 text-sm">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <div>
            <p className="font-extrabold">This brief has limited evidence</p>
            <p className="mt-1 text-muted-foreground">
              PFIS found fewer than three transactions in this period. Trends and recommendations
              will become more reliable as activity arrives.
            </p>
          </div>
        </div>
      ) : null}

      <div
        id="recommendations"
        className="grid scroll-mt-24 gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,.65fr)]"
      >
        <FinancialHero>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm text-muted-foreground">Net cash flow</p>
              <p
                className={cn(
                  'money-value mt-1 text-4xl sm:text-5xl lg:text-6xl',
                  netCashFlow < 0 && 'text-danger',
                )}
              >
                {formatCurrency(netCashFlow, currency)}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                {netMovement === null
                  ? `${snapshot?.transaction_count ?? 0} tracked transactions this month`
                  : netMovement === 0
                    ? 'Unchanged from last month'
                    : `${formatCurrency(Math.abs(netMovement), currency)} ${
                        netMovement >= 0 ? 'better' : 'lower'
                      } than last month`}
              </p>
            </div>
            {healthScore !== undefined ? (
              <div className="text-right">
                <p className="text-xs text-muted-foreground">Monthly stability</p>
                <p
                  className={cn(
                    'money-value mt-1 text-3xl',
                    healthScore >= 70
                      ? 'text-success'
                      : healthScore >= 45
                        ? 'text-warning'
                        : 'text-danger',
                  )}
                >
                  {Math.round(healthScore)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Data confidence {financialHealth?.data_confidence ?? 0}
                </p>
              </div>
            ) : null}
          </div>
          <FinancialHorizon
            plan={cashPlan.data}
            loading={cashPlan.isLoading}
            onComplete={() => scrollTo('cash-plan')}
          />
        </FinancialHero>

        <ActionSurface
          icon={<Sparkles className="h-4 w-4" />}
          title={primaryAction?.title ?? 'Explore the drivers behind this month'}
          description={
            primaryAction?.description ??
            'PFIS has no urgent action for this period. Review the evidence and keep your data current.'
          }
          actionLabel={primaryAction?.action_label ?? 'Open insights'}
          onAction={() => scrollTo(actionTarget)}
          secondary={
            primaryAction?.expected_impact ||
            (primaryAction?.reason_codes?.length
              ? `Based on ${primaryAction.reason_codes.length} verified signal${primaryAction.reason_codes.length === 1 ? '' : 's'}`
              : 'Based on your selected month')
          }
          footer={
            primaryAction && !decisions.isLoading ? (
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={
                    updateRecommendation.isPending || actionResolution?.status === 'blocked'
                  }
                  onClick={() =>
                    updateRecommendation.mutate({
                      recommendationId: primaryAction.id,
                      state: 'accepted',
                    })
                  }
                >
                  <Check aria-hidden="true" className="h-3.5 w-3.5" /> Use this action
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-background hover:bg-background/10"
                  disabled={updateRecommendation.isPending}
                  aria-label={`Snooze ${primaryAction.title} for 7 days`}
                  onClick={() =>
                    updateRecommendation.mutate({
                      recommendationId: primaryAction.id,
                      state: 'snoozed',
                    })
                  }
                >
                  <Clock3 aria-hidden="true" className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-background hover:bg-background/10"
                  disabled={updateRecommendation.isPending}
                  aria-label={`Mark ${primaryAction.title} as not relevant`}
                  onClick={() =>
                    updateRecommendation.mutate({
                      recommendationId: primaryAction.id,
                      state: 'not_relevant',
                    })
                  }
                >
                  <X aria-hidden="true" className="h-3.5 w-3.5" />
                </Button>
              </div>
            ) : undefined
          }
        />
      </div>

      {primaryAction &&
      !decisions.isLoading &&
      (actionResolution ||
        primaryAction.consequence ||
        primaryAction.smallest_action ||
        actionConflicts.length ||
        actionGoals.length) ? (
        <details className="rounded-xl border border-border/70 bg-card px-4 py-3 sm:px-5">
          <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
            Show recommendation evidence and trade-offs
          </summary>
          <div className="mt-3 grid gap-2 text-sm leading-6 text-muted-foreground">
            {actionResolution ? (
              <p>
                <span className="font-bold text-foreground">{actionResolution.label}:</span>{' '}
                {actionResolution.next_step}
              </p>
            ) : null}
            {primaryAction.consequence ? (
              <p>
                <span className="font-bold text-foreground">Bounded consequence:</span>{' '}
                {formatRecommendationConsequence(primaryAction.consequence, currency)}
              </p>
            ) : null}
            {primaryAction.smallest_action ? (
              <p>
                <span className="font-bold text-foreground">Smallest feasible step:</span>{' '}
                {primaryAction.smallest_action}
              </p>
            ) : null}
            {actionConflicts.slice(0, 2).map((conflict) => (
              <p key={conflict.code}>
                <span className="font-bold text-warning">{conflict.title}:</span>{' '}
                {conflict.description}
              </p>
            ))}
            {actionGoals.length ? (
              <p>
                <span className="font-bold text-foreground">Supports:</span>{' '}
                {actionGoals.map((goal) => goal.label).join(', ')}
              </p>
            ) : null}
          </div>
        </details>
      ) : null}

      <RecommendationFollowUp />

      <section aria-labelledby="financial-pulse-title">
        <div className="mb-5 flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <p className="text-xs font-bold text-muted-foreground">Financial pulse</p>
            <h2
              id="financial-pulse-title"
              className="mt-1 text-2xl font-extrabold tracking-[-0.035em]"
            >
              The three signals that matter now
            </h2>
          </div>
          <Button variant="link" onClick={() => scrollTo('analytics')}>
            View full outlook <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
        <div className="grid gap-5 border-y border-border/70 py-6 md:grid-cols-3 md:divide-x md:divide-border">
          <Pulse
            label="Spent this month"
            value={formatCurrency(spend, currency)}
            context={formatComparison(monthComparison?.spend_change_pct)}
            tone={
              monthComparison?.spend_change_pct && monthComparison.spend_change_pct > 0
                ? 'danger'
                : 'neutral'
            }
          />
          <Pulse
            label="Projected month end"
            value={formatCurrency(projection?.projected_net ?? netCashFlow, currency)}
            context={
              projection
                ? `At ${formatCurrency(projection.daily_spend_rate, currency)} per day`
                : 'Projection is being prepared'
            }
            tone={(projection?.projected_net ?? netCashFlow) < 0 ? 'warning' : 'positive'}
          />
          <Pulse
            label="Recurring burden"
            value={recurringBurden === undefined ? '—' : `${recurringBurden.toFixed(1)}%`}
            context={
              projection
                ? `${formatCurrency(projection.recurring_commitments, currency)} in commitments`
                : 'Commitment analysis is being prepared'
            }
            tone={recurringBurden !== undefined && recurringBurden > 35 ? 'warning' : 'neutral'}
          />
        </div>
      </section>

      <section
        id="guidance"
        className="grid scroll-mt-24 gap-7 lg:grid-cols-[minmax(260px,.72fr)_minmax(0,1.28fr)]"
      >
        <div>
          <p className="text-xs font-bold text-muted-foreground">What changed</p>
          <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
            Evidence behind today’s brief
          </h2>
          <p className="mt-3 max-w-sm text-sm leading-6 text-muted-foreground">
            PFIS separates observed facts from recommendations so you can see why each action
            appears.
          </p>
        </div>
        <div className="space-y-6">
          {evidence.length ? (
            evidence.map((item, index) => (
              <InsightSurface
                key={`${item.title}-${index}`}
                icon={
                  index === 0 ? (
                    <TrendingUp className="h-4 w-4" />
                  ) : (
                    <WalletCards className="h-4 w-4" />
                  )
                }
                title={item.title}
                description={item.description}
                tone={
                  item.severity === 'success'
                    ? 'positive'
                    : item.severity === 'warning' || item.severity === 'danger'
                      ? 'attention'
                      : 'neutral'
                }
              />
            ))
          ) : (
            <InsightSurface
              icon={<TrendingDown className="h-4 w-4" />}
              title="No unusual movement needs attention"
              description="PFIS will surface material changes as more activity is recorded."
              tone="positive"
            />
          )}
        </div>
      </section>

      <footer className="flex flex-col justify-between gap-3 border-t border-border/70 pt-5 text-xs text-muted-foreground sm:flex-row">
        <p data-testid="brief-data-through">
          Based on activity through {projection?.data_through || 'the selected period'} ·{' '}
          {snapshot?.transaction_count ?? 0} transactions
          {data?.sync_summary.last_synced_at
            ? ` · Synced ${formatTime(data.sync_summary.last_synced_at)}`
            : ''}
        </p>
        <button
          type="button"
          onClick={() => scrollTo('guidance')}
          className="focus-ring rounded text-left font-bold text-primary"
        >
          See how PFIS reached this →
        </button>
      </footer>
    </div>
  );
}

function TodaySkeleton() {
  return (
    <div className="space-y-10" role="status" aria-label="Loading financial brief">
      <div className="space-y-3">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="h-12 max-w-3xl" />
        <Skeleton className="h-6 max-w-2xl" />
      </div>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(300px,.65fr)]">
        <Skeleton className="h-[390px]" />
        <Skeleton className="h-[390px]" />
      </div>
      <Skeleton className="h-32" />
    </div>
  );
}

function FinancialHorizon({
  plan,
  loading,
  onComplete,
}: {
  plan?: CashPlan;
  loading: boolean;
  onComplete: () => void;
}) {
  const ready = plan?.readiness === 'ready';
  const currentPosition =
    plan?.planning_balance ?? plan?.estimated_balance ?? plan?.verified_balance;
  const currentPositionAsOf =
    plan?.planning_balance_as_of ?? plan?.estimated_balance_as_of ?? plan?.balance_as_of;
  const currentPositionLabel =
    plan?.balance_basis === 'estimated' ? 'Estimated current position' : 'Verified bank position';
  const missingAction: Record<NonNullable<CashPlan['readiness']>, string> = {
    ready: '',
    needs_verified_balance: 'Record a verified bank balance',
    needs_fresh_balance: 'Refresh the verified bank balance',
    needs_next_income: 'Confirm the next income date',
    needs_position_review: 'Review current bank activity',
  };
  const horizonItems = ready
    ? [
        {
          label: currentPositionLabel,
          evidence: plan.balance_basis === 'estimated' ? 'Estimated' : 'Observed',
          value: formatCurrency(currentPosition, plan.currency),
          detail: `As of ${formatDate(currentPositionAsOf)}`,
        },
        {
          label: 'Confirmed obligations',
          evidence: 'Confirmed',
          value: `−${formatCurrency(plan.commitment_total, plan.currency)}`,
          detail: `Due before ${formatDate(plan.next_income_date)}`,
        },
        {
          label: 'Approved reserves',
          evidence: 'Approved',
          value: `−${formatCurrency(plan.approved_reserve_total, plan.currency)}`,
          detail: 'Only allocations you explicitly approved',
        },
        {
          label: 'Flexible money',
          evidence: 'Calculated',
          value: formatCurrency(plan.flexible_money ?? 0, plan.currency),
          detail: `Available to plan until ${formatDate(plan.next_income_date)}`,
        },
      ]
    : [
        {
          label: currentPositionLabel,
          evidence:
            plan?.readiness === 'needs_position_review'
              ? 'Review'
              : currentPosition != null
                ? 'Observed'
                : 'Required',
          value:
            currentPosition != null
              ? formatCurrency(currentPosition, plan?.currency)
              : 'Not recorded',
          detail: currentPositionAsOf
            ? `As of ${formatDate(currentPositionAsOf)}${plan?.readiness === 'needs_position_review' ? ' · not spendable yet' : ''}`
            : 'No estimate used',
        },
        {
          label: 'Confirmed obligations',
          evidence: 'Held',
          value: 'Not calculated',
          detail: 'Calculated only after the required facts are current',
        },
        {
          label: 'Approved reserves',
          evidence: 'Held',
          value: 'Not calculated',
          detail: 'Draft reserves never reduce money',
        },
        {
          label: 'Next confirmed income',
          evidence: plan?.next_income_date ? 'Confirmed' : 'Required',
          value: plan?.next_income_date ? formatDate(plan.next_income_date) : 'Not confirmed',
          detail: 'PFIS never guesses salary timing',
        },
      ];

  return (
    <figure className="mt-8" aria-labelledby="money-horizon-title">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-primary/15 pb-4">
        <div>
          <p className="text-[0.68rem] font-extrabold uppercase tracking-[0.18em] text-foreground">
            Financial horizon
          </p>
          <h2 id="money-horizon-title" className="mt-1 text-lg font-extrabold tracking-tight">
            {loading
              ? 'Checking verified planning inputs'
              : ready
                ? `${formatCurrency(plan.flexible_money ?? 0, plan.currency)} is flexible until ${formatDate(plan.next_income_date)}`
                : plan
                  ? missingAction[plan.readiness]
                  : 'Connect a verified bank position'}
          </h2>
        </div>
        <Badge variant={ready ? 'success' : 'warning'}>
          {ready ? 'Statement-backed plan' : 'Data action needed'}
        </Badge>
      </div>

      <dl className="relative mt-6 grid gap-x-5 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
        <div
          className="absolute left-4 right-4 top-2 hidden h-px bg-gradient-to-r from-primary/45 via-settlement/45 to-intelligence/45 lg:block"
          aria-hidden="true"
        />
        {horizonItems.map((item, index) => (
          <div key={item.label} className="relative min-w-0">
            <span
              className={cn(
                'mb-4 hidden h-4 w-4 rounded-full border-[3px] border-background shadow-[0_0_0_1px_hsl(var(--primary)/.35)] lg:block',
                index === horizonItems.length - 1 ? 'bg-intelligence' : 'bg-primary',
              )}
              aria-hidden="true"
            />
            <dt className="text-xs font-bold text-muted-foreground">{item.label}</dt>
            <dd
              className={cn(
                'money-value mt-1 truncate text-xl',
                ready && index === horizonItems.length - 1 ? 'text-intelligence' : '',
              )}
            >
              {item.value}
            </dd>
            <dd className="mt-1 text-[0.68rem] font-extrabold uppercase tracking-[0.12em] text-foreground">
              {item.evidence}
            </dd>
            <dd className="mt-1 text-xs leading-5 text-muted-foreground">{item.detail}</dd>
          </div>
        ))}
      </dl>

      {!ready ? (
        <Button className="mt-5" size="sm" variant="outline" onClick={onComplete}>
          Complete Cash Plan evidence <ArrowRight className="h-4 w-4" />
        </Button>
      ) : null}

      <details className="mt-4 border-t border-primary/15 pt-2 text-sm">
        <summary className="focus-ring cursor-pointer rounded-md py-2 font-bold text-muted-foreground hover:text-foreground">
          Evidence and calculation assumptions
        </summary>
        {plan ? (
          <div className="mt-2 grid gap-4 pb-2 text-xs leading-5 text-muted-foreground sm:grid-cols-[.7fr_1.3fr]">
            <p>
              Funding scope{' '}
              <strong className="text-foreground">
                {plan.primary_financial_account_id ? 'one confirmed bank account' : 'not selected'}
              </strong>
              <br />
              Balance as of{' '}
              <strong className="text-foreground">{formatDate(plan.balance_as_of)}</strong>
            </p>
            <ul className="list-disc space-y-1 pl-4">
              {plan.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
              {ready ? (
                <li>
                  Flexible money equals verified bank balance minus confirmed pre-income commitments
                  minus approved reserve allocations.
                </li>
              ) : null}
            </ul>
          </div>
        ) : (
          <p className="pb-2 text-xs text-muted-foreground">
            PFIS will show the observed facts and deterministic calculation after a funding account
            is selected.
          </p>
        )}
      </details>
    </figure>
  );
}

function Pulse({
  label,
  value,
  context,
  tone,
}: {
  label: string;
  value: string;
  context: string;
  tone: 'danger' | 'warning' | 'positive' | 'neutral';
}) {
  return (
    <div className="px-0 md:px-6 md:first:pl-0">
      <p className="text-xs font-bold text-muted-foreground">{label}</p>
      <p
        className={cn(
          'money-value mt-2 text-3xl',
          tone === 'danger' && 'text-danger',
          tone === 'warning' && 'text-warning',
          tone === 'positive' && 'text-success',
        )}
      >
        {value}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{context}</p>
    </div>
  );
}

function firstName(value: string) {
  const local = value.includes('@') ? value.split('@')[0] : value;
  return local.trim().split(/\s+/)[0] || 'there';
}

function formatRecommendationConsequence(consequence: RecommendationConsequence, currency: string) {
  const amount =
    consequence.low === consequence.high
      ? consequence.low.toLocaleString(undefined, { maximumFractionDigits: 2 })
      : `${consequence.low.toLocaleString(undefined, { maximumFractionDigits: 2 })}–${consequence.high.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  const value =
    consequence.unit === 'currency'
      ? `${formatCurrency(consequence.low, consequence.currency ?? currency)}${
          consequence.low === consequence.high
            ? ''
            : `–${formatCurrency(consequence.high, consequence.currency ?? currency)}`
        }`
      : consequence.unit === 'records'
        ? `${amount} record${consequence.high === 1 ? '' : 's'}`
        : `${amount} percentage points`;
  return `${value} · ${consequence.metric}`;
}

function greeting(timezone: string) {
  const hour = Number(
    new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      hour: 'numeric',
      hourCycle: 'h23',
    }).format(new Date()),
  );
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

function formatComparison(value?: number | null) {
  if (value === undefined || value === null) return 'No previous month comparison yet';
  if (value === 0) return 'Unchanged from last month';
  return `${Math.abs(value).toFixed(0)}% ${value > 0 ? 'above' : 'below'} last month`;
}
