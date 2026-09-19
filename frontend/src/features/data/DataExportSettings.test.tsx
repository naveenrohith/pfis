import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DataExportSettings } from './DataExportSettings';

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  portableExport: vi.fn(),
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
  }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify: mocks.notify }),
}));

vi.mock('@/lib/api', () => ({
  api: { portableExport: mocks.portableExport },
}));

function renderExportSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <DataExportSettings />
    </QueryClientProvider>,
  );
}

describe('DataExportSettings', () => {
  beforeEach(() => {
    mocks.notify.mockReset();
    mocks.portableExport.mockReset();
    mocks.portableExport.mockResolvedValue({
      blob: new Blob(['portable-data'], { type: 'application/zip' }),
      filename: 'pfis-portable-export-20260731.zip',
    });
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:portable-export'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  it('explains the manifest, sensitive contents, and credential exclusions', () => {
    renderExportSettings();

    expect(screen.getByText('Schema version 6')).toBeInTheDocument();
    expect(screen.getByText('Included record groups')).toBeInTheDocument();
    expect(
      screen.getByText('Forecast snapshots and their later measured outcomes'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Recommendation decisions, relevance feedback, and outcome checks'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Temporal decisions and planning history used for historical forecasts'),
    ).toBeInTheDocument();
    expect(screen.getByText('Always excluded')).toBeInTheDocument();
    expect(screen.getByText(/Gmail access and refresh credentials/)).toBeInTheDocument();
    expect(screen.getByText(/may contain sensitive financial details/)).toBeInTheDocument();
  });

  it('downloads the authenticated user portable copy', async () => {
    renderExportSettings();

    fireEvent.click(screen.getByRole('button', { name: 'Download portable copy' }));

    await waitFor(() => expect(mocks.portableExport).toHaveBeenCalledWith('user-1'));
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:portable-export'));
    expect(mocks.notify).toHaveBeenCalledWith('Portable copy downloaded', 'success');
  });
});
