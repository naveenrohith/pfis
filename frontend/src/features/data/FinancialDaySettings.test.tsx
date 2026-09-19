import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FinancialDaySettings } from './FinancialDaySettings';

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  updateProfile: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 'user-1',
      name: 'Test user',
      email: 'test@example.com',
      currency: 'INR',
      timezone: 'Asia/Kolkata',
    },
    updateProfile: mocks.updateProfile,
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
      <FinancialDaySettings />
    </QueryClientProvider>,
  );
}

describe('FinancialDaySettings', () => {
  beforeEach(() => {
    mocks.notify.mockReset();
    mocks.updateProfile.mockReset();
    mocks.updateProfile.mockResolvedValue({
      id: 'user-1',
      name: 'Test user',
      email: 'test@example.com',
      currency: 'INR',
      timezone: 'America/New_York',
    });
  });

  it('saves a valid changed financial timezone', async () => {
    renderSettings();
    const input = screen.getByLabelText('IANA timezone');
    const save = screen.getByRole('button', { name: 'Save financial day' });
    expect(save).toBeDisabled();

    fireEvent.change(input, { target: { value: 'America/New_York' } });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() =>
      expect(mocks.updateProfile).toHaveBeenCalledWith({
        timezone: 'America/New_York',
      }),
    );
    expect(mocks.notify).toHaveBeenCalledWith('Financial day saved', 'success');
  });

  it('keeps an invalid timezone inline and unsaveable', () => {
    renderSettings();
    fireEvent.change(screen.getByLabelText('IANA timezone'), {
      target: { value: 'Mars/Olympus_Mons' },
    });

    expect(screen.getByRole('alert')).toHaveTextContent('Enter a valid timezone');
    expect(screen.getByRole('button', { name: 'Save financial day' })).toBeDisabled();
  });
});
