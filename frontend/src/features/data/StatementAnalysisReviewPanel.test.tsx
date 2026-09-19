import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StatementAnalysisReviewPanel } from './StatementAnalysisReviewPanel';

const apiMocks = vi.hoisted(() => ({
  reviewStatementPdf: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 'user-1',
      name: 'Test',
      email: 'test@example.com',
      currency: 'INR',
    },
  }),
}));

vi.mock('@/features/workspace/queries', () => ({
  queryKeys: {
    statementAnalysisReviews: (userId: string) => ['statementAnalysisReviews', userId],
  },
  useStatementAnalysisReviews: () => ({
    data: [
      {
        id: 'review-1',
        document_fingerprint: 'sha256:bounded',
        institution: 'hdfc',
        product_type: 'deposit_account',
        format_id: 'hdfc-deposit-generic',
        support_status: 'recognized_not_supported',
        confidence: 0.88,
        reason_codes: ['generic_deposit_account_signature'],
        activity_types: ['upi', 'debit_card'],
        detector_version: 'pfis-statement-detector-3',
        status: 'pending_review',
        created_at: '2026-08-10T08:00:00Z',
        analysis: {
          status: 'partial',
          source_kind: 'generic_table',
          period_start: '2026-07-01',
          period_end: '2026-07-31',
          opening_balance: 10000,
          closing_balance: 11350,
          row_count: 2,
          preview_count: 2,
          omitted_line_count: 0,
          debit_total: 750,
          credit_total: 2100,
          rail_totals: { upi: 750, transfer: 2100 },
          reconciled: null,
          confidence: 0.8,
          reason_codes: ['ambiguous_direction'],
          ruleset_version: 'statement-review-1',
          lines: [
            {
              line_number: 1,
              transaction_date: '2026-07-04',
              description: 'UPI merchant redacted',
              amount: 750,
              direction: 'debit',
              payment_rail: 'upi',
              balance_after: 9250,
              confidence: 0.82,
              reason_codes: [],
            },
          ],
        },
      },
    ],
    isLoading: false,
    error: null,
  }),
}));

vi.mock('@/lib/api', () => ({
  api: apiMocks,
}));

function renderPanel(file: File | null = new File(['%PDF-1.7 test'], 'bank-statement.pdf')) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <StatementAnalysisReviewPanel
        file={file}
        detection={{
          institution: 'hdfc',
          product_type: 'deposit_account',
          support_status: 'recognized_not_supported',
          confidence: 0.88,
          reason_codes: ['generic_deposit_account_signature'],
          activity_types: ['upi'],
          detector_version: 'pfis-statement-detector-3',
        }}
      />
    </QueryClientProvider>,
  );
}

describe('StatementAnalysisReviewPanel', () => {
  it('saves a selected PDF and exposes a bounded redacted artifact', async () => {
    const file = new File(['%PDF-1.7 test'], 'bank-statement.pdf', {
      type: 'application/pdf',
    });
    apiMocks.reviewStatementPdf.mockResolvedValue({ id: 'review-2' });
    renderPanel(file);

    expect(screen.getByText('Keep unfamiliar layouts reviewable')).toBeInTheDocument();
    expect(screen.getByText('HDFC bank account / Recognized layout needs review')).toBeInTheDocument();
    expect(screen.getByText('SAVED ANALYSIS ARTIFACTS')).toBeInTheDocument();
    expect(screen.getByText('UPI merchant redacted')).toBeInTheDocument();
    expect(screen.getByText(/does not import a transaction or balance/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save redacted analysis' }));
    await waitFor(() => expect(apiMocks.reviewStatementPdf).toHaveBeenCalledWith('user-1', file));
    expect(await screen.findByText(/Redacted analysis saved/i)).toBeInTheDocument();
  });

  it('keeps retained artifacts visible without a new file selection', () => {
    renderPanel(null);

    expect(screen.getByText('SAVED ANALYSIS ARTIFACTS')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save redacted analysis' })).not.toBeInTheDocument();
  });
});
