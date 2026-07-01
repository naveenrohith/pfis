import { useQuery } from '@tanstack/react-query';
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
