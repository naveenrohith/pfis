import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { InboxSection } from './InboxSection';

const mocks = vi.hoisted(() => ({
  runSync: vi.fn(),
  scrollTo: vi.fn(),
  disconnectGmail: vi.fn(),
  notify: vi.fn(),
  autoSyncStatus: {
    data: {
      gmail_account_id: 'gmail-1',
      enabled: true,
      interval_seconds: 300,
      status: 'paused',
      error: 'Gmail authorization is invalid or revoked',
    },
    isLoading: false,
  },
}));

vi.mock('@/features/workspace/queries', () => ({
  queryKeys: {
    autoSyncStatus: (userId: string) => ['autoSyncStatus', userId],
  },
  useEmails: () => ({
    data: {
      all_total: 0,
      processed_total: 0,
      unprocessed_total: 0,
      emails: [],
    },
    isLoading: false,
  }),
  useSyncStatus: () => ({
    data: { latest_status: 'failed', runs: [] },
  }),
  useAutoSyncStatus: () => mocks.autoSyncStatus,
}));

vi.mock('@/features/workspace/SyncContext', () => ({
  useSync: () => ({
    running: false,
    liveConnected: true,
    runSync: mocks.runSync,
    gmailConnectUrl: '/api/auth/gmail/connect?user_id=user-1',
  }),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 'user-1',
      name: 'Test',
      email: 'test@example.com',
      currency: 'INR',
      timezone: 'Asia/Kolkata',
    },
  }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify: mocks.notify }),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      disconnectGmail: mocks.disconnectGmail,
    },
  };
});

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ scrollTo: mocks.scrollTo }),
}));

function renderInbox() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <InboxSection />
    </QueryClientProvider>,
  );
}

describe('InboxSection Gmail recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('routes a paused authorization state to Gmail reconnect', () => {
    renderInbox();

    expect(screen.getByRole('alert')).toHaveTextContent(
      'After reconnecting, PFIS resumes automatic sync every 5 minutes.',
    );

    expect(screen.getByRole('link', { name: 'Reconnect Gmail' })).toHaveAttribute(
      'href',
      '/api/auth/gmail/connect?user_id=user-1',
    );
    expect(mocks.runSync).not.toHaveBeenCalled();
  });

  it('confirms disconnect and explains which evidence remains', async () => {
    const user = userEvent.setup();
    mocks.disconnectGmail.mockResolvedValue({
      status: 'disconnected',
      provider_revocation: 'revoked',
      retained_raw_email_count: 4,
      derived_records_retained: true,
    });
    renderInbox();

    await user.click(screen.getByRole('button', { name: 'Disconnect Gmail' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(
      'Already synced emails, transactions, and their evidence stay in PFIS.',
    );
    await user.click(within(dialog).getByRole('button', { name: 'Disconnect Gmail' }));

    await waitFor(() => expect(mocks.disconnectGmail).toHaveBeenCalledWith('user-1'));
    expect(mocks.notify).toHaveBeenCalledWith(
      'Gmail disconnected and provider access revoked',
      'success',
    );
  });
});
