import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TodayExperience } from './TodayExperience';

const { cashPlanState, scrollTo, recommendations, decisions, setGuidanceState } = vi.hoisted(
  () => ({
    cashPlanState: {
      data: undefined as
        | {
            primary_financial_account_id: string;
            currency: string;
            verified_balance: number | null;
            balance_as_of: string | null;
            next_income_date: string | null;
            confirmed_commitments: [];
            commitment_total: number;
            approved_reserve_total: number;
            flexible_money: number | null;
            daily_allowance: number | null;
            readiness:
              'ready' | 'needs_verified_balance' | 'needs_fresh_balance' | 'needs_next_income';
            assumptions: string[];
          }
        | undefined,
      isLoading: false,
    },
    scrollTo: vi.fn(),
    recommendations: [] as Array<{
      id: string;
      title: string;
      description: string;
      action_label: string;
      target: string;
      expected_impact: string;
      reason_codes: string[];
    }>,
    decisions: [] as Array<Record<string, unknown>>,
    setGuidanceState: vi.fn(),
  }),
);

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', name: 'Asha', email: 'asha@example.com', currency: 'INR' },
  }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ scrollTo }),
}));

vi.mock('@/features/workspace/WorkspaceContext', () => ({
  useWorkspace: () => ({ month: 7, year: 2026 }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify: vi.fn() }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    setGuidanceState,
    guidanceDecisions: vi.fn(() => Promise.resolve(decisions)),
    guidanceOutcomes: vi.fn().mockResolvedValue([]),
    recordGuidanceOutcome: vi.fn(),
  },
}));

vi.mock('@/features/workspace/SyncContext', () => ({
  useSync: () => ({ liveConnected: true, running: false }),
}));

vi.mock('@/features/workspace/queries', () => ({
  useCashPlan: () => cashPlanState,
  useWorkspaceSnapshot: () => ({
    isLoading: false,
    isError: false,
    data: {
      snapshot: {
        income: 50000,
        spend: 20000,
        net_cash_flow: 30000,
        transaction_count: 12,
      },
      projection: undefined,
      financial_health: {
        monthly_stability: 75,
        recurring_burden: 10,
        data_sufficiency: 'high',
        data_confidence: 90,
      },
      month_comparison: null,
      recommendations,
      insights: [],
      sync_summary: { last_synced_at: null },
    },
    refetch: vi.fn(),
  }),
}));

describe('Today Financial Horizon', () => {
  beforeEach(() => {
    scrollTo.mockClear();
    recommendations.splice(0);
    decisions.splice(0);
    setGuidanceState.mockReset();
    setGuidanceState.mockResolvedValue({ state: 'accepted' });
  });

  function renderToday() {
    const client = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    });
    return render(
      <QueryClientProvider client={client}>
        <TodayExperience />
      </QueryClientProvider>,
    );
  }

  it('uses the ready Cash Plan read model instead of a spend forecast', () => {
    cashPlanState.data = {
      primary_financial_account_id: 'bank-1',
      currency: 'INR',
      verified_balance: 30000,
      balance_as_of: '2026-07-28',
      next_income_date: '2026-08-01',
      confirmed_commitments: [],
      commitment_total: 5000,
      approved_reserve_total: 2000,
      flexible_money: 23000,
      daily_allowance: null,
      readiness: 'ready',
      assumptions: ['One confirmed bank account.'],
    };

    renderToday();

    expect(screen.getByText('Safe to spend')).toBeInTheDocument();
    expect(screen.getByText('Ready for planning')).toBeInTheDocument();
    expect(screen.queryByText('Monthly stability')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Show calculation details'));
    expect(screen.getByText('Flexible money')).toBeInTheDocument();
    expect(screen.getByText('Confirmed obligations')).toBeInTheDocument();
    expect(screen.getByText('Approved reserves')).toBeInTheDocument();
    expect(screen.queryByText(/Forecast ·/)).not.toBeInTheDocument();
  });

  it('keeps the Today brief focused and exposes evidence and actions as URL destinations', () => {
    renderToday();

    const navigation = screen.getByRole('navigation', { name: 'Today views' });
    expect(screen.getByRole('link', { name: 'Brief' })).toHaveAttribute('href', '#overview');
    expect(screen.getByRole('link', { name: 'Why it changed' })).toHaveAttribute(
      'href',
      '#guidance',
    );
    expect(screen.getByRole('link', { name: 'Actions' })).toHaveAttribute(
      'href',
      '#recommendations',
    );
    expect(navigation).toContainElement(screen.getByRole('link', { name: 'Brief' }));
    expect(
      screen.queryByRole('heading', { name: 'Your action follow-up' }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('link', { name: 'Why it changed' }));
    expect(scrollTo).toHaveBeenCalledWith('guidance');
  });

  it('shows a data action and never invents flexible money for incomplete inputs', () => {
    cashPlanState.data = {
      primary_financial_account_id: 'bank-1',
      currency: 'INR',
      verified_balance: 30000,
      balance_as_of: '2026-07-10',
      next_income_date: '2026-08-01',
      confirmed_commitments: [],
      commitment_total: 0,
      approved_reserve_total: 0,
      flexible_money: null,
      daily_allowance: null,
      readiness: 'needs_fresh_balance',
      assumptions: ['The latest verified balance is stale.'],
    };

    renderToday();

    expect(screen.getByText('Refresh the observed bank balance')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Show calculation details'));
    expect(screen.getAllByText('Not calculated')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: /Review Safe to spend/i }));
    expect(scrollTo).toHaveBeenCalledWith('cash-plan');
  });

  it('offers recommendation decisions on the mounted Today surface', async () => {
    recommendations.push({
      id: 'review-1',
      title: 'Review uncertain activity',
      description: 'Confirm one uncertain record.',
      action_label: 'Open review queue',
      target: 'review',
      expected_impact: 'Improve the reliability of financial totals.',
      reason_codes: ['review'],
    });

    renderToday();
    fireEvent.click(await screen.findByRole('button', { name: 'Use this action' }));

    await waitFor(() =>
      expect(setGuidanceState).toHaveBeenCalledWith(
        'user-1',
        'review-1',
        'accepted',
        undefined,
        '2026-07-01',
      ),
    );
  });

  it('does not offer the same recommendation again after it is accepted', async () => {
    recommendations.push({
      id: 'review-1',
      title: 'Review uncertain activity',
      description: 'Confirm one uncertain record.',
      action_label: 'Open review queue',
      target: 'review',
      expected_impact: 'Improve the reliability of financial totals.',
      reason_codes: ['review'],
    });
    decisions.push({
      id: 'decision-1',
      recommendation_id: 'review-1',
      state: 'accepted',
      title: 'Review uncertain activity',
      updated_at: '2026-07-31T12:00:00Z',
    });

    renderToday();

    expect(
      await screen.findByRole('heading', { name: 'Explore the drivers behind this month' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Use this action' })).not.toBeInTheDocument();
  });
});
