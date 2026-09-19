import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QuickAddDialog } from './QuickAddDialog';

const { createTransfer, notify } = vi.hoisted(() => ({
  createTransfer: vi.fn(),
  notify: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', name: 'Test', email: 'test@example.com', currency: 'INR' },
  }),
}));

vi.mock('@/features/workspace/WorkspaceContext', () => ({
  useWorkspace: () => ({ month: 7, year: 2026 }),
}));

vi.mock('@/features/workspace/queries', () => ({
  queryKeys: {
    transactions: (...args: unknown[]) => ['transactions', ...args],
    summary: (...args: unknown[]) => ['summary', ...args],
    workspace: (...args: unknown[]) => ['workspace', ...args],
    guidanceBrief: (...args: unknown[]) => ['guidanceBrief', ...args],
    accounts: (...args: unknown[]) => ['accounts', ...args],
    netWorth: (...args: unknown[]) => ['netWorth', ...args],
  },
  useAccounts: () => ({
    data: [
      {
        id: 'bank-1',
        institution_name: 'Primary Bank',
        account_type: 'bank',
        masked_number: '••••1001',
        is_active: true,
      },
      {
        id: 'cash-1',
        institution_name: 'Daily cash',
        account_type: 'cash',
        masked_number: 'Pocket',
        is_active: true,
      },
    ],
  }),
  useCategories: () => ({ data: [] }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    createTransfer,
    createTransaction: vi.fn(),
  },
}));

describe('QuickAddDialog ATM cash workflow', () => {
  beforeEach(() => {
    createTransfer.mockReset();
    createTransfer.mockResolvedValue({
      transfer_group_id: 'transfer-1',
      debit_transaction_id: 'debit-1',
      credit_transaction_id: 'credit-1',
      amount: 500,
      currency: 'INR',
      transaction_date: '2026-07-27',
      payment_rail: 'atm',
    });
    notify.mockReset();
  });

  it('records an ATM withdrawal as a bank-to-cash transfer', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const onClose = vi.fn();

    render(
      <QueryClientProvider client={queryClient}>
        <QuickAddDialog open onClose={onClose} />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('radio', { name: /ATM cash/i }));
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '500' } });
    fireEvent.change(screen.getByLabelText('Bank account'), { target: { value: 'bank-1' } });
    fireEvent.change(screen.getByLabelText('Cash pocket'), { target: { value: 'cash-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add activity' }));

    await waitFor(() =>
      expect(createTransfer).toHaveBeenCalledWith(
        'user-1',
        expect.objectContaining({
          from_account_id: 'bank-1',
          to_account_id: 'cash-1',
          amount: 500,
          payment_rail: 'atm',
          description: 'ATM cash withdrawal',
        }),
      ),
    );
    expect(notify).toHaveBeenCalledWith('Cash withdrawal recorded', 'success');
    expect(onClose).toHaveBeenCalled();
  });
});
