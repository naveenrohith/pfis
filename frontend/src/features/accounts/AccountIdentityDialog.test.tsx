import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/ui/Toast';
import { AccountIdentityDialog } from './AccountIdentityDialog';

const { updateAccount } = vi.hoisted(() => ({ updateAccount: vi.fn() }));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', name: 'Test', email: 'test@example.com', currency: 'INR' },
  }),
}));

vi.mock('@/lib/api', () => ({
  api: { updateAccount },
}));

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AccountIdentityDialog
          account={{
            id: 'account-1',
            user_id: 'user-1',
            institution_name: 'Unknown',
            account_type: 'unknown',
            balance_kind: 'asset',
            masked_number: '****9913',
            currency: 'INR',
            is_active: true,
            latest_balance: null,
            balance_as_of: null,
            created_at: '2026-07-01T00:00:00Z',
          }}
          onClose={vi.fn()}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe('AccountIdentityDialog', () => {
  it('requires an explicit product and derives accounting direction from it', async () => {
    updateAccount.mockResolvedValue({
      id: 'account-1',
      account_type: 'credit_card',
      balance_kind: 'liability',
    });
    renderDialog();

    fireEvent.change(screen.getByLabelText('Institution or account label'), {
      target: { value: 'HDFC card' },
    });
    fireEvent.change(screen.getByLabelText('Financial product'), {
      target: { value: 'credit_card' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm identity' }));

    await waitFor(() =>
      expect(updateAccount).toHaveBeenCalledWith('user-1', 'account-1', {
        institution_name: 'HDFC card',
        account_type: 'credit_card',
        balance_kind: 'liability',
        masked_number: '****9913',
      }),
    );
  });
});
