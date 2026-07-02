import {
  TrendingDown,
  TrendingUp,
  PiggyBank,
  Receipt,
  ClipboardCheck,
  Wallet,
  ShieldAlert,
  Activity,
  Trash2,
  MailCheck,
  MailWarning,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { StatCard, type CardTone } from '@/components/cards/StatCard';
import { useWorkspaceSnapshot } from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency } from '@/lib/format';

export function OverviewSection() {
  const { user } = useAuth();
  const workspace = useWorkspaceSnapshot();
  const { running, status, liveConnected, log, clearLog } = useSync();
  const { scrollTo } = useDashboardUi();

  const currency = user?.currency ?? 'INR';
  const snap = workspace.data?.snapshot;
  const sync = workspace.data?.sync_summary;

  const income = snap?.income ?? 0;
  const spend = snap?.spend ?? 0;
  const savings = snap?.savings ?? 0;
  const netCashFlow = snap?.net_cash_flow ?? 0;
  const txnCount = snap?.transaction_count ?? 0;
  const reviewCount = snap?.review_count ?? 0;
  const budgetRisk = snap?.budget_risk_count ?? 0;

  const metrics: {
    label: string;
    value: string;
    icon: typeof TrendingDown;
    tone: CardTone;
    target?: string;
  }[] = [
    { label: 'Income', value: formatCurrency(income, currency), icon: TrendingUp, tone: 'success' },
    { label: 'Spent', value: formatCurrency(spend, currency), icon: TrendingDown, tone: 'danger' },
    {
      label: 'Saved',
      value: formatCurrency(savings, currency),
      icon: PiggyBank,
      tone: savings >= 0 ? 'success' : 'warning',
    },
    {
      label: 'Net cash flow',
      value: formatCurrency(netCashFlow, currency),
      icon: Wallet,
      tone: netCashFlow >= 0 ? 'success' : 'danger',
    },
    {
      label: 'Transactions',
      value: String(txnCount),
      icon: Receipt,
      tone: 'info',
      target: 'transactions',
    },
    {
      label: 'Needs review',
      value: String(reviewCount),
      icon: ClipboardCheck,
      tone: reviewCount > 0 ? 'warning' : 'success',
      target: 'review',
    },
    {
      label: 'Budget risk',
      value: String(budgetRisk),
      icon: ShieldAlert,
      tone: budgetRisk > 0 ? 'danger' : 'success',
      target: 'budgets',
    },
  ];

  const statusTone =
    status === 'completed'
      ? 'success'
      : status === 'failed'
        ? 'danger'
        : status === 'running' || status === 'queued'
          ? 'info'
          : 'default';

  return (
    <div>
      <SectionTitle
        eyebrow="Overview"
        title={
          savings >= 0
            ? `You saved ${formatCurrency(savings, currency)} this month`
            : 'Spending exceeds income'
        }
        description="Month-to-date performance, sync health, and review pressure in one workspace."
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4 lg:col-span-3">
          {workspace.isLoading
            ? Array.from({ length: 7 }).map((_, i) => <Skeleton key={i} className="h-28" />)
            : metrics.map((m) => (
                <StatCard
                  key={m.label}
                  label={m.label}
                  value={m.value}
                  icon={m.icon}
                  tone={m.tone}
                  onClick={m.target ? () => scrollTo(m.target!) : undefined}
                />
              ))}
        </div>

        <Card className="lg:col-span-2">
          <CardContent className="flex h-full flex-col gap-4 p-4 sm:p-5">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-2 font-bold">
                <Activity className="h-4 w-4 text-info" /> Command center
              </h3>
              <div className="flex gap-2">
                <Badge variant={liveConnected ? 'success' : 'default'}>
                  {liveConnected ? 'Live' : 'Fallback'}
                </Badge>
                <Badge variant={statusTone}>
                  {running ? 'Running' : status === 'idle' ? 'Ready' : status}
                </Badge>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <Stat icon={<MailCheck className="h-4 w-4" />} label="Processed" value={sync?.processed_total ?? 0} />
              <Stat icon={<MailWarning className="h-4 w-4" />} label="Waiting" value={sync?.unprocessed_total ?? 0} />
              <Stat icon={<ClipboardCheck className="h-4 w-4" />} label="Review" value={reviewCount} />
              <Stat icon={<Activity className="h-4 w-4" />} label="Sync" value={sync?.latest_status ?? snap?.sync_status ?? 'idle'} text />
            </div>
            <p className="rounded-lg border border-border bg-muted/35 p-3 text-sm text-muted-foreground">
              {reviewCount > 0
                ? `${reviewCount} transaction(s) need confirmation before this month is clean.`
                : budgetRisk > 0
                  ? `${budgetRisk} budget area(s) need attention.`
                  : 'No immediate cleanup items. Keep the inbox sync current.'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="flex h-full flex-col gap-3 p-4 sm:p-5">
            <div className="mt-1 flex items-center justify-between">
              <p className="text-xs font-semibold text-muted-foreground">Activity log</p>
              {log.length > 0 && (
                <button
                  onClick={clearLog}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                >
                  <Trash2 className="h-3 w-3" /> Clear
                </button>
              )}
            </div>
            <div className="h-40 overflow-y-auto rounded-lg border border-border bg-muted/40 p-3 font-mono text-xs">
              {log.length === 0 ? (
                <p className="text-muted-foreground">No activity yet. Run a sync to begin.</p>
              ) : (
                log.map((entry, i) => (
                  <p key={i} className="leading-relaxed">
                    <span className="text-muted-foreground">[{entry.time}]</span> {entry.message}
                  </p>
                ))
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  text,
  icon,
}: {
  label: string;
  value: number | string;
  text?: boolean;
  icon?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/35 p-3">
      <div className="mb-2 flex items-center justify-between text-muted-foreground">
        <p className="text-xs font-semibold">{label}</p>
        {icon}
      </div>
      <p className={text ? 'font-semibold capitalize' : 'text-xl font-bold'}>{value}</p>
    </div>
  );
}
