import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Activity, CalendarClock, Plus, Target, TrendingUp } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Label, Select } from '@/components/ui/Input';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { queryKeys, useGoals, useWorkspaceSnapshot } from '@/features/workspace/queries';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatCurrency } from '@/lib/format';
import type { Goal, GoalType, RecurringPayment } from '@/lib/types';
import { ScenarioStudio } from './ScenarioStudio';

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

export function AnalyticsSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const workspace = useWorkspaceSnapshot();
  const cashFlow = workspace.data?.projection;
  const health = workspace.data?.financial_health;
  const goals = useGoals();
  const currency = user?.currency ?? 'INR';

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Analytics"
          title="Outlook and goals"
          description="Forward-looking cash flow, monthly stability, data confidence, and progress toward the outcomes you set."
          action={
            health ? (
              <Badge variant={health.monthly_stability >= 70 ? 'success' : 'warning'}>
                Stability {health.monthly_stability}
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
            {workspace.isLoading ? (
              <Skeleton className="h-36" />
            ) : cashFlow ? (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Metric
                    label="Net to date"
                    value={formatCurrency(cashFlow.net_to_date, currency)}
                  />
                  <Metric
                    label="Projected net"
                    value={formatCurrency(cashFlow.projected_net, currency)}
                  />
                  <Metric
                    label="Spend/day"
                    value={formatCurrency(cashFlow.daily_spend_rate, currency)}
                  />
                  <Metric
                    label="Expected income"
                    value={formatCurrency(cashFlow.expected_income, currency)}
                  />
                  <Metric
                    label="Confirmed commitments"
                    value={formatCurrency(cashFlow.confirmed_commitments, currency)}
                  />
                  <Metric
                    label="Flexible projection"
                    value={formatCurrency(cashFlow.flexible_spend_projection, currency)}
                  />
                </div>
                <div className="rounded-xl border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
                  Expected spend range: {formatCurrency(cashFlow.projected_range_low, currency)}–
                  {formatCurrency(cashFlow.projected_range_high, currency)} ·{' '}
                  {Math.round(cashFlow.confidence * 100)}% confidence · {cashFlow.historical_months}{' '}
                  comparable months
                </div>
                <p className="text-xs leading-5 text-muted-foreground">{cashFlow.assumptions[2]}</p>
              </>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="grid gap-3 p-4 sm:p-5">
            <h3 className="flex items-center gap-2 font-bold">
              <Activity className="h-4 w-4 text-success" /> Stability & data confidence
            </h3>
            {workspace.isLoading ? (
              <Skeleton className="h-36" />
            ) : health ? (
              <>
                <div className="grid grid-cols-2 divide-x divide-border border-y border-border py-4">
                  <Metric label="Monthly stability" value={String(health.monthly_stability)} />
                  <div className="pl-4">
                    <Metric label="Data confidence" value={String(health.data_confidence)} />
                  </div>
                </div>
                <div className="grid gap-1.5">
                  {health.signals.map((signal) => (
                    <div key={signal.label} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{signal.label}</span>
                      <Badge variant={signal.severity}>
                        {signal.value == null ? 'Not configured' : `${signal.value}%`}
                      </Badge>
                    </div>
                  ))}
                </div>
                <p className="text-xs leading-5 text-muted-foreground">
                  Stability measures the month. Data confidence measures how much PFIS can trust the
                  underlying classifications; it does not improve the stability score.
                </p>
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <CommitmentLedger
        commitments={workspace.data?.recurring_commitments ?? []}
        currency={currency}
      />

      <ScenarioStudio
        userId={user?.id ?? ''}
        month={month}
        year={year}
        currency={currency}
        baseline={cashFlow}
      />

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

function CommitmentLedger({
  commitments,
  currency,
}: {
  commitments: RecurringPayment[];
  currency: string;
}) {
  const active = commitments.filter((item) => item.status !== 'inactive');
  return (
    <section aria-labelledby="commitment-rhythm-title" className="mt-6 border-y border-border py-5">
      <div className="mb-4 flex flex-col justify-between gap-2 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-bold text-muted-foreground">Commitment rhythm</p>
          <h3 id="commitment-rhythm-title" className="mt-1 text-xl font-extrabold">
            Confirmed commitments & early signals
          </h3>
        </div>
        <p className="text-xs text-muted-foreground">
          Expected dates appear only when cadence evidence supports them.
        </p>
      </div>
      {active.length ? (
        <div className="divide-y divide-border">
          {active.map((item) => (
            <div
              key={`${item.merchant}-${item.cadence ?? 'irregular'}`}
              className="grid min-w-0 gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center"
            >
              <div className="min-w-0">
                <p className="truncate font-bold">{item.merchant}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.cadence || 'Irregular'} · {Math.round(item.confidence * 100)}% confidence ·{' '}
                  {item.occurrences} observations
                </p>
              </div>
              <div className="text-left sm:text-right">
                <p className="font-bold tabular-nums">
                  {formatCurrency(item.monthly_equivalent, currency)} / month
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.status === 'mature'
                    ? 'Confirmed'
                    : item.status === 'missed'
                      ? 'Possibly missed'
                      : 'Early signal'}
                </p>
              </div>
              <Badge variant={item.status === 'mature' ? 'success' : 'warning'}>
                <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
                {item.next_expected_date
                  ? DATE_FORMAT.format(new Date(`${item.next_expected_date}T00:00:00`))
                  : 'Date withheld'}
              </Badge>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          No cadence has enough evidence to plan around yet.
        </p>
      )}
    </section>
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
              <Input
                id="goal-label"
                name="goal-label"
                autoComplete="off"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="goal-amount">Target</Label>
              <Input
                id="goal-amount"
                name="goal-amount"
                type="number"
                min={1}
                inputMode="decimal"
                autoComplete="off"
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
