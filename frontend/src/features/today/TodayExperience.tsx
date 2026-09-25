import {
  ArrowRight,
  CalendarDays,
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
import { FinancialHero, InsightSurface, PageIntro } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { WorkspaceContextBar } from '@/components/system';
import { useAuth } from '@/features/auth/AuthContext';
import { RecommendationFollowUp } from '@/features/guidance/RecommendationFollowUp';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import {
  queryKeys,
  useCashPlan,
  useFinancialHorizon,
  useWorkspaceSnapshot,
} from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatCurrency, formatDate, formatTime } from '@/lib/format';
import type {
  CashPlan,
  FinancialHorizonEvent,
  FinancialHorizonResponse,
  FinancialHorizonRiskSignal,
  RecommendationConsequence,
  RecommendationDecision,
} from '@/lib/types';
import { cn } from '@/lib/utils';
import { buildTodayBriefCopy } from './todayCopy';
import {
  deriveTodayState,
  type TodayFinancialState,
  type TodayStaleSync,
  type TodayUnavailableSignal,
} from './todayState';

export function TodayExperience() {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const { activeSection, scrollTo } = useDashboardUi();
  const currentView = ['overview', 'guidance', 'recommendations'].includes(activeSection)
    ? activeSection
    : 'overview';
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const workspace = useWorkspaceSnapshot();
  const cashPlan = useCashPlan();
  const horizon = useFinancialHorizon(30);
  const decisions = useQuery({
    queryKey: ['guidance', 'decisions', user?.id ?? 'signed-out'],
    queryFn: () => api.guidanceDecisions(user!.id),
    enabled: Boolean(user),
  });
  const { running, updateChannelLabel, updateChannelVariant } = useSync();
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

  const todayState = deriveTodayState({
    data: workspace.data,
    workspaceLoading: workspace.isLoading,
    workspaceError: workspace.isError,
    cashPlanError: cashPlan.isError,
    decisionsError: decisions.isError,
    syncRunning: running,
    now: Date.now(),
  });

  if (todayState.kind === 'loading') return <TodaySkeleton />;

  if (todayState.kind === 'full-error') {
    return (
      <div className="space-y-8" data-today-state="full-error">
        <PageIntro
          eyebrow="Financial brief"
          title="Your financial brief could not be loaded."
          description="Your records are unchanged. PFIS could not reach this month’s summary, so it is not showing any figures rather than guessing."
        />
        <section role="alert" aria-labelledby="today-full-error-title">
          <h2 id="today-full-error-title" className="sr-only">
            Financial brief unavailable
          </h2>
          <EmptyState
            icon={<CircleAlert aria-hidden="true" className="h-5 w-5" />}
            title="The summary is temporarily unavailable"
            description="Retry the summary. If it keeps failing, check your connected sources in Data & settings."
            action={
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  type="button"
                  aria-disabled={workspace.isFetching || undefined}
                  onClick={() => {
                    if (!workspace.isFetching) void workspace.refetch();
                  }}
                >
                  <RefreshCw
                    aria-hidden="true"
                    className={cn('h-4 w-4', workspace.isFetching && 'motion-safe:animate-spin')}
                  />
                  {workspace.isFetching ? 'Retrying summary…' : 'Retry summary'}
                </Button>
                <Button type="button" variant="outline" onClick={() => scrollTo('inbox')}>
                  Open Data &amp; settings <ArrowRight aria-hidden="true" className="h-4 w-4" />
                </Button>
              </div>
            }
          />
        </section>
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
  const primaryAction = decisions.isError
    ? undefined
    : data?.recommendations.find(
        (recommendation) => !hiddenRecommendationIds.has(recommendation.id),
      );
  const actionConflicts = primaryAction?.conflicts ?? [];
  const actionGoals = primaryAction?.goal_links ?? [];
  const actionResolution = primaryAction?.resolution;
  const actionTarget = primaryAction?.target ?? 'insights';
  const recurringBurden = financialHealth?.recurring_burden;
  const evidence = (data?.insights ?? []).slice(0, 2);
  const financialState = todayState.financial;
  const lowData = financialState === 'low-data';
  const transactionCount = snapshot?.transaction_count ?? 0;
  const safeToSpendReviewNeeded =
    !cashPlan.isLoading && (cashPlan.isError || cashPlan.data?.readiness !== 'ready');

  const { headline, summary } = buildTodayBriefCopy({
    transactionCount,
    netCashFlow,
    name,
    currency,
    recommendationTitle: primaryAction?.title,
    financialState,
  });
  const noActionCopy = noActionGuidance(financialState);
  const retryUnavailable = () => {
    if (todayState.unavailable.includes('summary')) void workspace.refetch();
    if (todayState.unavailable.includes('safe-to-spend')) void cashPlan.refetch();
    if (todayState.unavailable.includes('action-status')) void decisions.refetch();
  };
  const retryingUnavailable =
    (todayState.unavailable.includes('summary') && workspace.isFetching) ||
    (todayState.unavailable.includes('safe-to-spend') && cashPlan.isFetching) ||
    (todayState.unavailable.includes('action-status') && decisions.isFetching);

  return (
    <div className="space-y-6" data-today-state={todayState.kind}>
      <PageIntro
        eyebrow={`${greeting(user?.timezone ?? 'Asia/Kolkata')} · ${currentView === 'overview' ? 'Financial brief' : currentView === 'guidance' ? 'Evidence' : 'Action history'}`}
        title={
          currentView === 'overview'
            ? headline
            : currentView === 'guidance'
              ? 'What changed, and why?'
              : 'Your action follow-up'
        }
        description={
          currentView === 'overview'
            ? summary
            : currentView === 'guidance'
              ? 'A short, evidence-led explanation of the changes behind this month’s brief.'
              : 'Review accepted actions and record what happened. Each outcome is final.'
        }
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={updateChannelVariant}>
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  updateChannelVariant === 'success'
                    ? 'bg-success'
                    : updateChannelVariant === 'warning'
                      ? 'bg-warning'
                      : 'bg-muted-foreground',
                )}
              />
              {running ? 'Syncing' : updateChannelLabel}
            </Badge>
            {currentView === 'overview' && safeToSpendReviewNeeded ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="lg:hidden"
                onClick={() => scrollTo('cash-plan')}
              >
                Review Safe to spend <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </Button>
            ) : null}
          </div>
        }
      />

      <WorkspaceContextBar label="Today views">
        <nav
          aria-label="Today views"
          className="scrollbar-none flex min-h-11 max-w-full items-center gap-1 overflow-x-auto rounded-lg bg-secondary/75 p-1 sm:w-auto"
        >
          {[
            { value: 'overview', label: 'Brief' },
            { value: 'guidance', label: 'Why it changed' },
            { value: 'recommendations', label: 'Actions' },
          ].map((view) => (
            <a
              key={view.value}
              href={`#${view.value}`}
              aria-current={currentView === view.value ? 'page' : undefined}
              onClick={(event) => {
                if (
                  event.button !== 0 ||
                  event.metaKey ||
                  event.ctrlKey ||
                  event.shiftKey ||
                  event.altKey
                ) {
                  return;
                }
                event.preventDefault();
                scrollTo(view.value);
              }}
              className={cn(
                'focus-ring relative z-10 inline-flex min-h-11 shrink-0 items-center rounded-md px-3 text-sm font-bold transition-colors',
                currentView === view.value
                  ? 'bg-card text-foreground shadow-lift'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {view.label}
            </a>
          ))}
        </nav>
      </WorkspaceContextBar>

      <TodayStatusNotices
        stale={todayState.stale}
        unavailable={todayState.unavailable}
        retrying={retryingUnavailable}
        onRetry={retryUnavailable}
        onOpenSources={() => scrollTo('inbox')}
      />

      {currentView === 'overview' ? (
        <div className="scroll-mt-24 space-y-6">
          {lowData ? (
            <section
              aria-labelledby="today-low-data-title"
              className="flex flex-col gap-3 border-y border-warning/25 bg-warning/5 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex items-start gap-3">
                <CircleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <div>
                  <h2 id="today-low-data-title" className="font-extrabold">
                    This brief has limited evidence
                  </h2>
                  <p className="mt-1 text-muted-foreground">
                    {transactionCount === 0
                      ? 'PFIS has no transactions in this period yet.'
                      : 'PFIS found fewer than three transactions in this period.'}{' '}
                    Connect a source or import activity; projections stay hidden until there is
                    enough evidence.
                  </p>
                </div>
              </div>
              <Button
                type="button"
                size="sm"
                className="shrink-0 self-start sm:self-center"
                onClick={() => scrollTo('inbox')}
              >
                Connect or import activity <ArrowRight aria-hidden="true" className="h-4 w-4" />
              </Button>
            </section>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,.65fr)]">
            <FinancialHero className={cn(financialState === 'deficit' && 'bg-muted/60')}>
              <p className="text-sm text-muted-foreground">Net cash flow this month</p>
              <p
                className={cn(
                  'money-value mt-1 text-4xl sm:text-5xl',
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
                        netMovement >= 0 ? 'higher' : 'lower'
                      } than last month`}
              </p>
              <SafeToSpendHorizon
                plan={cashPlan.data}
                loading={cashPlan.isLoading}
                unavailable={cashPlan.isError}
                onComplete={() => scrollTo('cash-plan')}
              />
            </FinancialHero>

            {decisions.isError ? (
              <section
                className="flex flex-col justify-center gap-3 border-l-2 border-warning bg-warning/5 px-4 py-5"
                role="alert"
                aria-labelledby="action-status-error-title"
              >
                <div>
                  <p className="text-xs font-bold text-muted-foreground">Recommended next</p>
                  <h2 id="action-status-error-title" className="mt-1 text-base font-extrabold">
                    Action status is unavailable
                  </h2>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    PFIS could not check which recommendations you have already handled. Retry
                    before taking another action so it does not repeat one.
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void decisions.refetch()}
                  className="self-start"
                >
                  <RefreshCw aria-hidden="true" className="h-4 w-4" /> Retry action status
                </Button>
              </section>
            ) : (
              <InsightSurface
                icon={<Sparkles className="h-4 w-4" />}
                eyebrow={primaryAction ? 'Recommended next' : noActionCopy.eyebrow}
                title={primaryAction?.title ?? noActionCopy.title}
                description={primaryAction?.description ?? noActionCopy.description}
                tone={primaryAction ? 'intelligence' : noActionCopy.tone}
                className="h-full"
                meta={
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => scrollTo(actionTarget)}
                      >
                        {primaryAction?.action_label ?? 'Open insights'}
                        <ArrowRight className="h-4 w-4" aria-hidden="true" />
                      </Button>
                      <span>
                        {primaryAction?.expected_impact ||
                          (primaryAction?.reason_codes?.length
                            ? `Based on ${primaryAction.reason_codes.length} signals`
                            : 'Based on your selected month')}
                      </span>
                    </div>
                    {primaryAction && !decisions.isLoading ? (
                      <div className="flex flex-wrap items-center gap-2 border-t border-border/65 pt-3">
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
                    ) : null}
                  </div>
                }
              />
            )}
          </div>

          {primaryAction &&
          !decisions.isLoading &&
          (actionResolution ||
            primaryAction.consequence ||
            primaryAction.smallest_action ||
            actionConflicts.length ||
            actionGoals.length) ? (
            <details className="border-y border-border/70 px-1 py-3">
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

          <NextThirtyDaysHorizon
            horizon={horizon.data}
            loading={horizon.isLoading}
            error={horizon.isError}
            onRetry={() => void horizon.refetch()}
          />

          <section aria-labelledby="financial-pulse-title">
            <div className="mb-3 flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-end">
              <div>
                <p className="text-xs font-bold text-muted-foreground">At a glance</p>
                <h2 id="financial-pulse-title" className="mt-1 text-lg font-extrabold">
                  Two signals for this month
                </h2>
              </div>
              <Button variant="link" onClick={() => scrollTo('analytics')}>
                View full outlook <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
            <div className="grid gap-5 border-y border-border/70 py-4 sm:grid-cols-2 sm:divide-x sm:divide-border">
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
                value={
                  lowData
                    ? 'Not projected'
                    : formatCurrency(projection?.projected_net ?? netCashFlow, currency)
                }
                context={
                  lowData
                    ? 'PFIS needs more activity before projecting this month'
                    : projection
                      ? `At ${formatCurrency(projection.daily_spend_rate, currency)} per day`
                      : 'Projection is being prepared'
                }
                tone={
                  lowData
                    ? 'neutral'
                    : (projection?.projected_net ?? netCashFlow) < 0
                      ? 'warning'
                      : 'positive'
                }
              />
            </div>
          </section>

          <footer className="flex flex-col justify-between gap-3 border-t border-border/70 pt-4 text-xs text-muted-foreground sm:flex-row">
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
      ) : null}

      {currentView === 'guidance' ? (
        <section id="guidance" className="scroll-mt-24 space-y-5" aria-labelledby="guidance-title">
          <div className="max-w-2xl">
            <p className="text-xs font-bold text-muted-foreground">Evidence, not another score</p>
            <h2 id="guidance-title" className="mt-1 text-xl font-extrabold">
              The signals behind this brief
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              PFIS separates observed changes from recommendations so you can inspect why an action
              appears.
            </p>
          </div>
          {lowData ? (
            <InsightSurface
              icon={<CircleAlert className="h-4 w-4" aria-hidden="true" />}
              title="Too little activity to assess a trend"
              description="PFIS found fewer than three transactions in this period, so it can’t determine whether a movement is unusual yet. Review the source activity as more records arrive."
              tone="neutral"
              meta={
                <Button
                  type="button"
                  variant="link"
                  className="min-h-11 px-0"
                  onClick={() => scrollTo('transactions')}
                >
                  Review activity <ArrowRight aria-hidden="true" className="h-4 w-4" />
                </Button>
              }
            />
          ) : evidence.length ? (
            <div className="divide-y divide-border border-y border-border">
              {evidence.map((item, index) => (
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
              ))}
            </div>
          ) : (
            <InsightSurface
              icon={<TrendingDown className="h-4 w-4" />}
              title="No unusual movement needs attention"
              description="PFIS will surface material changes as more activity is recorded."
              tone="positive"
            />
          )}
          <div className="grid gap-4 border-t border-border pt-4 sm:grid-cols-2">
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
            <Pulse
              label="Data confidence"
              value={
                financialHealth?.data_confidence == null
                  ? 'Not available'
                  : `${financialHealth.data_confidence}%`
              }
              context="Read alongside the underlying evidence, not as a guarantee."
              tone="neutral"
            />
          </div>
          <footer className="border-t border-border pt-4 text-xs text-muted-foreground">
            Based on activity through {projection?.data_through || 'the selected period'} ·{' '}
            {snapshot?.transaction_count ?? 0} transactions
            {data?.sync_summary.last_synced_at
              ? ` · Synced ${formatTime(data.sync_summary.last_synced_at)}`
              : ''}
          </footer>
        </section>
      ) : null}

      {currentView === 'recommendations' ? (
        <section id="recommendations" className="scroll-mt-24" aria-labelledby="actions-title">
          <h2 id="actions-title" className="sr-only">
            Accepted action follow-up
          </h2>
          {decisions.isLoading ? (
            <Skeleton className="h-28" />
          ) : decisions.isError ? (
            <EmptyState
              icon={<CircleAlert className="h-5 w-5" aria-hidden="true" />}
              title="Action history is unavailable"
              description="PFIS couldn’t check which accepted actions need follow-up. Retry to load the history; no empty state has been inferred."
              action={
                <Button type="button" onClick={() => void decisions.refetch()}>
                  <RefreshCw aria-hidden="true" className="h-4 w-4" /> Retry action history
                </Button>
              }
            />
          ) : (decisions.data ?? []).some(
              (decision: RecommendationDecision) => decision.state === 'accepted',
            ) ? (
            <RecommendationFollowUp />
          ) : (
            <EmptyState
              icon={<Check className="h-5 w-5" aria-hidden="true" />}
              title="No action outcomes to review"
              description="When you choose an action from the brief, its follow-up will appear here."
              action={<Button onClick={() => scrollTo('overview')}>Back to your brief</Button>}
            />
          )}
        </section>
      ) : null}
    </div>
  );
}

function TodaySkeleton() {
  return (
    <div
      className="space-y-10"
      role="status"
      aria-busy="true"
      aria-label="Loading financial brief"
      data-today-state="loading"
    >
      <span className="sr-only">Loading your position, priority action, and signals.</span>
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

const UNAVAILABLE_SIGNAL_LABELS: Record<TodayUnavailableSignal, string> = {
  summary: 'the monthly summary',
  'safe-to-spend': 'Safe to spend',
  'action-status': 'action status',
};

function TodayStatusNotices({
  stale,
  unavailable,
  retrying,
  onRetry,
  onOpenSources,
}: {
  stale: TodayStaleSync | null;
  unavailable: TodayUnavailableSignal[];
  retrying: boolean;
  onRetry: () => void;
  onOpenSources: () => void;
}) {
  if (!stale && !unavailable.length) return null;
  const signalList = formatList(unavailable.map((signal) => UNAVAILABLE_SIGNAL_LABELS[signal]));

  return (
    <div className="space-y-3">
      {stale ? (
        <section
          role="status"
          aria-labelledby="today-stale-title"
          className="flex flex-col gap-3 border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-3">
            <Clock3 aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div>
              <h2 id="today-stale-title" className="font-extrabold">
                {stale.reason === 'failed'
                  ? 'The latest sync did not finish'
                  : 'Showing last known values'}
              </h2>
              <p className="mt-1 text-muted-foreground">
                {stale.lastSyncedAt
                  ? `Sources last synced ${formatDate(stale.lastSyncedAt)} at ${formatTime(stale.lastSyncedAt)}.`
                  : 'Sources have not completed a sync yet.'}{' '}
                Newer activity may be missing until they refresh.
              </p>
            </div>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="shrink-0 self-start sm:self-center"
            onClick={onOpenSources}
          >
            Review data sources <ArrowRight aria-hidden="true" className="h-4 w-4" />
          </Button>
        </section>
      ) : null}
      {unavailable.length ? (
        <section
          role="status"
          aria-labelledby="today-partial-error-title"
          className="flex flex-col gap-3 border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-3">
            <CircleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div>
              <h2 id="today-partial-error-title" className="font-extrabold">
                Some signals could not be refreshed
              </h2>
              <p className="mt-1 text-muted-foreground">
                PFIS could not refresh {signalList}.{' '}
                {unavailable.includes('summary')
                  ? 'The figures below are from the last successful load.'
                  : 'The rest of this page is unaffected.'}
              </p>
            </div>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-disabled={retrying || undefined}
            className="shrink-0 self-start sm:self-center"
            onClick={() => {
              if (!retrying) onRetry();
            }}
          >
            <RefreshCw
              aria-hidden="true"
              className={cn('h-4 w-4', retrying && 'motion-safe:animate-spin')}
            />
            {retrying ? 'Retrying…' : 'Retry unavailable signals'}
          </Button>
        </section>
      ) : null}
    </div>
  );
}

function noActionGuidance(financialState: TodayFinancialState | null): {
  eyebrow: string;
  title: string;
  description: string;
  tone: 'neutral' | 'attention';
} {
  if (financialState === 'deficit') {
    return {
      eyebrow: 'Start here',
      title: 'Find the largest driver of this shortfall',
      description:
        'Spending is above income this month. Review the evidence to choose the adjustment with the most near-term effect.',
      tone: 'attention',
    };
  }
  if (financialState === 'attention') {
    return {
      eyebrow: 'Worth a look',
      title: 'Review the pressure building this month',
      description:
        'You are ahead so far, but one signal is moving the wrong way. Review the evidence before it grows.',
      tone: 'attention',
    };
  }
  if (financialState === 'low-data') {
    return {
      eyebrow: 'No recommendation yet',
      title: 'Add activity before acting on this month',
      description:
        'PFIS needs more transactions before it can recommend an action with confidence.',
      tone: 'neutral',
    };
  }
  return {
    eyebrow: 'No urgent action',
    title: 'Explore the drivers behind this month',
    description:
      'PFIS has no urgent action for this period. Review the evidence and keep your data current.',
    tone: 'neutral',
  };
}

function formatList(items: string[]) {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

function SafeToSpendHorizon({
  plan,
  loading,
  unavailable,
  onComplete,
}: {
  plan?: CashPlan;
  loading: boolean;
  unavailable: boolean;
  onComplete: () => void;
}) {
  const readyPlan =
    !unavailable && plan?.readiness === 'ready' && plan.flexible_money != null ? plan : null;
  const ready = readyPlan != null;
  const currentPosition =
    plan?.planning_balance ?? plan?.estimated_balance ?? plan?.verified_balance;
  const currentPositionAsOf =
    plan?.planning_balance_as_of ?? plan?.estimated_balance_as_of ?? plan?.balance_as_of;
  const currentPositionLabel =
    plan?.balance_basis === 'estimated' ? 'Estimated bank position' : 'Observed bank position';
  const missingAction: Record<NonNullable<CashPlan['readiness']>, string> = {
    ready: '',
    needs_verified_balance: 'Record an observed bank balance',
    needs_fresh_balance: 'Refresh the observed bank balance',
    needs_next_income: 'Confirm the next income date',
    needs_position_review: 'Review current bank activity',
  };

  return (
    <figure className="mt-6 border-t border-primary/15 pt-4" aria-labelledby="money-horizon-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-foreground">
            Safe to spend
          </p>
          <h2 id="money-horizon-title" className="mt-1 text-xl font-extrabold tracking-tight">
            {loading
              ? 'Checking planning inputs'
              : unavailable
                ? 'Safe to spend is unavailable'
                : readyPlan
                  ? formatCurrency(readyPlan.flexible_money, readyPlan.currency)
                  : plan
                    ? missingAction[plan.readiness] || 'Review calculation inputs'
                    : 'Set up a bank position'}
          </h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {readyPlan
              ? `Flexible until ${formatDate(readyPlan.next_income_date)} · ${readyPlan.balance_basis === 'estimated' ? 'estimated position' : 'observed position'}${currentPositionAsOf ? ` as of ${formatDate(currentPositionAsOf)}` : ''}`
              : unavailable
                ? 'PFIS could not refresh the planning inputs, so no amount is shown.'
                : 'Not calculated until the required evidence is ready.'}
          </p>
        </div>
        <Badge variant={ready ? 'success' : 'warning'}>
          {ready ? 'Ready for planning' : unavailable ? 'Not refreshed' : 'Evidence needed'}
        </Badge>
      </div>

      {!ready ? (
        <Button
          className="mt-5 hidden lg:inline-flex"
          size="sm"
          variant="outline"
          onClick={onComplete}
        >
          Review Safe to spend <ArrowRight className="h-4 w-4" />
        </Button>
      ) : null}

      <details className="mt-4 border-t border-primary/15 pt-2 text-sm">
        <summary className="focus-ring cursor-pointer rounded-md py-2 font-bold text-muted-foreground hover:text-foreground">
          Show calculation details
        </summary>
        {plan ? (
          <div className="mt-3 space-y-4 pb-2">
            <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-xs font-bold text-muted-foreground">{currentPositionLabel}</dt>
                <dd className="mt-1 text-sm font-extrabold">
                  {currentPosition == null
                    ? 'Not recorded'
                    : formatCurrency(currentPosition, plan.currency)}
                </dd>
                <dd className="mt-1 text-xs text-muted-foreground">
                  {currentPositionAsOf
                    ? `As of ${formatDate(currentPositionAsOf)}`
                    : 'No dated observation'}
                  {plan.balance_basis === 'estimated'
                    ? ' · estimate'
                    : ' · user/provider observation'}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-bold text-muted-foreground">Confirmed obligations</dt>
                <dd className="mt-1 text-sm font-extrabold">
                  {ready
                    ? `−${formatCurrency(plan.commitment_total, plan.currency)}`
                    : 'Not calculated'}
                </dd>
                <dd className="mt-1 text-xs text-muted-foreground">
                  {ready
                    ? `Due before ${formatDate(plan.next_income_date)}`
                    : 'Held until required evidence is ready'}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-bold text-muted-foreground">Approved reserves</dt>
                <dd className="mt-1 text-sm font-extrabold">
                  {ready
                    ? `−${formatCurrency(plan.approved_reserve_total, plan.currency)}`
                    : 'Not calculated'}
                </dd>
                <dd className="mt-1 text-xs text-muted-foreground">
                  Draft reserves do not reduce the amount
                </dd>
              </div>
              {readyPlan ? (
                <div>
                  <dt className="text-xs font-bold text-muted-foreground">Flexible money</dt>
                  <dd className="mt-1 text-sm font-extrabold">
                    {formatCurrency(readyPlan.flexible_money, readyPlan.currency)}
                  </dd>
                  <dd className="mt-1 text-xs text-muted-foreground">
                    Available to plan until {formatDate(readyPlan.next_income_date)}
                  </dd>
                </div>
              ) : null}
              <div>
                <dt className="text-xs font-bold text-muted-foreground">Next confirmed income</dt>
                <dd className="mt-1 text-sm font-extrabold">
                  {plan.next_income_date ? formatDate(plan.next_income_date) : 'Not confirmed'}
                </dd>
                <dd className="mt-1 text-xs text-muted-foreground">
                  PFIS does not guess income timing
                </dd>
              </div>
            </dl>
            <div className="grid gap-3 border-t border-primary/15 pt-3 text-xs leading-5 text-muted-foreground sm:grid-cols-[.7fr_1.3fr]">
              <p>
                Funding scope{' '}
                <strong className="text-foreground">
                  {plan.primary_financial_account_id ? 'one selected bank account' : 'not selected'}
                </strong>
              </p>
              <ul className="list-disc space-y-1 pl-4">
                {plan.assumptions.map((assumption) => (
                  <li key={assumption}>{assumption}</li>
                ))}
                {readyPlan ? (
                  <li>
                    Flexible money equals the observed or estimated bank position minus confirmed
                    pre-income commitments and approved reserve allocations.
                  </li>
                ) : null}
              </ul>
            </div>
          </div>
        ) : (
          <p className="pb-2 text-xs text-muted-foreground">
            PFIS will show the observed facts and calculation after a funding account is selected.
          </p>
        )}
      </details>
    </figure>
  );
}

function NextThirtyDaysHorizon({
  horizon,
  loading,
  error,
  onRetry,
}: {
  horizon?: FinancialHorizonResponse;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}) {
  const currency = horizon?.current_position.currency ?? 'INR';
  const events = horizon?.events ?? [];
  const risks = horizon?.risk_signals ?? [];
  const missingEvidence = horizon?.missing_evidence ?? [];
  const empty =
    horizon &&
    events.length === 0 &&
    risks.length === 0 &&
    missingEvidence.length === 0 &&
    !horizon.lowest_projected_point &&
    !horizon.lowest_projected_point_unavailable_reason;

  return (
    <section
      aria-labelledby="next-30-days-title"
      className="rounded-2xl border border-border/70 bg-card/80 p-4 shadow-sm"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <p className="text-xs font-bold text-muted-foreground">Financial Horizon</p>
          <h2 id="next-30-days-title" className="mt-1 text-xl font-extrabold">
            Next 30 days
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            A dated view of upcoming money movement, projected pressure, and the evidence PFIS
            still needs.
          </p>
        </div>
        {horizon ? (
          <Badge variant={horizonStatusVariant(horizon.status)}>
            {horizonStatusLabel(horizon.status)}
          </Badge>
        ) : null}
      </div>

      {loading ? (
        <div className="mt-5 grid gap-3" role="status" aria-label="Loading the next 30 days">
          <Skeleton className="h-16" />
          <Skeleton className="h-24" />
          <span className="sr-only">Loading dated events and horizon evidence.</span>
        </div>
      ) : error ? (
        <div
          role="alert"
          className="mt-5 flex flex-col gap-3 border-l-2 border-warning bg-warning/5 px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between"
        >
          <div>
            <h3 className="font-extrabold">The Financial Horizon could not be refreshed</h3>
            <p className="mt-1 text-muted-foreground">
              Your Today brief stays visible. Retry to load the server-owned 30 day outlook.
            </p>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={onRetry}>
            <RefreshCw aria-hidden="true" className="h-4 w-4" /> Retry horizon
          </Button>
        </div>
      ) : empty ? (
        <EmptyState
          icon={<CalendarDays aria-hidden="true" className="h-5 w-5" />}
          title="No dated pressure in the next 30 days"
          description="PFIS did not find upcoming commitments, card dates, or balance-forecast risks that need action in this horizon."
        />
      ) : horizon ? (
        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,.9fr)]">
          <div className="space-y-4">
            <section aria-labelledby="horizon-events-title">
              <h3 id="horizon-events-title" className="text-sm font-extrabold">
                Dated upcoming events
              </h3>
              {events.length ? (
                <ol className="mt-3 divide-y divide-border/70 border-y border-border/70">
                  {events.slice(0, 5).map((event) => (
                    <HorizonEventRow key={event.id} event={event} currency={currency} />
                  ))}
                </ol>
              ) : (
                <p className="mt-2 text-sm text-muted-foreground">
                  No dated events are available for this horizon.
                </p>
              )}
            </section>

            <section aria-labelledby="horizon-lowest-title">
              <h3 id="horizon-lowest-title" className="text-sm font-extrabold">
                Lowest projected point
              </h3>
              {horizon.lowest_projected_point ? (
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  Expected balance reaches{' '}
                  <span className="font-extrabold text-foreground">
                    {formatCurrency(horizon.lowest_projected_point.expected_balance, currency)}
                  </span>{' '}
                  on {formatDate(horizon.lowest_projected_point.date)}.
                </p>
              ) : (
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {horizon.lowest_projected_point_unavailable_reason ||
                    'PFIS needs more balance-forecast evidence before naming a lowest point.'}
                </p>
              )}
            </section>
          </div>

          <div className="space-y-4">
            <section aria-labelledby="horizon-risk-title">
              <h3 id="horizon-risk-title" className="text-sm font-extrabold">
                Risk signals
              </h3>
              {risks.length ? (
                <ul className="mt-3 space-y-3">
                  {risks.slice(0, 3).map((risk) => (
                    <HorizonRiskRow key={risk.code} risk={risk} currency={currency} />
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-muted-foreground">
                  No risk signal needs attention in this horizon.
                </p>
              )}
            </section>

            <section aria-labelledby="horizon-evidence-title">
              <h3 id="horizon-evidence-title" className="text-sm font-extrabold">
                Missing evidence
              </h3>
              {missingEvidence.length ? (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm leading-6 text-muted-foreground">
                  {missingEvidence.slice(0, 4).map((item) => (
                    <li key={item}>{humanizeReason(item)}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-muted-foreground">
                  No missing evidence is blocking this horizon.
                </p>
              )}
            </section>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function HorizonEventRow({
  event,
  currency,
}: {
  event: FinancialHorizonEvent;
  currency: string;
}) {
  return (
    <li className="grid gap-2 py-3 sm:grid-cols-[7.5rem_minmax(0,1fr)_auto] sm:items-center">
      <time dateTime={event.date} className="text-sm font-extrabold">
        {formatDate(event.date)}
      </time>
      <div className="min-w-0">
        <p className="font-bold">{event.label}</p>
        <p className="text-xs text-muted-foreground">
          {sourceLabel(event.source)} · {statusLabel(event.status)}
        </p>
      </div>
      {event.amount == null ? null : (
        <p
          className={cn(
            'money-value text-sm',
            event.direction === 'out' && 'text-danger',
            event.direction === 'in' && 'text-success',
          )}
        >
          {event.direction === 'out' ? '−' : event.direction === 'in' ? '+' : ''}
          {formatCurrency(event.amount, currency)}
        </p>
      )}
    </li>
  );
}

function HorizonRiskRow({
  risk,
  currency,
}: {
  risk: FinancialHorizonRiskSignal;
  currency: string;
}) {
  const recovery = riskRecoveryLink(risk);
  return (
    <li className="rounded-xl border border-border/70 bg-background/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant={
            risk.severity === 'danger'
              ? 'danger'
              : risk.severity === 'warning'
                ? 'warning'
                : 'info'
          }
        >
          {risk.severity}
        </Badge>
        {risk.date ? (
          <time dateTime={risk.date} className="text-xs font-bold text-muted-foreground">
            {formatDate(risk.date)}
          </time>
        ) : null}
      </div>
      <p className="mt-2 text-sm font-extrabold">{risk.label}</p>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">
        {risk.detail}
        {risk.amount == null ? '' : ` · ${formatCurrency(risk.amount, currency)}`}
      </p>
      <a href={recovery.href} className="focus-ring mt-2 inline-flex rounded text-sm font-bold text-primary">
        {recovery.label} <ArrowRight aria-hidden="true" className="ml-1 h-4 w-4" />
      </a>
    </li>
  );
}

function horizonStatusVariant(status: FinancialHorizonResponse['status']) {
  if (status === 'healthy') return 'success';
  if (status === 'deficit') return 'danger';
  if (status === 'attention' || status === 'stale') return 'warning';
  return 'outline';
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

function sourceLabel(source: FinancialHorizonEvent['source']) {
  const labels: Record<FinancialHorizonEvent['source'], string> = {
    balance_position: 'Balance position',
    cash_plan: 'Cash Plan',
    commitment: 'Commitment',
    liability: 'Liability',
    card_upcoming: 'Cards',
    card_due_runway: 'Card runway',
    balance_forecast: 'Balance forecast',
  };
  return labels[source];
}

function statusLabel(status: FinancialHorizonEvent['status']) {
  const labels: Record<FinancialHorizonEvent['status'], string> = {
    verified: 'verified',
    planned: 'planned',
    estimated: 'estimated',
    risk: 'risk',
    provisional: 'provisional',
  };
  return labels[status];
}

function riskRecoveryLink(risk: FinancialHorizonRiskSignal) {
  const text = `${risk.source} ${risk.code}`.toLowerCase();
  if (text.includes('card')) return { href: '#cards', label: 'Review cards' };
  if (text.includes('plan') || text.includes('cash') || text.includes('forecast')) {
    return { href: '#plan', label: 'Review plan' };
  }
  return { href: '#data', label: 'Review data' };
}

function humanizeReason(reason: string) {
  return reason.replace(/[_-]+/g, ' ');
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
