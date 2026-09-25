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
import { ExplainAction } from '@/features/ai/ExplainAction';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import {
  useAdjudicateAnomaly,
  useAdjudicateAnomalySample,
  useAnomalySamples,
  useInsights,
  useMerchants,
  useSummary,
  useWorkspaceSnapshot,
} from '@/features/workspace/queries';
import { useMonthlySnapshot } from '@/features/insights/monthlySnapshotQueries';
import {
  formatChartAxisCurrency,
  formatChartCurrency,
  formatChartDate,
  formatCurrency,
  formatDate,
} from '@/lib/format';
import type { ExplainPayload, MonthlySnapshotResponse } from '@/lib/types';

export function InsightsSection(_props: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const { setCategoryDrill, scrollTo } = useDashboardUi();
  const { month, year } = useWorkspace();
  const summary = useSummary();
  const insights = useInsights();
  const adjudicateAnomaly = useAdjudicateAnomaly();
  const anomalySamples = useAnomalySamples();
  const adjudicateAnomalySample = useAdjudicateAnomalySample();
  const workspace = useWorkspaceSnapshot();
  const monthlySnapshot = useMonthlySnapshot();
  const merchantIntelligence = useMerchants();
  const currency = user?.currency ?? 'INR';

  if (summary.isLoading || insights.isLoading || workspace.isLoading || monthlySnapshot.isLoading) {
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
  const trend = (insights.data?.daily_trend ?? []).map((point) => {
    if (!Number.isInteger(point.day) || point.day == null || point.day < 1) return point;
    const date = new Date(year, month - 1, point.day);
    if (date.getMonth() !== month - 1) return point;
    return {
      ...point,
      date: `${year}-${String(month).padStart(2, '0')}-${String(point.day).padStart(2, '0')}`,
    };
  });
  const hasDailySpendEvidence = trend.some((point) => point.total > 0);
  const topCategory = categories[0];
  const spendChange = comparison?.spend_change_pct;
  const conclusion = buildConclusion(topCategory?.name, spendChange);
  const categoryDeltas = new Map(
    (comparison?.category_deltas ?? []).map((delta) => [delta.category, delta]),
  );

  return (
    <article className="min-w-0">
      <MonthlySnapshotBrief
        snapshot={monthlySnapshot.data}
        currency={currency}
        month={month}
        year={year}
        userId={user?.id}
      />

      <header className="grid gap-4 border-b border-border/70 pb-5 sm:gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="max-w-3xl">
          <p className="text-xs font-extrabold tracking-[0.12em] text-intelligence">
            MONTHLY INVESTIGATION
          </p>
          <h2 className="mt-2 text-pretty text-2xl font-extrabold tracking-[-0.04em] sm:text-3xl">
            {conclusion}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Every conclusion below leads back to observed ledger evidence. Forecasts and recurring
            candidates remain labelled; they are not treated as facts.
          </p>
        </div>
        <div className="text-sm leading-6 text-muted-foreground lg:max-w-xs">
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
        <section className="min-w-0 py-6 lg:pr-8">
          <SectionHeading
            index="01"
            title="Where the movement happened"
            description="Daily observed debit spend. Peaks are investigation points, not balance changes."
          />
          {hasDailySpendEvidence ? (
            <div className="mt-6">
              <ChartFrame
                title="Observed spend by day"
                description={
                  <>
                    <span>
                      Daily debit spend · {currency} · {formatDate(trend[0].date)} to{' '}
                      {formatDate(trend[trend.length - 1].date)}
                    </span>
                    <span className="mt-1 block font-semibold text-foreground">
                      Takeaway: higher plotted days are investigation points, not balance changes.
                    </span>
                  </>
                }
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
                        tickFormatter={formatChartDate}
                        tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                        interval="preserveStartEnd"
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                        tickFormatter={(value) => formatChartAxisCurrency(value, currency)}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        formatter={(value) => formatChartCurrency(value, currency)}
                        labelFormatter={(value) => formatDate(String(value))}
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
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </ChartFrame>
            </div>
          ) : (
            <EmptyState
              icon={<CalendarRange />}
              title="No debit activity this month"
              description="There is nothing to plot for this period yet. Add or sync debit activity to build a traceable daily timeline."
              action={
                <Button variant="outline" onClick={() => scrollTo('transactions')}>
                  Open activity <ArrowRight className="h-4 w-4" />
                </Button>
              }
            />
          )}
        </section>

        <aside
          className="border-t border-border/70 py-6 lg:border-l lg:border-t-0 lg:pl-8"
          aria-labelledby="drivers-title"
        >
          <SectionHeading
            index="02"
            title="Largest measured drivers"
            description="Select a category to inspect its ledger records and confirm what shaped the month."
            id="drivers-title"
          />
          {categories.length ? (
            <ol className="mt-4 divide-y divide-border/65">
              {categories.slice(0, 5).map((category, index) => {
                const delta = categoryDeltas.get(category.name);
                return (
                  <li key={category.name}>
                    <div className="grid gap-2 py-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                      <button
                        type="button"
                        onClick={() => {
                          setCategoryDrill({ categoryId: category.name, label: category.name });
                          scrollTo('transactions');
                        }}
                        className="focus-ring grid min-h-14 w-full grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-2 rounded text-left"
                      >
                        <span className="text-xs font-extrabold text-muted-foreground">
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-bold">{category.name}</span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {category.count} entries
                            {delta?.change_pct == null
                              ? ' · no prior baseline'
                              : ` · ${formatChange(delta.change_pct)} vs prior month`}
                          </span>
                        </span>
                        <span className="money-value pl-1 text-right text-sm font-extrabold">
                          {formatCurrency(category.total, currency)}
                        </span>
                      </button>
                      <ExplainAction
                        userId={user?.id}
                        payload={{
                          month,
                          year,
                          subject_id: category.name,
                          surface: 'insights_driver',
                          title: category.name,
                          description: `${category.count} ledger entries make this a leading monthly driver.`,
                          metrics: {
                            total: category.total,
                            count: category.count,
                            change_pct: delta?.change_pct,
                          },
                        }}
                      />
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="mt-4 text-sm text-muted-foreground">
              Drivers will appear after PFIS has observed classified activity.
            </p>
          )}
        </aside>
      </div>

      {anomalies.length ? (
        <section className="border-t border-border/70 py-7">
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
                <div className="mt-4 flex flex-wrap justify-end border-t border-warning/20 pt-4">
                  <ExplainAction
                    userId={user?.id}
                    payload={{
                      month,
                      year,
                      subject_id: anomaly.id,
                      surface: 'insights_anomaly',
                      title: anomaly.label,
                      description: `${anomaly.kind} departure compared with the user’s own history.`,
                      metrics: {
                        current_amount: anomaly.current_amount,
                        baseline_amount: anomaly.baseline_amount,
                        delta_pct: anomaly.delta_pct,
                        confidence: anomaly.confidence,
                      },
                    }}
                  />
                </div>
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
        <section className="border-t border-border/70 py-7">
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
            explainPayload: {
              month,
              year,
              subject_id: merchant.merchant_key,
              surface: 'insights_merchant',
              title: merchant.name,
              description: 'Merchant concentration in the selected month.',
              metrics: {
                total_spend: merchant.total_spend,
                transaction_count: merchant.transaction_count,
                avg_spend: merchant.avg_spend,
              },
            },
          }))}
          userId={user?.id}
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
            explainPayload: {
              month,
              year,
              subject_id: item.merchant,
              surface: 'insights_recurring',
              title: item.merchant,
              description: 'History-based recurring candidate in the selected month.',
              metrics: {
                monthly_equivalent: item.monthly_equivalent,
                occurrences: item.occurrences,
                confidence: item.confidence,
              },
            },
          }))}
          userId={user?.id}
        />
      </div>

      {(workspace.data?.review_summary?.pending_count ?? 0) > 0 ? (
        <footer className="bg-warning/7 flex flex-col gap-3 border-t border-warning/25 py-5 sm:flex-row sm:items-center sm:justify-between">
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

function MonthlySnapshotBrief({
  snapshot,
  currency,
  month,
  year,
  userId,
}: {
  snapshot?: MonthlySnapshotResponse;
  currency: string;
  month: number;
  year: number;
  userId?: string;
}) {
  if (!snapshot) {
    return (
      <section className="mb-6 rounded-3xl border border-border/70 bg-muted/25 p-5">
        <p className="text-sm text-muted-foreground">
          This month in brief is unavailable. The driver evidence below remains visible.
        </p>
      </section>
    );
  }

  const coverage = snapshot.coverage;
  const coverageLabel = coverage.incomplete_month ? 'Incomplete month' : 'Complete period';
  const coverageDetail = buildCoverageDetail(coverage);
  const leadCategory = snapshot.top_categories[0];
  const leadMerchant = snapshot.top_merchants[0];
  const attentionBudget = snapshot.budget_status.find((budget) =>
    ['warning', 'danger', 'over', 'over_budget', 'at_risk'].includes(budget.status),
  );
  const primaryAnomaly = snapshot.notable_anomalies[0];
  const primaryRecurring = snapshot.recurring_changes[0];

  return (
    <section
      aria-labelledby="monthly-snapshot-title"
      className="mb-6 rounded-3xl border border-intelligence/20 bg-intelligence/5 p-5 sm:p-6"
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(17rem,0.55fr)]">
        <div className="min-w-0">
          <p className="text-xs font-extrabold tracking-[0.12em] text-intelligence">
            THIS MONTH IN BRIEF
          </p>
          <h2
            id="monthly-snapshot-title"
            className="mt-2 text-pretty text-2xl font-extrabold tracking-[-0.04em]"
          >
            {buildSnapshotHeadline(snapshot, currency)}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            PFIS is reading {snapshot.transaction_count} ledger records for {snapshot.month_label}.
            Income, spend, and net are server-computed; recurring streams, anomalies, and budgets
            stay labelled by evidence quality.
          </p>

          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            <SnapshotMetric label="Income" value={formatCurrency(snapshot.income, currency)} />
            <SnapshotMetric label="Spend" value={formatCurrency(snapshot.spend, currency)} />
            <SnapshotMetric label="Net" value={formatCurrency(snapshot.net, currency)} />
          </div>
        </div>

        <aside className="rounded-2xl border border-border/70 bg-card/65 p-4">
          <p className="text-xs font-extrabold uppercase tracking-[0.1em] text-muted-foreground">
            Coverage
          </p>
          <p className="mt-2 font-extrabold">{coverageLabel}</p>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{coverageDetail}</p>
        </aside>
      </div>

      <div className="mt-5 grid gap-3 lg:grid-cols-2">
        <NarrativeEvidence
          title="Top categories"
          empty="No categorized spend is available yet."
          rows={snapshot.top_categories.slice(0, 3).map((category) => ({
            key: category.category_id ?? category.name,
            label: category.name,
            value: formatCurrency(category.total, currency),
            detail: `${category.count} entries`,
          }))}
        />
        <NarrativeEvidence
          title="Top merchants"
          empty="No merchant concentration is available yet."
          rows={snapshot.top_merchants.slice(0, 3).map((merchant) => ({
            key: merchant.name,
            label: merchant.name,
            value: formatCurrency(merchant.total, currency),
            detail: `${merchant.count} entries`,
          }))}
        />
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <SnapshotSignal
          title="Budget status"
          value={
            attentionBudget
              ? `${attentionBudget.category ?? 'A budget'} is ${attentionBudget.status.replaceAll('_', ' ')}`
              : snapshot.budget_status.length
                ? 'No budget is flagged'
                : 'No budget evidence'
          }
          detail={
            attentionBudget
              ? `${formatCurrency(attentionBudget.actual, currency)} of ${formatCurrency(
                  attentionBudget.limit,
                  currency,
                )} observed.`
              : 'Budget rows come directly from the monthly snapshot.'
          }
        />
        <SnapshotSignal
          title="Recurring changes"
          value={
            primaryRecurring?.merchant
              ? `${primaryRecurring.merchant} is ${primaryRecurring.status ?? 'tracked'}`
              : 'No recurring change flagged'
          }
          detail={
            primaryRecurring?.monthly_equivalent == null
              ? 'Recurring candidates remain estimates until evidence matures.'
              : `${formatCurrency(primaryRecurring.monthly_equivalent, currency)} monthly equivalent · ${primaryRecurring.data_sufficiency ?? 'unknown'} evidence.`
          }
        />
        <SnapshotSignal
          title="Anomalies"
          value={
            primaryAnomaly?.label ? `${primaryAnomaly.label} needs review` : 'No anomaly flagged'
          }
          detail={
            primaryAnomaly?.current_amount == null
              ? 'PFIS found no material departure in the snapshot.'
              : `${formatCurrency(primaryAnomaly.current_amount, currency)} observed; not a fraud claim.`
          }
        />
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-intelligence/20 pt-4">
        <p className="text-sm leading-6 text-muted-foreground">
          Takeaway: {buildSnapshotTakeaway(leadCategory?.name, leadMerchant?.name, snapshot)}
        </p>
        <ExplainAction
          userId={userId}
          payload={{
            month,
            year,
            subject_id: snapshot.month_label,
            surface: 'insights_monthly_snapshot',
            title: 'This month in brief',
            description: `Monthly snapshot for ${snapshot.month_label} with coverage labelled ${coverageLabel.toLowerCase()}.`,
            metrics: {
              income: snapshot.income,
              spend: snapshot.spend,
              net: snapshot.net,
              transaction_count: snapshot.transaction_count,
            },
          }}
        />
      </div>
    </section>
  );
}

function SnapshotMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border/70 bg-card/70 p-3">
      <p className="text-xs font-bold text-muted-foreground">{label}</p>
      <p className="money-value mt-1 text-lg font-extrabold">{value}</p>
    </div>
  );
}

function NarrativeEvidence({
  title,
  empty,
  rows,
}: {
  title: string;
  empty: string;
  rows: Array<{ key: string; label: string; value: string; detail: string }>;
}) {
  return (
    <section className="rounded-2xl border border-border/70 bg-card/55 p-4">
      <h3 className="text-sm font-extrabold">{title}</h3>
      {rows.length ? (
        <ul className="mt-3 grid gap-2">
          {rows.map((row) => (
            <li key={row.key} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 text-sm">
              <span className="min-w-0">
                <span className="block truncate font-bold">{row.label}</span>
                <span className="block truncate text-xs text-muted-foreground">{row.detail}</span>
              </span>
              <span className="money-value font-extrabold">{row.value}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">{empty}</p>
      )}
    </section>
  );
}

function SnapshotSignal({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <section className="rounded-2xl border border-border/70 bg-card/55 p-4">
      <h3 className="text-sm font-extrabold">{title}</h3>
      <p className="mt-2 text-sm font-bold">{value}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p>
    </section>
  );
}

function EvidenceList({
  icon,
  title,
  description,
  empty,
  rows,
  userId,
  className = '',
}: {
  icon: ReactNode;
  title: string;
  description: string;
  empty: string;
  rows: Array<{
    key: string;
    label: string;
    meta: string;
    value: string;
    explainPayload?: ExplainPayload;
  }>;
  userId?: string;
  className?: string;
}) {
  return (
    <section className={`py-7 ${className}`}>
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
              <span className="flex flex-wrap items-center justify-end gap-2">
                <span className="money-value whitespace-nowrap text-sm font-extrabold">
                  {row.value}
                </span>
                {row.explainPayload ? (
                  <ExplainAction userId={userId} payload={row.explainPayload} />
                ) : null}
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

function buildSnapshotHeadline(snapshot: MonthlySnapshotResponse, currency: string): string {
  if (snapshot.transaction_count === 0) {
    return `${snapshot.month_label} needs more evidence before PFIS can explain the month.`;
  }
  const direction =
    snapshot.net > 0 ? 'positive net movement' : snapshot.net < 0 ? 'negative net movement' : 'flat net movement';
  return `${snapshot.month_label} shows ${direction}: ${formatCurrency(snapshot.net, currency)} net.`;
}

function buildSnapshotTakeaway(
  category: string | undefined,
  merchant: string | undefined,
  snapshot: MonthlySnapshotResponse,
): string {
  if (snapshot.transaction_count === 0) return 'connect or import activity before reading patterns.';
  if (category && merchant) return `${category} and ${merchant} are the first places to inspect.`;
  if (category) return `${category} is the first category to inspect.`;
  if (merchant) return `${merchant} is the first merchant to inspect.`;
  return 'PFIS has totals but not enough ranked evidence yet.';
}

function buildCoverageDetail(coverage: MonthlySnapshotResponse['coverage']): string {
  const latest = coverage.latest_transaction_date
    ? `latest ledger activity ${formatDate(coverage.latest_transaction_date)}`
    : 'no ledger activity dated in this period';
  const freshness =
    coverage.data_freshness_days == null
      ? 'freshness unknown'
      : `${coverage.data_freshness_days} day(s) since latest activity`;
  const sync = coverage.latest_sync_status
    ? `sync ${coverage.latest_sync_status}${coverage.last_synced_at ? ` at ${formatDate(coverage.last_synced_at)}` : ''}`
    : 'sync status unavailable';
  return `${latest}; ${freshness}; ${sync}.`;
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
