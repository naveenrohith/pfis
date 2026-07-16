import {
  ArrowRight,
  CheckCircle2,
  TrendingDown,
  TrendingUp,
  PiggyBank,
  ClipboardCheck,
  Wallet,
  ShieldAlert,
  MailWarning,
} from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { StatCard, type CardTone } from '@/components/cards/StatCard';
import { RecommendationCard } from '@/components/cards/RecommendationCard';
import { queryKeys, useDashboardPreferences, useWorkspaceSnapshot } from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency } from '@/lib/format';
import { useTransactions } from '@/features/workspace/queries';
import { PaymentMethodVisuals } from './PaymentMethodVisuals';
import { api } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';

export function OverviewSection() {
  const { user } = useAuth();
  const workspace = useWorkspaceSnapshot();
  const transactions = useTransactions();
  const { running, status, liveConnected } = useSync();
  const { scrollTo } = useDashboardUi();
  const preferences = useDashboardPreferences();
  const queryClient = useQueryClient();
  const { notify } = useToast();

  const currency = user?.currency ?? 'INR';
  const snap = workspace.data?.snapshot;
  const sync = workspace.data?.sync_summary;

  const income = snap?.income ?? 0;
  const spend = snap?.spend ?? 0;
  const savings = snap?.savings ?? 0;
  const netCashFlow = snap?.net_cash_flow ?? 0;
  const reviewCount = snap?.review_count ?? 0;
  const budgetRisk = snap?.budget_risk_count ?? 0;
  const unprocessedCount = sync?.unprocessed_total ?? 0;
  const recommendations = workspace.data?.recommendations ?? [];
  const nextRecommendation = recommendations[0];

  const metrics: {
    id: string;
    label: string;
    value: string;
    icon: typeof TrendingDown;
    tone: CardTone;
  }[] = [
    { id: 'income', label: 'Income', value: formatCurrency(income, currency), icon: TrendingUp, tone: 'success' },
    { id: 'spent', label: 'Spent', value: formatCurrency(spend, currency), icon: TrendingDown, tone: 'danger' },
    {
      id: 'savings',
      label: 'Saved',
      value: formatCurrency(savings, currency),
      icon: PiggyBank,
      tone: savings >= 0 ? 'success' : 'warning',
    },
    {
      id: 'net-cash-flow',
      label: 'Net cash flow',
      value: formatCurrency(netCashFlow, currency),
      icon: Wallet,
      tone: netCashFlow >= 0 ? 'success' : 'danger',
    },
  ];
  const preferenceMap = new Map((preferences.data?.widgets ?? []).map((widget, index) => [widget.id, { ...widget, index }]));
  const visibleMetrics = metrics
    .filter((metric) => preferenceMap.get(metric.id)?.visible !== false)
    .sort((left, right) => (preferenceMap.get(left.id)?.index ?? 99) - (preferenceMap.get(right.id)?.index ?? 99));
  const attentionVisible = preferenceMap.get('attention')?.visible !== false;
  const nextActionVisible = preferenceMap.get('next-action')?.visible !== false;

  const chooseGoal = useMutation({
    mutationFn: (goal: 'budgeting' | 'saving' | 'recurring_reduction' | 'cleanup') => {
      if (!user) throw new Error('Sign in to personalize PFIS');
      return api.updateDashboardPreferences(user.id, { onboarding_goal: goal });
    },
    onSuccess: (data) => {
      if (user) queryClient.setQueryData(queryKeys.dashboardPreferences(user.id), data);
      notify('Your workspace is personalized', 'success');
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  const attentionItems = [
    {
      label: 'Transactions to confirm',
      description: 'Resolve low-confidence data before relying on the month totals.',
      count: reviewCount,
      target: 'review',
      icon: ClipboardCheck,
      variant: 'warning' as const,
    },
    {
      label: 'Budgets at risk',
      description: 'Review categories nearing or exceeding their monthly limit.',
      count: budgetRisk,
      target: 'budgets',
      icon: ShieldAlert,
      variant: 'danger' as const,
    },
    {
      label: 'Inbox items waiting',
      description: 'Process pending source records to keep this workspace current.',
      count: unprocessedCount,
      target: 'inbox',
      icon: MailWarning,
      variant: 'info' as const,
    },
  ].filter((item) => item.count > 0);

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
        eyebrow="Financial position"
        title={
          attentionItems.length > 0
            ? `${attentionItems.length} area${attentionItems.length === 1 ? '' : 's'} need attention`
            : savings >= 0
              ? `You saved ${formatCurrency(savings, currency)} this month`
              : 'Spending exceeds income'
        }
        description="Start with your position, clear anything affecting accuracy, then take the highest-impact next action."
        action={
          <>
            <Badge variant={liveConnected ? 'success' : 'default'}>
              {liveConnected ? 'Live data' : 'Polling'}
            </Badge>
            <Badge variant={statusTone}>{running ? 'Syncing' : status === 'idle' ? 'Current' : status}</Badge>
          </>
        }
      />

      {preferences.data && !preferences.data.onboarding_goal && (
        <Card className="mb-4 border-primary/20 bg-gradient-to-r from-primary/10 via-card to-card">
          <CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.14em] text-primary">Personalize PFIS</p>
              <p className="mt-1 font-bold">What matters most right now?</p>
              <p className="mt-1 text-sm text-muted-foreground">Your choice sets the starting emphasis without hiding any financial data.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {[
                ['saving', 'Save more'],
                ['budgeting', 'Stay on budget'],
                ['recurring_reduction', 'Reduce subscriptions'],
                ['cleanup', 'Clean up data'],
              ].map(([value, label]) => (
                <Button key={value} variant="outline" size="sm" onClick={() => chooseGoal.mutate(value as 'budgeting' | 'saving' | 'recurring_reduction' | 'cleanup')}>
                  {label}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className={`grid grid-cols-1 gap-3 sm:grid-cols-2 ${visibleMetrics.length > 3 ? 'xl:grid-cols-4' : 'xl:grid-cols-3'}`}>
        {workspace.isLoading
          ? Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-28" />)
          : visibleMetrics.map((metric) => (
              <StatCard
                key={metric.label}
                label={metric.label}
                value={metric.value}
                icon={metric.icon}
                tone={metric.tone}
                className={preferenceMap.get(metric.id)?.size === 'large' ? 'sm:col-span-2' : undefined}
              />
            ))}
      </div>

      {(attentionVisible || nextActionVisible) && <div className="mt-4 grid gap-4 lg:grid-cols-5">
        {attentionVisible && <Card className={nextActionVisible ? 'lg:col-span-3' : 'lg:col-span-5'}>
          <CardContent className="p-4 sm:p-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Attention queue</p>
                <h3 className="mt-1 font-bold">Protect the accuracy of this month</h3>
              </div>
              <Badge variant={attentionItems.length > 0 ? 'warning' : 'success'}>
                {attentionItems.length > 0 ? `${attentionItems.length} open` : 'All clear'}
              </Badge>
            </div>

            {attentionItems.length === 0 ? (
              <div className="flex items-start gap-3 rounded-lg border border-success/25 bg-success/10 p-4">
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
                <div>
                  <p className="text-sm font-bold">Your financial data is ready for decisions</p>
                  <p className="mt-1 text-xs text-muted-foreground">No pending reviews, budget risks, or inbox backlog.</p>
                </div>
              </div>
            ) : (
              <div className="grid gap-2">
                {attentionItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      type="button"
                      key={item.target}
                      onClick={() => scrollTo(item.target)}
                      className="dashboard-row flex w-full items-center gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-bold">{item.label}</span>
                        <span className="block text-xs text-muted-foreground">{item.description}</span>
                      </span>
                      <Badge variant={item.variant}>{item.count}</Badge>
                      <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    </button>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>}

        {nextActionVisible && <div className={attentionVisible ? 'lg:col-span-2' : 'lg:col-span-5'}>
          {workspace.isLoading ? (
            <Skeleton className="h-full min-h-48" />
          ) : nextRecommendation ? (
            <div>
              <p className="mb-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">Next best action</p>
              <RecommendationCard
                title={nextRecommendation.title}
                description={nextRecommendation.description}
                severity={nextRecommendation.severity}
                actionLabel={nextRecommendation.action_label}
                onAction={() => scrollTo(nextRecommendation.target)}
                className="h-[calc(100%-1.5rem)]"
              />
            </div>
          ) : (
            <Card className="h-full">
              <CardContent className="flex h-full min-h-48 flex-col items-start justify-center p-5">
                <CheckCircle2 className="h-6 w-6 text-success" />
                <p className="mt-3 font-bold">No urgent recommendation</p>
                <p className="mt-1 text-sm text-muted-foreground">Explore your trends or keep the inbox current.</p>
                <Button variant="link" className="mt-3" onClick={() => scrollTo('insights')}>
                  Explore insights <ArrowRight className="h-4 w-4" />
                </Button>
              </CardContent>
            </Card>
          )}
        </div>}
      </div>}
      <PaymentMethodVisuals transactions={transactions.data ?? []} currency={currency} />
    </div>
  );
}
