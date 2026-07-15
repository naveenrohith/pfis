import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts';
import { BarChart3, Lightbulb, Store, Repeat, TrendingDown, TrendingUp } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { ChartCard } from '@/components/cards/ChartCard';
import { InsightCard } from '@/components/cards/InsightCard';
import { useInsights, useMonthComparison, useSummary } from '@/features/workspace/queries';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency, formatCompact } from '@/lib/format';
import { CHART_COLORS } from '@/lib/colors';

export function InsightsSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const insights = useInsights();
  const summary = useSummary();
  const comparison = useMonthComparison();
  const { setCategoryDrill, scrollTo } = useDashboardUi();
  const currency = user?.currency ?? 'INR';

  const breakdown = summary.data?.category_breakdown ?? [];
  const merchants = summary.data?.top_merchants ?? [];
  const trend = insights.data?.daily_trend ?? [];
  const recurring = insights.data?.recurring_payments ?? [];
  const cards = insights.data?.insights ?? [];

  const pieData = breakdown.map((c) => ({ name: c.name, value: c.total }));
  const totalCategorySpend = breakdown.reduce((sum, category) => sum + category.total, 0);
  const topCategory = breakdown[0];
  const peakDay = trend.reduce<(typeof trend)[number] | null>(
    (peak, point) => (!peak || point.total > peak.total ? point : peak),
    null,
  );

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Insights"
          title="Drivers and patterns"
          description="Historical evidence: where money went, when spending moved, and what changed from last month."
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Category breakdown"
          description="Click a category to drill into matching transactions."
          loading={summary.isLoading}
          chartSummary={
            topCategory
              ? `${topCategory.name} is the largest category at ${formatCurrency(topCategory.total, currency)} out of ${formatCurrency(totalCategorySpend, currency)} categorized spend.`
              : 'No categorized spending is available.'
          }
          context="The ring shows each category's share of categorized debit spending. Use the adjacent category buttons for transaction drill-down."
          dataTable={
            breakdown.length > 0 ? (
              <table className="w-full text-left text-xs">
                <caption className="sr-only">Category spending data</caption>
                <thead>
                  <tr className="text-muted-foreground">
                    <th className="px-2 py-1">Category</th>
                    <th className="px-2 py-1 text-right">Spend</th>
                    <th className="px-2 py-1 text-right">Transactions</th>
                  </tr>
                </thead>
                <tbody>
                  {breakdown.map((category) => (
                    <tr key={category.name} className="border-t border-border">
                      <td className="px-2 py-1.5">{category.name}</td>
                      <td className="px-2 py-1.5 text-right">
                        {formatCurrency(category.total, currency)}
                      </td>
                      <td className="px-2 py-1.5 text-right">{category.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : undefined
          }
        >
          {pieData.length === 0 ? (
            <EmptyState
              icon={<BarChart3 />}
              title="No spending yet"
              description="Categorized spending will appear here."
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <div role="img" aria-label="Category spending share chart">
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={58}
                      outerRadius={90}
                      paddingAngle={2}
                    >
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value: number) => formatCurrency(value, currency)}
                      contentStyle={{
                        background: 'hsl(var(--card))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: 8,
                        color: 'hsl(var(--card-foreground))',
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="grid content-center gap-1.5">
                {breakdown.slice(0, 6).map((c, i) => (
                  <button
                    key={c.name}
                    onClick={() => {
                      setCategoryDrill({ categoryId: c.name, label: c.name });
                      scrollTo('transactions');
                    }}
                    className="dashboard-row flex items-center justify-between gap-2 text-sm"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
                      />
                      <span className="truncate">
                        {c.icon} {c.name}
                      </span>
                    </span>
                    <span className="shrink-0 font-semibold">
                      {formatCurrency(c.total, currency)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </ChartCard>

        <ChartCard
          title="Daily spend trend"
          description="Track day-by-day spending concentration."
          loading={insights.isLoading}
          chartSummary={
            peakDay
              ? `The highest recorded day is ${peakDay.date} at ${formatCurrency(peakDay.total, currency)} across ${trend.length} plotted days.`
              : 'No daily spending trend is available.'
          }
          context="Each point is total debit spending recorded for that day. Peaks identify dates worth investigating; they do not represent account balance."
          dataTable={
            trend.length > 0 ? (
              <table className="w-full text-left text-xs">
                <caption className="sr-only">Daily spending trend data</caption>
                <thead>
                  <tr className="text-muted-foreground">
                    <th className="px-2 py-1">Date</th>
                    <th className="px-2 py-1 text-right">Spend</th>
                    <th className="px-2 py-1 text-right">Transactions</th>
                  </tr>
                </thead>
                <tbody>
                  {trend.map((point) => (
                    <tr key={point.date} className="border-t border-border">
                      <td className="px-2 py-1.5">{point.date}</td>
                      <td className="px-2 py-1.5 text-right">
                        {formatCurrency(point.total, currency)}
                      </td>
                      <td className="px-2 py-1.5 text-right">{point.count ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : undefined
          }
        >
          {trend.length === 0 ? (
            <EmptyState
              icon={<TrendingUp />}
              title="No trend data"
              description="Daily spending will plot here."
            />
          ) : (
            <div role="img" aria-label="Daily spending trend chart">
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={trend} margin={{ left: -12, right: 8, top: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                    tickFormatter={(v) => formatCompact(v)}
                  />
                  <Tooltip
                    formatter={(value: number) => formatCurrency(value, currency)}
                    contentStyle={{
                      background: 'hsl(var(--card))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: 8,
                      color: 'hsl(var(--card-foreground))',
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="total"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2.5}
                    dot={{ r: 2 }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="grid gap-2 p-4 sm:p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Lightbulb className="h-4 w-4 text-warning" /> Smart insights
            </h3>
            {insights.isLoading ? (
              <Skeleton className="h-40" />
            ) : cards.length === 0 ? (
              <EmptyState icon={<Lightbulb />} title="No insights yet" />
            ) : (
              cards.map((card, i) => (
                <InsightCard
                  key={i}
                  icon={card.icon}
                  title={card.title}
                  description={card.description}
                  severity={card.severity}
                />
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="grid gap-3 p-4 sm:p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <TrendingDown className="h-4 w-4 text-warning" /> Month over month
            </h3>
            {comparison.isLoading ? (
              <Skeleton className="h-36" />
            ) : comparison.data ? (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <ComparisonMetric
                    label="Spend"
                    value={formatCurrency(comparison.data.spend, currency)}
                  />
                  <ComparisonMetric
                    label="Spend change"
                    value={formatChange(comparison.data.spend_change_pct)}
                  />
                  <ComparisonMetric
                    label="Income"
                    value={formatCurrency(comparison.data.income, currency)}
                  />
                  <ComparisonMetric
                    label="Income change"
                    value={formatChange(comparison.data.income_change_pct)}
                  />
                </div>
                <div className="grid gap-1">
                  {comparison.data.category_deltas.slice(0, 3).map((delta) => (
                    <div
                      key={delta.category}
                      className="flex justify-between text-xs text-muted-foreground"
                    >
                      <span>{delta.category}</span>
                      <span>{formatChange(delta.change_pct)}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No prior-month comparison yet.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="grid gap-2 p-4 sm:p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Store className="h-4 w-4 text-info" /> Top merchants
            </h3>
            {merchants.length === 0 ? (
              <p className="text-sm text-muted-foreground">No merchant data yet.</p>
            ) : (
              merchants.slice(0, 6).map((m, i) => (
                <div
                  key={m.name}
                  className="dashboard-row flex items-center justify-between gap-2 text-sm"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent text-xs font-bold text-accent-foreground">
                      {i + 1}
                    </span>
                    <span className="truncate">{m.name}</span>
                  </span>
                  <span className="shrink-0 font-semibold">
                    {formatCurrency(m.total, currency)}{' '}
                    <span className="text-xs text-muted-foreground">/ {m.count}x</span>
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="grid gap-2 p-4 sm:p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Repeat className="h-4 w-4 text-primary" /> Recurring charges
            </h3>
            {recurring.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recurring charges detected.</p>
            ) : (
              recurring.slice(0, 6).map((r) => (
                <div
                  key={r.merchant}
                  className="dashboard-row flex items-center justify-between gap-2 text-sm"
                >
                  <span className="min-w-0 truncate">{r.merchant}</span>
                  <span className="shrink-0 font-semibold">
                    {formatCurrency(r.avg_amount, currency)}{' '}
                    <span className="text-xs text-muted-foreground">/ {r.occurrences}x</span>
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ComparisonMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/35 p-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-bold">{value}</p>
    </div>
  );
}

function formatChange(value: number | null | undefined): string {
  if (value == null) return 'New';
  return `${value > 0 ? '+' : ''}${value}%`;
}
