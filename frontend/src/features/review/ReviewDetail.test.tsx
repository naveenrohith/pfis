import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Transaction } from '@/lib/types';
import { ReviewDetail } from './ReviewDetail';

const { linkAtmWithdrawalToCash, replaceTransactionSplits, transactionSplits, notify } = vi.hoisted(
  () => ({
    linkAtmWithdrawalToCash: vi.fn(),
    replaceTransactionSplits: vi.fn(),
    transactionSplits: vi.fn(),
    notify: vi.fn(),
  }),
);

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', name: 'Test', email: 'test@example.com', currency: 'INR' },
  }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ scrollTo: vi.fn() }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    linkAtmWithdrawalToCash,
    transactionSplits,
    replaceTransactionSplits,
    updateTransaction: vi.fn(),
  },
}));

const transaction: Transaction = {
  id: 'transaction-1',
  amount: 1000,
  currency: 'INR',
  transaction_type: 'debit',
  payment_method: 'other',
  transaction_status: 'completed',
  transaction_date: '2026-07-27',
  merchant_raw: 'Household shop',
  merchant_normalized: 'Household shop',
  confidence_score: 1,
  reviewed_flag: true,
  tags: [],
};

describe('ReviewDetail split allocation', () => {
  it('submits allocations without creating ledger events', async () => {
    transactionSplits.mockResolvedValue([
      {
        id: 'split-1',
        transaction_id: 'transaction-1',
        user_id: 'user-1',
        label: 'Groceries',
        amount: 650,
        category_id: null,
        created_at: '2026-07-27T00:00:00Z',
      },
      {
        id: 'split-2',
        transaction_id: 'transaction-1',
        user_id: 'user-1',
        label: 'Household',
        amount: 350,
        category_id: null,
        created_at: '2026-07-27T00:00:00Z',
      },
    ]);
    replaceTransactionSplits.mockResolvedValue([]);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ReviewDetail
          transaction={transaction}
          categories={[]}
          accounts={[]}
          currency="INR"
          onSaved={vi.fn()}
          onNext={vi.fn()}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByLabelText('Label 1')).toHaveValue('Groceries');
      expect(screen.getAllByLabelText('Amount')[0]).toHaveValue(650);
      expect(screen.getByRole('button', { name: 'Save splits' })).toBeEnabled();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Save splits' }));

    await waitFor(() =>
      expect(replaceTransactionSplits).toHaveBeenCalledWith('user-1', 'transaction-1', [
        { label: 'Groceries', amount: 650, category_id: null },
        { label: 'Household', amount: 350, category_id: null },
      ]),
    );
    expect(notify).toHaveBeenCalledWith('Split allocations saved', 'success');
  });

  it('converts an observed ATM debit into a cash-pocket transfer explicitly', async () => {
    transactionSplits.mockResolvedValue([]);
    linkAtmWithdrawalToCash.mockResolvedValue({
      transfer_group_id: 'transfer-1',
      debit_transaction_id: 'transaction-1',
      credit_transaction_id: 'transaction-2',
      amount: 1000,
      currency: 'INR',
      transaction_date: '2026-07-27',
      payment_rail: 'atm',
    });
    const onSaved = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ReviewDetail
          transaction={{
            ...transaction,
            payment_method: 'debit_card',
            payment_rail: 'atm',
            financial_account_id: 'bank-1',
            is_accounting_adjustment: true,
            ledger_subtype: 'unlinked_atm_withdrawal',
          }}
          categories={[]}
          accounts={[
            {
              id: 'bank-1',
              user_id: 'user-1',
              institution_name: 'HDFC Bank',
              account_type: 'bank',
              balance_kind: 'asset',
              masked_number: '••••4017',
              currency: 'INR',
              is_active: true,
              created_at: '2026-07-01T00:00:00Z',
            },
            {
              id: 'cash-1',
              user_id: 'user-1',
              institution_name: 'Wallet cash',
              account_type: 'cash',
              balance_kind: 'asset',
              masked_number: 'CASH',
              currency: 'INR',
              is_active: true,
              created_at: '2026-07-01T00:00:00Z',
            },
          ]}
          currency="INR"
          onSaved={onSaved}
          onNext={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Finish the ATM cash movement')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Cash pocket'), 'cash-1');
    await userEvent.click(screen.getByRole('button', { name: 'Move into cash pocket' }));

    await waitFor(() =>
      expect(linkAtmWithdrawalToCash).toHaveBeenCalledWith('user-1', 'transaction-1', 'cash-1'),
    );
    expect(onSaved).toHaveBeenCalled();
  });
});
