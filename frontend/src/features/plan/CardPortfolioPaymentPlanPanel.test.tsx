import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CardPortfolioPaymentPlanPanel } from './CardPortfolioPaymentPlanPanel';
import type { CardPortfolioPaymentPlan, CardPaymentScenario } from '@/lib/types';

const scenario = (
  kind: CardPaymentScenario['scenario'],
  amount: number,
  additional: number,
): CardPaymentScenario => ({
  scenario: kind,
  payment_date: '2026-08-25',
  payment_amount: amount,
  planned_payment_applied: amount - additional,
  additional_payment_amount: additional,
  effective_payment_amount: amount,
  remaining_total_due: kind === 'total_due' ? 0 : 9000,
  expected_funding_balance_after: 5000,
  lower_band_funding_balance_after: 4200,
  upper_band_funding_balance_after: 5800,
  expected_cash_gap: 0,
  lower_band_cash_gap: 0,
  expected_covered: true,
  lower_band_covered: true,
  status: 'covered',
});

const fundingPath = {
  funding_account_id: 'bank-1',
  funding_account_label: 'Plan Bank',
  card_ids: ['card-1', 'card-2'],
  cards_covered_on_lower_band: 2,
  cards_at_risk: 0,
  forecast_status: 'ready' as const,
  status: 'covered' as const,
  starting_balance: 15000,
  starting_balance_as_of: '2026-08-10',
  starting_balance_basis: 'observed' as const,
  lowest_expected_balance_after: 5000,
  lowest_lower_band_balance_after: 4200,
  lowest_upper_band_balance_after: 5800,
  first_lower_band_shortfall_date: null,
  lower_band_cash_gap: 0,
  confidence: 0.86,
  reason_codes: ['shared_funding_path_replayed'],
  assumptions: [],
};

const plan: CardPortfolioPaymentPlan = {
  as_of: '2026-08-10',
  state: 'ready',
  card_count: 2,
  cards_with_statement: 2,
  cards_needing_review: 0,
  minimum_due_plan: {
    strategy: 'minimum_due',
    status: 'covered',
    issuer_payment_target_total: 1000,
    planned_payment_total: 600,
    additional_payment_total: 400,
    effective_payment_total: 1000,
    remaining_total_due: 9000,
    cards_with_target: 2,
    cards_with_funding_path: 2,
    cards_covered_on_lower_band: 2,
    cards_at_risk: 0,
    cards_unavailable: 0,
    confidence: 0.86,
    reason_codes: [],
    funding_paths: [fundingPath],
  },
  total_due_plan: {
    strategy: 'total_due',
    status: 'covered',
    issuer_payment_target_total: 10000,
    planned_payment_total: 2000,
    additional_payment_total: 8000,
    effective_payment_total: 10000,
    remaining_total_due: 0,
    cards_with_target: 2,
    cards_with_funding_path: 2,
    cards_covered_on_lower_band: 2,
    cards_at_risk: 0,
    cards_unavailable: 0,
    confidence: 0.86,
    reason_codes: ['shared_funding_path_replayed'],
    funding_paths: [fundingPath],
  },
  cards: [
    {
      financial_account_id: 'card-1',
      label: 'Plan Card One',
      currency: 'INR',
      runway_status: 'covered',
      statement_date: '2026-08-05',
      due_date: '2026-08-25',
      total_due: 6000,
      minimum_due: 600,
      funding_account_id: 'bank-1',
      funding_account_label: 'Plan Bank',
      minimum_due_scenario: scenario('minimum_due', 600, 0),
      total_due_scenario: scenario('total_due', 6000, 5000),
      confidence: 0.9,
      reason_codes: [],
      evidence: [],
      assumptions: [],
    },
    {
      financial_account_id: 'card-2',
      label: 'Plan Card Two',
      currency: 'INR',
      runway_status: 'covered',
      statement_date: '2026-08-05',
      due_date: '2026-09-01',
      total_due: 4000,
      minimum_due: 400,
      funding_account_id: 'bank-1',
      funding_account_label: 'Plan Bank',
      minimum_due_scenario: scenario('minimum_due', 400, 0),
      total_due_scenario: scenario('total_due', 4000, 3000),
      confidence: 0.86,
      reason_codes: [],
      evidence: [],
      assumptions: [],
    },
  ],
  confidence: 0.86,
  reason_codes: ['portfolio_payment_plans_composed'],
  evidence: [],
  assumptions: [],
  ruleset_version: 'pfis-card-portfolio-payment-plan-1',
};

describe('CardPortfolioPaymentPlanPanel', () => {
  it('compares issuer targets and keeps funding evidence visible', () => {
    render(<CardPortfolioPaymentPlanPanel plan={plan} currency="INR" />);

    expect(screen.getByRole('heading', { name: 'Minimum due or total due?' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Payment plan comparison' })).toBeInTheDocument();
    expect(screen.getByText('Additional after planned')).toBeInTheDocument();
    expect(screen.getAllByText('Plan Bank')).not.toHaveLength(0);
    expect(screen.getByText(/does not schedule, submit, reserve, or confirm/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText('Review per-card payment evidence'));

    expect(screen.getByRole('table', { name: 'Per-card payment evidence' })).toBeInTheDocument();
    expect(screen.getByText('Plan Card One')).toBeInTheDocument();
    expect(screen.getByText('Plan Card Two')).toBeInTheDocument();
  });

  it('stays hidden for a single card and explains unavailable refreshes', () => {
    const { container, rerender } = render(
      <CardPortfolioPaymentPlanPanel
        plan={{ ...plan, card_count: 1, cards: plan.cards.slice(0, 1) }}
        currency="INR"
      />,
    );

    expect(container).toBeEmptyDOMElement();

    rerender(<CardPortfolioPaymentPlanPanel currency="INR" error={new Error('network')} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Payment comparison needs a refresh');
  });
});
