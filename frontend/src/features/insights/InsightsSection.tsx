import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ReactNode } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  CalendarRange,
  CircleAlert,
  Repeat2,
  Store,
} from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { ChartFrame } from '@/components/system';
import { Button } from '@/components/ui/Button';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthContext';
import {
  useAdjudicateAnomaly,
  useAdjudicateAnomalySample,
  useAnomalySamples,
  useInsights,
  useMerchants,
  useSummary,
  useWorkspaceSnapshot,
} from '@/features/workspace/queries';
import { formatChartCurrency, formatCompact, formatCurrency, formatDate } from '@/lib/format';

export function InsightsSection(_props: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const { setCategoryDrill, scrollTo } = useDashboardUi();
  const summary = useSummary();
  const insights = useInsights();
  const adjudicateAnomaly = useAdjudicateAnomaly();
  const anomalySamples = useAnomalySamples();
  const adjudicateAnomalySample = useAdjudicateAnomalySample();
  const workspace = useWorkspaceSnapshot();
  const merchantIntelligence = useMerchants();
  const currency = user?.currency ?? 'INR';

  if (summary.isLoading || insights.isLoading || workspace.isLoading) {
    return <Skeleton className="h-[38rem]" />;
  }

  const spend = summary.data?.total_spend ?? 0;
  const income = summary.data?.total_income ?? 0;
  const comparison = workspace.data?.month_comparison;
  const categories = summary.data?.category_breakdown ?? [];
  const merchants = merchantIntelligence.data ?? [];
  const recurring = insights.data?.recurring_payments ?? [];
  const anomalies = insights.data?.anomalies ?? [];
  const samples = anomalySamples.data ?? [];
  const trend = insights.data?.daily_trend ?? [];
  const topCategory = categories[0];
  const spendChange = comparison?.spend_change_pct;
  const conclusion = buildConclusion(topCategory?.name, spendChange);
  const maxCategory = Math.max(...categories.map((item) => item.total), 1);

  return (
    <article className="overflow-hidden rounded-2xl border border-border/70 bg-card">
      <header className="grid gap-7 border-b border-border/70 px-5 py-7 sm:px-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="max-w-3xl">
          <p className="text-xs font-extrabold tracking-[0.12em] text-intelligence">
            MONTHLY INVESTIGATION
          </p>
          <h2 className="mt-3 text-pretty text-3xl font-extrabold tracking-[-0.045em] sm:text-4xl">
            {conclusion}
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            Every conclusion below leads back to observed ledger evidence. Forecasts and recurring
            candidates remain labelled; they are not treated as facts.
          </p>
        </div>
        <div className="max-w-sm text-sm leading-6 text-muted-foreground">
          <p>
            <span className="font-extrabold text-foreground">
              {formatCurrency(spend, currency)} observed spend
            </span>{' '}
            against {formatCurrency(income, currency)} observed income.
          </p>
          <p className="mt-2 text-xs">
            {spendChange == null
              ? 'There is no prior-month baseline yet.'
              : `${formatChange(spendChange)} versus the prior month.`}
          </p>
        </div>
      </header>

      <div className="grid lg:grid-cols-[minmax(0,1.55fr)_minmax(18rem,0.75fr)]">
        <section className="min-w-0 px-5 py-7 sm:px-8 lg:border-r lg:border-border/70">
          <SectionHeading
            index="01"
            title="Where the movement happened"
            description="Daily observed debit spend. Peaks are investigation points, not balance changes."
          />
          {trend.length ? (
            <div className="mt-6">
              <ChartFrame
                title="Observed spend by day"
                description={`Daily debit spend · ${currency} · ${formatDate(trend[0].date)} to ${formatDate(trend[trend.length - 1].date)}`}
                summary={`Daily observed debit spend from ${formatDate(trend[0].date)} to ${formatDate(trend[trend.length - 1].date)}. Peaks are investigation points, not balance changes.`}
                dataTable={
                  <table className="w-full min-w-[28rem] text-left text-sm">
                    <caption className="sr-only">
                      Daily observed debit spend and entry count
                    </caption>
                    <thead>
                      <tr className="border-b border-border/65 text-xs text-muted-foreground">
                        <th scope="col" className="px-2 py-2">
                          Date
                        </th>
                        <th scope="col" className="px-2 py-2 text-right">
                          Spend ({currency})
                        </th>
                        <th scope="col" className="px-2 py-2 text-right">
                          Entries
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {trend.map((point) => (
                        <tr key={point.date} className="border-b border-border/45 last:border-0">
                          <th scope="row" className="px-2 py-2 font-bold">
                            {formatDate(point.date)}
                          </th>
                          <td className="money-value px-2 py-2 text-right">
                            {formatCurrency(point.total, currency)}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums">
                            {point.count ?? '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                }
              >
                <div className="h-72 min-w-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={trend} margin={{ left: 4, right: 12, top: 8, bottom: 4 }}>
                      <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
                      <XAxis
                        dataKey="date"
                        tickFormatter={(value) => formatDate(String(value))}
                        tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                        interval="preserveStartEnd"
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                        tickFormatter={(value) => formatCompact(value)}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        formatter={(value) => formatChartCurrency(value, currency)}
                        contentStyle={{
                          background: 'hsl(var(--card))',
                          border: '1px solid hsl(var(--border))',
                          borderRadius: 10,
                          color: 'hsl(var(--card-foreground))',
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="total"
                        name={`Daily spend (${currency})`}
                        stroke="hsl(var(--intelligence))"
                        strokeWidth={3}
                        dot={false}
                        activeDot={{ r: 5 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </ChartFrame>
            </div>
          ) : (
            <EmptyState
              icon={<CalendarRange />}
              title="No daily evidence yet"
              description="Add or sync a few activities and PFIS will turn them into a traceable timeline."
              action={
                <Button variant="outline" onClick={() => scrollTo('transactions')}>
                  Open activity <ArrowRight className="h-4 w-4" />
                </Button>
              }
            />
          )}
        </section>

        <aside className="px-5 py-7 sm:px-8" aria-labelledby="evidence-spine-title">
          <SectionHeading
            index="EVIDENCE"
            title="Why it changed"
            description="The shortest path from the monthly conclusion to its supporting records."
            id="evidence-spine-title"
          />
          <ol className="relative mt-6 space-y-0 before:absolute before:bottom-5 before:left-[0.68rem] before:top-5 before:w-px before:bg-border">
            {(comparison?.category_deltas ?? []).slice(0, 4).map((delta) => (
              <li
                key={delta.category}
                className="relative grid grid-cols-[1.4rem_minmax(0,1fr)] gap-3 py-3"
              >
                <span className="relative z-10 mt-1 h-5 w-5 rounded-full border-4 border-card bg-intelligence" />
                <div>
                  <p className="font-bold">{delta.category}</p>
                  <p className="mt-0.5 text-sm leading-5 text-muted-foreground">
                    {formatCurrency(delta.current, currency)}
                    {delta.change_pct == null
                      ? ' with no prior baseline'
                      : ` · ${formatChange(delta.change_pct)} from prior month`}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <Button
            variant="outline"
            className="mt-5 w-full"
            onClick={() => scrollTo('transactions')}
          >
            Inspect ledger evidence <ArrowRight className="h-4 w-4" />
          </Button>
        </aside>
      </div>

      <section className="border-t border-border/70 px-5 py-7 sm:px-8">
        <SectionHeading
          index="02"
          title="Ranked drivers"
          description="Start with the largest measured contributor, then open its ledger evidence."
        />
        <div className="mt-6 divide-y divide-border/65">
          {categories.length ? (
            categories.slice(0, 8).map((category, index) => (
              <button
                type="button"
                key={category.name}
                onClick={() => {
                  setCategoryDrill({ categoryId: category.name, label: category.name });
                  scrollTo('transactions');
                }}
                className="focus-ring grid min-h-14 w-full grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3 rounded text-left"
              >
                <span className="text-sm font-extrabold text-muted-foreground">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <span className="min-w-0">
                  <span className="flex items-baseline justify-between gap-4">
                    <span className="truncate font-bold">{category.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {category.count} entries
                    </span>
                  </span>
                  <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-muted">
                    <span
                      className="block h-full rounded-full bg-intelligence"
                      style={{ width: `${(category.total / maxCategory) * 100}%` }}
                    />
                  </span>
                </span>
                <span className="money-value pl-2 text-sm font-extrabold">
                  {formatCurrency(category.total, currency)}
                </span>
              </button>
            ))
          ) : (
            <div className="rounded-xl bg-muted/45 px-4 py-5 text-sm text-muted-foreground">
              Ranked drivers will appear after PFIS has observed classified activity.
            </div>
          )}
        </div>
      </section>

      {anomalies.length ? (
        <section className="border-t border-border/70 px-5 py-7 sm:px-8">
          <SectionHeading
            index="03"
            title="Departures from your rhythm"
            description="Material category and merchant changes against your own 24-month history, with seasonal context when repeated same-month evidence exists. These are review signals, not fraud claims."
          />
          <div className="mt-6 grid gap-4 xl:grid-cols-2">
            {anomalies.map((anomaly) => (
              <article
                key={anomaly.id}
                className="rounded-2xl border border-warning/25 bg-warning/5 p-4 sm:p-5"
              >
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 rounded-xl bg-warning/15 p-2 text-warning">
                    <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate font-extrabold">{anomaly.label}</h3>
                      <span className="rounded-full border border-warning/30 px-2 py-0.5 text-[0.65rem] font-extrabold uppercase tracking-[0.08em] text-warning">
                        {anomaly.kind}
                      </span>
                    </div>
                    <p className="mt-1 text-sm leading-5 text-muted-foreground">
                      {formatCurrency(anomaly.current_amount, currency)} this month vs{' '}
                      {formatCurrency(anomaly.baseline_amount, currency)} typical ·{' '}
                      {formatChange(anomaly.delta_pct)} above baseline
                    </p>
                  </div>
                </div>
                <dl className="mt-5 grid grid-cols-3 gap-3 border-t border-warning/20 pt-4 text-xs">
                  <div>
                    <dt className="font-bold text-muted-foreground">Change</dt>
                    <dd className="money-value mt-1 text-sm font-extrabold">
                      {formatCurrency(anomaly.delta_amount, currency)}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-bold text-muted-foreground">History</dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {anomaly.history_periods} months
                    </dd>
                  </div>
                  <div>
                    <dt className="font-bold text-muted-foreground">Confidence</dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {Math.round(anomaly.confidence * 100)}%
                    </dd>
                  </div>
                </dl>
                <details className="mt-4 border-t border-warning/20 pt-2 text-xs text-muted-foreground">
                  <summary className="focus-ring cursor-pointer rounded py-2 font-bold text-foreground">
                    Show evidence and assumptions
                  </summary>
                  <div className="mt-2 grid gap-4 sm:grid-cols-2">
                    <ul className="space-y-1.5">
                      {anomaly.evidence.map((item) => (
                        <li key={item.label} className="flex justify-between gap-3">
                          <span>{item.label}</span>
                          <span className="font-bold text-foreground">{item.value}</span>
                        </li>
                      ))}
                    </ul>
                    <ul className="list-disc space-y-1 pl-4 leading-5">
                      {anomaly.assumptions.map((assumption) => (
                        <li key={assumption}>{assumption}</li>
                      ))}
                    </ul>
                  </div>
                </details>
                <div className="mt-4 border-t border-warning/20 pt-4">
                  <p className="text-xs font-bold text-muted-foreground">
                    Was this departure useful to flag?
                  </p>
                  <div
                    className="mt-2 flex flex-wrap gap-2"
                    role="group"
                    aria-label={`Adjudicate ${anomaly.label}`}
                  >
                    {(
                      [
                        ['expected', 'Expected'],
                        ['material', 'Material'],
                        ['insufficient_evidence', 'Not enough evidence'],
                      ] as const
                    ).map(([decision, label]) => (
                      <Button
                        key={decision}
                        size="sm"
                        variant={anomaly.adjudication === decision ? 'secondary' : 'outline'}
                        disabled={adjudicateAnomaly.isPending}
                        aria-pressed={anomaly.adjudication === decision}
                        onClick={() =>
                          adjudicateAnomaly.mutate({ anomalyId: anomaly.id, decision })
                        }
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                  {adjudicateAnomaly.isError ? (
                    <p className="mt-2 text-xs text-danger" role="status">
                      This decision could not be saved. The anomaly remains a review signal.
                    </p>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {samples.length ? (
        <section className="border-t border-border/70 px-5 py-7 sm:px-8">
          <SectionHeading
            index="04"
            title="Calibration sample"
            description="PFIS also asks about ordinary activity that did not trigger an alert. These balanced labels help measure recall and false-positive rate without treating the answer as a fraud claim."
          />
          <div className="mt-6 grid gap-4 xl:grid-cols-2">
            {samples.map((sample) => (
              <article
                key={sample.id}
                className="rounded-2xl border border-border/70 bg-muted/20 p-4 sm:p-5"
              >
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 rounded-xl bg-muted p-2 text-muted-foreground">
                    <CircleAlert className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate font-extrabold">{sample.label}</h3>
                      <span className="rounded-full border border-border px-2 py-0.5 text-[0.65rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
                        {sample.kind} · no alert
                      </span>
                    </div>
                    <p className="mt-1 text-sm leading-5 text-muted-foreground">
                      {formatCurrency(sample.current_amount, currency)} this month vs{' '}
                      {formatCurrency(sample.baseline_amount, currency)} typical
                    </p>
                  </div>
                </div>
                <div className="mt-4 border-t border-border/70 pt-4">
                  <p className="text-xs font-bold text-muted-foreground">
                    Was this ordinary activity actually material?
                  </p>
                  <div
                    className="mt-2 flex flex-wrap gap-2"
                    role="group"
                    aria-label={`Adjudicate calibration sample ${sample.label}`}
                  >
                    {(
                      [
                        ['expected', 'Expected'],
                        ['material', 'Material'],
                        ['insufficient_evidence', 'Not enough evidence'],
                      ] as const
                    ).map(([decision, label]) => (
                      <Button
                        key={decision}
                        size="sm"
                        variant={sample.adjudication === decision ? 'secondary' : 'outline'}
                        disabled={adjudicateAnomalySample.isPending}
                        aria-pressed={sample.adjudication === decision}
                        onClick={() =>
                          adjudicateAnomalySample.mutate({ sampleId: sample.id, decision })
                        }
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                  {adjudicateAnomalySample.isError ? (
                    <p className="mt-2 text-xs text-danger" role="status">
                      This calibration label could not be saved.
                    </p>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <div className="grid border-t border-border/70 lg:grid-cols-2">
        <EvidenceList
          icon={<Store className="h-4 w-4" />}
          title="Merchant concentration"
          description="Canonical merchant identities, not raw statement descriptors."
          empty="No resolved merchant evidence yet."
          rows={merchants.slice(0, 6).map((merchant) => ({
            key: merchant.merchant_key,
            label: merchant.name,
            meta: `${merchant.transaction_count} entries · ${merchant.data_sufficiency} evidence`,
            value: formatCurrency(merchant.total_spend, currency),
          }))}
        />
        <EvidenceList
          icon={<Repeat2 className="h-4 w-4" />}
          title="Recurring candidates"
          description="History-based patterns remain candidates until the evidence matures."
          empty="No recurring pattern has enough evidence."
          className="border-t border-border/70 lg:border-l lg:border-t-0"
          rows={recurring.slice(0, 6).map((item) => ({
            key: item.merchant,
            label: item.merchant,
            meta: `${item.status} · ${Math.round(item.confidence * 100)}% confidence`,
            value: `${formatCurrency(item.monthly_equivalent, currency)}/mo`,
          }))}
        />
      </div>

      {(workspace.data?.review_summary?.pending_count ?? 0) > 0 ? (
        <footer className="bg-warning/7 flex flex-col gap-3 border-t border-warning/25 px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <p className="flex items-start gap-2 text-sm leading-6">
            <CircleAlert className="mt-1 h-4 w-4 shrink-0 text-warning" />
            <span>
              <strong>{workspace.data?.review_summary?.pending_count} unresolved records</strong>{' '}
              can still change merchant and category conclusions.
            </span>
          </p>
          <Button variant="outline" onClick={() => scrollTo('review')}>
            Resolve evidence
          </Button>
        </footer>
      ) : null}
    </article>
  );
}

function SectionHeading({
  index,
  title,
  description,
  id,
}: {
  index: string;
  title: string;
  description: string;
  id?: string;
}) {
  return (
    <div>
      <p className="text-xs font-extrabold tracking-[0.1em] text-muted-foreground">{index}</p>
      <h3 id={id} className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
        {title}
      </h3>
      <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>
    </div>
  );
}

function EvidenceList({
  icon,
  title,
  description,
  empty,
  rows,
  className = '',
}: {
  icon: ReactNode;
  title: string;
  description: string;
  empty: string;
  rows: Array<{ key: string; label: string; meta: string; value: string }>;
  className?: string;
}) {
  return (
    <section className={`px-5 py-7 sm:px-8 ${className}`}>
      <h3 className="flex items-center gap-2 text-lg font-extrabold">
        <span className="text-intelligence">{icon}</span> {title}
      </h3>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p>
      {rows.length ? (
        <div className="mt-5 divide-y divide-border/65">
          {rows.map((row) => (
            <div
              key={row.key}
              className="grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-2"
            >
              <span className="min-w-0">
                <span className="block truncate font-bold">{row.label}</span>
                <span className="block truncate text-xs text-muted-foreground">{row.meta}</span>
              </span>
              <span className="money-value whitespace-nowrap text-sm font-extrabold">
                {row.value}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-5 text-sm text-muted-foreground">{empty}</p>
      )}
    </section>
  );
}

function buildConclusion(category: string | undefined, change: number | null | undefined) {
  if (!category) return 'The month needs more classified evidence.';
  if (change == null) return `${category} is the largest observed driver this month.`;
  if (change > 0) return `${category} leads a ${Math.abs(change).toFixed(1)}% rise in spending.`;
  if (change < 0) return `Spending is down ${Math.abs(change).toFixed(1)}%, led by ${category}.`;
  return `Spending is steady, with ${category} still the largest driver.`;
}

function formatChange(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}
