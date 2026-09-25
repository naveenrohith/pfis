import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StatementReviewItem, Transaction, TransferMatchCandidate } from '@/lib/types';
import { ReviewSection } from './ReviewSection';

const state = vi.hoisted(() => ({
  focusedReviewId: null as string | null,
  focusReview: vi.fn(),
  scrollTo: vi.fn(),
}));

const queryMocks = vi.hoisted(() => ({
  useAccounts: vi.fn(),
  useCategories: vi.fn(),
  useLinkTransferMatch: vi.fn(),
  useStatementReviewItems: vi.fn(),
  useTransferMatchCandidates: vi.fn(),
  useTransactions: vi.fn(),
}));

const transaction: Transaction = {
  id: 'transaction-1',
  amount: 1250,
  currency: 'INR',
  transaction_type: 'debit',
  payment_method: 'other',
  transaction_date: '2026-09-20',
  merchant_normalized: 'Primary transaction',
  confidence_score: 0.5,
  reviewed_flag: false,
  tags: [],
};

const statementItem = {
  id: 'statement-1',
  transaction_date: '2026-09-19',
  description: 'Statement evidence item',
  amount: 500,
  transaction_type: 'debit',
  card_event: 'purchase',
  component_kind: 'purchase',
  review_outcome: 'needs_review',
  financial_account_id: 'account-1',
  account_label: 'Card account',
  masked_number: '••••1234',
  statement_date: '2026-09-21',
  decision_count: 0,
  candidate_transactions: [],
} as StatementReviewItem;

const transferCandidate = {
  candidate_id: 'candidate-1',
  debit_transaction_id: 'transaction-2',
  credit_transaction_id: 'transaction-3',
  debit_account_id: 'account-1',
  debit_account_label: 'Bank account',
  credit_account_id: 'account-2',
  credit_account_label: 'Card account',
  amount: 500,
  currency: 'INR',
  debit_date: '2026-09-19',
  credit_date: '2026-09-20',
  date_difference_days: 1,
  kind: 'card_payment',
  confidence: 0.9,
  ambiguous: false,
  reason_codes: ['amount_match'],
} as TransferMatchCandidate;

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1', currency: 'INR' } }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify: vi.fn() }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => state,
}));

vi.mock('@/features/review/ReviewDetail', () => ({
  ReviewDetail: () => <div data-testid="review-detail" />,
}));

vi.mock('@/features/subscriptions/SubscriptionsReviewPanel', () => ({
  SubscriptionsReviewPanel: () => <div>Subscriptions review</div>,
}));

vi.mock('@/lib/api', () => ({
  api: {
    bulkUpdate: vi.fn(),
    reviewStatementLine: vi.fn(),
  },
}));

vi.mock('@/features/workspace/queries', () => ({
  queryKeys: { statementReview: vi.fn() },
  ...queryMocks,
}));

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <ReviewSection embedded />
    </QueryClientProvider>,
  );

  return {
    ...result,
    rerenderSection: () =>
      result.rerender(
        <QueryClientProvider client={queryClient}>
          <ReviewSection embedded />
        </QueryClientProvider>,
      ),
  };
}

describe('ReviewSection activity review follow-up', () => {
  beforeEach(() => {
    state.focusedReviewId = null;
    state.focusReview.mockReset();
    state.focusReview.mockImplementation((id: string) => {
      state.focusedReviewId = id;
    });
    state.scrollTo.mockReset();
    queryMocks.useAccounts.mockReturnValue({ data: [], isLoading: false });
    queryMocks.useCategories.mockReturnValue({ data: [], isLoading: false });
    queryMocks.useLinkTransferMatch.mockReturnValue({ isPending: false, mutate: vi.fn() });
    queryMocks.useStatementReviewItems.mockReturnValue({ data: [], isLoading: false });
    queryMocks.useTransferMatchCandidates.mockReturnValue({ data: [], isLoading: false });
    queryMocks.useTransactions.mockReturnValue({ data: [transaction], isLoading: false });
  });

  it('keeps the transaction queue and detail before supplemental queues', () => {
    queryMocks.useStatementReviewItems.mockReturnValue({ data: [statementItem], isLoading: false });
    queryMocks.useTransferMatchCandidates.mockReturnValue({
      data: [transferCandidate],
      isLoading: false,
    });

    renderSection();

    const content = document.body.textContent ?? '';
    expect(content.indexOf('Primary transaction')).toBeLessThan(
      content.indexOf('Statement evidence'),
    );
    expect(content.indexOf('Transaction detail')).toBeLessThan(
      content.indexOf('Possible paired movements'),
    );
  });

  it('distinguishes an empty transaction queue from an entirely clear review state', () => {
    queryMocks.useTransactions.mockReturnValue({ data: [], isLoading: false });
    queryMocks.useStatementReviewItems.mockReturnValue({ data: [statementItem], isLoading: false });

    renderSection();

    expect(screen.getAllByText('No transactions need review').length).toBeGreaterThan(0);
    expect(screen.queryByText('Everything is ready')).not.toBeInTheDocument();
  });

  it('includes the subscriptions review surface in Activity review', () => {
    renderSection();

    expect(screen.getByText('Subscriptions review')).toBeInTheDocument();
  });

  it('focuses and scrolls the detail heading after transaction selection', async () => {
    const user = userEvent.setup();
    const { rerenderSection } = renderSection();
    const heading = screen.getByRole('heading', { name: 'Transaction detail' });
    const scrollIntoView = vi.fn();
    heading.scrollIntoView = scrollIntoView;

    await user.click(screen.getByRole('button', { name: /Primary transaction/ }));
    expect(state.focusReview).toHaveBeenCalledWith('transaction-1');

    rerenderSection();

    await waitFor(() => expect(heading).toHaveFocus());
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
  });

  it('keeps keyboard focus in review search after the detail has been focused', async () => {
    const user = userEvent.setup();
    const { rerenderSection } = renderSection();
    const heading = screen.getByRole('heading', { name: 'Transaction detail' });
    heading.scrollIntoView = vi.fn();

    await user.click(screen.getByRole('button', { name: /Primary transaction/ }));
    rerenderSection();
    await waitFor(() => expect(heading).toHaveFocus());

    const search = screen.getByPlaceholderText('Search merchant, account, reference...');
    await user.type(search, 'Primary');

    expect(search).toHaveValue('Primary');
    expect(search).toHaveFocus();
  });
});
