import type { QueryClient } from '@tanstack/react-query';
import type { FinancialChangeDomain } from '@/lib/types';

/**
 * One dependency policy for durable server changes. Keep these query roots in
 * sync with queryKeys in queries.ts; every match is additionally user-scoped.
 */
export const FINANCIAL_CHANGE_QUERY_ROOTS: Record<FinancialChangeDomain, readonly string[]> = {
  activity: [
    'transactions',
    'transactionSplits',
    'summary',
    'transferMatchCandidates',
    'workspace',
    'merchants',
    'categoryIntelligence',
    'budgets',
    'insights',
    'anomalySamples',
    'goals',
    'guidanceBrief',
    'accountPosition',
    'accounts',
    'netWorth',
    'cashPlan',
    'cardOverview',
    'balanceForecast',
    'cardDueRunway',
    'temporalEvents',
    'intelligenceReadiness',
    'reconciliationQuality',
    'learnedMerchantRules',
  ],
  today: [
    'workspace',
    'guidanceBrief',
    'goals',
    'cashPlan',
    'commitments',
    'reserves',
    'liabilities',
    'liabilitySchedule',
    'liabilityOverview',
    'bills',
    'cardOverview',
    'cardDueRunway',
    'cardPortfolioUpcoming',
    'cardPortfolioPaymentPlan',
    'balanceForecast',
    'netWorth',
  ],
  insights: [
    'insights',
    'anomalyAdjudications',
    'anomalySamples',
    'categoryIntelligence',
    'goals',
    'intelligenceReadiness',
    'reconciliationQuality',
  ],
  accounts: [
    'accounts',
    'accountIdentityHistory',
    'accountLinkRules',
    'netWorth',
    'cashPlan',
    'accountPosition',
    'balanceForecast',
    'balanceForecastSnapshots',
    'balanceForecastOutcomes',
    'balanceReconciliations',
    'balanceProviderStatus',
    'balanceProviderConnections',
    'balanceProviderMappings',
    'balanceProviderDiscoveredAccounts',
    'cardOverview',
    'cardDueRunway',
    'cardUtilizationHistory',
    'liabilityOverview',
  ],
  cards: [
    'cardOverview',
    'cardDueRunway',
    'cardUtilizationHistory',
    'cardPortfolioUpcoming',
    'cardPortfolioPaymentPlan',
    'accounts',
    'cardDisputes',
    'accountPosition',
    'netWorth',
    'cashPlan',
    'balanceForecast',
    'liabilities',
    'liabilityOverview',
    'commitments',
    'transactions',
    'transactionSplits',
    'summary',
    'workspace',
    'guidanceBrief',
  ],
  planning: [
    'cashPlan',
    'commitments',
    'reserves',
    'liabilities',
    'liabilityOverview',
    'liabilitySchedule',
    'payoffComparison',
    'bills',
    'goals',
    'workspace',
    'guidanceBrief',
    'cardOverview',
    'cardDisputes',
    'cardDueRunway',
    'cardPortfolioPaymentPlan',
    'accounts',
    'netWorth',
    'balanceForecast',
  ],
  guidance: ['guidanceBrief', 'guidance', 'workspace', 'goals'],
  statements: [
    'statementReview',
    'statementAnalysisReviews',
    'depositStatementReview',
    'transactionSplits',
    'transactions',
    'summary',
    'workspace',
    'insights',
    'accounts',
    'accountPosition',
    'netWorth',
    'cardOverview',
    'cardDueRunway',
    'cashPlan',
    'commitments',
    'liabilities',
    'liabilityOverview',
    'guidanceBrief',
  ],
  data: [
    'job',
    'emails',
    'syncStatus',
    'autoSyncStatus',
    'pipelineMetrics',
    'pipelineFailures',
    'healthChecklist',
    'sourceCoverage',
    'statementAnalysisReviews',
    'statementReview',
    'depositStatementReview',
    'learnedMerchantRules',
  ],
};

export async function invalidateFinancialChangeDomains(
  queryClient: QueryClient,
  userId: string,
  domains: readonly string[],
): Promise<void> {
  if (!userId || domains.length === 0) return;

  const roots = new Set<string>();
  let unknownDomain = false;
  for (const domain of domains) {
    if (!Object.prototype.hasOwnProperty.call(FINANCIAL_CHANGE_QUERY_ROOTS, domain)) {
      unknownDomain = true;
      continue;
    }
    for (const root of FINANCIAL_CHANGE_QUERY_ROOTS[domain as FinancialChangeDomain]) {
      roots.add(root);
    }
  }

  await queryClient.invalidateQueries({
    predicate: (query) =>
      query.queryKey.includes(userId) && (unknownDomain || roots.has(String(query.queryKey[0]))),
  });
}
