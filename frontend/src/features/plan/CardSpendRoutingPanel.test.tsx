import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CardSpendRoutingPanel } from './CardSpendRoutingPanel';

const { cardSpendRouting } = vi.hoisted(() => ({
  cardSpendRouting: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', name: 'Test', email: 'test@example.com', currency: 'INR' },
  }),
}));

vi.mock('@/lib/api', () => ({
  api: { cardSpendRouting },
}));

const response = {
  as_of: '2026-08-10',
  amount: 5000,
  category: 'travel',
  priority: 'rewards' as const,
  currency: 'INR',
  state: 'ready' as const,
  recommended_card_id: 'card-travel',
  options: [
    {
      financial_account_id: 'card-travel',
      label: 'Travel Card',
      currency: 'INR',
      status: 'recommended' as const,
      current_outstanding: 20000,
      credit_limit: 100000,
      current_utilization_pct: 20,
      projected_statement_balance: 25000,
      projected_statement_utilization_pct: 25,
      utilization_status: 'within_target' as const,
      utilization_target_pct: 40,
      target_headroom_amount: 15000,
      hard_headroom_amount: 75000,
      reward_label: 'Travel rewards',
      reward_rate_pct: 5,
      estimated_reward: 250,
      reward_status: 'explicit' as const,
      source_kind: 'ledger_estimate' as const,
      confidence: 0.84,
      reason_codes: ['recommended_by_explicit_priority'],
      assumptions: [],
    },
    {
      financial_account_id: 'card-cashback',
      label: 'Cashback Card',
      currency: 'INR',
      status: 'over_target' as const,
      current_outstanding: 35000,
      credit_limit: 100000,
      current_utilization_pct: 35,
      projected_statement_balance: 40000,
      projected_statement_utilization_pct: 40,
      utilization_status: 'over_target' as const,
      utilization_target_pct: 30,
      target_headroom_amount: -10000,
      hard_headroom_amount: 60000,
      reward_label: null,
      reward_rate_pct: null,
      estimated_reward: null,
      reward_status: 'category_mismatch' as const,
      source_kind: 'provider' as const,
      confidence: 0.9,
      reason_codes: [],
      assumptions: [],
    },
  ],
  confidence: 0.84,
  reason_codes: ['recommended_card_present'],
  assumptions: [],
  ruleset_version: 'pfis-card-spend-routing-1',
};

describe('CardSpendRoutingPanel', () => {
  it('submits explicit purchase intent and renders evidence-ranked options', async () => {
    cardSpendRouting.mockResolvedValue(response);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <CardSpendRoutingPanel cardCount={2} currency="INR" />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText('Purchase amount'), { target: { value: '5000' } });
    fireEvent.change(screen.getByLabelText('Category (optional)'), {
      target: { value: 'travel' },
    });
    fireEvent.change(screen.getByLabelText('Priority'), { target: { value: 'rewards' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview routing' }));

    expect(await screen.findByText('Recommended: Travel Card')).toBeInTheDocument();
    expect(cardSpendRouting).toHaveBeenCalledWith('user-1', {
      amount: 5000,
      category: 'travel',
      priority: 'rewards',
    });
    expect(
      screen.getByRole('table', { name: 'Hypothetical card routing options' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Provider evidence/)).toBeInTheDocument();
    expect(screen.getByText(/does not quote issuer rewards/i)).toBeInTheDocument();
  });

  it('does not render for an empty card workspace', () => {
    const queryClient = new QueryClient();
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <CardSpendRoutingPanel cardCount={0} currency="INR" />
      </QueryClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
