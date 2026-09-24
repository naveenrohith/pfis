import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Building2,
  Landmark,
  Plus,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { ChartFrame } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Dialog } from '@/components/ui/Dialog';
import { Input, Label, Select } from '@/components/ui/Input';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useToast } from '@/components/ui/Toast';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { AccountIdentityDialog } from '@/features/accounts/AccountIdentityDialog';
import { useAuth } from '@/features/auth/AuthContext';
import {
  queryKeys,
  useAccounts,
  useBalanceProviderStatus,
  useBalanceProviderDiscoveredAccounts,
  useEnqueueBalanceRefresh,
  useJob,
  useMapBalanceProviderAccount,
  useNetWorth,
  useRequestBalanceProviderConsent,
} from '@/features/workspace/queries';
import { api } from '@/lib/api';
import {
  dateInputValueInTimezone,
  formatChartAxisCurrency,
  formatChartCurrency,
  formatChartDate,
  formatCurrency,
  formatDate,
  formatTime,
} from '@/lib/format';
import type {
  BalanceProviderAccountCandidate,
  BalanceProviderStatus,
  FinancialAccount,
} from '@/lib/types';

export function NetWorthSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const accounts = useAccounts();
  const netWorth = useNetWorth();
  const providerStatus = useBalanceProviderStatus();
  const { scrollTo } = useDashboardUi();
  const [accountOpen, setAccountOpen] = useState(false);
  const [balanceAccountId, setBalanceAccountId] = useState<string | null>(null);
  const [identityAccountId, setIdentityAccountId] = useState<string | null>(null);
  const [mappingProviderType, setMappingProviderType] = useState<string | null>(null);
  const currency = user?.currency ?? 'INR';
  const historyPoints = netWorth.data?.points ?? [];
  const unresolvedAccounts = (accounts.data ?? []).filter(
    (account) => account.is_active && identityStatus(account) !== 'confirmed',
  );
  const currentPositionStatus = netWorth.data?.current_position_status;
  const currentPositionLabel =
    currentPositionStatus === 'estimated'
      ? 'Estimated current position'
      : currentPositionStatus === 'observed'
        ? 'Observed current position'
        : currentPositionStatus === 'needs_review'
          ? 'Current position needs review'
          : currentPositionStatus === 'stale'
            ? 'Current position is stale'
            : null;

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Accounts"
          title="Net worth"
          description="Assets minus liabilities, grounded in owned observations and eligible settled movement."
          action={
            <Button size="sm" onClick={() => setAccountOpen(true)}>
              <Plus className="h-4 w-4" /> Add account
            </Button>
          }
        />
      ) : (
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-xl font-extrabold tracking-[-0.025em]">Your financial position</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Owned balances only—no guessed market values.
            </p>
          </div>
          <Button size="sm" onClick={() => setAccountOpen(true)}>
            <Plus className="h-4 w-4" /> Add account
          </Button>
        </div>
      )}

      {netWorth.isLoading || accounts.isLoading ? (
        <Skeleton className="h-80" />
      ) : (accounts.data?.length ?? 0) === 0 ? (
        <Card>
          <CardContent className="p-6">
            <EmptyState
              icon={<Landmark />}
              title="No accounts yet"
              description="Add an asset or liability account, then record a balance to calculate true net worth."
            />
          </CardContent>
        </Card>
      ) : (
        <>
          {netWorth.isError && !netWorth.data ? (
            <section
              className="mb-4 flex flex-col gap-3 border-l-2 border-warning bg-warning/5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
              role="alert"
              aria-labelledby="net-worth-error-title"
            >
              <div>
                <h3 id="net-worth-error-title" className="text-sm font-extrabold">
                  Position data is unavailable
                </h3>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  PFIS could not load the account totals. It will keep them unavailable rather than
                  treating missing data as zero.
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void netWorth.refetch()}
              >
                <RefreshCw aria-hidden="true" className="h-4 w-4" /> Retry position
              </Button>
            </section>
          ) : null}
          {unresolvedAccounts.length ? (
            <section
              className="mb-4 border-l-2 border-warning bg-warning/5 px-4 py-3"
              aria-labelledby="unresolved-account-title"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex gap-3">
                  <AlertTriangle
                    className="mt-0.5 h-5 w-5 shrink-0 text-warning"
                    aria-hidden="true"
                  />
                  <div>
                    <h3 id="unresolved-account-title" className="text-sm font-extrabold">
                      {unresolvedAccounts.length} account{' '}
                      {unresolvedAccounts.length === 1 ? 'identity needs' : 'identities need'}{' '}
                      confirmation
                    </h3>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      Confirm the product type before PFIS uses these instruments in position, debt,
                      or Cash Plan calculations.
                    </p>
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setIdentityAccountId(unresolvedAccounts[0].id)}
                >
                  Resolve first account
                </Button>
              </div>
            </section>
          ) : null}
          {providerStatus.data ? (
            <BalanceProviderNotice
              status={providerStatus.data}
              onOpenSettings={() => scrollTo('settings')}
              onOpenMapping={setMappingProviderType}
            />
          ) : null}
          <BalanceProviderMappingDialog
            open={Boolean(mappingProviderType)}
            providerType={mappingProviderType}
            accounts={accounts.data ?? []}
            onClose={() => setMappingProviderType(null)}
          />
          <dl
            data-testid="position-summary"
            aria-label="Account position summary"
            className="mt-4 grid grid-cols-2 border-y border-border/70 sm:grid-cols-3 sm:divide-x sm:divide-border"
          >
            <div className="col-span-2 py-4 pr-4 sm:col-span-1 sm:pr-5">
              <dt className="text-xs font-semibold text-muted-foreground">Net worth</dt>
              <dd className="money-value mt-1 text-3xl font-extrabold tracking-[-0.05em]">
                {netWorth.data ? formatCurrency(netWorth.data.net_worth, currency) : 'Unavailable'}
              </dd>
            </div>
            <div className="border-t border-border/70 py-3 pr-4 sm:border-l sm:border-t-0 sm:px-5">
              <dt className="text-xs font-semibold text-muted-foreground">Assets</dt>
              <dd className="money-value mt-1 text-lg font-bold">
                {netWorth.data ? formatCurrency(netWorth.data.assets, currency) : 'Unavailable'}
              </dd>
            </div>
            <div className="border-t border-border/70 py-3 sm:border-l sm:px-5 sm:py-4">
              <dt className="text-xs font-semibold text-muted-foreground">Liabilities</dt>
              <dd className="money-value mt-1 text-lg font-bold">
                {netWorth.data
                  ? formatCurrency(netWorth.data.liabilities, currency)
                  : 'Unavailable'}
              </dd>
            </div>
          </dl>
          {currentPositionLabel ? (
            <div
              className="mt-4 border-l-2 border-primary/50 pl-4 text-xs text-muted-foreground"
              role="status"
              aria-live="polite"
            >
              <p className="font-extrabold uppercase tracking-[0.1em] text-foreground">
                Current position · {currentPositionLabel}
                {netWorth.data?.current_position_as_of
                  ? ` · as of ${netWorth.data.current_position_as_of}`
                  : ''}
              </p>
              <p className="mt-1 leading-5">
                {currentPositionStatus === 'needs_review' || currentPositionStatus === 'stale'
                  ? 'Totals remain on the latest recorded snapshot until every account has a fresh, reconciled position.'
                  : 'Totals include only eligible settled movement after each account’s dated balance observation.'}
              </p>
            </div>
          ) : null}

          <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
            <section
              className="min-w-0 border-y border-border/70 py-5"
              aria-label="Net-worth history"
            >
              {historyPoints.length === 0 ? (
                <>
                  <h3 className="font-bold">Net-worth history</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {netWorth.isError && !netWorth.data
                      ? 'History is unavailable until account positions can be loaded.'
                      : 'Append-only balance snapshots; no market-price estimates.'}
                  </p>
                  {!netWorth.isError || netWorth.data ? (
                    <div className="mt-4">
                      <EmptyState
                        icon={<TrendingUp />}
                        title="Add your first balance"
                        description="History begins when an account has a dated balance snapshot."
                      />
                    </div>
                  ) : null}
                </>
              ) : (
                <ChartFrame
                  title="Net-worth history"
                  description={`Net worth in ${currency} · ${formatDate(historyPoints[0].date)} to ${formatDate(historyPoints[historyPoints.length - 1].date)} · dated account snapshots`}
                  summary={`Net worth changed from ${formatCurrency(historyPoints[0].net_worth, currency)} on ${formatDate(historyPoints[0].date)} to ${formatCurrency(historyPoints[historyPoints.length - 1].net_worth, currency)} on ${formatDate(historyPoints[historyPoints.length - 1].date)}. The line connects retained balance snapshots; it does not estimate market values between them.`}
                  dataTable={
                    <table className="w-full min-w-[38rem] text-left text-sm">
                      <caption className="sr-only">Net-worth history values in {currency}</caption>
                      <thead>
                        <tr className="border-b border-border/65 text-xs text-muted-foreground">
                          <th scope="col" className="px-2 py-2">
                            Date
                          </th>
                          <th scope="col" className="px-2 py-2">
                            Assets ({currency})
                          </th>
                          <th scope="col" className="px-2 py-2">
                            Liabilities ({currency})
                          </th>
                          <th scope="col" className="px-2 py-2">
                            Net worth ({currency})
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {historyPoints.map((point) => (
                          <tr key={point.date} className="border-b border-border/45 last:border-0">
                            <th scope="row" className="whitespace-nowrap px-2 py-2 font-bold">
                              {formatDate(point.date)}
                            </th>
                            <td className="money-value px-2 py-2">
                              {formatCurrency(point.assets, currency)}
                            </td>
                            <td className="money-value px-2 py-2">
                              {formatCurrency(point.liabilities, currency)}
                            </td>
                            <td className="money-value px-2 py-2 font-bold">
                              {formatCurrency(point.net_worth, currency)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  }
                >
                  <ResponsiveContainer width="100%" height={260}>
                    <LineChart
                      data={historyPoints}
                      margin={{ left: 8, right: 12, top: 8, bottom: 2 }}
                    >
                      <CartesianGrid vertical={false} stroke="hsl(var(--border))" />
                      <XAxis
                        dataKey="date"
                        tickFormatter={formatChartDate}
                        tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                        tickFormatter={(value) => formatChartAxisCurrency(value, currency)}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        formatter={(value) => formatChartCurrency(value, currency)}
                        labelFormatter={(value) => formatDate(String(value))}
                        contentStyle={{
                          background: 'hsl(var(--card))',
                          border: '1px solid hsl(var(--border))',
                          borderRadius: 12,
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="net_worth"
                        name={`Net worth (${currency})`}
                        stroke="hsl(var(--primary))"
                        strokeWidth={2.5}
                        dot={{ r: 3 }}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </ChartFrame>
              )}
            </section>

            <Card>
              <CardContent className="grid gap-3 p-5">
                <h3 className="font-bold">Your accounts</h3>
                {(accounts.data ?? []).map((account) => (
                  <div
                    key={account.id}
                    className="dashboard-row grid w-full grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-2 sm:flex sm:gap-3"
                  >
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted">
                      <Building2 className="h-4 w-4 text-primary" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-bold">
                        {account.institution_name}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {account.account_type} · {account.masked_number}
                      </span>
                    </span>
                    <span className="min-w-0 text-right" aria-live="polite">
                      <span className="block text-sm font-bold">
                        {account.current_balance != null
                          ? formatCurrency(account.current_balance, account.currency)
                          : account.latest_balance == null
                            ? 'Add balance'
                            : formatCurrency(account.latest_balance, account.currency)}
                      </span>
                      {account.current_balance != null ? (
                        <span
                          className={`block text-[0.68rem] ${
                            account.current_balance_status === 'needs_review' ||
                            account.current_balance_status === 'stale' ||
                            account.current_balance_status === 'incomplete'
                              ? 'text-warning'
                              : 'text-muted-foreground'
                          }`}
                          title={
                            account.current_balance_reason_codes?.length
                              ? account.current_balance_reason_codes.join(', ')
                              : undefined
                          }
                        >
                          {accountPositionLabel(
                            account.current_balance_status,
                            account.account_type,
                          )}
                          {' · '}
                          {account.current_balance_as_of ?? 'today'}
                        </span>
                      ) : null}
                      {account.current_balance == null && account.latest_balance != null ? (
                        <span className="block text-[0.68rem] text-muted-foreground">
                          Observed · {account.balance_as_of ?? 'date unknown'}
                        </span>
                      ) : null}
                      <div className="flex flex-wrap justify-end gap-1">
                        <Badge variant={account.balance_kind === 'asset' ? 'success' : 'warning'}>
                          {account.balance_kind}
                        </Badge>
                        {identityStatus(account) !== 'confirmed' ? (
                          <Badge variant="outline">{identityStatus(account)}</Badge>
                        ) : null}
                      </div>
                    </span>
                    <Button
                      size="sm"
                      variant={identityStatus(account) !== 'confirmed' ? 'outline' : 'ghost'}
                      className="col-span-3 justify-self-end sm:ml-auto sm:col-span-1"
                      onClick={() =>
                        identityStatus(account) !== 'confirmed'
                          ? setIdentityAccountId(account.id)
                          : setBalanceAccountId(account.id)
                      }
                    >
                      {identityStatus(account) !== 'confirmed' ? 'Review identity' : 'Position'}
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <AccountDialog open={accountOpen} onClose={() => setAccountOpen(false)} />
      <BalanceDialog accountId={balanceAccountId} onClose={() => setBalanceAccountId(null)} />
      <AccountIdentityDialog
        account={(accounts.data ?? []).find((account) => account.id === identityAccountId) ?? null}
        onClose={() => setIdentityAccountId(null)}
      />
    </div>
  );
}

function identityStatus(account: { account_type: string; identity_status?: string }) {
  return (
    account.identity_status ?? (account.account_type === 'unknown' ? 'unresolved' : 'confirmed')
  );
}

function accountPositionLabel(
  status:
    | 'needs_observation'
    | 'observed'
    | 'estimated'
    | 'stale'
    | 'incomplete'
    | 'needs_review'
    | undefined,
  accountType?: string,
) {
  const noun = accountType === 'credit_card' ? 'outstanding' : 'current';
  switch (status) {
    case 'observed':
      return `Observed ${noun}`;
    case 'estimated':
      return `Estimated ${noun}`;
    case 'needs_review':
      return `${noun[0].toUpperCase()}${noun.slice(1)} needs review`;
    case 'stale':
      return `Stale ${noun}`;
    case 'incomplete':
      return 'Incomplete source';
    default:
      return `${noun[0].toUpperCase()}${noun.slice(1)} position`;
  }
}

function BalanceProviderNotice({
  status,
  onOpenSettings,
  onOpenMapping,
}: {
  status: BalanceProviderStatus;
  onOpenSettings: () => void;
  onOpenMapping: (providerType: string) => void;
}) {
  const { notify } = useToast();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const requestConsent = useRequestBalanceProviderConsent();
  const refresh = useEnqueueBalanceRefresh();
  const [refreshJobId, setRefreshJobId] = useState<string | null>(null);
  const refreshJob = useJob(refreshJobId ?? undefined);
  const supportedProviderTypes = status.supported_provider_types ?? [];
  const transportConfigured = supportedProviderTypes.length > 0;
  const connection =
    status.connections?.find(
      (item) => item.status === 'active' && supportedProviderTypes.includes(item.provider_type),
    ) ?? status.connections?.find((item) => supportedProviderTypes.includes(item.provider_type));
  const providerType = connection?.provider_type ?? supportedProviderTypes[0] ?? null;
  const providerLabel =
    status.provider_name ??
    (providerType
      ? providerType
          .split(/[_-]/)
          .filter(Boolean)
          .map((part) => part[0].toUpperCase() + part.slice(1))
          .join(' ')
      : 'provider');
  const hasCompleteMapping =
    status.account_count > 0 && status.mapped_account_count === status.account_count;
  const connectionIsActive = connection?.status === 'active';
  const canRefresh = Boolean(status.refresh_supported && connectionIsActive && hasCompleteMapping);
  const actionPending = requestConsent.isPending || refresh.isPending || refreshJobId !== null;
  const connectionLabel =
    connection?.status === 'active'
      ? 'Connected'
      : connection?.status === 'pending'
        ? 'Consent pending'
        : connection?.status === 'expired'
          ? 'Consent expired'
          : connection?.status === 'revoked'
            ? 'Disconnected'
            : connection?.status === 'error'
              ? 'Needs attention'
              : 'Not connected';
  const consentPending = status.reason_codes.includes('provider_consent_pending');
  const consentExpired = status.reason_codes.includes('provider_consent_expired');

  useEffect(() => {
    const jobStatus = refreshJob.data?.status;
    if (!refreshJobId || !jobStatus) return;
    if (jobStatus === 'completed') {
      setRefreshJobId(null);
      notify('Balance evidence arrived; positions are updating', 'success');
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.balanceProviderStatus(user?.id ?? ''),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user?.id ?? '') }),
        queryClient.invalidateQueries({ queryKey: queryKeys.netWorth(user?.id ?? '') }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user?.id ?? '') }),
        queryClient.invalidateQueries({ queryKey: ['cardOverview', user?.id ?? ''] }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', user?.id ?? ''] }),
      ]);
    } else if (jobStatus === 'failed') {
      setRefreshJobId(null);
      notify(
        refreshJob.data?.error_message ?? 'Balance refresh failed; review provider status',
        'error',
      );
    }
  }, [notify, queryClient, refreshJob.data, refreshJobId, user?.id]);
  const title =
    status.status === 'ready'
      ? 'Latest provider observations are inside their refresh window'
      : status.status === 'due' || status.status === 'overdue'
        ? 'Provider observations need a refresh'
        : status.status === 'incomplete'
          ? 'Provider coverage is incomplete'
          : consentPending
            ? 'Provider consent is pending'
            : consentExpired
              ? 'Provider consent has expired'
              : 'Automatic bank and card refresh is not available in this deployment';
  const tone =
    status.status === 'ready'
      ? 'border-success/25 bg-success/[0.035]'
      : status.status === 'blocked' || status.status === 'not_configured'
        ? 'border-intelligence/25 bg-intelligence/[0.035]'
        : 'border-warning/35 bg-warning/[0.035]';
  const badgeVariant = status.status === 'ready' ? 'success' : 'warning';

  const requestConsentForProvider = async () => {
    if (!providerType) return;
    try {
      await requestConsent.mutateAsync(providerType);
      notify(`${providerLabel} consent request created`, 'success');
    } catch (error) {
      notify((error as Error).message, 'error');
    }
  };

  const refreshProvider = async () => {
    if (!providerType || !canRefresh) return;
    const idempotencyKey =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? `balance-refresh:${providerType}:${crypto.randomUUID()}`
        : `balance-refresh:${providerType}:${Date.now()}`;
    try {
      const queuedJob = await refresh.mutateAsync({ providerType, idempotencyKey });
      setRefreshJobId(queuedJob.id);
      notify('Balance refresh queued; PFIS is waiting for provider evidence', 'success');
    } catch (error) {
      notify((error as Error).message, 'error');
    }
  };

  return (
    <section
      className={`mt-4 border p-4 ${tone}`}
      aria-labelledby="balance-provider-status-title"
      role="status"
      aria-live="polite"
      aria-busy={actionPending}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 rounded-lg bg-card/80 p-2 text-intelligence shadow-sm">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
              Bank & card refresh
            </p>
            <h3 id="balance-provider-status-title" className="mt-1 text-sm font-extrabold">
              {title}
            </h3>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">
              {status.refresh_supported
                ? 'A consented connector can refresh these accounts; verify coverage before treating an amount as current truth.'
                : consentPending
                  ? `The ${providerLabel} consent handoff is pending. PFIS will not change a balance until the provider returns a complete, dated observation.`
                  : consentExpired
                    ? `The ${providerLabel} consent has expired. Reconnect before using a provider amount as current truth.`
                    : transportConfigured
                      ? `A ${providerLabel} connector is available, but consent is not active. Request consent before using provider amounts as current truth.`
                      : 'PFIS can roll eligible settled activity forward, but this deployment has no consented provider transport. Current amounts remain explicitly observed or estimated, never live.'}
            </p>
            <p className="mt-2 text-xs font-bold text-foreground">Next: {status.next_step}</p>
            {providerType ? (
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                <span>
                  <span className="font-semibold text-foreground">{providerLabel}</span> ·{' '}
                  {connectionLabel}
                </span>
                {connection?.last_refresh_completed_at ? (
                  <span>Last completed {formatTime(connection.last_refresh_completed_at)}</span>
                ) : null}
                {connection?.last_error_code ? (
                  <span className="font-semibold text-warning">Refresh needs attention</span>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
          <Badge variant={badgeVariant}>
            {status.mapped_account_count}/{status.account_count} mapped
          </Badge>
          {canRefresh ? (
            <Button
              type="button"
              size="sm"
              variant="primary"
              onClick={refreshProvider}
              disabled={actionPending}
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${refresh.isPending || refreshJobId ? 'animate-spin' : ''}`}
                aria-hidden="true"
              />
              {refresh.isPending
                ? 'Starting…'
                : refreshJobId
                  ? 'Waiting for evidence…'
                  : 'Refresh balances'}
            </Button>
          ) : providerType && connection?.status !== 'pending' && !connectionIsActive ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={requestConsentForProvider}
              disabled={actionPending}
            >
              {requestConsent.isPending ? 'Requesting…' : 'Request consent'}
            </Button>
          ) : !status.refresh_supported && supportedProviderTypes.length === 0 ? (
            <Button type="button" size="sm" variant="outline" onClick={onOpenSettings}>
              Review connection path
            </Button>
          ) : !hasCompleteMapping && connectionIsActive ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => (providerType ? onOpenMapping(providerType) : onOpenSettings())}
            >
              Map all accounts
            </Button>
          ) : null}
          {connection?.status === 'pending' ? (
            <Button type="button" size="sm" variant="outline" onClick={onOpenSettings}>
              Review consent
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function BalanceProviderMappingDialog({
  open,
  providerType,
  accounts,
  onClose,
}: {
  open: boolean;
  providerType: string | null;
  accounts: FinancialAccount[];
  onClose: () => void;
}) {
  const { notify } = useToast();
  const discovered = useBalanceProviderDiscoveredAccounts(providerType ?? undefined);
  const mapAccount = useMapBalanceProviderAccount();
  const [selections, setSelections] = useState<Record<string, string>>({});
  const candidates = useMemo(() => discovered.data ?? [], [discovered.data]);
  const eligibleAccounts = accounts.filter(
    (account) => account.is_active && account.account_type !== 'unknown',
  );

  useEffect(() => {
    if (!open) return;
    setSelections((current) => {
      const next = { ...current };
      for (const candidate of candidates) {
        if (candidate.mapped_financial_account_id && !next[candidate.mapped_financial_account_id]) {
          next[candidate.mapped_financial_account_id] = candidate.provider_account_id;
        }
      }
      return next;
    });
  }, [candidates, open]);

  const labelForCandidate = (candidate: BalanceProviderAccountCandidate) => {
    const identity = candidate.masked_number || candidate.display_name || 'Provider account';
    const type = candidate.account_type
      ? candidate.account_type.replace('_', ' ')
      : 'financial account';
    return `${identity} · ${type}`;
  };

  const mapSelectedAccount = async (accountId: string) => {
    if (!providerType) return;
    const providerAccountId = selections[accountId];
    if (!providerAccountId) return;
    const candidate = candidates.find((item) => item.provider_account_id === providerAccountId);
    if (!candidate || candidate.mapped_financial_account_id === accountId) return;
    if (candidate.mapped_financial_account_id) {
      notify('Choose an unassigned provider account', 'error');
      return;
    }
    try {
      await mapAccount.mutateAsync({
        accountId,
        providerType,
        providerAccountId,
      });
      notify('Provider account mapped', 'success');
    } catch (error) {
      notify((error as Error).message, 'error');
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Map provider accounts"
      description="Match each owned account to the identity returned by the consented provider. PFIS never asks for a full account or card number."
      className="max-w-2xl"
    >
      {discovered.isPending ? (
        <div className="grid gap-3" role="status" aria-live="polite">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <p className="text-xs text-muted-foreground">Loading provider accounts…</p>
        </div>
      ) : discovered.isError ? (
        <div className="rounded-lg border border-warning/30 bg-warning/[0.06] p-4" role="alert">
          <p className="text-sm font-bold">Provider account discovery is unavailable</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {(discovered.error as Error).message}. No mapping was changed.
          </p>
        </div>
      ) : candidates.length === 0 ? (
        <div className="rounded-lg border border-border/70 bg-muted/25 p-4">
          <p className="text-sm font-bold">No provider accounts returned</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Finish the provider consent handoff, then reopen this mapping step.
          </p>
        </div>
      ) : (
        <div className="grid gap-3" aria-live="polite">
          {eligibleAccounts.map((account) => {
            const currentCandidate = candidates.find(
              (candidate) => candidate.mapped_financial_account_id === account.id,
            );
            const selectedProviderId =
              selections[account.id] ?? currentCandidate?.provider_account_id ?? '';
            return (
              <div
                key={account.id}
                className="grid gap-2 rounded-lg border border-border/70 bg-muted/20 p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto] sm:items-end"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold">{account.institution_name}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {account.account_type.replace('_', ' ')} · {account.masked_number}
                  </p>
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor={`provider-account-${account.id}`}>Provider identity</Label>
                  <Select
                    id={`provider-account-${account.id}`}
                    name={`provider_account_${account.id}`}
                    value={selectedProviderId}
                    onChange={(event) =>
                      setSelections((current) => ({
                        ...current,
                        [account.id]: event.target.value,
                      }))
                    }
                  >
                    <option value="">Choose an account…</option>
                    {candidates.map((candidate) => {
                      const mappedElsewhere =
                        Boolean(candidate.mapped_financial_account_id) &&
                        candidate.mapped_financial_account_id !== account.id;
                      return (
                        <option
                          key={candidate.provider_account_id}
                          value={candidate.provider_account_id}
                          disabled={mappedElsewhere}
                        >
                          {labelForCandidate(candidate)}
                          {mappedElsewhere ? ' · already mapped' : ''}
                        </option>
                      );
                    })}
                  </Select>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant={currentCandidate ? 'secondary' : 'primary'}
                  onClick={() => mapSelectedAccount(account.id)}
                  disabled={
                    !selectedProviderId || mapAccount.isPending || Boolean(currentCandidate)
                  }
                >
                  {currentCandidate ? 'Mapped' : mapAccount.isPending ? 'Mapping…' : 'Map account'}
                </Button>
              </div>
            );
          })}
        </div>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </Dialog>
  );
}

function AccountDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [name, setName] = useState('');
  const [masked, setMasked] = useState('');
  const [type, setType] = useState('bank');
  const [kind, setKind] = useState<'asset' | 'liability'>('asset');
  const create = useMutation({
    mutationFn: () => {
      if (!user) throw new Error('Sign in to add an account');
      return api.createAccount(user.id, {
        institution_name: name,
        account_type: type,
        balance_kind: kind,
        masked_number: masked,
        currency: user.currency,
      });
    },
    onSuccess: () => {
      if (user) queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) });
      notify('Account added', 'success');
      setName('');
      setMasked('');
      onClose();
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  return (
    <Dialog open={open} onClose={onClose} title="Add financial account">
      <div className="grid gap-3">
        <div className="grid gap-1">
          <Label htmlFor="account-name">Account name</Label>
          <Input
            id="account-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Primary bank"
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="account-masked">Masked identifier</Label>
          <Input
            id="account-masked"
            value={masked}
            onChange={(event) => setMasked(event.target.value)}
            placeholder="••••1234 or Home"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1">
            <Label htmlFor="account-type">Type</Label>
            <Select
              id="account-type"
              value={type}
              onChange={(event) => setType(event.target.value)}
            >
              <option value="bank">Bank</option>
              <option value="cash">Cash</option>
              <option value="investment">Investment</option>
              <option value="credit_card">Credit card</option>
              <option value="loan">Loan</option>
            </Select>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="account-kind">Balance kind</Label>
            <Select
              id="account-kind"
              value={kind}
              onChange={(event) => setKind(event.target.value as typeof kind)}
            >
              <option value="asset">Asset</option>
              <option value="liability">Liability</option>
            </Select>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => create.mutate()}
            disabled={!name.trim() || !masked.trim() || create.isPending}
          >
            Add account
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function BalanceDialog({ accountId, onClose }: { accountId: string | null; onClose: () => void }) {
  const { user } = useAuth();
  const financialToday = dateInputValueInTimezone(user?.timezone ?? 'Asia/Kolkata');
  const { scrollTo } = useDashboardUi();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [amount, setAmount] = useState('');
  const [asOf, setAsOf] = useState(financialToday);
  const position = useQuery({
    queryKey: ['accountPosition', user?.id ?? '', accountId ?? ''],
    queryFn: () => api.accountPosition(user!.id, accountId!),
    enabled: Boolean(user && accountId),
    staleTime: 5 * 60 * 1000,
  });
  const providerObserved =
    position.data?.observed_source === 'connector' &&
    position.data.coverage_status === 'fresh' &&
    position.data.coverage_complete === true;
  const observedProof =
    position.data?.observed_as_of && position.data.observed_balance != null
      ? providerObserved
        ? `Provider observed ${formatCurrency(position.data.observed_balance, position.data.currency)} on ${position.data.observed_as_of}${position.data.observed_at ? ` · retrieved ${formatTime(position.data.observed_at)}` : ''}; this position is inside its refresh window.`
        : `Observed ${formatCurrency(position.data.observed_balance, position.data.currency)} on ${position.data.observed_as_of}; settled movement is ${formatCurrency(position.data.settled_movement_since_observation ?? 0, position.data.currency)} through ${position.data.estimated_as_of ?? 'today'}.`
      : 'Record a dated balance observation before PFIS estimates the current position.';
  const save = useMutation({
    mutationFn: () => {
      if (!user || !accountId) throw new Error('Choose an account');
      return api.addBalance(user.id, accountId, Number(amount), asOf);
    },
    onSuccess: () => {
      if (user) {
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) });
        queryClient.invalidateQueries({ queryKey: queryKeys.netWorth(user.id) });
        queryClient.invalidateQueries({
          queryKey: ['accountPosition', user.id, accountId ?? ''],
        });
        queryClient.invalidateQueries({
          queryKey: ['balanceForecast', user.id, accountId ?? ''],
        });
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', user.id] });
      }
      notify('Balance snapshot saved', 'success');
      setAmount('');
      onClose();
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  return (
    <Dialog open={!!accountId} onClose={onClose} title="Account position">
      <div className="grid gap-3">
        {position.data ? (
          <section className="rounded-lg bg-muted/55 p-4" aria-labelledby="position-conclusion">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <p className="text-xs font-bold text-muted-foreground">LATEST RECORDED POSITION</p>
                <h3 id="position-conclusion" className="money-value mt-1 text-xl font-extrabold">
                  {position.data.verified_balance == null
                    ? 'No balance recorded'
                    : formatCurrency(position.data.verified_balance, position.data.currency)}
                </h3>
              </div>
              <Badge
                variant={
                  position.data.reconciliation_status === 'reconciled'
                    ? 'success'
                    : position.data.reconciliation_status === 'needs_review'
                      ? 'warning'
                      : 'outline'
                }
              >
                {position.data.reconciliation_status.replace('_', ' ')}
              </Badge>
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {position.data.balance_as_of
                ? providerObserved
                  ? `Provider-observed ${position.data.balance_as_of} from ${position.data.balance_source}; freshness is ${position.data.coverage_status}.`
                  : `Observed ${position.data.balance_as_of} from ${position.data.balance_source}. This is not a live bank balance.`
                : 'Add a dated balance observation; PFIS will not derive a current amount from partial alerts.'}
            </p>
            <div
              className="mt-4 border-t border-border/70 pt-4"
              aria-live="polite"
              aria-label="Estimated current account position"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <p className="text-xs font-bold text-muted-foreground">
                    {providerObserved
                      ? 'CURRENT POSITION · PROVIDER OBSERVED'
                      : 'CURRENT POSITION · ESTIMATE'}
                  </p>
                  <p className="mt-1 text-sm font-extrabold">
                    {position.data.position_status === 'needs_review'
                      ? 'Estimate needs review'
                      : position.data.position_status === 'estimated'
                        ? 'Settled activity rolled forward'
                        : position.data.position_status === 'observed'
                          ? 'Observed anchor'
                          : 'Needs an observed anchor'}
                  </p>
                </div>
                <p className="money-value text-xl font-extrabold">
                  {position.data.estimated_balance == null
                    ? 'Needs anchor'
                    : formatCurrency(position.data.estimated_balance, position.data.currency)}
                </p>
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {observedProof}
                {(position.data.pending_increase ?? 0) > 0 ||
                (position.data.pending_decrease ?? 0) > 0
                  ? ` Pending impact of ${formatCurrency((position.data.pending_increase ?? 0) + (position.data.pending_decrease ?? 0), position.data.currency)} is excluded from the estimate.`
                  : ''}
                {position.data.coverage_status === 'overdue'
                  ? ' Provider refresh is overdue; PFIS keeps this amount reviewable rather than calling it live.'
                  : position.data.coverage_complete === false
                    ? ' Provider history is incomplete; PFIS keeps this amount reviewable rather than treating it as safe current truth.'
                    : ''}
              </p>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-3">
              <div>
                <dt className="text-xs text-muted-foreground">Known inflows</dt>
                <dd className="money-value mt-1 text-sm font-extrabold text-success">
                  {formatCurrency(position.data.inflows, position.data.currency)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Known outflows</dt>
                <dd className="money-value mt-1 text-sm font-extrabold">
                  {formatCurrency(position.data.outflows, position.data.currency)}
                </dd>
              </div>
            </dl>
            {position.data.opening_balance != null &&
            position.data.known_movement != null &&
            position.data.verified_balance != null ? (
              <div className="mt-4 border-t border-border/70 pt-4">
                <p className="text-xs font-bold text-muted-foreground">
                  SNAPSHOT-TO-SNAPSHOT PROOF
                </p>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <dt className="text-muted-foreground">
                      Opening · {position.data.opening_as_of}
                    </dt>
                    <dd className="money-value mt-1 font-extrabold">
                      {formatCurrency(position.data.opening_balance, position.data.currency)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Known movement</dt>
                    <dd className="money-value mt-1 font-extrabold">
                      {formatCurrency(position.data.known_movement, position.data.currency)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Closing</dt>
                    <dd className="money-value mt-1 font-extrabold">
                      {formatCurrency(position.data.verified_balance, position.data.currency)}
                    </dd>
                  </div>
                </dl>
                {position.data.unexplained_amount ? (
                  <p className="mt-3 text-xs font-bold text-warning">
                    {formatCurrency(
                      Math.abs(position.data.unexplained_amount),
                      position.data.currency,
                    )}{' '}
                    remains unexplained.
                  </p>
                ) : (
                  <p className="mt-3 text-xs font-bold text-success">
                    Opening balance plus known movement equals the closing snapshot.
                  </p>
                )}
              </div>
            ) : null}
            {Object.keys(position.data.rail_breakdown).length ? (
              <div className="mt-4 border-t border-border/70 pt-4">
                <p className="text-xs font-bold text-muted-foreground">OUTFLOW EVIDENCE BY RAIL</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {Object.entries(position.data.rail_breakdown).map(([rail, value]) => (
                    <Badge key={rail} variant="outline">
                      {rail.replace('_', ' ')} · {formatCurrency(value, position.data.currency)}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}
            {position.data.review_count ? (
              <div className="mt-4 border-t border-border/70 pt-4">
                <p className="text-xs font-bold text-warning">
                  {position.data.review_count} focused reconciliation item
                  {position.data.review_count === 1 ? '' : 's'} need review.
                </p>
                <div className="mt-2 grid gap-2">
                  {position.data.reconciliation_items.map((item) => (
                    <details key={item.id} className="rounded-lg border border-border/70 p-3">
                      <summary className="focus-ring cursor-pointer rounded text-xs font-bold">
                        {item.title}
                        {item.amount != null
                          ? ` · ${formatCurrency(item.amount, position.data.currency)}`
                          : ''}
                      </summary>
                      <p className="mt-2 text-xs leading-5 text-muted-foreground">
                        {item.description}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.basis}</p>
                    </details>
                  ))}
                </div>
                <Button
                  className="mt-3"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    onClose();
                    scrollTo('review');
                  }}
                >
                  Open Activity review
                </Button>
              </div>
            ) : null}
          </section>
        ) : null}
        <h3 className="mt-1 font-extrabold">Record an observed balance</h3>
        <div className="grid gap-1">
          <Label htmlFor="balance-amount">Balance amount</Label>
          <Input
            id="balance-amount"
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="balance-date">As of</Label>
          <Input
            id="balance-date"
            type="date"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Balance history is append-only. Each observation keeps its source and as-of date.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={Number(amount) < 0 || amount === '' || save.isPending}
          >
            Save balance
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
