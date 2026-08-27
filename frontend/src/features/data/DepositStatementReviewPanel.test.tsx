import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DepositStatementReviewPanel } from './DepositStatementReviewPanel';

const { reviewDepositStatementLine } = vi.hoisted(() => ({
  reviewDepositStatementLine: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', currency: 'INR' },
  }),
}));

vi.mock('@/features/workspace/queries', () => ({
  queryKeys: {
    accounts: (userId: string) => ['accounts', userId],
    depositStatementReview: (userId: string) => ['depositStatementReview', userId],
    statementReview: (userId: string) => ['statementReview', userId],
  },
  useDepositStatementReviewItems: () => ({
    isLoading: false,
    error: null,
    data: [
      {
        id: 'deposit-line-1',
        line_number: 4,
        transaction_date: '2026-08-08',
        value_date: '2026-08-08',
        description: 'POS MERCHANT WITHOUT RAIL',
        reference_id: 'REF-1',
        amount: 1250,
        transaction_type: 'debit',
        payment_rail: 'other',
        balance_after: 48000,
        review_outcome: 'needs_review',
        created_transaction_id: null,
        financial_account_id: 'bank-1',
        account_label: 'HDFC Bank',
        masked_number: '••••1234',
        period_start: '2026-08-01',
        period_end: '2026-08-10',
        decision_count: 0,
      },
    ],
  }),
}));

vi.mock('@/lib/api', () => ({
  api: { reviewDepositStatementLine },
}));

describe('DepositStatementReviewPanel', () => {
  it('requires an explicit rail before importing an unresolved row', async () => {
    reviewDepositStatementLine.mockResolvedValue({});
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <DepositStatementReviewPanel />
      </QueryClientProvider>,
    );

    expect(screen.getByRole('heading', { name: '1 row need a payment rail' })).toBeInTheDocument();
    const importButton = screen.getByRole('button', { name: 'Import row' });
    expect(importButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Payment rail'), { target: { value: 'upi' } });
    expect(importButton).toBeEnabled();
    fireEvent.click(importButton);

    await waitFor(() =>
      expect(reviewDepositStatementLine).toHaveBeenCalledWith(
        'user-1',
        'deposit-line-1',
        expect.objectContaining({ decision: 'import', payment_rail: 'upi' }),
      ),
    );
  });
});
