import { useQuery } from '@tanstack/react-query';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { monthlySnapshotApi } from '@/lib/api';

const FINANCIAL_STALE_TIME_MS = 5 * 60 * 1000;

export const monthlySnapshotQueryKey = (userId: string, month: number, year: number) =>
  ['monthlySnapshot', userId, month, year] as const;

export function useMonthlySnapshot() {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const userId = user?.id ?? '';

  return useQuery({
    queryKey: monthlySnapshotQueryKey(userId, month, year),
    queryFn: () => monthlySnapshotApi.monthlySnapshot(userId, month, year),
    enabled: !!userId,
    staleTime: FINANCIAL_STALE_TIME_MS,
    refetchOnWindowFocus: true,
  });
}
