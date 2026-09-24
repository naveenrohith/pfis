import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useInsights } from '@/features/workspace/queries';
import { InsightsSection } from './InsightsSection';

const longMerchant = 'DAD CAR Loan Adjustment With A Very Long Merchant Descriptor';
const longRecurringMerchant = 'Recurring Marketplace Subscription With A Very Long Name';

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { currency: 'INR' } }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ setCategoryDrill: vi.fn(), scrollTo: vi.fn() }),
}));

vi.mock('@/features/workspace/WorkspaceContext', () => ({
  useWorkspace: () => ({ month: 8, year: 2026 }),
}));

vi.mock('@/features/workspace/queries', () => ({
  useAdjudicateAnomaly: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useAdjudicateAnomalySample: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useAnomalySamples: () => ({ isLoading: false, data: [] }),
  useInsights: vi.fn(() => ({
    isLoading: false,
    data: {
      daily_trend: [
        { date: '10 Aug', day: 10, total: 5000, count: 2 },
        { date: '11 Aug', day: 11, total: 12000, count: 4 },
      ],
      insights: [],
      recurring_payments: [
        {
          merchant: longRecurringMerchant,
          avg_amount: 19750,
          monthly_equivalent: 19750,
          occurrences: 4,
          status: 'mature',
          cadence: 'monthly',
          confidence: 0.94,
        },
      ],
    },
  })),
  useSummary: () => ({
    isLoading: false,
    data: {
      category_breakdown: [
        {
          name: 'An unusually long category name for a narrow panel',
          total: 12000,
          count: 4,
        },
      ],
      top_merchants: [{ name: longMerchant, total: 25000, count: 1 }],
    },
  }),
  useMerchants: () => ({
    isLoading: false,
    data: [
      {
        merchant_key: 'long-merchant',
        name: longMerchant,
        total_spend: 25000,
        transaction_count: 1,
        avg_spend: 25000,
        recurrence_likelihood: 0,
        recurrence_status: 'inactive',
        recurrence_confidence: 0,
        data_sufficiency: 'low',
      },
    ],
  }),
  useWorkspaceSnapshot: () => ({
    isLoading: false,
    data: {
      month_comparison: {
        spend: 63804,
        spend_change_pct: 74.2,
        income: 43200,
        income_change_pct: null,
        category_deltas: [
          {
            category: 'An unusually long category name for a narrow panel',
            current: 12000,
            change_pct: 65.8,
          },
        ],
      },
    },
  }),
}));

describe('Insights investigation layout', () => {
  it('pairs the daily trend with one ranked, ledger-linked driver list', () => {
    render(<InsightsSection embedded />);

    expect(screen.getByText('MONTHLY INVESTIGATION')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Largest measured drivers' })).toBeInTheDocument();
    const leadingDriver = screen.getByRole('button', {
      name: /An unusually long category name for a narrow panel/,
    });
    expect(leadingDriver).toHaveTextContent('4 entries');
    expect(leadingDriver).toHaveTextContent('+65.8% vs prior month');
    expect(screen.queryByRole('heading', { name: 'Ranked drivers' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Observed spend by day' })).toBeInTheDocument();
    expect(screen.getByText(/Daily debit spend · INR · 10 Aug 2026 to 11 Aug 2026/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('View chart data'));
    expect(
      screen.getByRole('table', { name: 'Daily observed debit spend and entry count' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Merchant concentration')).toBeInTheDocument();
    expect(screen.getByText(longMerchant)).toHaveClass('truncate');
    expect(screen.getByText(longRecurringMerchant)).toHaveClass('truncate');
  });

  it('renders an honest empty state when the period only contains zero-filled days', () => {
    vi.mocked(useInsights).mockReturnValueOnce({
      isLoading: false,
      data: {
        daily_trend: [{ date: '11 Aug', day: 11, total: 0, count: 0 }],
        insights: [],
        recurring_payments: [],
        anomalies: [],
      },
    } as unknown as ReturnType<typeof useInsights>);

    render(<InsightsSection embedded />);

    expect(screen.getByText('No debit activity this month')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Observed spend by day' })).not.toBeInTheDocument();
  });
});
