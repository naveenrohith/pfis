import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SubscriptionReviewListResponse } from '@/lib/types';
import { SubscriptionsReviewPanel } from './SubscriptionsReviewPanel';

const notify = vi.fn();

const apiMocks = vi.hoisted(() => ({
  recurringReview: vi.fn(),
  recordRecurringReviewAction: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1', currency: 'INR' } }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify }),
}));

vi.mock('@/lib/api', () => ({
  subscriptionReviewApi: apiMocks,
}));

const response: SubscriptionReviewListResponse = {
  schema_version: 'pfis-subscription-review-list-1',
  as_of: '2026-09-25',
  ruleset_version: 'pfis-recurring-4',
  thresholds: {},
  excluded_count: 1,
  items: [
    {
      schema_version: 'pfis-subscription-review-item-1',
      id: 'stream-1',
      stream_key: 'stream-1',
      merchant: 'StreamCo Premium',
      lifecycle_status: 'mature',
      cadence: 'monthly',
      typical_amount: 899,
      monthly_equivalent: 899,
      currency: 'INR',
      amount_change_detected: true,
      amount_low: 799,
      amount_high: 999,
      occurrences: 4,
      cadence_confidence: 0.88,
      amount_confidence: 0.9,
      confidence: 0.86,
      last_seen: '2026-09-20',
      next_expected: '2026-10-20',
      next_expected_null_reason: null,
      days_since_last_expected: 0,
      evidence_transaction_ids: ['tx-1', 'tx-2', 'tx-3', 'tx-4'],
      financial_account_id: 'account-1',
      user_action: null,
      action_id: null,
      action_note: null,
      action_updated_at: null,
      ruleset_version: 'pfis-recurring-4',
    },
    {
      schema_version: 'pfis-subscription-review-item-1',
      id: 'stream-2',
      stream_key: 'stream-2',
      merchant: 'Cloud Tools',
      lifecycle_status: 'candidate',
      cadence: null,
      typical_amount: 1200,
      monthly_equivalent: 1200,
      currency: 'INR',
      amount_change_detected: false,
      amount_low: 1200,
      amount_high: 1200,
      occurrences: 2,
      cadence_confidence: 0.4,
      amount_confidence: 0.8,
      confidence: 0.6,
      last_seen: '2026-09-18',
      next_expected: null,
      next_expected_null_reason: 'insufficient_occurrences',
      days_since_last_expected: null,
      evidence_transaction_ids: ['tx-5', 'tx-6'],
      financial_account_id: null,
      user_action: null,
      action_id: null,
      action_note: null,
      action_updated_at: null,
      ruleset_version: 'pfis-recurring-4',
    },
  ],
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <SubscriptionsReviewPanel />
    </QueryClientProvider>,
  );
}

describe('SubscriptionsReviewPanel', () => {
  beforeEach(() => {
    notify.mockReset();
    apiMocks.recurringReview.mockReset();
    apiMocks.recordRecurringReviewAction.mockReset();
    apiMocks.recurringReview.mockResolvedValue(response);
    apiMocks.recordRecurringReviewAction.mockResolvedValue({
      schema_version: 'pfis-subscription-review-action-1',
      id: 'action-1',
      stream_key: 'stream-1',
      merchant: 'StreamCo Premium',
      action: 'confirm',
      note: null,
      created_at: '2026-09-25T10:00:00Z',
      updated_at: '2026-09-25T10:00:00Z',
    });
  });

  it('shows lifecycle meanings, schedule facts, and withheld-date reasons', async () => {
    renderPanel();

    expect(await screen.findByText('StreamCo Premium')).toBeInTheDocument();
    expect(
      screen.getByText('The stream repeats with enough evidence to expect the next charge.'),
    ).toBeInTheDocument();
    expect(screen.getByText('₹899')).toBeInTheDocument();
    expect(screen.getByText('Changed')).toBeInTheDocument();
    expect(screen.getByText('4 entries')).toBeInTheDocument();
    expect(
      screen.getByText('PFIS needs at least three observations before dating the next charge.'),
    ).toBeInTheDocument();
  });

  it('records a decision without applying an optimistic removal', async () => {
    const user = userEvent.setup();
    renderPanel();

    await screen.findByText('StreamCo Premium');
    await user.click(screen.getAllByRole('button', { name: /Confirm/i })[0]);

    await waitFor(() =>
      expect(apiMocks.recordRecurringReviewAction).toHaveBeenCalledWith(
        'user-1',
        'stream-1',
        'confirm',
        undefined,
      ),
    );
    expect(screen.getByText('StreamCo Premium')).toBeInTheDocument();
    expect(notify).toHaveBeenCalledWith('StreamCo Premium review saved.', 'success');
  });

  it('explains the clear state including excluded decisions', async () => {
    apiMocks.recurringReview.mockResolvedValue({ ...response, items: [] });

    renderPanel();

    expect(await screen.findByText('No subscriptions need review')).toBeInTheDocument();
    expect(screen.getByText('1 stream already dismissed or cancelled.')).toBeInTheDocument();
  });
});
