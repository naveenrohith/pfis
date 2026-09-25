import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, api } from '@/lib/api';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { dateInputValueInTimezone } from '@/lib/format';

const FINANCIAL_STALE_TIME_MS = 5 * 60 * 1000;
const OPERATIONAL_REFETCH_INTERVAL_MS = 60_000;

const financialQueryPolicy = {
  staleTime: FINANCIAL_STALE_TIME_MS,
  refetchOnWindowFocus: true,
} as const;

const operationalQueryPolicy = {
  refetchInterval: OPERATIONAL_REFETCH_INTERVAL_MS,
  refetchIntervalInBackground: false,
} as const;

const capabilityQueryPolicy = {
  staleTime: 60 * 60 * 1000,
  refetchOnWindowFocus: false,
} as const;

/** Shared query keys so mutations can invalidate precisely. */
export const queryKeys = {
  categories: ['categories'] as const,
  summary: (u: string, m: number, y: number) => ['summary', u, m, y] as const,
  transactions: (u: string, m: number, y: number) => ['transactions', u, m, y] as const,
  transferMatchCandidates: (u: string, accountId?: string) =>
    ['transferMatchCandidates', u, accountId ?? 'all'] as const,
  emails: (u: string) => ['emails', u] as const,
  syncStatus: (u: string) => ['syncStatus', u] as const,
  autoSyncStatus: (u: string) => ['autoSyncStatus', u] as const,
  insights: (u: string, m: number, y: number) => ['insights', u, m, y] as const,
  anomalyAdjudications: (u: string) => ['anomalyAdjudications', u] as const,
  anomalySamples: (u: string, m: number, y: number) => ['anomalySamples', u, m, y] as const,
  budgets: (u: string, m: number, y: number) => ['budgets', u, m, y] as const,
  budgetDrilldown: (u: string, b: string, m: number, y: number, limit: number) =>
    ['budgetDrilldown', u, b, m, y, limit] as const,
  workspace: (u: string, m: number, y: number) => ['workspace', u, m, y] as const,
  horizon: (u: string, days = 30) => ['horizon', u, days] as const,
  merchants: (u: string, m: number, y: number) => ['merchants', u, m, y] as const,
  learnedMerchantRules: (u: string) => ['learnedMerchantRules', u] as const,
  categoryIntelligence: (u: string, m: number, y: number) =>
    ['categoryIntelligence', u, m, y] as const,
  goals: (u: string, m: number, y: number) => ['goals', u, m, y] as const,
  guidanceBrief: (u: string, m: number, y: number, cadence?: string, asOf?: string) =>
    cadence
      ? (['guidanceBrief', u, m, y, cadence, asOf] as const)
      : (['guidanceBrief', u, m, y] as const),
  dashboardPreferences: (u: string) => ['dashboardPreferences', u] as const,
  accounts: (u: string) => ['accounts', u] as const,
  balanceProviderStatus: (u: string) => ['balanceProviderStatus', u] as const,
  balanceProviderConnections: (u: string) => ['balanceProviderConnections', u] as const,
  balanceProviderMappings: (u: string, providerType?: string) =>
    providerType
      ? (['balanceProviderMappings', u, providerType] as const)
      : (['balanceProviderMappings', u] as const),
  balanceProviderDiscoveredAccounts: (u: string, providerType: string) =>
    ['balanceProviderDiscoveredAccounts', u, providerType] as const,
  accountIdentityHistory: (u: string, accountId: string) =>
    ['accountIdentityHistory', u, accountId] as const,
  accountLinkRules: (u: string) => ['accountLinkRules', u] as const,
  netWorth: (u: string) => ['netWorth', u] as const,
  balanceForecast: (u: string, accountId: string, horizonDays = 30) =>
    ['balanceForecast', u, accountId, horizonDays] as const,
  balanceForecastSnapshots: (u: string, accountId: string) =>
    ['balanceForecastSnapshots', u, accountId] as const,
  balanceForecastOutcomes: (u: string, accountId: string) =>
    ['balanceForecastOutcomes', u, accountId] as const,
  balanceReconciliations: (u: string, accountId: string) =>
    ['balanceReconciliations', u, accountId] as const,
  cardDueRunway: (u: string, accountId: string) => ['cardDueRunway', u, accountId] as const,
  cardUtilizationHistory: (u: string, accountId: string) =>
    ['cardUtilizationHistory', u, accountId] as const,
  cardPortfolioUpcoming: (u: string) => ['cardPortfolioUpcoming', u] as const,
  cardPortfolioPaymentPlan: (u: string) => ['cardPortfolioPaymentPlan', u] as const,
  cashPlan: (u: string) => ['cashPlan', u] as const,
  temporalEvents: (u: string) => ['temporalEvents', u] as const,
  sourceCoverage: (u: string) => ['sourceCoverage', u] as const,
  intelligenceReadiness: (u: string) => ['intelligenceReadiness', u] as const,
  reconciliationQuality: (u: string) => ['reconciliationQuality', u] as const,
  commitments: (u: string) => ['commitments', u] as const,
  reserves: (u: string) => ['reserves', u] as const,
  liabilities: (u: string) => ['liabilities', u] as const,
  liabilityOverview: (u: string) => ['liabilityOverview', u] as const,
  bills: (u: string) => ['bills', u] as const,
  healthChecklist: (u: string) => ['healthChecklist', u] as const,
  households: (u: string) => ['households', u] as const,
  householdMembers: (u: string, h: string) => ['householdMembers', u, h] as const,
  householdExpenses: (u: string, h: string) => ['householdExpenses', u, h] as const,
  householdSettlements: (u: string, h: string) => ['householdSettlements', u, h] as const,
  statementReview: (u: string) => ['statementReview', u] as const,
  statementAnalysisReviews: (u: string) => ['statementAnalysisReviews', u] as const,
  depositStatementReview: (u: string) => ['depositStatementReview', u] as const,
  pipelineMetrics: (u: string, m: number, y: number) => ['pipelineMetrics', u, m, y] as const,
  pipelineFailures: (u: string, resolved: boolean) => ['pipelineFailures', u, resolved] as const,
  productCapabilities: ['productCapabilities'] as const,
  operationalHealth: ['operationalHealth'] as const,
  job: (u: string, jobId: string) => ['job', u, jobId] as const,
};

function useUserId(): string {
  const { user } = useAuth();
  return user?.id ?? '';
}

export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories,
    queryFn: () => api.categories(),
    ...financialQueryPolicy,
  });
}

export function useSummary() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.summary(userId, month, year),
    queryFn: () => api.summary(userId, month, year),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useTransactions() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.transactions(userId, month, year),
    queryFn: () => api.transactions(userId, { month, year, limit: 200 }),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useTransferMatchCandidates() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.transferMatchCandidates(userId),
    queryFn: () => api.transferMatchCandidates(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useLinkTransferMatch() {
  const userId = useUserId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      debitTransactionId: string;
      counterpartyTransactionId: string;
      kind: 'card_payment' | 'account_transfer';
    }) =>
      api.linkTransferMatch(userId, payload.debitTransactionId, {
        counterparty_transaction_id: payload.counterpartyTransactionId,
        kind: payload.kind,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.transferMatchCandidates(userId) }),
        queryClient.invalidateQueries({ queryKey: ['transactions'] }),
        queryClient.invalidateQueries({ queryKey: ['accountPosition'] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.netWorth(userId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(userId) }),
        queryClient.invalidateQueries({ queryKey: ['cardOverview', userId] }),
        queryClient.invalidateQueries({ queryKey: ['balanceForecast', userId] }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', userId] }),
      ]);
    },
  });
}

export function useEmails() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.emails(userId),
    queryFn: () => api.emails(userId, 12),
    enabled: !!userId,
    ...operationalQueryPolicy,
  });
}

export function useSyncStatus() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.syncStatus(userId),
    queryFn: () => api.syncStatus(userId),
    enabled: !!userId,
    ...operationalQueryPolicy,
  });
}

export function useAutoSyncStatus() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.autoSyncStatus(userId),
    queryFn: async () => {
      try {
        return await api.autoSyncStatus(userId);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: !!userId,
    retry: false,
    ...operationalQueryPolicy,
  });
}

export function useIntelligenceReadiness() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.intelligenceReadiness(userId),
    queryFn: () => api.intelligenceReadiness(userId),
    enabled: !!userId,
    staleTime: FINANCIAL_STALE_TIME_MS,
    refetchOnWindowFocus: true,
  });
}

export function useReconciliationQuality() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.reconciliationQuality(userId),
    queryFn: () => api.reconciliationQuality(userId),
    enabled: !!userId,
    staleTime: FINANCIAL_STALE_TIME_MS,
    refetchOnWindowFocus: true,
  });
}

export function useInsights() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.insights(userId, month, year),
    queryFn: () => api.insights(userId, month, year),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useAdjudicateAnomaly() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      anomalyId: string;
      decision: 'expected' | 'material' | 'insufficient_evidence';
      note?: string;
    }) =>
      api.adjudicateAnomaly(userId, payload.anomalyId, month, year, payload.decision, payload.note),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.insights(userId, month, year) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.anomalyAdjudications(userId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.intelligenceReadiness(userId) }),
      ]);
    },
  });
}

export function useAnomalySamples() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.anomalySamples(userId, month, year),
    queryFn: () => api.anomalySamples(userId, month, year),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useAdjudicateAnomalySample() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      sampleId: string;
      decision: 'expected' | 'material' | 'insufficient_evidence';
      note?: string;
    }) =>
      api.adjudicateAnomalySample(
        userId,
        payload.sampleId,
        month,
        year,
        payload.decision,
        payload.note,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.anomalySamples(userId, month, year) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.anomalyAdjudications(userId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.intelligenceReadiness(userId) }),
      ]);
    },
  });
}

export function useBudgets() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.budgets(userId, month, year),
    queryFn: () => api.budgetsTrack(userId, month, year),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useBudgetDrilldown(budgetId: string, enabled = true, limit = 100) {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.budgetDrilldown(userId, budgetId, month, year, limit),
    queryFn: () => api.budgetDrilldown(budgetId, userId, month, year, limit),
    enabled: !!userId && !!budgetId && enabled,
    ...financialQueryPolicy,
  });
}

export function useWorkspaceSnapshot() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.workspace(userId, month, year),
    queryFn: () => api.workspace(userId, month, year),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useFinancialHorizon(days = 30) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.horizon(userId, days),
    queryFn: () => api.horizon(userId, days),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useMerchants() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.merchants(userId, month, year),
    queryFn: () => api.merchants(userId, month, year),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useLearnedMerchantRules() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.learnedMerchantRules(userId),
    queryFn: () => api.learnedMerchantRules(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useDeleteLearnedMerchantRule() {
  const userId = useUserId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) => api.deleteLearnedMerchantRule(userId, ruleId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.learnedMerchantRules(userId) });
    },
  });
}

export function useCategoryIntelligence() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.categoryIntelligence(userId, month, year),
    queryFn: () => api.categoryIntelligence(userId, month, year),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useGoals() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.goals(userId, month, year),
    queryFn: () => api.goals(userId, month, year),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useGuidanceBrief() {
  const userId = useUserId();
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const preferences = useDashboardPreferences();
  const cadence = preferences.data?.briefing_cadence ?? 'daily';
  const financialDate = dateInputValueInTimezone(user?.timezone ?? 'Asia/Kolkata');
  const [financialYear, financialMonth, financialDay] = financialDate.split('-').map(Number);
  const asOf = `${year}-${String(month).padStart(2, '0')}-${String(
    month === financialMonth && year === financialYear
      ? financialDay
      : new Date(Date.UTC(year, month, 0)).getUTCDate(),
  ).padStart(2, '0')}`;
  return useQuery({
    queryKey: queryKeys.guidanceBrief(userId, month, year, cadence, asOf),
    queryFn: () => api.guidanceBrief(userId, cadence, asOf),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useDashboardPreferences() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.dashboardPreferences(userId),
    queryFn: () => api.dashboardPreferences(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useAccounts() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.accounts(userId),
    queryFn: () => api.accounts(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useBalanceProviderStatus() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.balanceProviderStatus(userId),
    queryFn: () => api.balanceProviderStatus(userId),
    enabled: !!userId,
    ...operationalQueryPolicy,
  });
}

export function useBalanceProviderConnections() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.balanceProviderConnections(userId),
    queryFn: () => api.balanceProviderConnections(userId),
    enabled: !!userId,
    ...operationalQueryPolicy,
  });
}

export function useBalanceProviderMappings(providerType?: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.balanceProviderMappings(userId, providerType),
    queryFn: () => api.balanceProviderMappings(userId, providerType),
    enabled: !!userId,
    ...operationalQueryPolicy,
  });
}

export function useBalanceProviderDiscoveredAccounts(providerType?: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.balanceProviderDiscoveredAccounts(userId, providerType ?? ''),
    queryFn: () => api.balanceProviderDiscoveredAccounts(userId, providerType!),
    enabled: !!userId && !!providerType,
    ...operationalQueryPolicy,
  });
}

function invalidateBalanceProviderDependents(
  queryClient: ReturnType<typeof useQueryClient>,
  userId: string,
) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.balanceProviderStatus(userId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.balanceProviderConnections(userId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.balanceProviderMappings(userId) }),
    queryClient.invalidateQueries({ queryKey: ['balanceProviderDiscoveredAccounts', userId] }),
    queryClient.invalidateQueries({ queryKey: queryKeys.accounts(userId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.netWorth(userId) }),
    queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(userId) }),
    queryClient.invalidateQueries({ queryKey: ['accountPosition', userId] }),
    queryClient.invalidateQueries({ queryKey: ['cardOverview', userId] }),
    queryClient.invalidateQueries({ queryKey: ['cardDueRunway', userId] }),
    queryClient.invalidateQueries({ queryKey: ['balanceForecast', userId] }),
  ]);
}

export function useRequestBalanceProviderConsent() {
  const userId = useUserId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (providerType: string) => api.requestBalanceProviderConsent(userId, providerType),
    onSuccess: () => invalidateBalanceProviderDependents(queryClient, userId),
  });
}

export function useRevokeBalanceProviderConsent() {
  const userId = useUserId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (providerType: string) => api.revokeBalanceProviderConsent(userId, providerType),
    onSuccess: () => invalidateBalanceProviderDependents(queryClient, userId),
  });
}

export function useMapBalanceProviderAccount() {
  const userId = useUserId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { accountId: string; providerType: string; providerAccountId: string }) =>
      api.mapBalanceProviderAccount(userId, payload.accountId, {
        provider_type: payload.providerType,
        provider_account_id: payload.providerAccountId,
      }),
    onSuccess: () => invalidateBalanceProviderDependents(queryClient, userId),
  });
}

export function useUnmapBalanceProviderAccount() {
  const userId = useUserId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { accountId: string; providerType: string }) =>
      api.unmapBalanceProviderAccount(userId, payload.accountId, payload.providerType),
    onSuccess: () => invalidateBalanceProviderDependents(queryClient, userId),
  });
}

export function useEnqueueBalanceRefresh() {
  const userId = useUserId();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      providerType: string;
      accountIds?: string[];
      idempotencyKey?: string;
    }) =>
      api.enqueueBalanceRefresh(
        userId,
        payload.providerType,
        payload.accountIds ?? [],
        payload.idempotencyKey,
      ),
    onSuccess: () => invalidateBalanceProviderDependents(queryClient, userId),
  });
}

export function useJob(jobId?: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.job(userId, jobId ?? ''),
    queryFn: () => api.job(jobId!),
    enabled: !!userId && !!jobId,
    refetchInterval: 3_000,
    refetchOnWindowFocus: true,
    retry: false,
  });
}

export function useAccountLinkRules() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.accountLinkRules(userId),
    queryFn: () => api.accountLinkRules(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useNetWorth() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.netWorth(userId),
    queryFn: () => api.netWorth(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useCashPlan() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.cashPlan(userId),
    queryFn: () => api.cashPlan(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useAccountBalanceForecast(accountId?: string, horizonDays = 30, enabled = true) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.balanceForecast(userId, accountId ?? '', horizonDays),
    queryFn: () => api.accountBalanceForecast(userId, accountId!, horizonDays),
    enabled: !!userId && !!accountId && enabled,
    ...financialQueryPolicy,
  });
}

export function useAccountBalanceReconciliations(accountId?: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.balanceReconciliations(userId, accountId ?? ''),
    queryFn: () => api.accountBalanceReconciliations(userId, accountId!),
    enabled: !!userId && !!accountId,
    ...financialQueryPolicy,
  });
}

export function useCardDueRunway(accountId?: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.cardDueRunway(userId, accountId ?? ''),
    queryFn: () => api.cardDueRunway(userId, accountId!),
    enabled: !!userId && !!accountId,
    ...financialQueryPolicy,
  });
}

export function useCardUtilizationHistory(accountId?: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.cardUtilizationHistory(userId, accountId ?? ''),
    queryFn: () => api.cardUtilizationHistory(userId, accountId!),
    enabled: !!userId && !!accountId,
    ...financialQueryPolicy,
  });
}

export function useCardPortfolioUpcomingState(enabled = true) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.cardPortfolioUpcoming(userId),
    queryFn: () => api.cardPortfolioUpcomingState(userId),
    enabled: !!userId && enabled,
    ...financialQueryPolicy,
  });
}

export function useCardPortfolioPaymentPlan(enabled = true) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.cardPortfolioPaymentPlan(userId),
    queryFn: () => api.cardPortfolioPaymentPlan(userId),
    enabled: !!userId && enabled,
    ...financialQueryPolicy,
  });
}

export function useAccountBalanceForecastSnapshots(accountId?: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.balanceForecastSnapshots(userId, accountId ?? ''),
    queryFn: () => api.accountBalanceForecastSnapshots(userId, accountId!),
    enabled: !!userId && !!accountId,
    ...financialQueryPolicy,
  });
}

export function useAccountBalanceForecastOutcomes(accountId?: string) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.balanceForecastOutcomes(userId, accountId ?? ''),
    queryFn: () => api.accountBalanceForecastOutcomes(userId, accountId!),
    enabled: !!userId && !!accountId,
    ...financialQueryPolicy,
  });
}

export function useCommitments() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.commitments(userId),
    queryFn: () => api.commitments(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useReserves() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.reserves(userId),
    queryFn: () => api.reserves(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useLiabilities() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.liabilities(userId),
    queryFn: () => api.liabilities(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useLiabilityOverview() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.liabilityOverview(userId),
    queryFn: () => api.liabilityOverview(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useBills() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.bills(userId),
    queryFn: () => api.bills(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useHealthChecklist() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.healthChecklist(userId),
    queryFn: () => api.healthChecklist(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useHouseholds() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.households(userId),
    queryFn: () => api.households(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useStatementReviewItems() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.statementReview(userId),
    queryFn: () => api.statementReviewItems(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useStatementAnalysisReviews() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.statementAnalysisReviews(userId),
    queryFn: () => api.statementAnalysisReviews(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function useDepositStatementReviewItems() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.depositStatementReview(userId),
    queryFn: () => api.depositStatementReviewItems(userId),
    enabled: !!userId,
    ...financialQueryPolicy,
  });
}

export function usePipelineMetrics() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.pipelineMetrics(userId, month, year),
    queryFn: () => api.pipelineMetrics(userId, month, year),
    enabled: !!userId,
    ...operationalQueryPolicy,
  });
}

export function usePipelineFailures(resolved = false) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.pipelineFailures(userId, resolved),
    queryFn: () => api.pipelineFailures(userId, resolved, 20),
    enabled: !!userId,
    ...operationalQueryPolicy,
  });
}

export function useProductCapabilities() {
  return useQuery({
    queryKey: queryKeys.productCapabilities,
    queryFn: () => api.productCapabilities(),
    ...capabilityQueryPolicy,
  });
}

export function useOperationalHealth() {
  return useQuery({
    queryKey: queryKeys.operationalHealth,
    queryFn: () => api.operationalHealth(),
    ...operationalQueryPolicy,
  });
}
