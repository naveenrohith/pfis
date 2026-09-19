import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StatementImportSection } from './StatementImportSection';

const apiMocks = vi.hoisted(() => ({
  createAccountLinkRule: vi.fn(),
  deactivateAccountLinkRule: vi.fn(),
  detectStatement: vi.fn(),
  importStatement: vi.fn(),
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
    accounts: (userId: string) => ['accounts', userId],
    accountLinkRules: (userId: string) => ['accountLinkRules', userId],
    statementReview: (userId: string) => ['statementReview', userId],
    statementAnalysisReviews: (userId: string) => ['statementAnalysisReviews', userId],
    depositStatementReview: (userId: string) => ['depositStatementReview', userId],
  },
  useAccounts: () => ({
    isLoading: false,
    data: [
      {
        id: 'card-1',
        institution_name: 'HDFC Bank',
        account_type: 'credit_card',
        balance_kind: 'liability',
        masked_number: '••••9911',
        currency: 'INR',
        is_active: true,
        identity_status: 'confirmed',
      },
      {
        id: 'bank-1',
        institution_name: 'HDFC Bank',
        account_type: 'bank',
        balance_kind: 'asset',
        masked_number: '••••1234',
        currency: 'INR',
        is_active: true,
        identity_status: 'confirmed',
      },
      {
        id: 'bank-2',
        institution_name: 'ICICI Bank',
        account_type: 'bank',
        balance_kind: 'asset',
        masked_number: '••••5678',
        currency: 'INR',
        is_active: true,
        identity_status: 'confirmed',
      },
    ],
  }),
  useAccountLinkRules: () => ({ data: [] }),
  useStatementAnalysisReviews: () => ({ data: [], isLoading: false, error: null }),
  useDepositStatementReviewItems: () => ({ data: [], isLoading: false, error: null }),
}));

vi.mock('@/lib/api', () => ({
  api: apiMocks,
}));

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <StatementImportSection />
    </QueryClientProvider>,
  );
}

describe('StatementImportSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('imports a PDF with extract-then-delete disclosure and explicit outcomes', async () => {
    apiMocks.detectStatement.mockResolvedValue({
      institution: 'hdfc',
      product_type: 'credit_card',
      format_id: 'hdfc-credit-card-digital',
      support_status: 'supported',
      confidence: 0.95,
      reason_codes: ['total_amount_due'],
      activity_types: ['credit_card'],
      detector_version: 'pfis-statement-detector-3',
    });
    apiMocks.importStatement.mockResolvedValue({
      product_type: 'credit_card',
      detection: { product_type: 'credit_card', support_status: 'supported' },
      credit_card_statement: {
        id: 'statement-1',
        statement_date: '2026-07-22',
        period_start: '2026-06-23',
        period_end: '2026-07-22',
        total_due: 1500,
        due_date: '2026-08-11',
        currency: 'INR',
        lines: [
          { id: 'line-1', review_outcome: 'matched' },
          { id: 'line-2', review_outcome: 'needs_review' },
        ],
      },
    });
    renderSection();

    expect(screen.getByText('Extract, then delete')).toBeInTheDocument();
    const file = new File(['%PDF-1.7 test'], 'statement.pdf', {
      type: 'application/pdf',
    });
    fireEvent.change(screen.getByLabelText('Digital PDF'), {
      target: { files: [file] },
    });
    await waitFor(() => expect(apiMocks.detectStatement).toHaveBeenCalledWith('user-1', file));
    expect(await screen.findByText('HDFC credit card')).toBeInTheDocument();
    const submit = screen.getByRole('button', { name: 'Import verified statement' });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.submit(submit.closest('form')!);

    await waitFor(() =>
      expect(apiMocks.importStatement).toHaveBeenCalledWith('user-1', 'card-1', file),
    );
    expect(await screen.findByText('Import reconciled')).toBeInTheDocument();
    expect(screen.getByText('1 lines need evidence review')).toBeInTheDocument();
  });

  it('routes a recognized deposit statement to the owned bank account', async () => {
    apiMocks.detectStatement.mockResolvedValue({
      institution: 'hdfc',
      product_type: 'deposit_account',
      format_id: 'hdfc-deposit-pipe-v1',
      support_status: 'supported',
      confidence: 0.97,
      reason_codes: ['reviewed_import_profile'],
      activity_types: ['upi', 'atm'],
      detector_version: 'pfis-statement-detector-3',
    });
    apiMocks.importStatement.mockResolvedValue({
      product_type: 'deposit_account',
      detection: { product_type: 'deposit_account', support_status: 'supported' },
      deposit_account_statement: {
        id: 'deposit-1',
        financial_account_id: 'bank-1',
        period_start: '2026-07-01',
        period_end: '2026-07-05',
        opening_balance: 10000,
        closing_balance: 31510,
        currency: 'INR',
        imported_transaction_count: 4,
        review_count: 1,
        lines: [{ id: 'line-1', review_outcome: 'needs_review' }],
      },
    });
    renderSection();
    const file = new File(['%PDF-1.7 deposit'], 'bank-statement.pdf', {
      type: 'application/pdf',
    });

    fireEvent.change(screen.getByLabelText('Digital PDF'), { target: { files: [file] } });

    expect(await screen.findByText('HDFC bank account')).toBeInTheDocument();
    expect(screen.getByLabelText('Matching financial account')).toHaveValue('bank-1');
    const submit = screen.getByRole('button', { name: 'Import verified statement' });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.submit(submit.closest('form')!);
    await waitFor(() =>
      expect(apiMocks.importStatement).toHaveBeenCalledWith('user-1', 'bank-1', file),
    );
    expect(await screen.findByText(/31,510/)).toBeInTheDocument();
    expect(screen.getByText('Closing balance')).toBeInTheDocument();
  });

  it('keeps recognized but unreviewed layouts read-only', async () => {
    apiMocks.detectStatement.mockResolvedValue({
      institution: 'hdfc',
      product_type: 'deposit_account',
      format_id: 'hdfc-deposit-account-tabular',
      support_status: 'recognized_not_supported',
      confidence: 0.86,
      reason_codes: ['account_statement'],
      activity_types: ['upi'],
      detector_version: 'pfis-statement-detector-3',
    });
    renderSection();
    const file = new File(['%PDF-1.7 unknown layout'], 'unreviewed.pdf', {
      type: 'application/pdf',
    });

    fireEvent.change(screen.getByLabelText('Digital PDF'), { target: { files: [file] } });

    expect(await screen.findByText(/exact layout is not write-enabled/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import verified statement' })).toBeDisabled();
    expect(apiMocks.importStatement).not.toHaveBeenCalled();
  });

  it('identifies an unrecognized issuer without enabling persistence', async () => {
    apiMocks.detectStatement.mockResolvedValue({
      institution: null,
      product_type: 'deposit_account',
      format_id: 'generic-deposit-account-candidate',
      support_status: 'recognized_not_supported',
      confidence: 0.72,
      reason_codes: ['generic_deposit_account_signature'],
      activity_types: ['upi', 'debit_card'],
      detector_version: 'pfis-statement-detector-3',
    });
    renderSection();
    const file = new File(['%PDF-1.7 other bank'], 'other-bank.pdf', {
      type: 'application/pdf',
    });

    fireEvent.change(screen.getByLabelText('Digital PDF'), { target: { files: [file] } });

    expect((await screen.findAllByText(/Unidentified issuer bank account/)).length).toBeGreaterThan(
      0,
    );
    expect(screen.getByRole('button', { name: 'Import verified statement' })).toBeDisabled();
    expect(screen.getByLabelText('Matching financial account')).toBeDisabled();
    expect(apiMocks.importStatement).not.toHaveBeenCalled();
  });

  it('requires an explicit approval before using a masked account-link rule', async () => {
    apiMocks.createAccountLinkRule.mockResolvedValue({
      id: 'rule-1',
      user_id: 'user-1',
      financial_account_id: 'card-1',
      evidence_kind: 'masked_suffix',
      evidence_value: '9911',
      currency: 'INR',
      is_active: true,
      repaired_transaction_count: 2,
      created_at: '2026-07-28T00:00:00Z',
    });
    renderSection();

    fireEvent.click(screen.getByRole('button', { name: 'Approve suffix ••••9911' }));
    await waitFor(() =>
      expect(apiMocks.createAccountLinkRule).toHaveBeenCalledWith('user-1', {
        financial_account_id: 'card-1',
        evidence_kind: 'masked_suffix',
        evidence_value: '9911',
        currency: 'INR',
      }),
    );
    expect(
      await screen.findByText('Rule approved. 2 historical transactions repaired.'),
    ).toBeInTheDocument();
  });
});
