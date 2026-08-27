import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RawEmailRetentionSettings } from './RawEmailRetentionSettings';

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
      raw_email_retention_days: 365,
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
      <RawEmailRetentionSettings />
    </QueryClientProvider>,
  );
}

async function choose(label: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole('combobox', { name: 'Keep processed source content' }));
  await user.click(await screen.findByRole('option', { name: label }));
  return user;
}

describe('RawEmailRetentionSettings', () => {
  beforeEach(() => {
    mocks.notify.mockReset();
    mocks.updateProfile.mockReset();
    mocks.updateProfile.mockResolvedValue({ raw_email_retention_days: 90 });
  });

  it('explains redaction boundaries and keeps the unchanged policy disabled', () => {
    renderSettings();

    expect(screen.getByText(/Unresolved parser failures keep their source content/)).toBeVisible();
    expect(screen.getByText(/Message ID, dates, parser evidence/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save retention policy' })).toBeDisabled();
  });

  it('confirms an irreversible shorter policy before saving it', async () => {
    renderSettings();
    const user = await choose('90 days');

    await user.click(screen.getByRole('button', { name: 'Save retention policy' }));
    expect(screen.getByRole('dialog', { name: 'Shorten source retention?' })).toBeVisible();
    expect(mocks.updateProfile).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Apply shorter policy' }));

    await waitFor(() =>
      expect(mocks.updateProfile).toHaveBeenCalledWith({ raw_email_retention_days: 90 }),
    );
    expect(mocks.notify).toHaveBeenCalledWith('Source retention policy saved', 'success');
  });

  it('saves a non-destructive longer policy without confirmation', async () => {
    renderSettings();
    const user = await choose('Keep until I delete it');

    await user.click(screen.getByRole('button', { name: 'Save retention policy' }));

    await waitFor(() =>
      expect(mocks.updateProfile).toHaveBeenCalledWith({ raw_email_retention_days: null }),
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
