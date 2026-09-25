import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useInsights } from '@/features/workspace/queries';
import { useMonthlySnapshot } from './monthlySnapshotQueries';
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

vi.mock('./monthlySnapshotQueries', () => ({
  useMonthlySnapshot: vi.fn(() => ({
    isLoading: false,
    data: {
      month: 8,
      year: 2026,
      month_label: '2026-08',
      income: 43200,
      spend: 63804,
      net: -20604,
      transaction_count: 7,
      top_categories: [
        {
          category_id: 'category-food',
          name: 'An unusually long category name for a narrow panel',
          total: 12000,
          count: 4,
        },
      ],
      top_merchants: [{ name: longMerchant, total: 25000, count: 1 }],
      budget_status: [
        {
          category: 'Dining',
          limit: 10000,
          actual: 12000,
          usage_pct: 120,
          status: 'over_budget',
        },
      ],
      recurring_changes: [
        {
          merchant: longRecurringMerchant,
          status: 'mature',
          cadence: 'monthly',
          monthly_equivalent: 19750,
          confidence: 0.94,
          data_sufficiency: 'high',
        },
      ],
      notable_anomalies: [
        {
          id: 'anomaly-food',
          kind: 'category',
          label: 'Dining',
          current_amount: 12000,
          baseline_amount: 7000,
          delta_amount: 5000,
          delta_pct: 71.4,
          confidence: 0.9,
          data_sufficiency: 'high',
        },
      ],
      coverage: {
        incomplete_month: true,
        latest_transaction_date: '2026-08-11',
        data_freshness_days: 2,
        latest_sync_status: 'success',
        last_synced_at: '2026-08-11T08:00:00Z',
      },
    },
  })),
}));

describe('Insights investigation layout', () => {
  it('pairs the daily trend with one ranked, ledger-linked driver list', () => {
    render(<InsightsSection embedded />);

    expect(screen.getByRole('heading', { name: /negative net movement/i })).toBeInTheDocument();
    expect(screen.getByText('Incomplete month')).toBeInTheDocument();
    expect(screen.getByText(/latest ledger activity/)).toBeInTheDocument();
    expect(screen.getByText(/Top categories/)).toBeInTheDocument();
    expect(screen.getByText(/Budget status/)).toBeInTheDocument();
    expect(screen.getByText(/Recurring changes/)).toBeInTheDocument();
    expect(screen.getByText(/Anomalies/)).toBeInTheDocument();
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
    expect(screen.getAllByText(longMerchant).some((node) => node.classList.contains('truncate'))).toBe(
      true,
    );
    expect(
      screen.getAllByText(longRecurringMerchant).some((node) => node.classList.contains('truncate')),
    ).toBe(true);
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
    vi.mocked(useMonthlySnapshot).mockReturnValueOnce({
      isLoading: false,
      data: {
        month: 8,
        year: 2026,
        month_label: '2026-08',
        income: 0,
        spend: 0,
        net: 0,
        transaction_count: 0,
        top_categories: [],
        top_merchants: [],
        budget_status: [],
        recurring_changes: [],
        notable_anomalies: [],
        coverage: { incomplete_month: true },
      },
    } as unknown as ReturnType<typeof useMonthlySnapshot>);

    render(<InsightsSection embedded />);

    expect(screen.getByText('No debit activity this month')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Observed spend by day' })).not.toBeInTheDocument();
  });
});
