import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Activity, Plus, Target, TrendingUp } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Label, Select } from '@/components/ui/Input';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { queryKeys, useCashFlow, useFinancialHealth, useGoals } from '@/features/workspace/queries';
import { useToast } from '@/components/ui/Toast';
import { ExplainAction } from '@/features/ai/ExplainAction';
import { api } from '@/lib/api';
import { formatCurrency } from '@/lib/format';
import type { Goal, GoalType } from '@/lib/types';

export function AnalyticsSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const cashFlow = useCashFlow();
  const health = useFinancialHealth();
  const goals = useGoals();
  const currency = user?.currency ?? 'INR';

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Analytics"
          title="Outlook and goals"
          description="Forward-looking cash flow, financial health, and progress toward the outcomes you set."
          action={
            health.data ? (
              <Badge variant={health.data.score >= 70 ? 'success' : 'warning'}>
                Health {health.data.score}
              </Badge>
            ) : undefined
          }
        />
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardContent className="grid gap-3 p-4 sm:p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <TrendingUp className="h-4 w-4 text-info" /> Cash-flow projection
            </h3>
            {cashFlow.isLoading ? (
              <Skeleton className="h-36" />
            ) : cashFlow.data ? (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Metric
                    label="Net to date"
                    value={formatCurrency(cashFlow.data.net_to_date, currency)}
                  />
                  <Metric
                    label="Projected net"
                    value={formatCurrency(cashFlow.data.projected_net, currency)}
                  />
                  <Metric
                    label="Spend/day"
                    value={formatCurrency(cashFlow.data.daily_spend_rate, currency)}
                  />
                  <Metric
                    label="Projected spend"
                    value={formatCurrency(cashFlow.data.projected_spend, currency)}
                  />
                  <Metric
                    label="Recurring commitments"
                    value={formatCurrency(cashFlow.data.recurring_commitments, currency)}
                  />
                  <Metric
                    label="Budget remaining"
                    value={formatCurrency(cashFlow.data.budgeted_remaining, currency)}
                  />
                </div>
                <div className="rounded-xl border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
                  Expected spend range:{' '}
                  {formatCurrency(cashFlow.data.projected_range_low, currency)}–
                  {formatCurrency(cashFlow.data.projected_range_high, currency)}.{' '}
                  {cashFlow.data.assumptions[2]}
                </div>
                <ExplainAction
                  payload={{
                    surface: 'cash flow',
                    title: 'Cash-flow projection',
                    description: `Projected month-end net is ${formatCurrency(cashFlow.data.projected_net, currency)}.`,
                    metrics: {
                      net_to_date: formatCurrency(cashFlow.data.net_to_date, currency),
                      daily_spend_rate: formatCurrency(cashFlow.data.daily_spend_rate, currency),
                    },
                  }}
                />
              </>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="grid gap-3 p-4 sm:p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Activity className="h-4 w-4 text-success" /> Financial health
            </h3>
            {health.isLoading ? (
              <Skeleton className="h-36" />
            ) : health.data ? (
              <>
                <div className="flex items-end justify-between">
                  <span className="text-5xl font-extrabold">{health.data.score}</span>
                  <Badge variant={health.data.score >= 70 ? 'success' : 'warning'}>
                    {health.data.score >= 70 ? 'Stable' : 'Needs attention'}
                  </Badge>
                </div>
                <div className="grid gap-1.5">
                  {health.data.signals.map((signal) => (
                    <div key={signal.label} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{signal.label}</span>
                      <Badge variant={signal.severity}>{signal.value}%</Badge>
                    </div>
                  ))}
                </div>
                <ExplainAction
                  payload={{
                    surface: 'financial health',
                    title: `Financial health score ${health.data.score}`,
                    metrics: {
                      savings_rate: `${health.data.savings_rate}%`,
                      budget_adherence: `${health.data.budget_adherence}%`,
                      recurring_burden: `${health.data.recurring_burden}%`,
                      review_cleanliness: `${health.data.review_cleanliness}%`,
                    },
                  }}
                />
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <GoalBoard
        userId={user?.id ?? ''}
        month={month}
        year={year}
        currency={currency}
        goals={goals.data ?? []}
        loading={goals.isLoading}
      />
    </div>
  );
}

function GoalBoard({
  userId,
  month,
  year,
  currency,
  goals,
  loading,
}: {
  userId: string;
  month: number;
  year: number;
  currency: string;
  goals: Goal[];
  loading: boolean;
}) {
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [goalType, setGoalType] = useState<GoalType>('savings');
  const [label, setLabel] = useState('Save more this month');
  const [targetAmount, setTargetAmount] = useState('10000');

  const create = useMutation({
    mutationFn: () =>
      api.createGoal(userId, {
        goal_type: goalType,
        label,
        target_amount: Number(targetAmount),
        target_month: month,
        target_year: year,
      }),
    onSuccess: () => {
      notify('Goal created', 'success');
      queryClient.invalidateQueries({ queryKey: queryKeys.goals(userId, month, year) });
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });

  return (
    <Card className="mt-4">
      <CardContent className="grid gap-4 p-4 sm:p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h3 className="flex items-center gap-2 font-bold">
              <Target className="h-4 w-4 text-primary" /> Goals
            </h3>
            <p className="text-sm text-muted-foreground">
              Track savings, category reduction, and recurring-spend reduction.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-[9rem_minmax(12rem,1fr)_7rem_auto]">
            <Select value={goalType} onChange={(e) => setGoalType(e.target.value as GoalType)}>
              <option value="savings">Savings</option>
              <option value="category_reduction">Category cap</option>
              <option value="recurring_reduction">Recurring cap</option>
            </Select>
            <div>
              <Label htmlFor="goal-label">Label</Label>
              <Input id="goal-label" value={label} onChange={(e) => setLabel(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="goal-amount">Target</Label>
              <Input
                id="goal-amount"
                type="number"
                min={1}
                value={targetAmount}
                onChange={(e) => setTargetAmount(e.target.value)}
              />
            </div>
            <Button
              className="self-end"
              onClick={() => create.mutate()}
              disabled={!userId || create.isPending || Number(targetAmount) <= 0}
            >
              <Plus className="h-4 w-4" /> Add
            </Button>
          </div>
        </div>

        {loading ? (
          <Skeleton className="h-28" />
        ) : goals.length === 0 ? (
          <EmptyState
            icon={<Target />}
            title="No goals yet"
            description="Create a goal to start tracking progress against this month."
          />
        ) : (
          <div className="grid gap-3 lg:grid-cols-3">
            {goals.map((goal) => (
              <div key={goal.id} className="rounded-lg border border-border bg-muted/25 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-semibold">{goal.label}</p>
                    <p className="text-xs capitalize text-muted-foreground">
                      {goal.goal_type.replace('_', ' ')}
                    </p>
                  </div>
                  <Badge
                    variant={
                      goal.status === 'achieved'
                        ? 'success'
                        : goal.status === 'at_risk'
                          ? 'warning'
                          : 'info'
                    }
                  >
                    {goal.status}
                  </Badge>
                </div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary"
                    style={{ width: `${goal.progress_pct}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {formatCurrency(goal.current_amount, currency)} /{' '}
                  {formatCurrency(goal.target_amount, currency)}
                </p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/35 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-bold">{value}</p>
    </div>
  );
}
