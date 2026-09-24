import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CalendarClock,
  CheckCircle2,
  Landmark,
  PiggyBank,
  Plus,
  Receipt,
  ShieldCheck,
  WalletCards,
} from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { FinancialHero, InsightSurface, LedgerRow } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Label, Select } from '@/components/ui/Input';
import { EmptyState } from '@/components/ui/Skeleton';
import { useToast } from '@/components/ui/Toast';
import { AccountIdentityDialog } from '@/features/accounts/AccountIdentityDialog';
import { useAuth } from '@/features/auth/AuthContext';
import {
  queryKeys,
  useAccountBalanceForecast,
  useAccounts,
  useCashPlan,
  useCommitments,
  useLiabilityOverview,
  useReserves,
} from '@/features/workspace/queries';
import { api } from '@/lib/api';
import {
  calendarDayDifference,
  dateInputValueInTimezone,
  formatCurrency,
  formatDate,
  formatTime,
} from '@/lib/format';
import type {
  CashPlan,
  AccountBalanceForecast,
  Commitment,
  FinancialAccount,
  Liability,
  LiabilityOverview,
  LiabilityScheduleItem,
  ReservePlan,
} from '@/lib/types';

export function FinancialPositionSection({ view }: { view: 'cash-plan' | 'liabilities' }) {
  const { user } = useAuth();
  const cashPlan = useCashPlan();
  const commitments = useCommitments();
  const reserves = useReserves();
  const liabilityOverview = useLiabilityOverview();
  const accounts = useAccounts();
  const data = view === 'cash-plan' ? cashPlan.data : liabilityOverview.data;

  if (!data && (cashPlan.isLoading || liabilityOverview.isLoading || accounts.isLoading)) {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-label="Loading financial position…"
        className="h-80 animate-soft-pulse rounded-xl bg-muted"
      />
    );
  }
  if (view === 'liabilities') {
    return (
      <LiabilityWorkspace
        overview={
          liabilityOverview.data ?? {
            currency: user?.currency ?? 'INR',
            liabilities: [],
            known_monthly_debt: 0,
            confirmed_monthly_debt: 0,
            observed_card_emi_monthly: 0,
            next_due_date: null,
            next_due_amount: null,
            complete_schedule_count: 0,
            partial_evidence_count: 0,
            assumptions: [],
          }
        }
        accounts={accounts.data ?? []}
      />
    );
  }
  const plan = cashPlan.data;
  if (!plan || plan.readiness !== 'ready') {
    return <CashPlanSetup plan={plan} accounts={accounts.data ?? []} />;
  }
  return (
    <CashPlanWorkspace
      plan={plan}
      accounts={accounts.data ?? []}
      commitments={commitments.data ?? []}
      reserves={reserves.data ?? []}
    />
  );
}

function CashPlanSetup({ plan, accounts }: { plan?: CashPlan; accounts: FinancialAccount[] }) {
  const { user } = useAuth();
  const financialToday = dateInputValueInTimezone(user?.timezone ?? 'Asia/Kolkata');
  const { scrollTo } = useDashboardUi();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const bankAccounts = useMemo(
    () => accounts.filter((account) => account.is_active && account.account_type === 'bank'),
    [accounts],
  );
  const unresolvedAccounts = useMemo(
    () => accounts.filter((account) => account.is_active && account.account_type === 'unknown'),
    [accounts],
  );
  const [accountId, setAccountId] = useState(
    bankAccounts.find((account) => account.id === plan?.primary_financial_account_id)?.id ||
      bankAccounts[0]?.id ||
      '',
  );
  const [incomeDate, setIncomeDate] = useState(plan?.next_income_date ?? '');
  const [identityAccountId, setIdentityAccountId] = useState<string | null>(null);
  const [balanceAmount, setBalanceAmount] = useState('');
  const [balanceAsOf, setBalanceAsOf] = useState(financialToday);
  const selectedAccount = bankAccounts.find((account) => account.id === accountId);
  const selectedSnapshotAge = selectedAccount?.balance_as_of
    ? calendarDayDifference(financialToday, selectedAccount.balance_as_of)
    : null;
  const needsBalance =
    selectedAccount?.latest_balance == null ||
    selectedSnapshotAge == null ||
    selectedSnapshotAge > 7 ||
    (plan?.primary_financial_account_id === selectedAccount?.id &&
      (plan?.readiness === 'needs_verified_balance' || plan?.readiness === 'needs_fresh_balance'));
  const needsPositionReview = plan?.readiness === 'needs_position_review';

  useEffect(() => {
    if (!bankAccounts.some((account) => account.id === accountId) && bankAccounts[0]) {
      setAccountId(bankAccounts[0].id);
    }
  }, [accountId, bankAccounts]);

  const saveBalance = useMutation({
    mutationFn: () => api.addBalance(user!.id, accountId, Number(balanceAmount), balanceAsOf),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.netWorth(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.balanceForecast(user!.id, accountId),
        }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', user!.id] }),
      ]);
      setBalanceAmount('');
      notify('Observed balance recorded', 'success');
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  const save = useMutation({
    mutationFn: () =>
      api.updateCashPlan(user!.id, {
        primary_financial_account_id: accountId,
        next_income_date: incomeDate,
        show_daily_allowance: false,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user!.id) });
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  if (!bankAccounts.length) {
    return (
      <>
        <section className="mx-auto max-w-3xl border-y border-border/70 py-6">
          <div className="flex gap-4">
            <span className="bg-intelligence/12 grid h-11 w-11 shrink-0 place-items-center rounded-lg text-intelligence">
              <WalletCards className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <p className="text-xs font-extrabold tracking-[0.1em] text-muted-foreground">
                CASH PLAN · STEP 1 OF 3
              </p>
              <h2 className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
                Confirm which account funds daily life
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                PFIS found account evidence, but it will not call an instrument a bank account until
                you confirm it. This keeps card liabilities and cash balances out of the
                spendable-money calculation.
              </p>
            </div>
          </div>
          {unresolvedAccounts.length ? (
            <div className="mt-5 divide-y divide-border/70 border-y border-border/70">
              {unresolvedAccounts.map((account) => (
                <div
                  key={account.id}
                  className="flex min-h-14 flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="text-sm font-bold">
                      {account.institution_name === 'Unknown'
                        ? `Unidentified instrument ${account.masked_number}`
                        : account.institution_name}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Imported evidence · {account.currency} · not used in calculations
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setIdentityAccountId(account.id)}
                  >
                    Confirm product
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-5">
              <EmptyState
                icon={<Landmark className="h-5 w-5" aria-hidden="true" />}
                title="No bank account evidence yet"
                description="Add a bank account manually, then return here to record a dated balance observation."
                action={
                  <Button variant="outline" onClick={() => scrollTo('networth')}>
                    Add account in Position
                  </Button>
                }
              />
            </div>
          )}
        </section>
        <AccountIdentityDialog
          account={accounts.find((account) => account.id === identityAccountId) ?? null}
          onClose={() => setIdentityAccountId(null)}
          onResolved={(account) => setAccountId(account.id)}
        />
      </>
    );
  }

  return (
    <section className="mx-auto max-w-3xl border-y border-border/70 py-6">
      <div className="flex gap-4">
        <span className="bg-intelligence/12 grid h-11 w-11 shrink-0 place-items-center rounded-lg text-intelligence">
          <WalletCards className="h-5 w-5" aria-hidden="true" />
        </span>
        <div>
          <p className="text-xs font-extrabold tracking-[0.1em] text-muted-foreground">
            CASH PLAN · EVIDENCE SETUP
          </p>
          <h2 className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
            Establish the money PFIS can safely plan
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Confirm one funding account, a recent observed balance, and the next income date. These
            are facts you control—not salary or live-balance guesses.
          </p>
        </div>
      </div>
      {needsPositionReview ? (
        <div
          className="mt-4 flex flex-col gap-3 border-l-2 border-warning/70 pl-4 sm:flex-row sm:items-center sm:justify-between"
          role="status"
          aria-live="polite"
        >
          <p className="text-sm leading-6 text-muted-foreground">
            The latest position includes activity that is pending, unreviewed, or missing a reliable
            cutoff. PFIS is showing the evidence, but it will not call the amount spendable until
            that activity is resolved.
            {plan?.estimated_balance != null ? (
              <span className="block font-bold text-foreground">
                Estimated current position: {formatCurrency(plan.estimated_balance, plan.currency)}
                {plan.estimated_balance_as_of
                  ? ` · as of ${formatDate(plan.estimated_balance_as_of)}`
                  : ''}
              </span>
            ) : null}
          </p>
          <Button type="button" size="sm" variant="outline" onClick={() => scrollTo('review')}>
            Review activity
          </Button>
        </div>
      ) : null}
      <form
        className="mt-5 grid gap-x-8 gap-y-4 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (accountId && incomeDate && !needsBalance) save.mutate();
        }}
      >
        <div className="grid gap-2 border-b border-border/70 pb-4 sm:grid-cols-[1.5rem_minmax(0,1fr)] md:col-span-2">
          <CheckCircle2 className="mt-7 h-5 w-5 text-success" aria-hidden="true" />
          <Field label="1. Primary bank account" htmlFor="cash-plan-account">
            <Select
              id="cash-plan-account"
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
            >
              {bankAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.institution_name} · {account.masked_number}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div className="grid gap-3 border-b border-border/70 pb-4 sm:grid-cols-[1.5rem_minmax(0,1fr)]">
          <CheckCircle2
            className={`mt-0.5 h-5 w-5 ${needsBalance ? 'text-muted-foreground' : 'text-success'}`}
            aria-hidden="true"
          />
          <div>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <p className="text-sm font-bold">2. Recent observed balance</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {selectedAccount?.latest_balance == null
                    ? 'No balance observation has been recorded.'
                    : `${formatCurrency(selectedAccount.latest_balance, selectedAccount.currency)} observed ${formatDate(selectedAccount.balance_as_of)}.`}
                </p>
              </div>
              {!needsBalance ? <Badge variant="success">Current</Badge> : null}
            </div>
            {needsBalance ? (
              <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem] sm:items-end">
                <Field label="Observed amount" htmlFor="cash-plan-balance">
                  <Input
                    id="cash-plan-balance"
                    type="number"
                    min="0"
                    step="0.01"
                    value={balanceAmount}
                    onChange={(event) => setBalanceAmount(event.target.value)}
                    placeholder="0.00"
                  />
                </Field>
                <Field label="Observed on" htmlFor="cash-plan-balance-date">
                  <Input
                    id="cash-plan-balance-date"
                    type="date"
                    max={financialToday}
                    value={balanceAsOf}
                    onChange={(event) => setBalanceAsOf(event.target.value)}
                  />
                </Field>
                <Button
                  type="button"
                  variant="outline"
                  className="sm:col-span-2 sm:justify-self-start"
                  onClick={() => saveBalance.mutate()}
                  disabled={
                    !accountId ||
                    balanceAmount === '' ||
                    Number(balanceAmount) < 0 ||
                    saveBalance.isPending
                  }
                >
                  Record balance
                </Button>
              </div>
            ) : null}
            <p className="mt-2 text-xs text-muted-foreground">
              Manual observations are append-only and labelled by date. They are never presented as
              a live bank balance.
            </p>
          </div>
        </div>

        <div className="grid gap-2 border-b border-border/70 pb-4 sm:grid-cols-[1.5rem_minmax(0,1fr)]">
          <CheckCircle2
            className={`mt-7 h-5 w-5 ${incomeDate ? 'text-success' : 'text-muted-foreground'}`}
            aria-hidden="true"
          />
          <Field label="3. Next confirmed income date" htmlFor="cash-plan-income-date">
            <Input
              id="cash-plan-income-date"
              type="date"
              min={financialToday}
              value={incomeDate}
              onChange={(event) => setIncomeDate(event.target.value)}
              required
            />
          </Field>
        </div>
        <div className="flex flex-wrap gap-2 pl-0 sm:pl-9 md:col-span-2">
          <Button type="submit" disabled={save.isPending || !incomeDate || needsBalance}>
            Calculate flexible money
          </Button>
          <Button type="button" variant="ghost" onClick={() => scrollTo('networth')}>
            Review all accounts
          </Button>
        </div>
      </form>
    </section>
  );
}

function CashPlanWorkspace({
  plan,
  accounts,
  commitments,
  reserves,
}: {
  plan: CashPlan;
  accounts: FinancialAccount[];
  commitments: Commitment[];
  reserves: ReservePlan[];
}) {
  const { user } = useAuth();
  const financialToday = dateInputValueInTimezone(user?.timezone ?? 'Asia/Kolkata');
  const balanceForecast = useAccountBalanceForecast(plan.primary_financial_account_id, 30);
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [commitment, setCommitment] = useState({
    label: '',
    amount: '',
    due_date: financialToday,
    commitment_type: 'bill',
    confirmed: false,
  });
  const [reserve, setReserve] = useState({
    label: '',
    target_amount: '',
    monthly_allocation: '',
    due_date: financialToday,
    approved: false,
  });
  const createCommitment = useMutation({
    mutationFn: () =>
      api.createCommitment(user!.id, {
        label: commitment.label,
        commitment_type: commitment.commitment_type,
        amount: Number(commitment.amount),
        due_date: commitment.due_date,
        cadence: null,
        financial_account_id: plan.primary_financial_account_id,
        liability_id: null,
        source_kind: 'manual',
        source_identifier: null,
        confirmed: commitment.confirmed,
      }),
    onSuccess: async () => {
      setCommitment((current) => ({
        ...current,
        label: '',
        amount: '',
        confirmed: false,
      }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.commitments(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.balanceForecast(user!.id, plan.primary_financial_account_id),
        }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', user!.id] }),
      ]);
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  const updateCommitment = useMutation({
    mutationFn: ({
      id,
      confirmed,
      is_active,
    }: {
      id: string;
      confirmed?: boolean;
      is_active?: boolean;
    }) => api.updateCommitment(user!.id, id, { confirmed, is_active }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.commitments(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.balanceForecast(user!.id, plan.primary_financial_account_id),
        }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', user!.id] }),
      ]);
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  const createReserve = useMutation({
    mutationFn: () =>
      api.createReserve(user!.id, {
        financial_account_id: plan.primary_financial_account_id,
        label: reserve.label,
        target_amount: Number(reserve.target_amount),
        due_date: reserve.due_date,
        monthly_allocation: Number(reserve.monthly_allocation),
        approved: reserve.approved,
      }),
    onSuccess: async () => {
      setReserve((current) => ({
        ...current,
        label: '',
        target_amount: '',
        monthly_allocation: '',
        approved: false,
      }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.reserves(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.balanceForecast(user!.id, plan.primary_financial_account_id),
        }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', user!.id] }),
      ]);
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  const updateReserve = useMutation({
    mutationFn: ({
      id,
      approved,
      is_active,
    }: {
      id: string;
      approved?: boolean;
      is_active?: boolean;
    }) => api.updateReserve(user!.id, id, { approved, is_active }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.reserves(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.balanceForecast(user!.id, plan.primary_financial_account_id),
        }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', user!.id] }),
      ]);
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  const fundingAccount = accounts.find(
    (account) => account.id === plan.primary_financial_account_id,
  );
  const currentPosition = plan.planning_balance ?? plan.estimated_balance ?? plan.verified_balance;
  const providerObserved =
    plan.observed_source === 'connector' &&
    plan.coverage_status === 'fresh' &&
    plan.coverage_complete === true;
  const positionBasis = providerObserved
    ? 'Provider-observed position'
    : plan.balance_basis === 'estimated'
      ? 'Estimated current position'
      : 'Observed position';
  const positionAsOf =
    plan.planning_balance_as_of ?? plan.estimated_balance_as_of ?? plan.balance_as_of;

  return (
    <div className="space-y-6">
      <FinancialHero>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              FLEXIBLE MONEY UNTIL {formatDate(plan.next_income_date)}
            </p>
            <p className="money-value mt-2 text-4xl font-extrabold tracking-[-0.06em] sm:text-5xl">
              {plan.flexible_money == null
                ? 'Not calculated'
                : formatCurrency(plan.flexible_money, plan.currency)}
            </p>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              Flexible money after confirmed commitments and approved reserves. It is a planning
              result, not a provider-reported live bank balance.
            </p>
            <div
              className="mt-4 border-t border-border/60 pt-3 text-xs text-muted-foreground"
              aria-live="polite"
            >
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-extrabold uppercase tracking-[0.1em] text-foreground">
                <span>{positionBasis}</span>
                <span className="text-muted-foreground/60">·</span>
                <span>
                  {currentPosition == null
                    ? 'Position unavailable'
                    : formatCurrency(currentPosition, plan.currency)}
                </span>
                {positionAsOf ? <span>· as of {formatDate(positionAsOf)}</span> : null}
              </div>
              <p className="mt-1 leading-5">
                {providerObserved
                  ? `Provider observation${plan.observed_at ? ` retrieved ${formatTime(plan.observed_at)}` : ''}; commitments and reserves are applied below.`
                  : plan.balance_basis === 'estimated'
                    ? `Observed anchor plus ${formatCurrency(plan.settled_movement_since_observation ?? 0, plan.currency)} of eligible settled movement.`
                    : 'No eligible settled movement has changed the observed anchor.'}
              </p>
            </div>
          </div>
          {plan.daily_allowance !== null ? (
            <Badge variant="info">
              Daily view {formatCurrency(plan.daily_allowance, plan.currency)}
            </Badge>
          ) : null}
        </div>
      </FinancialHero>

      <BalancePathPanel forecast={balanceForecast.data} isLoading={balanceForecast.isLoading} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(16rem,0.65fr)]">
        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="commitments-title">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 id="commitments-title" className="text-lg font-extrabold tracking-[-0.025em]">
                Before the next income
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Only commitments you explicitly confirmed are included.
              </p>
            </div>
            <Receipt className="h-5 w-5 text-intelligence" aria-hidden="true" />
          </div>
          {plan.confirmed_commitments.length ? (
            plan.confirmed_commitments.map((item) => (
              <LedgerRow
                key={item.id}
                leading={<span>{item.due_date.slice(-2)}</span>}
                title={item.label}
                subtitle={`${item.commitment_type} · due ${formatDate(item.due_date)}`}
                amount={formatCurrency(item.amount, plan.currency)}
              />
            ))
          ) : (
            <p className="py-5 text-sm text-muted-foreground">
              No confirmed commitments fall before the next income.
            </p>
          )}
          <details className="mt-5 rounded-lg border border-border/70 p-4">
            <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
              Add a confirmed commitment
            </summary>
            <form
              className="mt-4 grid gap-4 sm:grid-cols-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (commitment.label.trim() && Number(commitment.amount) > 0) {
                  createCommitment.mutate();
                }
              }}
            >
              <Field label="Label" htmlFor="commitment-label">
                <Input
                  id="commitment-label"
                  value={commitment.label}
                  onChange={(event) =>
                    setCommitment((current) => ({ ...current, label: event.target.value }))
                  }
                  required
                />
              </Field>
              <Field label="Amount" htmlFor="commitment-amount">
                <Input
                  id="commitment-amount"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  step="0.01"
                  value={commitment.amount}
                  onChange={(event) =>
                    setCommitment((current) => ({ ...current, amount: event.target.value }))
                  }
                  required
                />
              </Field>
              <Field label="Due date" htmlFor="commitment-date">
                <Input
                  id="commitment-date"
                  type="date"
                  value={commitment.due_date}
                  onChange={(event) =>
                    setCommitment((current) => ({
                      ...current,
                      due_date: event.target.value,
                    }))
                  }
                  required
                />
              </Field>
              <Field label="Type" htmlFor="commitment-type">
                <Select
                  id="commitment-type"
                  value={commitment.commitment_type}
                  onChange={(event) =>
                    setCommitment((current) => ({
                      ...current,
                      commitment_type: event.target.value,
                    }))
                  }
                >
                  <option value="bill">Bill</option>
                  <option value="rent">Rent</option>
                  <option value="insurance">Insurance</option>
                  <option value="emi">EMI</option>
                  <option value="other">Other</option>
                </Select>
              </Field>
              <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border border-border/70 px-3 py-2 text-sm sm:col-span-2">
                <input
                  type="checkbox"
                  checked={commitment.confirmed}
                  onChange={(event) =>
                    setCommitment((current) => ({
                      ...current,
                      confirmed: event.target.checked,
                    }))
                  }
                  className="h-5 w-5 accent-primary"
                />
                <span>
                  <span className="block font-bold">Include in flexible money now</span>
                  <span className="block text-xs leading-5 text-muted-foreground">
                    Leave this clear to save an unconfirmed draft that does not reduce spendable
                    money.
                  </span>
                </span>
              </label>
              <Button type="submit" disabled={createCommitment.isPending}>
                Save {commitment.confirmed ? 'confirmed commitment' : 'draft'}
              </Button>
            </form>
          </details>
          {commitments.length ? (
            <details className="mt-3 rounded-lg border border-border/70 p-4">
              <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
                Manage all commitments ({commitments.filter((item) => item.is_active).length}{' '}
                active)
              </summary>
              <div className="mt-3 divide-y divide-border/70">
                {commitments.map((item) => (
                  <div
                    key={item.id}
                    className="flex min-h-14 flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-bold">{item.label}</p>
                        <Badge
                          variant={
                            !item.is_active ? 'outline' : item.confirmed ? 'success' : 'warning'
                          }
                        >
                          {!item.is_active ? 'Paused' : item.confirmed ? 'Confirmed' : 'Draft'}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {formatCurrency(item.amount, plan.currency)} · due{' '}
                        {formatDate(item.due_date)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {item.is_active ? (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              updateCommitment.mutate({
                                id: item.id,
                                confirmed: !item.confirmed,
                              })
                            }
                          >
                            {item.confirmed ? 'Move to draft' : 'Confirm'}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              updateCommitment.mutate({ id: item.id, is_active: false })
                            }
                          >
                            Pause
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => updateCommitment.mutate({ id: item.id, is_active: true })}
                        >
                          Restore
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
        </section>

        <aside className="space-y-4">
          <InsightSurface
            icon={<Landmark className="h-4 w-4" aria-hidden="true" />}
            eyebrow={`${positionBasis} as of ${formatDate(positionAsOf)}`}
            title={formatCurrency(currentPosition, plan.currency)}
            description={fundingAccount?.institution_name ?? 'Recorded bank position'}
            tone="positive"
          />
          <InsightSurface
            icon={<Receipt className="h-4 w-4" aria-hidden="true" />}
            title={formatCurrency(plan.commitment_total, plan.currency)}
            description="Confirmed commitments"
            tone="attention"
          />
          <InsightSurface
            icon={<PiggyBank className="h-4 w-4" aria-hidden="true" />}
            title={formatCurrency(plan.approved_reserve_total, plan.currency)}
            description="Approved reserves this month"
            tone="intelligence"
          />
        </aside>
      </div>

      <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="reserves-title">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
            <PiggyBank className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 id="reserves-title" className="text-lg font-extrabold tracking-[-0.025em]">
              Future reserves
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Approved monthly allocations reduce flexible money; unapproved ideas do not.
            </p>
          </div>
        </div>
        <div className="mt-4 divide-y divide-border/70 border-y border-border/70">
          {reserves.length ? (
            reserves.map((item) => (
              <div
                key={item.id}
                className="flex min-h-16 flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <PiggyBank className="h-4 w-4 shrink-0 text-intelligence" aria-hidden="true" />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-bold">{item.label}</p>
                      <Badge
                        variant={
                          !item.is_active ? 'outline' : item.approved ? 'success' : 'warning'
                        }
                      >
                        {!item.is_active ? 'Paused' : item.approved ? 'Approved' : 'Draft'}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {formatCurrency(item.monthly_allocation, plan.currency)} per month · target{' '}
                      {formatCurrency(item.target_amount, plan.currency)} by{' '}
                      {formatDate(item.due_date)}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {item.is_active ? (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          updateReserve.mutate({ id: item.id, approved: !item.approved })
                        }
                      >
                        {item.approved ? 'Remove approval' : 'Approve'}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => updateReserve.mutate({ id: item.id, is_active: false })}
                      >
                        Pause
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => updateReserve.mutate({ id: item.id, is_active: true })}
                    >
                      Restore
                    </Button>
                  )}
                </div>
              </div>
            ))
          ) : (
            <p className="py-4 text-sm text-muted-foreground">
              No future expense reserves have been recorded.
            </p>
          )}
        </div>
        <details className="mt-5 rounded-lg border border-border/70 p-4">
          <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
            Add a future reserve
          </summary>
          <form
            className="mt-4 grid gap-4 sm:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (
                reserve.label.trim() &&
                Number(reserve.target_amount) > 0 &&
                Number(reserve.monthly_allocation) > 0
              ) {
                createReserve.mutate();
              }
            }}
          >
            <Field label="Expense label" htmlFor="reserve-label">
              <Input
                id="reserve-label"
                value={reserve.label}
                onChange={(event) =>
                  setReserve((current) => ({ ...current, label: event.target.value }))
                }
                required
              />
            </Field>
            <Field label="Target amount" htmlFor="reserve-target">
              <Input
                id="reserve-target"
                type="number"
                min="0.01"
                step="0.01"
                value={reserve.target_amount}
                onChange={(event) =>
                  setReserve((current) => ({
                    ...current,
                    target_amount: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field label="Monthly allocation" htmlFor="reserve-monthly">
              <Input
                id="reserve-monthly"
                type="number"
                min="0.01"
                step="0.01"
                value={reserve.monthly_allocation}
                onChange={(event) =>
                  setReserve((current) => ({
                    ...current,
                    monthly_allocation: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field label="Due date" htmlFor="reserve-date">
              <Input
                id="reserve-date"
                type="date"
                value={reserve.due_date}
                onChange={(event) =>
                  setReserve((current) => ({ ...current, due_date: event.target.value }))
                }
                required
              />
            </Field>
            <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border border-border/70 px-3 py-2 text-sm sm:col-span-2">
              <input
                type="checkbox"
                checked={reserve.approved}
                onChange={(event) =>
                  setReserve((current) => ({
                    ...current,
                    approved: event.target.checked,
                  }))
                }
                className="h-5 w-5 accent-primary"
              />
              <span>
                <span className="block font-bold">Approve this monthly allocation</span>
                <span className="block text-xs leading-5 text-muted-foreground">
                  Approval immediately reduces flexible money. Clear it to save the reserve as a
                  draft.
                </span>
              </span>
            </label>
            <Button type="submit" disabled={createReserve.isPending}>
              Save {reserve.approved ? 'approved reserve' : 'draft'}
            </Button>
          </form>
        </details>
      </section>
    </div>
  );
}

export function BalancePathPanel({
  forecast,
  isLoading,
}: {
  forecast?: AccountBalanceForecast;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <div className="h-64 animate-soft-pulse rounded-xl bg-muted" aria-hidden="true" />;
  }
  if (!forecast) return null;

  const isLiability = forecast.balance_kind === 'liability';
  const balanceLabel = isLiability ? 'outstanding' : 'cash';
  const statusVariant =
    forecast.status === 'ready'
      ? 'success'
      : forecast.status === 'needs_review'
        ? 'warning'
        : 'outline';
  const statusLabel =
    forecast.status === 'ready'
      ? 'Evidence path'
      : forecast.status === 'needs_review'
        ? 'Needs position review'
        : 'Needs observed anchor';
  const milestones = forecast.points
    .filter(
      (point, index, points) =>
        index === 0 ||
        index === points.length - 1 ||
        index % 7 === 0 ||
        point.event_count > 0 ||
        point.risk !== 'none',
    )
    .slice(0, 10);

  return (
    <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="balance-path-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="flex items-center gap-2 text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
            <CalendarClock className="h-4 w-4 text-intelligence" aria-hidden="true" />
            NEXT {forecast.horizon_days} DAYS · {isLiability ? 'OUTSTANDING' : 'BALANCE'} PATH
          </p>
          <h2 id="balance-path-title" className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
            Where this {balanceLabel} could land
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
            A deterministic path from the {forecast.starting_balance_basis ?? 'available'} position,
            using dated evidence and a settled-activity baseline. It is not a provider live balance.
          </p>
        </div>
        <Badge variant={statusVariant}>{statusLabel}</Badge>
      </div>

      {forecast.status === 'needs_anchor' ? (
        <div className="mt-5 rounded-lg border border-dashed border-border p-4 text-sm leading-6 text-muted-foreground">
          Record a dated balance or connect an observation for this account. PFIS will then show the
          future path without turning partial transaction history into a fake current amount.
        </div>
      ) : (
        <>
          <div className="mt-5 grid gap-4 sm:grid-cols-3">
            <div className="rounded-lg bg-muted/55 p-4">
              <p className="text-xs font-bold text-muted-foreground">Expected end</p>
              <p className="money-value mt-1 text-xl font-extrabold">
                {forecast.expected_ending_balance == null
                  ? '—'
                  : formatCurrency(forecast.expected_ending_balance, forecast.currency)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatDate(forecast.horizon_end)}
              </p>
            </div>
            <div className="rounded-lg bg-muted/55 p-4">
              <p className="text-xs font-bold text-muted-foreground">Lowest expected</p>
              <p className="money-value mt-1 text-xl font-extrabold">
                {forecast.lowest_expected_balance == null
                  ? '—'
                  : formatCurrency(forecast.lowest_expected_balance, forecast.currency)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {forecast.lowest_expected_date
                  ? formatDate(forecast.lowest_expected_date)
                  : 'No path'}
              </p>
            </div>
            <div className="rounded-lg bg-muted/55 p-4">
              <p className="text-xs font-bold text-muted-foreground">Uncertainty</p>
              <p className="mt-1 text-xl font-extrabold">
                {Math.round(forecast.confidence * 100)}%
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {forecast.data_sufficiency} evidence · {forecast.event_count} dated events
              </p>
            </div>
          </div>

          {forecast.first_shortfall_date ? (
            <p className="mt-4 rounded-lg bg-danger/10 px-4 py-3 text-sm font-bold leading-6 text-danger">
              The lower band crosses below zero by {formatDate(forecast.first_shortfall_date)}.
              Review the dated outflows before treating flexible money as safe.
            </p>
          ) : null}

          <div className="mt-5 divide-y divide-border/70 border-y border-border/70">
            {milestones.map((point) => (
              <div
                key={point.date}
                className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div>
                  <p className="text-sm font-bold">{formatDate(point.date)}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {point.event_count
                      ? `${point.event_count} dated event${point.event_count === 1 ? '' : 's'}`
                      : 'Settled-history baseline only'}
                    {point.risk_reasons.length ? ` · ${point.risk_reasons.join(', ')}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3 sm:justify-end">
                  <p className="money-value text-sm font-extrabold">
                    {point.expected_balance == null
                      ? '—'
                      : formatCurrency(point.expected_balance, forecast.currency)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    band{' '}
                    {point.low_balance == null
                      ? '—'
                      : formatCurrency(point.low_balance, forecast.currency)}{' '}
                    –{' '}
                    {point.high_balance == null
                      ? '—'
                      : formatCurrency(point.high_balance, forecast.currency)}
                  </p>
                  {point.risk !== 'none' ? (
                    <Badge variant={point.risk === 'shortfall' ? 'danger' : 'warning'}>
                      {point.risk === 'shortfall'
                        ? 'Shortfall'
                        : point.risk === 'limit_pressure'
                          ? 'Limit pressure'
                          : 'Watch'}
                    </Badge>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            {forecast.position_reason_codes.length
              ? `Position caveats: ${forecast.position_reason_codes.join(', ')}. `
              : ''}
            The band is a planning uncertainty range; issuer holds, pending authorizations, and
            provider available credit are not inferred.
          </p>
        </>
      )}
    </section>
  );
}

function LiabilityWorkspace({
  overview,
  accounts,
}: {
  overview: LiabilityOverview;
  accounts: FinancialAccount[];
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { liabilities, currency } = overview;
  const liabilityAccounts = accounts.filter((account) =>
    ['credit_card', 'loan', 'pay_later'].includes(account.account_type),
  );
  const [draft, setDraft] = useState({
    label: '',
    liability_type: 'loan' as Liability['liability_type'],
    financial_account_id: '',
    outstanding_principal: '',
    monthly_due: '',
    interest_rate: '',
    next_due_date: '',
  });
  const create = useMutation({
    mutationFn: () =>
      api.createLiability(user!.id, {
        label: draft.label,
        liability_type: draft.liability_type,
        financial_account_id: draft.financial_account_id || null,
        source_kind: 'manual',
        source_confidence: 1,
        outstanding_principal: Number(draft.outstanding_principal),
        monthly_due: Number(draft.monthly_due),
        next_due_date: draft.next_due_date || null,
        end_date: null,
        interest_rate: draft.interest_rate ? Number(draft.interest_rate) : null,
        tenure_months: null,
        remaining_installments: null,
        complete_schedule: false,
      }),
    onSuccess: async () => {
      setDraft((current) => ({
        ...current,
        label: '',
        outstanding_principal: '',
        monthly_due: '',
        interest_rate: '',
      }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.liabilities(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.liabilityOverview(user!.id),
        }),
      ]);
    },
  });

  return (
    <div className="space-y-7">
      <FinancialHero>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(16rem,0.75fr)] lg:items-end">
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              KNOWN MONTHLY DEBT PRESSURE
            </p>
            <p className="money-value mt-2 text-4xl font-extrabold tracking-[-0.06em] sm:text-5xl">
              {formatCurrency(overview.known_monthly_debt, currency)}
            </p>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Confirmed schedules and issuer-observed EMI components are separated below. PFIS does
              not turn an EMI label into a guessed balance, rate, or completion date.
            </p>
          </div>
          <dl className="divide-y divide-border/70 border-y border-border/70 text-sm">
            <DebtSummaryLine
              label="Confirmed schedules"
              value={formatCurrency(overview.confirmed_monthly_debt, currency)}
            />
            <DebtSummaryLine
              label="Observed card EMI"
              value={formatCurrency(overview.observed_card_emi_monthly, currency)}
              intelligence
            />
            <DebtSummaryLine
              label="Next sourced due"
              value={
                overview.next_due_date && overview.next_due_amount
                  ? `${formatCurrency(overview.next_due_amount, currency)} · ${formatDate(
                      overview.next_due_date,
                    )}`
                  : 'Not known'
              }
            />
          </dl>
        </div>
      </FinancialHero>

      <section
        className="overflow-hidden rounded-xl border border-border/70 bg-card"
        aria-labelledby="liability-title"
      >
        <header className="border-b border-border/70 px-5 py-5 sm:px-7">
          <p className="text-xs font-extrabold tracking-[0.08em] text-intelligence">
            SOURCE → OBLIGATION TRACE
          </p>
          <h2 id="liability-title" className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
            What the debt evidence actually says
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
            Observed facts, calculated totals, and missing schedule fields stay in one continuous
            ledger.
          </p>
        </header>
        {liabilities.length ? (
          <div>
            {liabilities.map((liability) => (
              <LiabilityEvidenceRow key={liability.id} liability={liability} currency={currency} />
            ))}
          </div>
        ) : (
          <div className="p-5 sm:p-7">
            <EmptyState
              icon={<ShieldCheck className="h-5 w-5" aria-hidden="true" />}
              title="No obligation evidence yet"
              description="Import a supported card statement or add a sourced loan. EMI-labelled lines become evidence, never a guessed schedule."
            />
          </div>
        )}
        <details className="border-t border-border/70 px-5 py-2 sm:px-7">
          <summary className="focus-ring min-h-11 cursor-pointer rounded py-4 text-sm font-extrabold">
            Add a sourced liability
          </summary>
          <form
            className="mt-4 grid gap-4 sm:grid-cols-2"
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              if (
                draft.label.trim() &&
                Number(draft.outstanding_principal) > 0 &&
                Number(draft.monthly_due) > 0
              ) {
                create.mutate();
              }
            }}
          >
            <Field label="Liability label" htmlFor="liability-label">
              <Input
                id="liability-label"
                name="liability_label"
                autoComplete="off"
                value={draft.label}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, label: event.target.value }))
                }
                required
              />
            </Field>
            <Field label="Product" htmlFor="liability-type">
              <Select
                id="liability-type"
                name="liability_type"
                autoComplete="off"
                value={draft.liability_type}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    liability_type: event.target.value as Liability['liability_type'],
                  }))
                }
              >
                <option value="loan">Loan</option>
                <option value="pay_later">Pay later</option>
                <option value="card_emi">Card EMI</option>
                <option value="credit_card">Credit card</option>
              </Select>
            </Field>
            <Field label="Linked account (optional)" htmlFor="liability-account">
              <Select
                id="liability-account"
                name="liability_account"
                autoComplete="off"
                value={draft.financial_account_id}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    financial_account_id: event.target.value,
                  }))
                }
              >
                <option value="">No linked account</option>
                {liabilityAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.institution_name} · {account.masked_number}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Outstanding balance" htmlFor="liability-balance">
              <Input
                id="liability-balance"
                name="liability_balance"
                autoComplete="off"
                type="number"
                min="0.01"
                step="0.01"
                value={draft.outstanding_principal}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    outstanding_principal: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field label="Monthly due" htmlFor="liability-monthly">
              <Input
                id="liability-monthly"
                name="liability_monthly_due"
                autoComplete="off"
                type="number"
                min="0.01"
                step="0.01"
                value={draft.monthly_due}
                onChange={(event) =>
                  setDraft((current) => ({ ...current, monthly_due: event.target.value }))
                }
                required
              />
            </Field>
            <Field label="Annual rate (optional)" htmlFor="liability-rate">
              <Input
                id="liability-rate"
                name="liability_annual_rate"
                autoComplete="off"
                type="number"
                min="0"
                step="0.0001"
                value={draft.interest_rate}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    interest_rate: event.target.value,
                  }))
                }
              />
            </Field>
            <Field label="Next due date (optional)" htmlFor="liability-date">
              <Input
                id="liability-date"
                name="liability_next_due_date"
                autoComplete="off"
                type="date"
                value={draft.next_due_date}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...current,
                    next_due_date: event.target.value,
                  }))
                }
              />
            </Field>
            <div className="flex items-end">
              <Button type="submit" disabled={create.isPending}>
                <Plus className="h-4 w-4" aria-hidden="true" />
                Save liability
              </Button>
            </div>
            {create.error ? (
              <p role="alert" className="text-sm font-bold text-danger sm:col-span-2">
                {create.error.message}
              </p>
            ) : null}
          </form>
        </details>
      </section>
      <div className="flex items-start gap-3 border-l-2 border-intelligence/35 pl-4">
        <CalendarClock className="mt-0.5 h-5 w-5 shrink-0 text-intelligence" aria-hidden="true" />
        <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
          Only complete schedules create confirmed Cash Plan commitments. Observed card EMI amounts
          explain the current statement but do not pretend to know the future.
        </p>
      </div>
    </div>
  );
}

function DebtSummaryLine({
  label,
  value,
  intelligence = false,
}: {
  label: string;
  value: string;
  intelligence?: boolean;
}) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-4 py-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={`money-value text-right font-extrabold ${
          intelligence ? 'text-intelligence' : ''
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function LiabilityEvidenceRow({ liability, currency }: { liability: Liability; currency: string }) {
  const observed = liability.schedule_status === 'observed_partial';
  return (
    <article className="border-b border-border/70 px-5 py-6 last:border-b-0 sm:px-7">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-extrabold tracking-[-0.02em]">
              {liability.label}
            </h3>
            <Badge variant={liability.complete_schedule ? 'success' : 'info'}>
              {liability.complete_schedule
                ? 'Schedule confirmed'
                : observed
                  ? 'Statement observed'
                  : 'User supplied'}
            </Badge>
          </div>
          <p className="mt-1 break-words text-sm text-muted-foreground">
            {liability.liability_type.replace('_', ' ')}
            {liability.issuer_plan_reference
              ? ` · issuer plan ${liability.issuer_plan_reference}`
              : ''}
            {liability.last_observed_statement_date
              ? ` · statement ${formatDate(liability.last_observed_statement_date)}`
              : ''}
          </p>
        </div>
        <div className="lg:text-right">
          <p className="text-xs font-extrabold tracking-[0.07em] text-muted-foreground">
            {observed ? 'LATEST OBSERVED INSTALMENT' : 'MONTHLY DUE'}
          </p>
          <p className="money-value mt-1 text-2xl font-extrabold tracking-[-0.04em]">
            {liability.monthly_due ? formatCurrency(liability.monthly_due, currency) : 'Not known'}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {liability.next_due_date
              ? `Due ${formatDate(liability.next_due_date)}`
              : 'No sourced due date'}
          </p>
        </div>
      </div>

      {observed ? (
        <div className="mt-5 grid grid-cols-2 border-y border-border/70 sm:grid-cols-4">
          <EvidenceAmount
            label="Principal"
            value={liability.observed_principal_component}
            currency={currency}
          />
          <EvidenceAmount
            label="Interest"
            value={liability.observed_interest_component}
            currency={currency}
          />
          <EvidenceAmount
            label="Tax on charges"
            value={liability.observed_tax_component}
            currency={currency}
          />
          <EvidenceAmount
            label="One-time fees"
            value={liability.observed_fee_component}
            currency={currency}
          />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
        <EvidenceFact
          label="Balance"
          value={
            liability.outstanding_principal !== null &&
            liability.outstanding_principal !== undefined
              ? formatCurrency(liability.outstanding_principal, currency)
              : 'unknown'
          }
        />
        <EvidenceFact
          label="Annual rate"
          value={
            liability.interest_rate !== null && liability.interest_rate !== undefined
              ? `${liability.interest_rate}%`
              : 'unknown'
          }
        />
        <EvidenceFact
          label="Remaining instalments"
          value={String(liability.remaining_installments ?? 'unknown')}
        />
        <EvidenceFact
          label="Evidence"
          value={
            liability.evidence_line_count
              ? `${liability.evidence_line_count} statement lines`
              : 'manual'
          }
        />
      </div>

      <details className="mt-4 border-l-2 border-intelligence/35 pl-4">
        <summary className="focus-ring min-h-11 cursor-pointer rounded py-3 text-sm font-extrabold">
          Inspect source and schedule limits
        </summary>
        <p className="pb-3 text-sm leading-6 text-muted-foreground">
          {observed
            ? 'PFIS grouped explicit issuer EMI components. The latest amount includes principal, interest, and tax; fees remain separate. Progress stays hidden until every remaining instalment is confirmed.'
            : liability.complete_schedule
              ? 'This obligation is backed by a complete issuer or user-confirmed schedule and can project commitments into the Cash Plan.'
              : 'This is a sourced obligation, but its complete repayment schedule has not been confirmed.'}
        </p>
      </details>

      {liability.complete_schedule ? (
        <ConfirmedSchedule liability={liability} currency={currency} />
      ) : (
        <ScheduleConfirmation liability={liability} />
      )}
    </article>
  );
}

function EvidenceAmount({
  label,
  value,
  currency,
}: {
  label: string;
  value?: number | null;
  currency: string;
}) {
  return (
    <div className="min-w-0 border-border/70 px-3 py-3 even:border-l sm:border-l sm:first:border-l-0">
      <p className="text-[0.68rem] font-extrabold tracking-[0.07em] text-muted-foreground">
        {label.toUpperCase()}
      </p>
      <p className="money-value mt-1 truncate text-sm font-extrabold">
        {value !== null && value !== undefined ? formatCurrency(value, currency) : 'Unknown'}
      </p>
    </div>
  );
}

function EvidenceFact({ label, value }: { label: string; value: string }) {
  return (
    <span>
      {label} <strong className="text-foreground">{value}</strong>
    </span>
  );
}

function ConfirmedSchedule({ liability, currency }: { liability: Liability; currency: string }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const schedule = useQuery({
    queryKey: ['liabilitySchedule', user?.id ?? '', liability.id],
    queryFn: () => api.liabilitySchedule(user!.id, liability.id),
    enabled: Boolean(user),
  });
  const update = useMutation({
    mutationFn: ({
      item,
      status,
    }: {
      item: LiabilityScheduleItem;
      status: LiabilityScheduleItem['status'];
    }) => api.updateLiabilityScheduleItem(user!.id, liability.id, item.id, status),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['liabilitySchedule', user!.id, liability.id],
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.liabilities(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.liabilityOverview(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.commitments(user!.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user!.id) }),
      ]);
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  return (
    <details className="mt-4 rounded-lg border border-border/70 p-4">
      <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
        Manage confirmed schedule ({liability.remaining_installments ?? 0} remaining)
      </summary>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        Marking an instalment paid or skipped removes only its linked Cash Plan commitment. The
        original schedule evidence remains visible.
      </p>
      <div className="mt-3 divide-y divide-border/70">
        {(schedule.data ?? []).map((item) => (
          <div
            key={item.id}
            className="flex min-h-14 flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-bold">{formatDate(item.due_date)}</p>
                <Badge
                  variant={
                    item.status === 'paid'
                      ? 'success'
                      : item.status === 'skipped'
                        ? 'warning'
                        : 'outline'
                  }
                >
                  {item.status}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatCurrency(item.installment_amount, currency)}
                {item.principal_amount != null
                  ? ` · principal ${formatCurrency(item.principal_amount, currency)}`
                  : ''}
                {item.interest_amount != null
                  ? ` · interest ${formatCurrency(item.interest_amount, currency)}`
                  : ''}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {item.status === 'upcoming' ? (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => update.mutate({ item, status: 'paid' })}
                  >
                    Mark paid
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => update.mutate({ item, status: 'skipped' })}
                  >
                    Skip
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => update.mutate({ item, status: 'upcoming' })}
                >
                  Restore upcoming
                </Button>
              )}
            </div>
          </div>
        ))}
        {schedule.isLoading ? (
          <p role="status" className="py-3 text-xs text-muted-foreground">
            Loading schedule…
          </p>
        ) : null}
      </div>
    </details>
  );
}

function ScheduleConfirmation({ liability }: { liability: Liability }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [items, setItems] = useState([
    {
      due_date: liability.next_due_date ?? '',
      installment_amount: liability.monthly_due?.toString() ?? '',
    },
  ]);
  const mutation = useMutation({
    mutationFn: () =>
      api.confirmLiabilitySchedule(user!.id, liability.id, {
        source_kind: 'manual',
        items: items.map((item) => ({
          due_date: item.due_date,
          installment_amount: Number(item.installment_amount),
          principal_amount: null,
          interest_amount: null,
          tax_amount: null,
          fee_amount: null,
        })),
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.liabilities(user!.id) }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.liabilityOverview(user!.id),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user!.id) }),
      ]);
    },
  });

  return (
    <details className="mb-4 rounded-lg border border-border/70 bg-background/40 p-4">
      <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
        Confirm complete instalment schedule
      </summary>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        Add every remaining instalment. Confirmation is permanent evidence and creates only the
        upcoming EMI commitments used by the Cash Plan.
      </p>
      <form
        className="mt-4 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (
            items.length > 0 &&
            items.every((item) => item.due_date && Number(item.installment_amount) > 0)
          ) {
            mutation.mutate();
          }
        }}
      >
        {items.map((item, index) => (
          <div
            key={`${liability.id}-${index}`}
            className="grid gap-3 rounded-lg bg-muted/45 p-3 sm:grid-cols-[1fr_1fr_auto]"
          >
            <Field
              label={`Due date ${index + 1}`}
              htmlFor={`schedule-date-${liability.id}-${index}`}
            >
              <Input
                id={`schedule-date-${liability.id}-${index}`}
                name={`schedule_due_date_${index + 1}`}
                autoComplete="off"
                type="date"
                value={item.due_date}
                onChange={(event) =>
                  setItems((current) =>
                    current.map((row, rowIndex) =>
                      rowIndex === index ? { ...row, due_date: event.target.value } : row,
                    ),
                  )
                }
                required
              />
            </Field>
            <Field label="Instalment amount" htmlFor={`schedule-amount-${liability.id}-${index}`}>
              <Input
                id={`schedule-amount-${liability.id}-${index}`}
                name={`schedule_amount_${index + 1}`}
                autoComplete="off"
                type="number"
                min="0.01"
                step="0.01"
                inputMode="decimal"
                value={item.installment_amount}
                onChange={(event) =>
                  setItems((current) =>
                    current.map((row, rowIndex) =>
                      rowIndex === index ? { ...row, installment_amount: event.target.value } : row,
                    ),
                  )
                }
                required
              />
            </Field>
            {items.length > 1 ? (
              <Button
                type="button"
                variant="ghost"
                className="self-end"
                onClick={() =>
                  setItems((current) => current.filter((_, rowIndex) => rowIndex !== index))
                }
              >
                Remove
              </Button>
            ) : null}
          </div>
        ))}
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              setItems((current) => [...current, { due_date: '', installment_amount: '' }])
            }
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            Add instalment
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            Confirm complete schedule
          </Button>
        </div>
        {mutation.error ? (
          <p role="alert" className="text-sm font-bold text-danger">
            {mutation.error.message}
          </p>
        ) : null}
      </form>
    </details>
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
