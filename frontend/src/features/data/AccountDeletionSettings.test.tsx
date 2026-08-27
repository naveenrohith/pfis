import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AccountDeletionSettings } from './AccountDeletionSettings';

const mocks = vi.hoisted(() => ({
  deleteAccount: vi.fn(),
  notify: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 'user-1',
      name: 'Test user',
      email: 'test@example.com',
      currency: 'INR',
      timezone: 'Asia/Kolkata',
      raw_email_retention_days: 365,
    },
    deleteAccount: mocks.deleteAccount,
  }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify: mocks.notify }),
}));

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AccountDeletionSettings />
    </QueryClientProvider>,
  );
}

describe('AccountDeletionSettings', () => {
  beforeEach(() => {
    mocks.deleteAccount.mockReset();
    mocks.notify.mockReset();
    mocks.deleteAccount.mockResolvedValue(undefined);
  });

  it('explains shared tombstones and focuses the safe dialog action', async () => {
    const user = userEvent.setup();
    renderSettings();

    expect(screen.getByText(/“Deleted participant” label/)).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Delete my account' }));

    const keep = screen.getByRole('button', { name: 'Keep my account' });
    await waitFor(() => expect(keep).toHaveFocus());
    expect(screen.getByText(/signed in within the last 15 minutes/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Permanently delete account' })).toBeDisabled();
  });

  it('requires the exact account-specific phrase before deleting', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByRole('button', { name: 'Delete my account' }));
    const input = screen.getByLabelText(/Type DELETE test@example.com to continue/);
    const remove = screen.getByRole('button', { name: 'Permanently delete account' });

    await user.type(input, 'DELETE wrong@example.com');
    expect(remove).toBeDisabled();
    await user.clear(input);
    await user.type(input, 'DELETE test@example.com');
    expect(remove).toBeEnabled();
    await user.click(remove);

    await waitFor(() =>
      expect(mocks.deleteAccount).toHaveBeenCalledWith('DELETE test@example.com'),
    );
    expect(mocks.notify).toHaveBeenCalledWith('Your PFIS account was deleted', 'success');
  });

  it('shows the recent-auth recovery instruction inline', async () => {
    mocks.deleteAccount.mockRejectedValue(new Error('Sign in again before deleting your account'));
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByRole('button', { name: 'Delete my account' }));
    await user.type(
      screen.getByLabelText(/Type DELETE test@example.com to continue/),
      'DELETE test@example.com',
    );
    await user.click(screen.getByRole('button', { name: 'Permanently delete account' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Sign in again before deleting your account',
    );
  });
});
