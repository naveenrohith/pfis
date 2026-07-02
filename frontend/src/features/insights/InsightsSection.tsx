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
import { BarChart3, Lightbulb, Store, Repeat, TrendingUp } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { ChartCard } from '@/components/cards/ChartCard';
import { InsightCard } from '@/components/cards/InsightCard';
import { useInsights, useSummary } from '@/features/workspace/queries';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency, formatCompact } from '@/lib/format';
import { CHART_COLORS } from '@/lib/colors';

export function InsightsSection() {
  const { user } = useAuth();
  const insights = useInsights();
  const summary = useSummary();
  const { setCategoryDrill, scrollTo } = useDashboardUi();
  const currency = user?.currency ?? 'INR';

  const breakdown = summary.data?.category_breakdown ?? [];
  const merchants = summary.data?.top_merchants ?? [];
  const trend = insights.data?.daily_trend ?? [];
  const recurring = insights.data?.recurring_payments ?? [];
  const cards = insights.data?.insights ?? [];

  const pieData = breakdown.map((c) => ({ name: c.name, value: c.total }));

  return (
    <div>
      <SectionTitle
        eyebrow="Insights"
        title="Spending intelligence"
        description="Category mix, daily spend movement, merchants, and recurring charges."
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Category breakdown"
          description="Click a category to drill into matching transactions."
          loading={summary.isLoading}
        >
          {pieData.length === 0 ? (
            <EmptyState
              icon={<BarChart3 />}
              title="No spending yet"
              description="Categorized spending will appear here."
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={58}
                    outerRadius={90}
                    paddingAngle={2}
                    onClick={(_, index) => {
                      const cat = breakdown[index];
                      if (cat) {
                        setCategoryDrill({ categoryId: cat.name, label: cat.name });
                        scrollTo('transactions');
                      }
                    }}
                  >
                    {pieData.map((_, i) => (
                      <Cell
                        key={i}
                        fill={CHART_COLORS[i % CHART_COLORS.length]}
                        className="cursor-pointer"
                      />
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
        >
          {trend.length === 0 ? (
            <EmptyState
              icon={<TrendingUp />}
              title="No trend data"
              description="Daily spending will plot here."
            />
          ) : (
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
          )}
        </ChartCard>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
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
          <CardContent className="grid gap-2 p-4 sm:p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Store className="h-4 w-4 text-info" /> Top merchants
            </h3>
            {merchants.length === 0 ? (
              <p className="text-sm text-muted-foreground">No merchant data yet.</p>
            ) : (
              merchants.slice(0, 6).map((m, i) => (
                <div key={m.name} className="dashboard-row flex items-center justify-between gap-2 text-sm">
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
                <div key={r.merchant} className="dashboard-row flex items-center justify-between gap-2 text-sm">
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
