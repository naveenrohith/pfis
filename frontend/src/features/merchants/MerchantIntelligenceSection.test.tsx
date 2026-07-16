import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MerchantIntelligenceSection } from './MerchantIntelligenceSection';

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { currency: 'INR' } }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ setExplorerSearch: vi.fn(), scrollTo: vi.fn() }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify: vi.fn() }),
}));

vi.mock('@/features/workspace/queries', () => ({
  useMerchants: () => ({
    isLoading: false,
    data: [
      {
        merchant_key: 'Stream House',
        name: 'Stream House',
        total_spend: 1497,
        transaction_count: 3,
        avg_spend: 499,
        category: 'Subscriptions',
        category_id: 'subscription',
        recurrence_likelihood: 0.94,
        recurrence_status: 'mature',
        recurrence_cadence: 'monthly',
        recurrence_confidence: 0.94,
        next_expected_date: '2026-08-15',
        data_sufficiency: 'high',
      },
    ],
  }),
  useLearnedMerchantRules: () => ({
    isLoading: false,
    data: [
      {
        id: 'rule-1',
        raw_descriptor: 'STRM HOUSE BLR 4921',
        normalized_name: 'Stream House',
        source: 'user_correction',
        confidence: 1,
        created_at: '2026-07-15T10:00:00Z',
        updated_at: '2026-07-15T10:00:00Z',
      },
    ],
  }),
  useDeleteLearnedMerchantRule: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

describe('Merchant intelligence evidence', () => {
  it('shows recurrence maturity and private learned mappings', () => {
    render(<MerchantIntelligenceSection embedded />);

    expect(screen.getByText('Confirmed Rhythm')).toBeInTheDocument();
    expect(screen.getByText('94%')).toBeInTheDocument();
    expect(screen.getByText('Learned From Your Corrections')).toBeInTheDocument();
    expect(screen.getByText(/STRM HOUSE BLR 4921/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Forget learned mapping for STRM HOUSE BLR 4921' }),
    ).toBeInTheDocument();
  });
});
