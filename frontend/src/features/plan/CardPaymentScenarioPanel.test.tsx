import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CardPaymentScenarioPanel } from './CardPaymentScenarioPanel';
import type { CardDueRunway } from '@/lib/types';

const runway: CardDueRunway = {
  financial_account_id: 'card-1',
  currency: 'INR',
  status: 'at_risk',
  statement_date: '2026-08-05',
  due_date: '2026-08-25',
  days_until_due: 15,
  total_due: 13000,
  minimum_due: 1300,
  estimated_current_outstanding: 14000,
  credit_limit: 100000,
  issuer_available_credit_limit: 86000,
  funding_account_id: 'bank-1',
  funding_account_label: 'HDFC Salary Account',
  funding_balance_basis: 'estimated',
  funding_balance_as_of: '2026-08-10',
  funding_position_status: 'estimated',
  funding_balance_before_due_expected: 18000,
  funding_balance_before_due_low: 10500,
  funding_balance_before_due_high: 25000,
  expected_balance_after_total_due: 5000,
  expected_cash_gap: 0,
  lower_band_cash_gap: 0,
  planned_payment_total: 500,
  expected_total_due_covered: true,
  lower_band_total_due_covered: true,
  minimum_due_covered_on_lower_band: true,
  confidence: 0.74,
  position_reason_codes: [],
  evidence: [],
  assumptions: [],
  ruleset_version: 'pfis-card-due-runway-2',
  payment_scenarios: [
    {
      scenario: 'minimum_due',
      payment_date: '2026-08-25',
      payment_amount: 1300,
      planned_payment_applied: 500,
      additional_payment_amount: 800,
      effective_payment_amount: 1300,
      remaining_total_due: 11700,
      expected_funding_balance_after: 16700,
      lower_band_funding_balance_after: 9200,
      upper_band_funding_balance_after: 23700,
      expected_cash_gap: 0,
      lower_band_cash_gap: 0,
      expected_covered: true,
      lower_band_covered: true,
      status: 'covered',
    },
    {
      scenario: 'total_due',
      payment_date: '2026-08-25',
      payment_amount: 13000,
      planned_payment_applied: 500,
      additional_payment_amount: 12500,
      effective_payment_amount: 13000,
      remaining_total_due: 0,
      expected_funding_balance_after: 5000,
      lower_band_funding_balance_after: -2500,
      upper_band_funding_balance_after: 12000,
      expected_cash_gap: 0,
      lower_band_cash_gap: 2500,
      expected_covered: true,
      lower_band_covered: false,
      status: 'at_risk',
    },
  ],
};

describe('CardPaymentScenarioPanel', () => {
  it('compares minimum and total due against the conservative funding path', () => {
    render(<CardPaymentScenarioPanel runway={runway} />);

    expect(screen.getByText('PAYMENT SCENARIOS')).toBeInTheDocument();
    expect(screen.getByText('Minimum due vs total due')).toBeInTheDocument();
    expect(
      screen.getByRole('table', { name: 'Card payment scenario comparison' }),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Covered on lower band')).not.toHaveLength(0);
    expect(screen.getAllByText('Cash path at risk')).not.toHaveLength(0);
    expect(screen.getAllByText(/Gap/)).not.toHaveLength(0);
    expect(
      screen.getByText(/does not schedule, submit, reserve, or confirm a payment/i),
    ).toBeInTheDocument();
  });

  it('suppresses the panel when the backend has no scenarios', () => {
    const { container } = render(
      <CardPaymentScenarioPanel runway={{ ...runway, payment_scenarios: [] }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
