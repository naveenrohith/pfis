import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { InboxSection } from './InboxSection';

const mocks = vi.hoisted(() => ({
  autoSync: vi.fn(),
  emails: vi.fn(),
  syncStatus: vi.fn(),
  runSync: vi.fn(),
  scrollTo: vi.fn(),
  disconnectGmail: vi.fn(),
  notify: vi.fn(),
}));

vi.mock('@/features/workspace/queries', () => ({
  queryKeys: {
    autoSyncStatus: (userId: string) => ['autoSyncStatus', userId],
  },
  useAutoSyncStatus: mocks.autoSync,
  useEmails: mocks.emails,
  useSyncStatus: mocks.syncStatus,
}));

vi.mock('@/features/workspace/SyncContext', () => ({
  useSync: () => ({
    running: false,
    liveConnected: true,
    runSync: mocks.runSync,
    gmailConnectUrl: '/api/auth/gmail/connect?user_id=user-123',
  }),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: {
      id: 'user-123',
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

describe('InboxSection Gmail connection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.autoSync.mockReturnValue({ data: null, isLoading: false, isError: false });
    mocks.emails.mockReturnValue({
      data: { all_total: 0, processed_total: 0, unprocessed_total: 0, emails: [] },
      isLoading: false,
    });
    mocks.syncStatus.mockReturnValue({ data: { latest_status: null, runs: [] } });
    window.history.replaceState({}, '', '/dashboard');
  });

  it('shows a scoped connect action when Gmail is disconnected', () => {
    renderInbox();

    const links = screen.getAllByRole('link', { name: 'Connect Gmail' });
    expect(links.length).toBeGreaterThan(0);
    expect(links[0]).toHaveAttribute('href', '/api/auth/gmail/connect?user_id=user-123');
    expect(screen.getByText('Connect Gmail to start syncing')).toBeInTheDocument();
  });

  it('shows the reauthorization state without treating it as disconnected', () => {
    mocks.autoSync.mockReturnValue({
      data: {
        gmail_account_id: 'gmail-1',
        connection_status: 'reauthorization_required',
        enabled: true,
        interval_seconds: 300,
        status: 'paused',
        error: 'Gmail authorization is invalid or revoked',
      },
      isLoading: false,
      isError: false,
    });

    renderInbox();

    expect(screen.getByText('Reconnect needed')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Reconnect Gmail' })[0]).toHaveAttribute(
      'href',
      '/api/auth/gmail/connect?user_id=user-123',
    );
    expect(screen.queryByText('Connect Gmail to start syncing')).not.toBeInTheDocument();
  });

  it('renders the callback notice and removes the flash query parameters', () => {
    window.history.replaceState({}, '', '/dashboard?gmail_auth=success');

    renderInbox();

    expect(screen.getByRole('status')).toHaveTextContent(
      'Gmail is connected. Your inbox is ready to sync.',
    );
    expect(window.location.search).toBe('');
  });

  it('confirms disconnect and explains which evidence remains', async () => {
    const user = userEvent.setup();
    mocks.autoSync.mockReturnValue({
      data: {
        gmail_account_id: 'gmail-1',
        connection_status: 'connected',
        enabled: true,
        interval_seconds: 300,
        status: 'idle',
        error: null,
      },
      isLoading: false,
      isError: false,
    });
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

    await waitFor(() => expect(mocks.disconnectGmail).toHaveBeenCalledWith('user-123'));
    expect(mocks.notify).toHaveBeenCalledWith(
      'Gmail disconnected and provider access revoked',
      'success',
    );
  });
});
