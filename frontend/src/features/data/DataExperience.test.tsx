import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DataExperience } from './DataExperience';

const mocks = vi.hoisted(() => ({
  autoSync: vi.fn(),
  runSync: vi.fn(),
  scrollTo: vi.fn(),
  setCustomizeOpen: vi.fn(),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({
    activeSection: 'inbox',
    scrollTo: mocks.scrollTo,
    setCustomizeOpen: mocks.setCustomizeOpen,
  }),
}));

vi.mock('@/features/workspace/queries', () => ({
  useAutoSyncStatus: mocks.autoSync,
  useSyncStatus: () => ({ data: { latest_status: null } }),
}));

vi.mock('@/features/workspace/SyncContext', () => ({
  useSync: () => ({
    running: false,
    updateChannelLabel: 'Automatic updates',
    updateChannelVariant: 'default',
    runSync: mocks.runSync,
    gmailConnectUrl: null,
  }),
}));

vi.mock('@/features/inbox/InboxSection', () => ({
  InboxSection: () => <div>Connections view</div>,
}));

describe('DataExperience connection action', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.autoSync.mockReturnValue({
      data: null,
      isSuccess: true,
      isLoading: false,
      isError: false,
    });
  });

  it('routes a disconnected workspace to Connections when no Gmail URL is available', async () => {
    render(<DataExperience />);

    const action = await screen.findByRole('button', { name: 'Open Connections' });
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();

    fireEvent.click(action);

    expect(mocks.scrollTo).toHaveBeenCalledWith('inbox');
  });

  it('keeps Sync now during loading and unrelated auto-sync errors', async () => {
    mocks.autoSync.mockReturnValue({
      data: null,
      isSuccess: false,
      isLoading: true,
      isError: false,
    });
    const { rerender } = render(<DataExperience />);
    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeInTheDocument();

    mocks.autoSync.mockReturnValue({
      data: undefined,
      isSuccess: false,
      isLoading: false,
      isError: true,
    });
    rerender(<DataExperience />);

    expect(screen.getByRole('button', { name: 'Sync now' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open Connections' })).not.toBeInTheDocument();
  });
});
