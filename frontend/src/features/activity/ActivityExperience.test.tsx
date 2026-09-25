import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ActivityExperience } from './ActivityExperience';

const dashboardState = vi.hoisted(() => ({
  activeSection: 'transactions',
  scrollTo: vi.fn(),
}));

const queryMocks = vi.hoisted(() => ({
  useAccounts: vi.fn(),
  useCashPocketBalance: vi.fn(),
  useTransactions: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1', currency: 'INR' } }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => dashboardState,
}));

vi.mock('@/lib/lazyWithRetry', () => ({
  lazyWithRetry: () => () => <div data-testid="lazy-activity-view" />,
}));

vi.mock('@/features/workspace/queries', () => queryMocks);

describe('ActivityExperience cash pocket summary', () => {
  beforeEach(() => {
    dashboardState.activeSection = 'transactions';
    dashboardState.scrollTo.mockClear();
    queryMocks.useTransactions.mockReturnValue({ data: [], isLoading: false });
    queryMocks.useAccounts.mockReturnValue({
      data: [
        {
          id: 'cash-1',
          account_type: 'cash',
          institution_name: 'Daily cash',
          is_active: true,
        },
      ],
    });
    queryMocks.useCashPocketBalance.mockReturnValue({
      isLoading: false,
      data: {
        account_id: 'cash-1',
        user_id: 'user-1',
        currency: 'INR',
        transfers_in: 2000,
        cash_spend: 650,
        balance: 1350,
        as_of: '2026-09-25',
      },
    });
  });

  it('shows server-computed cash balance and the ATM transfer explanation', () => {
    render(<ActivityExperience />);

    expect(queryMocks.useCashPocketBalance).toHaveBeenCalledWith('cash-1');
    expect(screen.getByText('Cash in hand')).toBeInTheDocument();
    expect(screen.getByText('₹1,350')).toBeInTheDocument();
    expect(screen.getByText('₹2,000')).toBeInTheDocument();
    expect(screen.getByText('₹650')).toBeInTheDocument();
    expect(
      screen.getByText(/ATM withdrawals are transfers into this pocket, not spend/i),
    ).toBeInTheDocument();
  });
});
