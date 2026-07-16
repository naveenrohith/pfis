import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';

/** Shared query keys so mutations can invalidate precisely. */
export const queryKeys = {
  categories: ['categories'] as const,
  summary: (u: string, m: number, y: number) => ['summary', u, m, y] as const,
  transactions: (u: string, m: number, y: number) => ['transactions', u, m, y] as const,
  emails: (u: string) => ['emails', u] as const,
  syncStatus: (u: string) => ['syncStatus', u] as const,
  autoSyncStatus: (u: string) => ['autoSyncStatus', u] as const,
  insights: (u: string, m: number, y: number) => ['insights', u, m, y] as const,
  budgets: (u: string, m: number, y: number) => ['budgets', u, m, y] as const,
  workspace: (u: string, m: number, y: number) => ['workspace', u, m, y] as const,
  merchants: (u: string, m: number, y: number) => ['merchants', u, m, y] as const,
  learnedMerchantRules: (u: string) => ['learnedMerchantRules', u] as const,
  categoryIntelligence: (u: string, m: number, y: number) =>
    ['categoryIntelligence', u, m, y] as const,
  goals: (u: string, m: number, y: number) => ['goals', u, m, y] as const,
  guidanceBrief: (u: string, m: number, y: number, cadence?: string) =>
    cadence
      ? (['guidanceBrief', u, m, y, cadence] as const)
      : (['guidanceBrief', u, m, y] as const),
  dashboardPreferences: (u: string) => ['dashboardPreferences', u] as const,
  accounts: (u: string) => ['accounts', u] as const,
  netWorth: (u: string) => ['netWorth', u] as const,
  pipelineMetrics: (u: string, m: number, y: number) => ['pipelineMetrics', u, m, y] as const,
  pipelineFailures: (u: string, resolved: boolean) => ['pipelineFailures', u, resolved] as const,
};

function useUserId(): string {
  const { user } = useAuth();
  return user?.id ?? '';
}

export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories,
    queryFn: () => api.categories(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useSummary() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.summary(userId, month, year),
    queryFn: () => api.summary(userId, month, year),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useTransactions() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.transactions(userId, month, year),
    queryFn: () => api.transactions(userId, { month, year, limit: 200 }),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useEmails() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.emails(userId),
    queryFn: () => api.emails(userId, 12),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useSyncStatus() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.syncStatus(userId),
    queryFn: () => api.syncStatus(userId),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useAutoSyncStatus() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.autoSyncStatus(userId),
    queryFn: () => api.autoSyncStatus(userId),
    enabled: !!userId,
    retry: false,
    refetchInterval: 30_000,
  });
}

export function useInsights() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.insights(userId, month, year),
    queryFn: () => api.insights(userId, month, year),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useBudgets() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.budgets(userId, month, year),
    queryFn: () => api.budgetsTrack(userId, month, year),
    enabled: !!userId,
  });
}

export function useWorkspaceSnapshot() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.workspace(userId, month, year),
    queryFn: () => api.workspace(userId, month, year),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useMerchants() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.merchants(userId, month, year),
    queryFn: () => api.merchants(userId, month, year),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useLearnedMerchantRules() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.learnedMerchantRules(userId),
    queryFn: () => api.learnedMerchantRules(userId),
    enabled: !!userId,
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
    refetchInterval: 30_000,
  });
}

export function useGoals() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.goals(userId, month, year),
    queryFn: () => api.goals(userId, month, year),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useGuidanceBrief() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  const preferences = useDashboardPreferences();
  const cadence = preferences.data?.briefing_cadence ?? 'daily';
  const asOf = `${year}-${String(month).padStart(2, '0')}-${String(
    month === new Date().getMonth() + 1 && year === new Date().getFullYear()
      ? new Date().getDate()
      : new Date(year, month, 0).getDate(),
  ).padStart(2, '0')}`;
  return useQuery({
    queryKey: queryKeys.guidanceBrief(userId, month, year, cadence),
    queryFn: () => api.guidanceBrief(userId, cadence, asOf),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function useDashboardPreferences() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.dashboardPreferences(userId),
    queryFn: () => api.dashboardPreferences(userId),
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useAccounts() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.accounts(userId),
    queryFn: () => api.accounts(userId),
    enabled: !!userId,
  });
}

export function useNetWorth() {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.netWorth(userId),
    queryFn: () => api.netWorth(userId),
    enabled: !!userId,
  });
}

export function usePipelineMetrics() {
  const userId = useUserId();
  const { month, year } = useWorkspace();
  return useQuery({
    queryKey: queryKeys.pipelineMetrics(userId, month, year),
    queryFn: () => api.pipelineMetrics(userId, month, year),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}

export function usePipelineFailures(resolved = false) {
  const userId = useUserId();
  return useQuery({
    queryKey: queryKeys.pipelineFailures(userId, resolved),
    queryFn: () => api.pipelineFailures(userId, resolved, 20),
    enabled: !!userId,
    refetchInterval: 30_000,
  });
}
