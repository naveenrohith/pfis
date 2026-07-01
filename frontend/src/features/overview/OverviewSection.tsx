import {
  TrendingDown,
  TrendingUp,
  PiggyBank,
  Receipt,
  ClipboardCheck,
  Trash2,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useSummary, useTransactions, useEmails } from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency } from '@/lib/format';

const REVIEW_THRESHOLD = 0.85;

const TONE_TEXT: Record<string, string> = {
  danger: 'text-danger',
  success: 'text-success',
  warning: 'text-warning',
  info: 'text-info',
};

export function OverviewSection() {
  const { user } = useAuth();
  const summary = useSummary();
  const transactions = useTransactions();
  const emails = useEmails();
  const { running, status, liveConnected, log, clearLog } = useSync();

  const currency = user?.currency ?? 'INR';
  const spend = summary.data?.total_spend ?? 0;
  const income = summary.data?.total_income ?? 0;
  const saved = income - spend;
  const txnCount = summary.data?.transaction_count ?? 0;
  const pendingReview =
    transactions.data?.filter((t) => !t.reviewed_flag && t.confidence_score < REVIEW_THRESHOLD)
      .length ?? 0;
  const unprocessed = emails.data?.unprocessed_total ?? 0;

  const metrics = [
    {
      label: 'Spent',
      value: formatCurrency(spend, currency),
      icon: TrendingDown,
      tone: 'danger' as const,
    },
    {
      label: 'Income',
      value: formatCurrency(income, currency),
      icon: TrendingUp,
      tone: 'success' as const,
    },
    {
      label: 'Saved',
      value: formatCurrency(saved, currency),
      icon: PiggyBank,
      tone: saved >= 0 ? ('success' as const) : ('warning' as const),
    },
    {
      label: 'Transactions',
      value: String(txnCount),
      icon: Receipt,
      tone: 'info' as const,
    },
    {
      label: 'Needs review',
      value: String(pendingReview),
      icon: ClipboardCheck,
      tone: pendingReview > 0 ? ('warning' as const) : ('success' as const),
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
        title={saved >= 0 ? `You saved ${formatCurrency(saved, currency)} this month` : 'Spending exceeds income'}
        description="A snapshot of your money this month."
      />

      {/* Hero metrics */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:col-span-2">
          {summary.isLoading
            ? Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-28" />)
            : metrics.map((m) => (
                <Card key={m.label}>
                  <CardContent className="flex flex-col gap-2 p-4">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-muted-foreground">{m.label}</span>
                      <m.icon className={`h-4 w-4 ${TONE_TEXT[m.tone]}`} />
                    </div>
                    <span className="text-2xl font-extrabold">{m.value}</span>
                  </CardContent>
                </Card>
              ))}
        </div>

        {/* Command center */}
        <Card className="lg:col-span-1">
          <CardContent className="flex h-full flex-col gap-3 p-5">
            <div className="flex items-center justify-between">
              <h3 className="font-bold">Command center</h3>
              <div className="flex gap-2">
                <Badge variant={liveConnected ? 'success' : 'default'}>
                  {liveConnected ? 'Live' : 'Fallback'}
                </Badge>
                <Badge variant={statusTone}>{running ? 'Running' : status === 'idle' ? 'Ready' : status}</Badge>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <Stat label="Processed" value={emails.data?.processed_total ?? 0} />
              <Stat label="Unprocessed" value={unprocessed} />
              <Stat label="Pending review" value={pendingReview} />
              <Stat label="Mode" value={user ? 'Active' : '—'} text />
            </div>
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
            <div className="h-32 overflow-y-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-xs">
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

function Stat({ label, value, text }: { label: string; value: number | string; text?: boolean }) {
  return (
    <div className="rounded-md border border-border bg-muted/40 p-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={text ? 'font-semibold' : 'text-lg font-bold'}>{value}</p>
    </div>
  );
}
