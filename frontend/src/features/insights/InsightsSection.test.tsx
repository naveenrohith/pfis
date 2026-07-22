import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { InsightsSection } from './InsightsSection';

const longMerchant = 'DAD CAR Loan Adjustment With A Very Long Merchant Descriptor';
const longRecurringMerchant = 'Recurring Marketplace Subscription With A Very Long Name';

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { currency: 'INR' } }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ setCategoryDrill: vi.fn(), scrollTo: vi.fn() }),
}));

vi.mock('@/features/workspace/queries', () => ({
  useInsights: () => ({
    isLoading: false,
    data: {
      daily_trend: [],
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
  }),
  useSummary: () => ({
    isLoading: false,
    data: {
      category_breakdown: [],
      top_merchants: [{ name: longMerchant, total: 25000, count: 1 }],
    },
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
          { category: 'An unusually long category name for a narrow panel', change_pct: 65.8 },
        ],
      },
    },
  }),
}));

describe('Insights summary layout', () => {
  it('keeps summary cards content-height and constrains long ledger rows', () => {
    render(<InsightsSection embedded />);

    const summaryGrid = screen.getByRole('region', { name: 'Monthly insight summaries' });
    expect(summaryGrid).toHaveClass('items-start');

    const merchantRow = screen.getByText(longMerchant).parentElement;
    expect(merchantRow).toHaveClass('grid-cols-[auto_minmax(0,1fr)_auto]', 'min-w-0');
    expect(screen.getByText(longMerchant)).toHaveClass('truncate');

    const recurringRow = screen.getByText(longRecurringMerchant).closest('.dashboard-row');
    expect(recurringRow).toHaveClass('grid-cols-[minmax(0,1fr)_auto]', 'min-w-0');
    expect(screen.getByText(longRecurringMerchant)).toHaveClass('truncate');
  });
});
