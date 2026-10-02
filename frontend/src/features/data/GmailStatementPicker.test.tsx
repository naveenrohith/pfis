import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GmailStatementPicker } from './GmailStatementPicker';

const mocks = vi.hoisted(() => ({
  candidates: vi.fn(),
  detect: vi.fn(),
  import: vi.fn(),
  connection: vi.fn(),
}));

vi.mock('@/features/workspace/queries', () => ({
  useAutoSyncStatus: mocks.connection,
}));
vi.mock('@/lib/api', () => ({
  api: {
    gmailStatementCandidates: mocks.candidates,
    detectGmailStatement: mocks.detect,
    importGmailStatement: mocks.import,
    gmailConnectUrl: (userId: string) => `/connect?user_id=${userId}`,
  },
  ApiError: class ApiError extends Error {},
}));

const account = {
  id: 'card-1',
  institution_name: 'HDFC Bank',
  account_type: 'credit_card',
  balance_kind: 'liability',
  masked_number: '••••9911',
  currency: 'INR',
  is_active: true,
  identity_status: 'confirmed',
} as never;
const candidate = {
  source_ref: 'opaque-1',
  sender: 'alerts@hdfc.com',
  subject: 'Statement',
  filename: 'statement.pdf',
  size_bytes: 1024,
  received_at: '2026-09-01T00:00:00Z',
};

function renderPicker() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const element = () => (
    <QueryClientProvider client={client}>
      <GmailStatementPicker userId="user-1" accounts={[account]} onImported={vi.fn()} />
    </QueryClientProvider>
  );
  const view = render(element());
  return { refresh: () => view.rerender(element()) };
}

describe('GmailStatementPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.connection.mockReturnValue({ isSuccess: true, data: { connection_status: 'connected' } });
    mocks.candidates.mockResolvedValue({
      candidates: [candidate],
      next_cursor: 'next',
      coverage_complete: true,
      message_failures: 0,
      truncated: false,
    });
    mocks.detect.mockResolvedValue({
      status: 'password_required',
      detection: null,
      document_fingerprint: null,
    });
  });

  it('resets a pending search on disconnect and ignores its response after reconnect', async () => {
    let release!: (value: unknown) => void;
    mocks.candidates.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const view = renderPicker();
    fireEvent.click(screen.getByRole('button', { name: 'Search Gmail' }));
    expect(screen.getByRole('button', { name: 'Searching…' })).toBeDisabled();
    mocks.connection.mockReturnValue({ isSuccess: true, data: null });
    view.refresh();
    expect(screen.getByText('Gmail is not connected.')).toBeInTheDocument();
    mocks.connection.mockReturnValue({ isSuccess: true, data: { connection_status: 'connected' } });
    view.refresh();
    expect(screen.getByRole('button', { name: 'Search Gmail' })).toBeEnabled();
    await act(async () =>
      release({
        candidates: [candidate],
        next_cursor: null,
        coverage_complete: true,
        message_failures: 0,
        truncated: false,
      }),
    );
    expect(screen.queryByRole('button', { name: /statement\.pdf/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Search Gmail' }));
    expect(await screen.findByRole('button', { name: /statement\.pdf/i })).toBeInTheDocument();
  });

  it('keeps password local, retries detection, and prevents duplicate import submits', async () => {
    renderPicker();
    fireEvent.click(screen.getByRole('button', { name: 'Search Gmail' }));
    fireEvent.click(await screen.findByRole('button', { name: /statement\.pdf/i }));
    expect(await screen.findByLabelText('PDF password')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('PDF password'), { target: { value: 'secret' } });
    mocks.detect.mockResolvedValueOnce({
      status: 'detected',
      detection: { institution: 'hdfc', product_type: 'credit_card', support_status: 'supported' },
      document_fingerprint: 'fp-1',
    });
    fireEvent.click(screen.getByRole('button', { name: 'Unlock and detect' }));
    await waitFor(() =>
      expect(mocks.detect).toHaveBeenLastCalledWith('user-1', 'opaque-1', 'secret'),
    );
    expect(await screen.findByLabelText('Matching financial account')).toHaveValue('card-1');
    let release!: (value: unknown) => void;
    mocks.import.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    const submit = screen.getByRole('button', { name: 'Import verified statement' });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(mocks.import).toHaveBeenCalledOnce();
    expect(mocks.import).toHaveBeenCalledWith(
      'user-1',
      expect.objectContaining({ password: 'secret' }),
    );
    release({
      product_type: 'credit_card',
      detection: { product_type: 'credit_card', support_status: 'supported' },
    });
  });

  it('pages older candidates and ignores a stale detection response', async () => {
    const second = { ...candidate, source_ref: 'opaque-2', filename: 'older.pdf' };
    mocks.candidates.mockReset();
    mocks.candidates
      .mockResolvedValueOnce({
        candidates: [candidate],
        next_cursor: 'next',
        coverage_complete: false,
        message_failures: 1,
        truncated: true,
      })
      .mockResolvedValueOnce({
        candidates: [second],
        next_cursor: null,
        coverage_complete: true,
        message_failures: 0,
        truncated: false,
      });
    renderPicker();
    fireEvent.click(screen.getByRole('button', { name: 'Search Gmail' }));
    const first = await screen.findByRole('button', { name: /statement\.pdf/i });
    fireEvent.click(screen.getByRole('button', { name: 'Show older candidates' }));
    await waitFor(() =>
      expect(mocks.candidates).toHaveBeenLastCalledWith(
        'user-1',
        expect.objectContaining({ cursor: 'next' }),
      ),
    );
    const slow = new Promise((resolve) =>
      setTimeout(
        () =>
          resolve({
            status: 'detected',
            detection: {
              institution: 'old',
              product_type: 'credit_card',
              support_status: 'supported',
            },
            document_fingerprint: 'old',
          }),
        20,
      ),
    );
    expect(screen.getByText(/Some messages could not be checked/)).toBeInTheDocument();
    mocks.detect.mockReturnValueOnce(slow).mockResolvedValueOnce({
      status: 'detected',
      detection: { institution: 'new', product_type: 'credit_card', support_status: 'supported' },
      document_fingerprint: 'new',
    });
    fireEvent.click(first);
    fireEvent.click(await screen.findByRole('button', { name: /older\.pdf/i }));
    await waitFor(() => expect(screen.getByText(/NEW/)).toBeInTheDocument());
  });
});
