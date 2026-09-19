import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { InboxSection } from './InboxSection';

const mocks = vi.hoisted(() => ({
  autoSync: vi.fn(),
  emails: vi.fn(),
  syncStatus: vi.fn(),
}));

vi.mock('@/features/workspace/queries', () => ({
  useAutoSyncStatus: mocks.autoSync,
  useEmails: mocks.emails,
  useSyncStatus: mocks.syncStatus,
}));

vi.mock('@/features/workspace/SyncContext', () => ({
  useSync: () => ({ running: false, liveConnected: true, retrySync: vi.fn() }),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-123' } }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ scrollTo: vi.fn() }),
}));

function renderInbox() {
  return render(<InboxSection embedded />);
}

describe('InboxSection Gmail connection', () => {
  beforeEach(() => {
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
    expect(screen.getByRole('link', { name: 'Reconnect Gmail' })).toHaveAttribute(
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
});
