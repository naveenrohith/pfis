import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/features/auth/AuthContext';
import { subscriptionReviewApi } from '@/lib/api';
import type { SubscriptionReviewAction } from '@/lib/types';

const FINANCIAL_STALE_TIME_MS = 5 * 60 * 1000;

export const subscriptionReviewQueryKey = (userId: string) =>
  ['subscriptionReview', userId] as const;

function useUserId(): string {
  const { user } = useAuth();
  return user?.id ?? '';
}

export function useSubscriptionReview() {
  const userId = useUserId();
  return useQuery({
    queryKey: subscriptionReviewQueryKey(userId),
    queryFn: () => subscriptionReviewApi.recurringReview(userId),
    enabled: !!userId,
    staleTime: FINANCIAL_STALE_TIME_MS,
    refetchOnWindowFocus: true,
  });
}

export function useRecordSubscriptionReviewAction() {
  const userId = useUserId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: { streamKey: string; action: SubscriptionReviewAction; note?: string }) =>
      subscriptionReviewApi.recordRecurringReviewAction(
        userId,
        payload.streamKey,
        payload.action,
        payload.note,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: subscriptionReviewQueryKey(userId),
      });
    },
  });
}
