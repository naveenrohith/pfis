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
import { Lightbulb, Store, Repeat } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useInsights, useSummary } from '@/features/workspace/queries';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency, formatCompact } from '@/lib/format';
import { CHART_COLORS } from '@/lib/colors';

const SEVERITY_VARIANT: Record<string, 'info' | 'success' | 'warning' | 'danger'> = {
  info: 'info',
  success: 'success',
  warning: 'warning',
  danger: 'danger',
};

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
      <SectionTitle eyebrow="Insights" title="Spending intelligence" description="Where your money goes and what stands out." />

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Category doughnut */}
        <Card>
          <CardContent className="p-5">
            <h3 className="mb-3 font-bold">Category breakdown</h3>
            {summary.isLoading ? (
              <Skeleton className="h-64" />
            ) : pieData.length === 0 ? (
              <EmptyState icon="📊" title="No spending yet" description="Categorized spending will appear here." />
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
                      className="flex items-center justify-between gap-2 rounded-md px-2 py-1 text-sm hover:bg-muted"
                    >
                      <span className="flex items-center gap-2">
                        <span
                          className="h-2.5 w-2.5 rounded-full"
                          style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
                        />
                        {c.icon} {c.name}
                      </span>
                      <span className="font-semibold">{formatCurrency(c.total, currency)}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Daily trend */}
        <Card>
          <CardContent className="p-5">
            <h3 className="mb-3 font-bold">Daily spend trend</h3>
            {insights.isLoading ? (
              <Skeleton className="h-64" />
            ) : trend.length === 0 ? (
              <EmptyState icon="📈" title="No trend data" description="Daily spending will plot here." />
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
                    stroke="#6366f1"
                    strokeWidth={2.5}
                    dot={{ r: 2 }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        {/* Insight feed */}
        <Card className="lg:col-span-1">
          <CardContent className="grid gap-2 p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Lightbulb className="h-4 w-4 text-warning" /> Smart insights
            </h3>
            {insights.isLoading ? (
              <Skeleton className="h-40" />
            ) : cards.length === 0 ? (
              <EmptyState icon="🧠" title="No insights yet" />
            ) : (
              cards.map((card, i) => (
                <div key={i} className="rounded-lg border border-border p-3">
                  <div className="flex items-center gap-2">
                    <span>{card.icon}</span>
                    <p className="text-sm font-semibold">{card.title}</p>
                    {card.severity && (
                      <Badge variant={SEVERITY_VARIANT[card.severity] ?? 'info'} className="ml-auto">
                        {card.severity}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{card.description}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Top merchants */}
        <Card>
          <CardContent className="grid gap-2 p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Store className="h-4 w-4 text-info" /> Top merchants
            </h3>
            {merchants.length === 0 ? (
              <p className="text-sm text-muted-foreground">No merchant data yet.</p>
            ) : (
              merchants.slice(0, 6).map((m, i) => (
                <div key={m.name} className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-xs font-bold text-accent-foreground">
                      {i + 1}
                    </span>
                    {m.name}
                  </span>
                  <span className="font-semibold">
                    {formatCurrency(m.total, currency)}{' '}
                    <span className="text-xs text-muted-foreground">· {m.count}×</span>
                  </span>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Recurring */}
        <Card>
          <CardContent className="grid gap-2 p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Repeat className="h-4 w-4 text-primary" /> Recurring charges
            </h3>
            {recurring.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recurring charges detected.</p>
            ) : (
              recurring.slice(0, 6).map((r) => (
                <div key={r.merchant} className="flex items-center justify-between gap-2 text-sm">
                  <span>{r.merchant}</span>
                  <span className="font-semibold">
                    {formatCurrency(r.avg_amount, currency)}{' '}
                    <span className="text-xs text-muted-foreground">· {r.occurrences}×</span>
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
