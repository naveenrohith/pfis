import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Transaction } from '@/lib/types';
import { TransactionsSection } from './TransactionsSection';

const dashboardState = vi.hoisted(() => ({
  categoryDrill: null as null | { categoryId: string; label: string },
  setCategoryDrill: vi.fn(),
  explorerSearch: '',
  setExplorerSearch: vi.fn((value: string) => {
    dashboardState.explorerSearch = value;
  }),
  focusReview: vi.fn(),
  setQuickAddOpen: vi.fn(),
}));

const queryMocks = vi.hoisted(() => ({
  useTransactions: vi.fn(),
}));

const ledgerTransaction: Transaction = {
  id: 'txn-1',
  amount: 750,
  currency: 'INR',
  transaction_type: 'debit',
  payment_method: 'other',
  transaction_date: '2026-09-24',
  merchant_normalized: 'Corner Store',
  confidence_score: 0.9,
  reviewed_flag: true,
  note: 'cash receipt kept',
  tags: ['cash', 'errand'],
};

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1', currency: 'INR' } }),
}));

vi.mock('@/features/workspace/WorkspaceContext', () => ({
  useWorkspace: () => ({ month: 9, year: 2026 }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => dashboardState,
}));

vi.mock('@/features/workspace/SyncContext', () => ({
  useSync: () => ({ running: false, runSync: vi.fn() }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    csvUrl: () => '/api/reports/export/csv?user_id=user-1',
    reportUrl: () => '/api/reports/monthly?user_id=user-1',
  },
}));

vi.mock('@/features/workspace/queries', () => queryMocks);

describe('TransactionsSection unified ledger filters', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/dashboard#transactions');
    dashboardState.categoryDrill = null;
    dashboardState.explorerSearch = '';
    dashboardState.setCategoryDrill.mockClear();
    dashboardState.setExplorerSearch.mockClear();
    dashboardState.focusReview.mockClear();
    dashboardState.setQuickAddOpen.mockClear();
    const queryResult = { data: [ledgerTransaction], isLoading: false };
    queryMocks.useTransactions.mockReset();
    queryMocks.useTransactions.mockImplementation(() => queryResult);
  });

  it('hydrates note and repeated tag filters from the URL and preserves the section hash', async () => {
    window.history.replaceState(null, '', '/dashboard?type=debit&note=receipt&tag=cash#transactions');

    render(<TransactionsSection embedded />);

    expect(queryMocks.useTransactions).toHaveBeenCalledWith({ note: 'receipt', tags: ['cash'] });
    expect(screen.getByLabelText('Search transaction notes')).toHaveValue('receipt');
    expect(screen.getByText('Tag: cash')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('1 transaction shown.');
    expect(window.location.hash).toBe('#transactions');

    await userEvent.click(screen.getByRole('button', { name: 'Clear all' }));

    await waitFor(() => expect(window.location.search).toBe(''));
    expect(window.location.hash).toBe('#transactions');
  });
});
