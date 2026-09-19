import { FormEvent, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle2,
  ChevronRight,
  HeartPulse,
  Home,
  Receipt,
  Scale,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { FinancialHero, LedgerRow } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Label, Select } from '@/components/ui/Input';
import { EmptyState } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthContext';
import {
  queryKeys,
  useBills,
  useHealthChecklist,
  useHouseholds,
  useLiabilities,
} from '@/features/workspace/queries';
import { api } from '@/lib/api';
import { dateInputValueInTimezone, formatCurrency, formatDate } from '@/lib/format';
import type {
  HealthChecklistItem,
  HouseholdMember,
  HouseholdSettlement,
  RoadmapBill,
} from '@/lib/types';

const checklistDefaults: Array<Pick<HealthChecklistItem, 'item_type' | 'label'>> = [
  { item_type: 'emergency_fund', label: 'Emergency fund' },
  { item_type: 'health_insurance', label: 'Health insurance reviewed' },
  { item_type: 'life_insurance', label: 'Life cover reviewed' },
  { item_type: 'nominee', label: 'Nominees confirmed' },
  { item_type: 'will', label: 'Will or succession plan' },
];

const statusLabel: Record<HealthChecklistItem['status'], string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  complete: 'Complete',
  not_applicable: 'Not applicable',
};

function mutationError(error: Error | null): string | null {
  return error?.message ?? null;
}

export function RoadmapExtensionsSection({ view }: { view: 'obligations' | 'household' }) {
  return view === 'obligations' ? <ObligationsWorkspace /> : <HouseholdWorkspace />;
}

function ObligationsWorkspace() {
  const { user } = useAuth();
  const financialToday = dateInputValueInTimezone(user?.timezone ?? 'Asia/Kolkata');
  const currency = user?.currency ?? 'INR';
  const queryClient = useQueryClient();
  const bills = useBills();
  const health = useHealthChecklist();
  const liabilities = useLiabilities();
  const [monthlyBudget, setMonthlyBudget] = useState('');
  const [billDraft, setBillDraft] = useState({
    label: '',
    amount: '',
    due_date: financialToday,
    bill_type: 'bill' as RoadmapBill['bill_type'],
    cadence: 'monthly' as NonNullable<RoadmapBill['cadence']>,
  });
  const payoffBudget = Number(monthlyBudget);
  const payoff = useQuery({
    queryKey: ['payoffComparison', user?.id ?? '', payoffBudget],
    queryFn: () => api.payoffComparison(user!.id, payoffBudget),
    enabled: Boolean(user && payoffBudget > 0),
    staleTime: 5 * 60 * 1000,
  });
  const createBill = useMutation({
    mutationFn: () =>
      api.createBill(user!.id, {
        ...billDraft,
        amount: Number(billDraft.amount),
        source_kind: 'manual',
        confirmed: true,
      }),
    onSuccess: async () => {
      setBillDraft((current) => ({ ...current, label: '', amount: '' }));
      await queryClient.invalidateQueries({ queryKey: queryKeys.bills(user!.id) });
    },
  });
  const updateBill = useMutation({
    mutationFn: ({ id, status }: { id: string; status: RoadmapBill['status'] }) =>
      api.updateBill(user!.id, id, { status }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.bills(user!.id) });
    },
  });
  const updateHealth = useMutation({
    mutationFn: ({
      item,
      status,
    }: {
      item: Pick<HealthChecklistItem, 'item_type' | 'label'>;
      status: HealthChecklistItem['status'];
    }) =>
      api.upsertHealthChecklist(user!.id, {
        ...item,
        status,
        note: null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.healthChecklist(user!.id),
      });
    },
  });

  const dueBills = (bills.data ?? []).filter(
    (bill) => bill.status === 'due' || bill.status === 'due_soon',
  );
  const dueTotal = dueBills.reduce((total, bill) => total + bill.amount, 0);
  const completedHealth = checklistDefaults.filter(
    (definition) =>
      health.data?.find((item) => item.item_type === definition.item_type)?.status === 'complete',
  ).length;
  const minimumDebt = (liabilities.data ?? []).reduce(
    (total, liability) => total + (liability.monthly_due ?? 0),
    0,
  );

  function submitBill(event: FormEvent) {
    event.preventDefault();
    if (!billDraft.label.trim() || Number(billDraft.amount) <= 0) return;
    createBill.mutate();
  }

  return (
    <div className="space-y-6">
      <FinancialHero>
        <div className="grid gap-6 md:grid-cols-[minmax(0,1.25fr)_minmax(16rem,0.75fr)] md:items-end">
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              CONFIRMED OBLIGATIONS
            </p>
            <p className="money-value mt-2 text-4xl font-extrabold tracking-[-0.06em] sm:text-5xl">
              {formatCurrency(dueTotal, currency)}
            </p>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              Due bills are explicit reminders. Only confirmed commitments affect the Cash Plan.
            </p>
          </div>
          <dl className="grid grid-cols-2 gap-4 border-t border-border/70 pt-5 md:border-l md:border-t-0 md:pl-6 md:pt-0">
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Open bills</dt>
              <dd className="money-value mt-1 text-xl font-extrabold">{dueBills.length}</dd>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Safety checks</dt>
              <dd className="money-value mt-1 text-xl font-extrabold">
                {completedHealth}/{checklistDefaults.length}
              </dd>
            </div>
          </dl>
        </div>
      </FinancialHero>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(19rem,0.75fr)]">
        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="bill-ledger-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="bill-ledger-title" className="text-lg font-extrabold tracking-[-0.025em]">
                Bills and subscriptions
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Record due, paid, or skipped status without inventing recurrence.
              </p>
            </div>
            <Badge variant={dueBills.length ? 'warning' : 'success'}>
              {dueBills.length ? `${dueBills.length} open` : 'Up to date'}
            </Badge>
          </div>
          <div className="mt-4">
            {(bills.data ?? []).length ? (
              (bills.data ?? []).map((bill) => (
                <article
                  key={bill.id}
                  className="border-b border-border/65 py-4 first:pt-0 last:border-b-0 last:pb-0"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
                      <Receipt className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <h3 className="font-extrabold">{bill.label}</h3>
                        <span className="money-value text-sm font-extrabold">
                          {formatCurrency(bill.amount, currency)}
                        </span>
                      </div>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        {formatDate(bill.due_date)} · {bill.status} ·{' '}
                        {bill.confirmed ? 'confirmed' : 'unconfirmed'}
                      </p>
                    </div>
                  </div>
                  {bill.status === 'due' || bill.status === 'due_soon' ? (
                    <div className="mt-3 flex flex-wrap gap-2 pl-0 sm:pl-[3.25rem]">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => updateBill.mutate({ id: bill.id, status: 'paid' })}
                        disabled={updateBill.isPending}
                      >
                        Mark paid
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => updateBill.mutate({ id: bill.id, status: 'skipped' })}
                        disabled={updateBill.isPending}
                      >
                        Skip
                      </Button>
                    </div>
                  ) : null}
                </article>
              ))
            ) : (
              <p className="rounded-lg bg-muted/55 p-4 text-sm text-muted-foreground">
                No bills recorded yet.
              </p>
            )}
          </div>
          <details className="mt-5 rounded-lg border border-border/70 p-4">
            <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
              Add a confirmed bill
            </summary>
            <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={submitBill}>
              <Field label="Bill label" htmlFor="bill-label">
                <Input
                  id="bill-label"
                  value={billDraft.label}
                  onChange={(event) =>
                    setBillDraft((current) => ({ ...current, label: event.target.value }))
                  }
                  required
                />
              </Field>
              <Field label="Amount" htmlFor="bill-amount">
                <Input
                  id="bill-amount"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  step="0.01"
                  value={billDraft.amount}
                  onChange={(event) =>
                    setBillDraft((current) => ({ ...current, amount: event.target.value }))
                  }
                  required
                />
              </Field>
              <Field label="Due date" htmlFor="bill-date">
                <Input
                  id="bill-date"
                  type="date"
                  value={billDraft.due_date}
                  onChange={(event) =>
                    setBillDraft((current) => ({
                      ...current,
                      due_date: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field label="Type" htmlFor="bill-type">
                <Select
                  id="bill-type"
                  value={billDraft.bill_type}
                  onChange={(event) =>
                    setBillDraft((current) => ({
                      ...current,
                      bill_type: event.target.value as RoadmapBill['bill_type'],
                    }))
                  }
                >
                  <option value="bill">Bill</option>
                  <option value="subscription">Subscription</option>
                  <option value="utility">Utility</option>
                  <option value="insurance">Insurance</option>
                  <option value="rent">Rent</option>
                </Select>
              </Field>
              <div className="sm:col-span-2">
                <Button type="submit" disabled={createBill.isPending}>
                  {createBill.isPending ? 'Saving…' : 'Save bill'}
                </Button>
              </div>
              <InlineError error={mutationError(createBill.error)} />
            </form>
          </details>
        </section>

        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="health-check-title">
          <div className="flex items-start gap-3">
            <span className="bg-success/12 grid h-10 w-10 shrink-0 place-items-center rounded-lg text-success">
              <HeartPulse className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <h2 id="health-check-title" className="text-lg font-extrabold tracking-[-0.025em]">
                Financial safety checklist
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                User-confirmed status only; PFIS does not infer coverage.
              </p>
            </div>
          </div>
          <ul className="mt-4 divide-y divide-border/65">
            {checklistDefaults.map((definition) => {
              const saved = health.data?.find((item) => item.item_type === definition.item_type);
              const status = saved?.status ?? 'not_started';
              const nextStatus = status === 'complete' ? 'not_started' : 'complete';
              return (
                <li key={definition.item_type} className="flex items-center gap-3 py-3">
                  <button
                    type="button"
                    className={`focus-ring grid h-11 w-11 shrink-0 place-items-center rounded-lg ${
                      status === 'complete'
                        ? 'bg-success/12 text-success'
                        : 'bg-muted text-muted-foreground'
                    }`}
                    aria-label={`${definition.label}: ${statusLabel[status]}. Change to ${statusLabel[nextStatus]}.`}
                    onClick={() => updateHealth.mutate({ item: definition, status: nextStatus })}
                    disabled={updateHealth.isPending}
                  >
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                  <div className="min-w-0">
                    <p className="text-sm font-extrabold">{definition.label}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{statusLabel[status]}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="payoff-title">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,0.7fr)_minmax(0,1.3fr)]">
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              OPTIONAL ANALYSIS
            </p>
            <h2 id="payoff-title" className="mt-1 text-lg font-extrabold tracking-[-0.025em]">
              Deterministic payoff comparison
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Compare highest-interest-first with smallest-balance-first using only explicit
              balances, rates, and minimums.
            </p>
            <div className="mt-4 max-w-xs">
              <Field label="Monthly debt budget" htmlFor="payoff-budget">
                <Input
                  id="payoff-budget"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  step="0.01"
                  placeholder={minimumDebt ? String(minimumDebt) : '25000'}
                  value={monthlyBudget}
                  onChange={(event) => setMonthlyBudget(event.target.value)}
                />
              </Field>
            </div>
          </div>
          <div aria-live="polite">
            {!payoffBudget ? (
              <EmptyState
                icon={<Scale className="h-5 w-5" aria-hidden="true" />}
                title="Enter a monthly debt budget"
                description="PFIS will show assumptions and exclude incomplete liabilities."
              />
            ) : payoff.data?.readiness !== 'ready' ? (
              <EmptyState
                icon={<ShieldCheck className="h-5 w-5" aria-hidden="true" />}
                title={
                  payoff.data?.readiness === 'insufficient_budget'
                    ? 'Budget is below known minimums'
                    : 'Complete liability evidence first'
                }
                description={
                  payoff.data?.assumptions[payoff.data.assumptions.length - 1] ??
                  'Add explicit balance, interest rate, and minimum payment.'
                }
              />
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {payoff.data.scenarios.map((scenario) => (
                  <article key={scenario.method} className="rounded-lg bg-muted/55 p-4">
                    <p className="text-xs font-extrabold tracking-[0.06em] text-muted-foreground">
                      {scenario.method === 'highest_interest_first'
                        ? 'HIGHEST INTEREST FIRST'
                        : 'SMALLEST BALANCE FIRST'}
                    </p>
                    <p className="money-value mt-2 text-2xl font-extrabold">
                      {scenario.estimated_months ?? '—'} months
                    </p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Estimated interest{' '}
                      {scenario.estimated_interest == null
                        ? 'unavailable'
                        : formatCurrency(scenario.estimated_interest, currency)}
                    </p>
                    <p className="mt-3 text-xs leading-5 text-muted-foreground">
                      {scenario.payoff_order.join(' → ')}
                    </p>
                  </article>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function HouseholdWorkspace() {
  const { user } = useAuth();
  const financialToday = dateInputValueInTimezone(user?.timezone ?? 'Asia/Kolkata');
  const queryClient = useQueryClient();
  const households = useHouseholds();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const householdId = selectedId ?? households.data?.[0]?.id ?? '';
  const selected = households.data?.find((item) => item.id === householdId);
  const [householdName, setHouseholdName] = useState('');
  const [memberId, setMemberId] = useState('');
  const [memberRole, setMemberRole] = useState<'member' | 'viewer'>('member');
  const [deleteConfirmation, setDeleteConfirmation] = useState('');
  const [expenseDraft, setExpenseDraft] = useState({
    label: '',
    amount: '',
    payer_user_id: '',
    expense_date: financialToday,
  });
  const [settlementDraft, setSettlementDraft] = useState({
    from_user_id: '',
    to_user_id: '',
    amount: '',
    settlement_date: financialToday,
  });
  const members = useQuery({
    queryKey: queryKeys.householdMembers(user?.id ?? '', householdId),
    queryFn: () => api.householdMembers(user!.id, householdId),
    enabled: Boolean(user && householdId),
  });
  const expenses = useQuery({
    queryKey: queryKeys.householdExpenses(user?.id ?? '', householdId),
    queryFn: () => api.householdExpenses(user!.id, householdId),
    enabled: Boolean(user && householdId),
  });
  const settlements = useQuery({
    queryKey: queryKeys.householdSettlements(user?.id ?? '', householdId),
    queryFn: () => api.householdSettlements(user!.id, householdId),
    enabled: Boolean(user && householdId),
  });
  const createHousehold = useMutation({
    mutationFn: () => api.createHousehold(user!.id, householdName),
    onSuccess: async (created) => {
      setHouseholdName('');
      setSelectedId(created.id);
      await queryClient.invalidateQueries({ queryKey: queryKeys.households(user!.id) });
    },
  });
  const addMember = useMutation({
    mutationFn: () => api.addHouseholdMember(user!.id, householdId, memberId, memberRole),
    onSuccess: async () => {
      setMemberId('');
      setMemberRole('member');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.households(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.householdMembers(user!.id, householdId),
        }),
      ]);
    },
  });
  const updateMember = useMutation({
    mutationFn: ({ memberUserId, role }: { memberUserId: string; role: 'member' | 'viewer' }) =>
      api.updateHouseholdMember(user!.id, householdId, memberUserId, role),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.households(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.householdMembers(user!.id, householdId),
        }),
      ]);
    },
  });
  const removeMember = useMutation({
    mutationFn: (memberUserId: string) =>
      api.removeHouseholdMember(user!.id, householdId, memberUserId),
    onSuccess: async (_, removedUserId) => {
      if (removedUserId === user!.id) setSelectedId(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.households(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.householdMembers(user!.id, householdId),
        }),
      ]);
    },
  });
  const createExpense = useMutation({
    mutationFn: () => {
      const participants = members.data ?? [];
      const amount = Number(expenseDraft.amount);
      const share = Math.floor((amount * 100) / participants.length) / 100;
      let assigned = 0;
      const splits = Object.fromEntries(
        participants.map((member, index) => {
          const value =
            index === participants.length - 1 ? Number((amount - assigned).toFixed(2)) : share;
          assigned += value;
          return [member.user_id, value];
        }),
      );
      return api.createHouseholdExpense(user!.id, householdId, {
        ...expenseDraft,
        amount,
        payer_user_id: expenseDraft.payer_user_id || user!.id,
        currency: user!.currency,
        splits,
      });
    },
    onSuccess: async () => {
      setExpenseDraft((current) => ({ ...current, label: '', amount: '' }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.households(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.householdExpenses(user!.id, householdId),
        }),
      ]);
    },
  });
  const createSettlement = useMutation({
    mutationFn: () =>
      api.createHouseholdSettlement(user!.id, householdId, {
        ...settlementDraft,
        amount: Number(settlementDraft.amount),
        currency: user!.currency,
      }),
    onSuccess: async () => {
      setSettlementDraft((current) => ({ ...current, amount: '' }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.households(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.householdSettlements(user!.id, householdId),
        }),
      ]);
    },
  });
  const updateSettlement = useMutation({
    mutationFn: ({
      settlement,
      status,
    }: {
      settlement: HouseholdSettlement;
      status: 'recorded' | 'cancelled';
    }) =>
      api.updateHouseholdSettlement(user!.id, householdId, settlement.id, {
        status,
        note: settlement.note,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.households(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.householdSettlements(user!.id, householdId),
        }),
      ]);
    },
  });
  const deleteHousehold = useMutation({
    mutationFn: () => api.deleteHousehold(user!.id, householdId),
    onSuccess: async () => {
      setDeleteConfirmation('');
      setSelectedId(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.households(user!.id) });
    },
  });

  const participants = useMemo(() => members.data ?? [], [members.data]);
  const currentMembership = participants.find((member) => member.user_id === user?.id);
  const canEdit = currentMembership?.role === 'owner' || currentMembership?.role === 'member';
  const isOwner = selected?.owner_user_id === user?.id;
  const memberLabel = (member: HouseholdMember) =>
    member.user_id === user?.id ? 'You' : `Member …${member.user_id.slice(-6)}`;

  if (!households.data?.length) {
    return (
      <section className="mx-auto max-w-2xl rounded-xl bg-card p-5 sm:p-7">
        <span className="bg-intelligence/12 grid h-11 w-11 place-items-center rounded-lg text-intelligence">
          <Home className="h-5 w-5" aria-hidden="true" />
        </span>
        <h2 className="mt-4 text-xl font-extrabold tracking-[-0.03em]">
          Start a privacy-safe household
        </h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Members see shared annotations and settlements only. Private accounts, transactions,
          statement lines, and source evidence remain private.
        </p>
        <form
          className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            if (householdName.trim()) createHousehold.mutate();
          }}
        >
          <div className="min-w-0 flex-1">
            <Field label="Household name" htmlFor="household-name">
              <Input
                id="household-name"
                value={householdName}
                onChange={(event) => setHouseholdName(event.target.value)}
                required
              />
            </Field>
          </div>
          <Button type="submit" disabled={createHousehold.isPending}>
            Create household
          </Button>
        </form>
        <InlineError error={mutationError(createHousehold.error)} />
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <FinancialHero className="bg-intelligence/10">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(17rem,0.8fr)] lg:items-end">
          <div>
            <div className="flex items-center gap-2 text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              <Users className="h-4 w-4 text-intelligence" aria-hidden="true" />
              SHARED ANNOTATIONS ONLY
            </div>
            <h2 className="mt-2 text-3xl font-extrabold tracking-[-0.05em]">{selected?.name}</h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              Private financial evidence is never shared. Settlements are records of intent or
              completion; PFIS does not move money.
            </p>
          </div>
          <dl className="grid grid-cols-3 gap-3 border-t border-border/70 pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
            <Metric label="Members" value={selected?.member_count ?? 0} />
            <Metric label="Expenses" value={selected?.expense_count ?? 0} />
            <Metric label="Open" value={selected?.open_settlement_count ?? 0} />
          </dl>
        </div>
      </FinancialHero>

      <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Households">
        {(households.data ?? []).map((household) => (
          <button
            key={household.id}
            type="button"
            aria-pressed={household.id === householdId}
            onClick={() => setSelectedId(household.id)}
            className="focus-ring min-h-11 shrink-0 rounded-lg border border-border px-3 text-sm font-bold hover:bg-muted"
          >
            {household.name}
          </button>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(19rem,0.8fr)]">
        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="shared-expenses-title">
          <h2 id="shared-expenses-title" className="text-lg font-extrabold tracking-[-0.025em]">
            Shared expense annotations
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Equal splits are stored independently from every member’s private ledger.
          </p>
          <div className="mt-4">
            {(expenses.data ?? []).length ? (
              (expenses.data ?? []).map((expense) => (
                <LedgerRow
                  key={expense.id}
                  leading={<Receipt className="h-4 w-4" aria-hidden="true" />}
                  title={expense.label}
                  subtitle={`${formatDate(expense.expense_date)} · ${
                    expense.payer_user_id === user?.id
                      ? 'paid by you'
                      : `paid by member …${expense.payer_user_id.slice(-6)}`
                  }`}
                  amount={formatCurrency(expense.amount, expense.currency)}
                />
              ))
            ) : (
              <p className="rounded-lg bg-muted/55 p-4 text-sm text-muted-foreground">
                No shared annotations yet.
              </p>
            )}
          </div>
          {canEdit ? (
            <details className="mt-5 rounded-lg border border-border/70 p-4">
              <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
                Add an equal-split expense
              </summary>
              <form
                className="mt-4 grid gap-4 sm:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (
                    expenseDraft.label.trim() &&
                    Number(expenseDraft.amount) > 0 &&
                    participants.length
                  ) {
                    createExpense.mutate();
                  }
                }}
              >
                <Field label="Expense label" htmlFor="expense-label">
                  <Input
                    id="expense-label"
                    value={expenseDraft.label}
                    onChange={(event) =>
                      setExpenseDraft((current) => ({
                        ...current,
                        label: event.target.value,
                      }))
                    }
                    required
                  />
                </Field>
                <Field label="Amount" htmlFor="expense-amount">
                  <Input
                    id="expense-amount"
                    type="number"
                    inputMode="decimal"
                    min="0.01"
                    step="0.01"
                    value={expenseDraft.amount}
                    onChange={(event) =>
                      setExpenseDraft((current) => ({
                        ...current,
                        amount: event.target.value,
                      }))
                    }
                    required
                  />
                </Field>
                <Field label="Paid by" htmlFor="expense-payer">
                  <Select
                    id="expense-payer"
                    value={expenseDraft.payer_user_id || user?.id}
                    onChange={(event) =>
                      setExpenseDraft((current) => ({
                        ...current,
                        payer_user_id: event.target.value,
                      }))
                    }
                  >
                    {participants.map((member) => (
                      <option key={member.id} value={member.user_id}>
                        {memberLabel(member)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Date" htmlFor="expense-date">
                  <Input
                    id="expense-date"
                    type="date"
                    value={expenseDraft.expense_date}
                    onChange={(event) =>
                      setExpenseDraft((current) => ({
                        ...current,
                        expense_date: event.target.value,
                      }))
                    }
                  />
                </Field>
                <div className="sm:col-span-2">
                  <Button type="submit" disabled={createExpense.isPending || !participants.length}>
                    Save shared annotation
                  </Button>
                </div>
                <InlineError error={mutationError(createExpense.error)} />
              </form>
            </details>
          ) : (
            <p className="mt-5 rounded-lg bg-muted/55 p-4 text-sm text-muted-foreground">
              Viewer access is read-only. Ask the household owner for member access to add
              annotations or settlements.
            </p>
          )}
        </section>

        <aside className="space-y-6">
          <section className="rounded-xl bg-card p-5" aria-labelledby="members-title">
            <h2 id="members-title" className="font-extrabold">
              Membership
            </h2>
            <ul className="mt-3 divide-y divide-border/65">
              {participants.map((member) => (
                <li key={member.id} className="flex items-center gap-3 py-3">
                  <span className="min-w-0 flex-1 truncate text-sm font-bold">
                    {memberLabel(member)}
                  </span>
                  {isOwner && member.role !== 'owner' ? (
                    <>
                      <Label className="sr-only" htmlFor={`member-role-${member.id}`}>
                        Access for {memberLabel(member)}
                      </Label>
                      <Select
                        id={`member-role-${member.id}`}
                        aria-label={`Access for ${memberLabel(member)}`}
                        className="w-28"
                        value={member.role}
                        disabled={updateMember.isPending || removeMember.isPending}
                        onChange={(event) =>
                          updateMember.mutate({
                            memberUserId: member.user_id,
                            role: event.target.value as 'member' | 'viewer',
                          })
                        }
                      >
                        <option value="member">Member</option>
                        <option value="viewer">Viewer</option>
                      </Select>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={removeMember.isPending || updateMember.isPending}
                        onClick={() => removeMember.mutate(member.user_id)}
                      >
                        Remove
                      </Button>
                    </>
                  ) : (
                    <Badge variant="outline">{member.role}</Badge>
                  )}
                </li>
              ))}
            </ul>
            <InlineError
              error={mutationError(updateMember.error) ?? mutationError(removeMember.error)}
            />
            {isOwner ? (
              <form
                className="mt-4 space-y-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (memberId.trim()) addMember.mutate();
                }}
              >
                <Field label="Add by PFIS user ID" htmlFor="member-id">
                  <Input
                    id="member-id"
                    value={memberId}
                    onChange={(event) => setMemberId(event.target.value)}
                    required
                  />
                </Field>
                <Field label="Access" htmlFor="member-role">
                  <Select
                    id="member-role"
                    value={memberRole}
                    onChange={(event) => setMemberRole(event.target.value as 'member' | 'viewer')}
                  >
                    <option value="member">Member — can add shared records</option>
                    <option value="viewer">Viewer — read only</option>
                  </Select>
                </Field>
                <Button className="mt-3 w-full" type="submit" variant="outline">
                  Add member
                </Button>
                <InlineError error={mutationError(addMember.error)} />
              </form>
            ) : currentMembership?.role !== 'owner' ? (
              <div className="mt-4 border-t border-border/65 pt-4">
                <Button
                  className="w-full"
                  variant="outline"
                  disabled={removeMember.isPending}
                  onClick={() => removeMember.mutate(user!.id)}
                >
                  Leave household
                </Button>
              </div>
            ) : null}
          </section>

          <section className="rounded-xl bg-card p-5" aria-labelledby="settlements-title">
            <h2 id="settlements-title" className="font-extrabold">
              Settlements
            </h2>
            <div className="mt-3 divide-y divide-border/65">
              {(settlements.data ?? []).map((settlement) => (
                <div key={settlement.id} className="py-3">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="money-value text-sm font-extrabold">
                      {formatCurrency(settlement.amount, settlement.currency)}
                    </p>
                    <Badge
                      variant={
                        settlement.status === 'planned'
                          ? 'warning'
                          : settlement.status === 'recorded'
                            ? 'success'
                            : 'outline'
                      }
                    >
                      {settlement.status}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Member …{settlement.from_user_id.slice(-6)} → member …
                    {settlement.to_user_id.slice(-6)}
                  </p>
                  {settlement.status === 'planned' && canEdit ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={updateSettlement.isPending}
                        onClick={() => updateSettlement.mutate({ settlement, status: 'recorded' })}
                      >
                        Record complete
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={updateSettlement.isPending}
                        onClick={() => updateSettlement.mutate({ settlement, status: 'cancelled' })}
                      >
                        Cancel intention
                      </Button>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            <InlineError error={mutationError(updateSettlement.error)} />
            {canEdit && participants.length >= 2 ? (
              <details className="mt-4 border-t border-border/65 pt-4">
                <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
                  Plan settlement
                </summary>
                <form
                  className="mt-4 space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (
                      settlementDraft.from_user_id &&
                      settlementDraft.to_user_id &&
                      settlementDraft.from_user_id !== settlementDraft.to_user_id &&
                      Number(settlementDraft.amount) > 0
                    ) {
                      createSettlement.mutate();
                    }
                  }}
                >
                  <Field label="From" htmlFor="settlement-from">
                    <Select
                      id="settlement-from"
                      value={settlementDraft.from_user_id}
                      onChange={(event) =>
                        setSettlementDraft((current) => ({
                          ...current,
                          from_user_id: event.target.value,
                        }))
                      }
                      required
                    >
                      <option value="">Select member</option>
                      {participants.map((member) => (
                        <option key={member.id} value={member.user_id}>
                          {memberLabel(member)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="To" htmlFor="settlement-to">
                    <Select
                      id="settlement-to"
                      value={settlementDraft.to_user_id}
                      onChange={(event) =>
                        setSettlementDraft((current) => ({
                          ...current,
                          to_user_id: event.target.value,
                        }))
                      }
                      required
                    >
                      <option value="">Select member</option>
                      {participants.map((member) => (
                        <option key={member.id} value={member.user_id}>
                          {memberLabel(member)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Amount" htmlFor="settlement-amount">
                    <Input
                      id="settlement-amount"
                      type="number"
                      inputMode="decimal"
                      min="0.01"
                      step="0.01"
                      value={settlementDraft.amount}
                      onChange={(event) =>
                        setSettlementDraft((current) => ({
                          ...current,
                          amount: event.target.value,
                        }))
                      }
                      required
                    />
                  </Field>
                  <Button type="submit" className="w-full">
                    Save intention
                  </Button>
                  <InlineError error={mutationError(createSettlement.error)} />
                </form>
              </details>
            ) : canEdit ? (
              <p className="mt-4 text-xs leading-5 text-muted-foreground">
                Add another household member to create settlements.
              </p>
            ) : null}
          </section>
        </aside>
      </div>

      <section className="rounded-xl border border-border/70 bg-card/60 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-hidden="true" />
            <div>
              <h2 className="font-extrabold">Privacy and deletion boundary</h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Members receive annotation-only visibility. Removing a member revokes access but
                retains shared history. Owners can delete a household only after planned settlements
                are recorded or cancelled; private ledgers are never deleted.
              </p>
            </div>
          </div>
          {isOwner ? (
            <details className="w-full shrink-0 lg:ml-auto lg:max-w-xs">
              <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold text-danger">
                Delete household
              </summary>
              <div className="mt-3 rounded-lg border border-danger/25 bg-danger/5 p-3">
                <Field label={`Type “${selected?.name}” to confirm`} htmlFor="delete-household">
                  <Input
                    id="delete-household"
                    value={deleteConfirmation}
                    autoComplete="off"
                    onChange={(event) => setDeleteConfirmation(event.target.value)}
                  />
                </Field>
                {selected?.open_settlement_count ? (
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    Record or cancel all planned settlements before deletion.
                  </p>
                ) : null}
                <Button
                  className="mt-3 w-full"
                  variant="danger"
                  disabled={
                    deleteHousehold.isPending ||
                    Boolean(selected?.open_settlement_count) ||
                    deleteConfirmation !== selected?.name
                  }
                  onClick={() => deleteHousehold.mutate()}
                >
                  Permanently delete shared records
                </Button>
                <InlineError error={mutationError(deleteHousehold.error)} />
              </div>
            </details>
          ) : (
            <ChevronRight
              className="ml-auto hidden h-4 w-4 text-muted-foreground sm:block"
              aria-hidden="true"
            />
          )}
        </div>
      </section>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}

function InlineError({ error }: { error: string | null }) {
  return error ? (
    <p role="alert" className="text-sm font-bold text-danger sm:col-span-2">
      {error}
    </p>
  ) : null;
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt className="text-xs font-bold text-muted-foreground">{label}</dt>
      <dd className="money-value mt-1 text-lg font-extrabold">{value}</dd>
    </div>
  );
}
