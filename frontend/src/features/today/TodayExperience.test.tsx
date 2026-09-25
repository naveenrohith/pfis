import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TodayExperience } from './TodayExperience';

const {
  cashPlanState,
  scrollTo,
  recommendations,
  decisions,
  setGuidanceState,
  todayUi,
  dataSufficiency,
  decisionQueryFails,
  workspaceState,
  workspaceRefetch,
} = vi.hoisted(() => ({
  workspaceState: {
    isLoading: false,
    isError: false,
    hasData: true,
    netCashFlow: 30000,
    transactionCount: 12,
    projectedNet: undefined as number | undefined,
    lastSyncedAt: null as string | null,
    latestStatus: null as string | null,
  },
  workspaceRefetch: vi.fn(),
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
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
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
  todayUi: { activeSection: 'overview' as 'overview' | 'guidance' | 'recommendations' },
  dataSufficiency: { value: 'high' as 'low' | 'medium' | 'high' },
  decisionQueryFails: { value: false },
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', name: 'Asha', email: 'asha@example.com', currency: 'INR' },
  }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ scrollTo, activeSection: todayUi.activeSection }),
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
    guidanceDecisions: vi.fn(() =>
      decisionQueryFails.value
        ? Promise.reject(new Error('Action history is temporarily unavailable'))
        : Promise.resolve(decisions),
    ),
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
    isLoading: workspaceState.isLoading,
    isError: workspaceState.isError,
    isFetching: false,
    error: workspaceState.isError ? new Error('GET /api/workspace failed: 503') : null,
    data: workspaceState.hasData
      ? {
          snapshot: {
            income: 50000,
            spend: 20000,
            net_cash_flow: workspaceState.netCashFlow,
            transaction_count: workspaceState.transactionCount,
            budget_risk_count: 0,
          },
          projection:
            workspaceState.projectedNet === undefined
              ? undefined
              : {
                  projected_net: workspaceState.projectedNet,
                  daily_spend_rate: 900,
                  recurring_commitments: 0,
                  data_through: '2026-07-20',
                },
          financial_health: {
            monthly_stability: 75,
            recurring_burden: 10,
            data_sufficiency: dataSufficiency.value,
            data_confidence: 90,
          },
          month_comparison: null,
          recommendations,
          insights: [],
          sync_summary: {
            last_synced_at: workspaceState.lastSyncedAt,
            latest_status: workspaceState.latestStatus,
          },
        }
      : undefined,
    refetch: workspaceRefetch,
  }),
}));

describe('Today Financial Horizon', () => {
  beforeEach(() => {
    scrollTo.mockClear();
    todayUi.activeSection = 'overview';
    dataSufficiency.value = 'high';
    decisionQueryFails.value = false;
    Object.assign(workspaceState, {
      isLoading: false,
      isError: false,
      hasData: true,
      netCashFlow: 30000,
      transactionCount: 12,
      projectedNet: undefined,
      lastSyncedAt: null,
      latestStatus: null,
    });
    workspaceRefetch.mockReset();
    cashPlanState.data = undefined;
    cashPlanState.isError = false;
    cashPlanState.refetch = vi.fn();
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
    const safeToSpendActions = screen.getAllByRole('button', {
      name: /Review Safe to spend/i,
    });
    expect(safeToSpendActions).toHaveLength(2);
    expect(safeToSpendActions[0]).toHaveClass('lg:hidden');
    expect(safeToSpendActions[1]).toHaveClass('hidden', 'lg:inline-flex');
    fireEvent.click(safeToSpendActions[0]);
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

  it('does not claim there is no unusual movement when the period has low evidence', () => {
    todayUi.activeSection = 'guidance';
    dataSufficiency.value = 'low';

    renderToday();

    expect(screen.getByText('Too little activity to assess a trend')).toBeInTheDocument();
    expect(screen.queryByText('No unusual movement needs attention')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Review activity' }));
    expect(scrollTo).toHaveBeenCalledWith('transactions');
  });

  it('shows a retry state instead of an empty action history when decisions fail to load', async () => {
    todayUi.activeSection = 'recommendations';
    decisionQueryFails.value = true;

    renderToday();

    expect(await screen.findByText('Action history is unavailable')).toBeInTheDocument();
    expect(screen.queryByText('No action outcomes to review')).not.toBeInTheDocument();

    decisionQueryFails.value = false;
    fireEvent.click(screen.getByRole('button', { name: 'Retry action history' }));
    expect(await screen.findByText('No action outcomes to review')).toBeInTheDocument();
  });

  it('does not offer a new recommendation while previously handled actions cannot be checked', async () => {
    recommendations.push({
      id: 'review-1',
      title: 'Review uncertain activity',
      description: 'Confirm one uncertain record.',
      action_label: 'Open review queue',
      target: 'review',
      expected_impact: 'Improve the reliability of financial totals.',
      reason_codes: ['review'],
    });
    decisionQueryFails.value = true;

    renderToday();

    expect(await screen.findByText('Action status is unavailable')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Use this action' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry action status' })).toBeInTheDocument();
  });

  describe('workspace state model', () => {
    function stateOf(container: HTMLElement) {
      return container.querySelector('[data-today-state]')?.getAttribute('data-today-state');
    }

    it('reinforces progress in the healthy state', () => {
      const { container } = renderToday();

      expect(stateOf(container)).toBe('healthy');
      expect(
        screen.getByRole('heading', {
          level: 1,
          name: 'Good work, Asha. You are keeping more than you spend.',
        }),
      ).toBeInTheDocument();
      expect(screen.queryByText('Some signals could not be refreshed')).not.toBeInTheDocument();
      expect(screen.queryByText('Showing last known values')).not.toBeInTheDocument();
    });

    it('explains emerging pressure in the attention state', () => {
      workspaceState.projectedNet = -4000;

      const { container } = renderToday();

      expect(stateOf(container)).toBe('attention');
      expect(
        screen.getByRole('heading', { name: 'Review the pressure building this month' }),
      ).toBeInTheDocument();
    });

    it('states a shortfall plainly without positive visuals in the deficit state', () => {
      workspaceState.netCashFlow = -6000;

      const { container } = renderToday();

      expect(stateOf(container)).toBe('deficit');
      expect(screen.getByText(/spent ₹6,000 more than you earned/)).toBeInTheDocument();
      expect(
        screen.getByRole('heading', { name: 'Find the largest driver of this shortfall' }),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Good work/)).not.toBeInTheDocument();
      expect(screen.getByText('Net cash flow this month').closest('section')).toHaveClass(
        'bg-muted/60',
      );
    });

    it('makes connecting data the primary action and hides forecasts in the low-data state', () => {
      dataSufficiency.value = 'low';
      workspaceState.transactionCount = 2;
      workspaceState.projectedNet = 12000;

      const { container } = renderToday();

      expect(stateOf(container)).toBe('low-data');
      expect(
        screen.getByRole('heading', { name: 'This brief has limited evidence' }),
      ).toBeInTheDocument();
      expect(screen.getByText('Not projected')).toBeInTheDocument();
      expect(screen.queryByText('₹12,000')).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Connect or import activity' }));
      expect(scrollTo).toHaveBeenCalledWith('inbox');
    });

    it('labels the age of last known values and routes to sources in the stale state', () => {
      workspaceState.lastSyncedAt = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();

      const { container } = renderToday();

      expect(stateOf(container)).toBe('stale');
      const notice = screen.getByRole('status', { name: 'Showing last known values' });
      expect(notice).toHaveTextContent(/Sources last synced/);
      expect(screen.getAllByText('₹30,000').length).toBeGreaterThan(0);
      fireEvent.click(screen.getByRole('button', { name: 'Review data sources' }));
      expect(scrollTo).toHaveBeenCalledWith('inbox');
    });

    it('treats a failed latest sync as stale even when the last sync is recent', () => {
      workspaceState.lastSyncedAt = new Date().toISOString();
      workspaceState.latestStatus = 'failed';

      const { container } = renderToday();

      expect(stateOf(container)).toBe('stale');
      expect(
        screen.getByRole('status', { name: 'The latest sync did not finish' }),
      ).toBeInTheDocument();
    });

    it('shows a grouped loading skeleton while the summary is first loading', () => {
      workspaceState.isLoading = true;
      workspaceState.hasData = false;

      renderToday();

      const loading = screen.getByRole('status', { name: 'Loading financial brief' });
      expect(loading).toHaveAttribute('aria-busy', 'true');
      expect(loading).toHaveAttribute('data-today-state', 'loading');
    });

    it('keeps usable sections and names the failed signal in the partial-error state', () => {
      cashPlanState.isError = true;

      const { container } = renderToday();

      expect(stateOf(container)).toBe('partial-error');
      const notice = screen.getByRole('status', { name: 'Some signals could not be refreshed' });
      expect(notice).toHaveTextContent('PFIS could not refresh Safe to spend.');
      expect(screen.getByText('Safe to spend is unavailable')).toBeInTheDocument();
      expect(screen.queryByText('Set up a bank position')).not.toBeInTheDocument();
      expect(screen.getAllByText('₹30,000').length).toBeGreaterThan(0);

      fireEvent.click(screen.getByRole('button', { name: 'Retry unavailable signals' }));
      expect(cashPlanState.refetch).toHaveBeenCalledTimes(1);
      expect(workspaceRefetch).not.toHaveBeenCalled();
    });

    it('keeps last loaded figures when a summary refresh fails', () => {
      workspaceState.isError = true;

      const { container } = renderToday();

      expect(stateOf(container)).toBe('partial-error');
      expect(
        screen.getByRole('status', { name: 'Some signals could not be refreshed' }),
      ).toHaveTextContent('The figures below are from the last successful load.');
      expect(screen.getAllByText('₹30,000').length).toBeGreaterThan(0);
    });

    it('gives human-readable recovery and Data & settings access in the full-error state', () => {
      workspaceState.isError = true;
      workspaceState.hasData = false;

      const { container } = renderToday();

      expect(stateOf(container)).toBe('full-error');
      expect(screen.getByRole('alert')).toHaveTextContent('The summary is temporarily unavailable');
      expect(screen.queryByText(/503/)).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Retry summary' }));
      expect(workspaceRefetch).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByRole('button', { name: /Open Data & settings/ }));
      expect(scrollTo).toHaveBeenCalledWith('inbox');
    });
  });
});
