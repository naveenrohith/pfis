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
  useAdjudicateAnomaly: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useAdjudicateAnomalySample: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useAnomalySamples: () => ({ isLoading: false, data: [] }),
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
  it('presents one conclusion with a traceable evidence spine', () => {
    render(<InsightsSection embedded />);

    expect(screen.getByText('MONTHLY INVESTIGATION')).toBeInTheDocument();
    expect(screen.getByText('Why it changed')).toBeInTheDocument();
    expect(screen.getByText('Merchant concentration')).toBeInTheDocument();
    expect(screen.getByText(longMerchant)).toHaveClass('truncate');
    expect(screen.getByText(longRecurringMerchant)).toHaveClass('truncate');
  });
});
