import {
  ArrowRight,
  CircleAlert,
  RefreshCw,
  Sparkles,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from 'lucide-react';
import { ActionSurface, FinancialHero, InsightSurface, PageIntro } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useAuth } from '@/features/auth/AuthContext';
import {
  useCashFlow,
  useFinancialHealth,
  useGuidanceBrief,
  useMonthComparison,
  useWorkspaceSnapshot,
} from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { formatCurrency, formatTime } from '@/lib/format';
import type { CashFlowProjection } from '@/lib/types';
import { cn } from '@/lib/utils';

export function TodayExperience() {
  const { user } = useAuth();
  const { scrollTo } = useDashboardUi();
  const workspace = useWorkspaceSnapshot();
  const brief = useGuidanceBrief();
  const cashFlow = useCashFlow();
  const comparison = useMonthComparison();
  const health = useFinancialHealth();
  const { liveConnected, running } = useSync();

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
  const guidance = brief.data;
  const projection = cashFlow.data;
  const financialHealth = health.data;
  const monthComparison = comparison.data;
  const name = firstName(user?.name || user?.email || 'there');
  const netCashFlow = snapshot?.net_cash_flow ?? 0;
  const spend = snapshot?.spend ?? 0;
  const previousNet = monthComparison
    ? monthComparison.previous_income - monthComparison.previous_spend
    : null;
  const netMovement = previousNet === null ? null : netCashFlow - previousNet;
  const primaryAction = guidance?.actions[0] ?? data?.recommendations[0];
  const actionTarget = primaryAction?.target ?? 'insights';
  const healthScore = financialHealth?.score ?? guidance?.health_score;
  const recurringBurden = financialHealth?.recurring_burden;
  const evidence = guidance?.changes?.length
    ? guidance.changes.slice(0, 2).map((change) => ({
        title: change,
        description: 'Included in today’s deterministic financial brief.',
        severity: 'info' as const,
      }))
    : (data?.insights ?? []).slice(0, 2);
  const lowData = (snapshot?.transaction_count ?? 0) < 3;

  const headline = guidance?.headline || fallbackHeadline(netCashFlow, name);
  const summary =
    guidance?.summary ||
    `You have ${netCashFlow >= 0 ? 'kept' : 'spent'} ${formatCurrency(Math.abs(netCashFlow), currency)} ${
      netCashFlow >= 0 ? 'after spending' : 'more than you earned'
    } this month.`;

  return (
    <div className="space-y-10">
      <PageIntro
        eyebrow={`${greeting()} · Financial brief`}
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
            {running ? 'Syncing' : liveConnected ? 'Live' : 'Polling'}
          </Badge>
        }
      />

      {lowData ? (
        <div className="flex items-start gap-3 rounded-xl bg-warning/10 px-4 py-3 text-sm">
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
        className="grid scroll-mt-24 gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(300px,.65fr)]"
      >
        <FinancialHero className="min-h-[390px]">
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
                <p className="text-xs text-muted-foreground">Financial health</p>
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
              </div>
            ) : null}
          </div>
          <MoneyHorizon projection={projection} currency={currency} net={netCashFlow} />
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
        />
      </div>

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
        <p>
          Based on activity through {guidance?.data_through || 'the selected period'} ·{' '}
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

function MoneyHorizon({
  projection,
  currency,
  net,
}: {
  projection?: CashFlowProjection;
  currency: string;
  net: number;
}) {
  const observed = projection?.net_to_date ?? net;
  const projected = projection?.projected_net;
  const daysRemaining = projection
    ? Math.max(projection.days_in_month - projection.days_elapsed, 0)
    : null;
  const horizonItems = [
    {
      label: 'Position today',
      evidence: 'Observed',
      value: formatCurrency(observed, currency),
      detail: 'Income less tracked spend',
    },
    {
      label: 'Daily pace',
      evidence: 'Calculated',
      value: projection ? formatCurrency(projection.daily_spend_rate, currency) : 'Preparing',
      detail: 'Average tracked spend per day',
    },
    {
      label: 'Recurring reserve',
      evidence: 'Calculated',
      value: projection ? formatCurrency(projection.recurring_commitments, currency) : 'Preparing',
      detail: 'Monthly commitments, not exact due dates',
    },
    {
      label: 'Month end',
      evidence: 'Forecast',
      value: projected === undefined ? 'Preparing' : formatCurrency(projected, currency),
      detail: projection
        ? `${formatCurrency(projection.income - projection.projected_range_high, currency)} to ${formatCurrency(
            projection.income - projection.projected_range_low,
            currency,
          )}`
        : 'Waiting for projection evidence',
    },
  ];

  return (
    <figure className="mt-8" aria-labelledby="money-horizon-title">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-primary/15 pb-4">
        <div>
          <p className="text-[0.68rem] font-extrabold uppercase tracking-[0.18em] text-foreground">
            Money horizon
          </p>
          <h2 id="money-horizon-title" className="mt-1 text-lg font-extrabold tracking-tight">
            {projected === undefined
              ? 'Preparing your month-end runway'
              : projected >= 0
                ? `A ${formatCurrency(projected, currency)} buffer is in view`
                : `${formatCurrency(Math.abs(projected), currency)} needs covering`}
          </h2>
        </div>
        <Badge variant={projected !== undefined && projected < 0 ? 'warning' : 'outline'}>
          Forecast {daysRemaining === null ? 'pending' : `· ${daysRemaining} days`}
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
                index === horizonItems.length - 1 && projected !== undefined && projected < 0
                  ? 'text-danger'
                  : '',
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

      <details className="border-t border-primary/15 pt-2 text-sm">
        <summary className="focus-ring cursor-pointer rounded-md py-2 font-bold text-muted-foreground hover:text-foreground">
          Evidence and forecast assumptions
        </summary>
        {projection ? (
          <div className="mt-2 grid gap-4 pb-2 text-xs leading-5 text-muted-foreground sm:grid-cols-[.7fr_1.3fr]">
            <p>
              Data through{' '}
              <strong className="text-foreground">
                {projection.data_through || 'the selected period'}
              </strong>
              <br />
              Ruleset <strong className="text-foreground">{projection.ruleset_version}</strong>
            </p>
            <ul className="list-disc space-y-1 pl-4">
              {projection.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="pb-2 text-xs text-muted-foreground">
            PFIS will show the source period and deterministic assumptions when projection data is
            ready.
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

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

function fallbackHeadline(netCashFlow: number, name: string) {
  return netCashFlow >= 0
    ? `Good work, ${name}. You are keeping more than you spend.`
    : `Hello, ${name}. This month needs one clear adjustment.`;
}

function formatComparison(value?: number | null) {
  if (value === undefined || value === null) return 'No previous month comparison yet';
  if (value === 0) return 'Unchanged from last month';
  return `${Math.abs(value).toFixed(0)}% ${value > 0 ? 'above' : 'below'} last month`;
}
