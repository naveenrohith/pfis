import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CardsSection } from './CardsSection';

const { addBalance, cardDisputes, cardOverview, saveCardPreferences } = vi.hoisted(() => ({
  addBalance: vi.fn(),
  cardDisputes: vi.fn(),
  cardOverview: vi.fn(),
  saveCardPreferences: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', name: 'Test', email: 'test@example.com', currency: 'INR' },
  }),
}));

vi.mock('@/features/workspace/queries', () => ({
  useAccounts: () => ({
    isLoading: false,
    data: [
      {
        id: 'card-1',
        institution_name: 'HDFC',
        account_type: 'credit_card',
        masked_number: '••••9913',
      },
    ],
  }),
  useAccountBalanceForecast: () => ({
    isLoading: false,
    data: undefined,
  }),
  useCardDueRunway: () => ({
    isLoading: false,
    data: {
      financial_account_id: 'card-1',
      currency: 'INR',
      status: 'at_risk',
      statement_date: '2026-02-05',
      due_date: '2026-02-25',
      days_until_due: 15,
      total_due: 13000,
      minimum_due: 1300,
      estimated_current_outstanding: 14000,
      credit_limit: 100000,
      issuer_available_credit_limit: 86000,
      funding_account_id: 'bank-1',
      funding_account_label: 'HDFC Salary Account',
      funding_balance_basis: 'estimated',
      funding_balance_as_of: '2026-02-12',
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
          payment_date: '2026-02-25',
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
          payment_date: '2026-02-25',
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
    },
  }),
  useCardPortfolioPaymentPlan: () => ({
    isLoading: false,
    error: null,
    data: undefined,
  }),
  useCardPortfolioUpcomingState: () => ({
    isLoading: false,
    error: null,
    data: undefined,
  }),
  useCardUtilizationHistory: () => ({
    isLoading: false,
    error: null,
    data: {
      financial_account_id: 'card-1',
      as_of: '2026-02-12',
      utilization_target_pct: 30,
      statement_points: [
        {
          as_of: '2026-01-05',
          basis: 'issuer_statement',
          statement_id: 'statement-0',
          balance: 12000,
          credit_limit: 100000,
          utilization_pct: 12,
          status: 'within_target',
          source_transaction_count: 0,
          confidence: 1,
          reason_codes: ['issuer_statement_total_due'],
        },
        {
          as_of: '2026-02-05',
          basis: 'issuer_statement',
          statement_id: 'statement-1',
          balance: 13000,
          credit_limit: 100000,
          utilization_pct: 13,
          status: 'within_target',
          source_transaction_count: 0,
          confidence: 1,
          reason_codes: ['issuer_statement_total_due'],
        },
      ],
      daily_points: [
        {
          as_of: '2026-02-12',
          basis: 'ledger_estimate',
          statement_id: 'statement-1',
          balance: 16800,
          credit_limit: 100000,
          utilization_pct: 16.8,
          status: 'within_target',
          source_transaction_count: 5,
          confidence: 0.78,
          reason_codes: ['ledger_rollforward_from_statement'],
        },
      ],
      trend: 'worsening',
      trend_basis: 'issuer_to_current_estimate',
      trend_delta_pct: 4.8,
      peak_statement_utilization_pct: 13,
      peak_daily_utilization_pct: 16.8,
      target_breach_count: 0,
      credit_limit_breach_count: 0,
      reason_codes: ['current_cycle_ledger_estimate_available'],
      assumptions: [],
      ruleset_version: 'pfis-card-utilization-history-1',
    },
  }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    addBalance,
    cardDisputes,
    cardOverview,
    saveCardPreferences,
    createCardDispute: vi.fn(),
    updateCardDispute: vi.fn(),
  },
}));

describe('CardsSection activity centre', () => {
  it('shows deterministic signals and issuer-action limitations', async () => {
    cardOverview.mockResolvedValue({
      financial_account_id: 'card-1',
      currency: 'INR',
      latest_statement_id: 'statement-1',
      statement_date: '2026-02-05',
      period_start: '2026-01-06',
      period_end: '2026-02-05',
      total_due: 13000,
      minimum_due: 1300,
      due_date: '2026-02-25',
      previous_due: 8000,
      payments_credits: 8000,
      purchases_debits: 13000,
      finance_charges: 0,
      credit_limit: 100000,
      available_credit_limit: 87000,
      available_cash_limit: 40000,
      observed_balance: 11000,
      observed_balance_as_of: '2026-02-05',
      observed_source: 'connector',
      observed_at: '2026-02-05T10:30:00Z',
      estimated_current_balance: 11400,
      estimated_current_as_of: '2026-02-06',
      refund_tracker: {
        status: 'pending',
        as_of: '2026-02-12',
        horizon_days: 90,
        pending_count: 1,
        pending_amount: 750,
        oldest_pending_date: '2026-02-10',
        posted_count_90d: 1,
        posted_amount_90d: 500,
        needs_review_count: 0,
        reason_codes: ['pending_refunds'],
        evidence: [
          {
            label: 'Pending refund evidence',
            value: '1 row(s) · 750.00',
            basis: 'Explicit pending refund.',
          },
        ],
        ruleset_version: 'pfis-card-refund-tracker-1',
      },
      next_statement_projection: {
        status: 'available',
        as_of: '2026-02-12',
        projected_statement_date: '2026-03-08',
        projected_balance: 16800,
        range_low: 14200,
        range_high: 19400,
        projected_utilization_pct: 16.8,
        confidence: 0.78,
        next_state: 'monitor_cycle',
        target_status: 'under_target',
        target_headroom_amount: 13200,
        target_excess_amount: 0,
        target_breach_date: null,
        target_breach_days: null,
        credit_limit_status: 'under_limit',
        credit_limit_headroom_amount: 83200,
        credit_limit_excess_amount: 0,
        credit_limit_breach_date: null,
        credit_limit_breach_days: null,
        calibration: 'historical_blend',
        historical_sample_count: 2,
        seasonal_sample_count: 2,
        seasonal_days_covered: 1,
        known_future_payment_total: 2000,
        known_future_charge_total: 1200,
        known_future_recurring_charge_total: 899,
        recurring_charge_candidates: [
          {
            merchant: 'STREAMCO',
            expected_date: '2026-02-18',
            expected_date_low: '2026-02-16',
            expected_date_high: '2026-02-20',
            expected_amount: 899,
            expected_amount_low: 850,
            expected_amount_high: 950,
            cadence: 'monthly',
            occurrences: 4,
            confidence: 0.86,
          },
        ],
        daily_path: [
          {
            date: '2026-02-13',
            days_from_today: 1,
            projected_balance: 11800,
            range_low: 11600,
            range_high: 12200,
            projected_utilization_pct: 11.8,
            target_status: 'under_target',
            credit_limit_status: 'under_limit',
            event_amount: 0,
            event_labels: [],
          },
          {
            date: '2026-02-18',
            days_from_today: 6,
            projected_balance: 14500,
            range_low: 13800,
            range_high: 15200,
            projected_utilization_pct: 14.5,
            target_status: 'under_target',
            credit_limit_status: 'under_limit',
            event_amount: 899,
            event_labels: ['Recurring: STREAMCO'],
          },
          {
            date: '2026-03-08',
            days_from_today: 24,
            projected_balance: 16800,
            range_low: 14200,
            range_high: 19400,
            projected_utilization_pct: 16.8,
            target_status: 'under_target',
            credit_limit_status: 'under_limit',
            event_amount: 0,
            event_labels: [],
          },
        ],
        reason_codes: ['current_cycle_pace_extrapolated'],
        evidence: [
          {
            label: 'Observed cycle activity',
            value: '5 settled non-payment events over 7 days',
            basis: 'Settled card activity.',
          },
        ],
        potential_pending_refund_total: 750,
        ruleset_version: 'pfis-card-statement-projection-9',
      },
      balance_status: 'observed',
      balance_confidence: 0.95,
      balance_reason_codes: [],
      coverage_status: 'fresh',
      coverage_complete: true,
      statement_utilization_pct: 13,
      utilization_target_pct: 30,
      coverage: { matched: 0, newly_imported: 2, ignored_by_rule: 0, needs_review: 1 },
      statement_lines: [
        {
          id: 'line-1',
          transaction_date: '2026-01-22',
          description: 'DE-IDENTIFIED MERCHANT',
          amount: 500,
          transaction_type: 'debit',
          card_event: 'purchase',
          review_outcome: 'newly_imported',
          created_transaction_id: 'transaction-1',
        },
      ],
      statement_history: [
        {
          id: 'statement-1',
          statement_date: '2026-02-05',
          period_start: '2026-01-06',
          period_end: '2026-02-05',
          due_date: '2026-02-25',
          total_due: 13000,
          minimum_due: 1300,
          line_count: 3,
          needs_review_count: 1,
        },
      ],
      planned_payments: [
        {
          id: 'intent-1',
          financial_account_id: 'card-1',
          paying_account_id: 'bank-1',
          amount: 13000,
          planned_for: '2026-02-20',
          status: 'planned',
          transfer_group_id: null,
          created_at: '2026-02-06T10:00:00Z',
        },
      ],
      calendar: [
        {
          id: 'calendar-1',
          financial_account_id: 'card-1',
          event_type: 'annual_fee',
          label: 'Annual fee review',
          event_date: '2026-10-05',
          source_kind: 'manual',
          created_at: '2026-02-06T10:00:00Z',
        },
      ],
      activity_signals: [
        {
          id: 'duplicate:1',
          signal_type: 'duplicate_candidate',
          title: 'Possible duplicate statement lines',
          description:
            '2 lines share the same date, normalized description, amount, and direction.',
          amount: 500,
          activity_date: '2026-01-22',
          basis: 'Exact statement evidence.',
        },
        {
          id: 'pending-reversal:1',
          signal_type: 'pending_reversal',
          title: 'Pending reversal needs follow-up',
          description: 'PFIS has reversal evidence that is not completed.',
          amount: 750,
          activity_date: '2026-01-23',
          basis: 'Explicit reversal status.',
        },
      ],
    });
    cardDisputes.mockResolvedValue([]);
    saveCardPreferences.mockResolvedValue({
      financial_account_id: 'card-1',
      utilization_target_pct: 30,
      reward_rules: [{ label: 'Dining', rate_pct: 2 }],
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <CardsSection />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole('heading', { name: 'Cards' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record verified position' })).toBeInTheDocument();

    addBalance.mockResolvedValue({ id: 'snapshot-1' });
    fireEvent.click(screen.getByRole('button', { name: 'Record verified position' }));
    expect(screen.getByRole('dialog')).toHaveTextContent(
      'This saves a user-observed balance for planning.',
    );
    fireEvent.change(screen.getByLabelText('Current outstanding'), {
      target: { value: '11500' },
    });
    fireEvent.change(screen.getByLabelText('As of'), {
      target: { value: '2026-02-12' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save user-observed position' }));
    await waitFor(() =>
      expect(addBalance).toHaveBeenCalledWith('user-1', 'card-1', 11500, '2026-02-12'),
    );

    fireEvent.click(screen.getByRole('tab', { name: 'Activity' }));
    expect(await screen.findByText('Activity centre')).toBeInTheDocument();
    const refundTracker = screen.getByRole('region', { name: 'Refund tracker' });
    expect(refundTracker).toHaveTextContent('Refunds in flight');
    expect(refundTracker).toHaveTextContent('₹750');
    expect(refundTracker).toHaveTextContent('oldest 10 Feb 2026');

    fireEvent.click(screen.getByRole('tab', { name: 'Overview' }));
    expect(screen.getAllByText('Provider-observed · fresh')).not.toHaveLength(0);
    expect(screen.getByText('NEXT STATEMENT FORECAST')).toBeInTheDocument();
    expect(screen.getByText('DAILY PATH TO STATEMENT CLOSE')).toBeInTheDocument();
    expect(screen.getByText('View 3 day-by-day evidence points')).toBeInTheDocument();
    expect(screen.getAllByText('Recurring: STREAMCO')).not.toHaveLength(0);
    expect(screen.getByText('UTILIZATION HISTORY')).toBeInTheDocument();
    expect(screen.getByText('Moving up')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Utilization moved from 12.0%/i })).toBeInTheDocument();
    expect(screen.getByText('View 3 recent evidence points')).toBeInTheDocument();
    expect(screen.getAllByText('16.8%')).not.toHaveLength(0);
    expect(screen.getAllByText('78%')).not.toHaveLength(0);
    expect(screen.getByText(/pace-based estimate, not an issuer amount/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Forecast calibration')).toHaveTextContent(
      'Calibrated against 2 prior settled card cycles.',
    );
    expect(screen.getByLabelText('Forecast calibration')).toHaveTextContent(
      'Includes a ₹2,000 planned payment before close.',
    );
    expect(screen.getByLabelText('Forecast calibration')).toHaveTextContent(
      'Includes ₹1,200 of scheduled card charges.',
    );
    expect(screen.getByLabelText('Forecast calibration')).toHaveTextContent(
      'Includes ₹899 from 1 recurring charge candidate.',
    );
    expect(screen.getByLabelText('Pending refund projection')).toHaveTextContent(
      'Pending refund evidence may lower the range by up to',
    );
    expect(screen.getByRole('region', { name: 'Recurring charge candidates' })).toHaveTextContent(
      'STREAMCO',
    );
    expect(screen.getByLabelText('Utilization target runway')).toHaveTextContent('Under target');
    expect(screen.getByLabelText('Utilization target runway')).toHaveTextContent(
      '₹13,200 projected headroom at close against your 30.0% target.',
    );
    expect(screen.getByText('Keep monitoring this billing cycle.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Evidence & controls' }));
    expect(screen.getByText('How this statement arrived at the due')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Activity' }));
    expect(screen.getByText('Latest statement ledger')).toBeInTheDocument();
    expect(screen.getAllByText('DE-IDENTIFIED MERCHANT')).toHaveLength(2);
    expect(screen.getByText('Possible duplicate statement lines')).toBeInTheDocument();
    expect(screen.getByText('Pending reversal needs follow-up')).toBeInTheDocument();
    expect(
      screen.getByText(/PFIS cannot block, reverse, or dispute card activity/i),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Payment plan' }));
    expect(screen.getByText('PAYMENT SCENARIOS')).toBeInTheDocument();
    expect(screen.getByText('Minimum due vs total due')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record manual transfer' })).toBeEnabled();
    expect(screen.getByText(/Neither action contacts your bank or issuer/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Evidence & controls' }));
    fireEvent.click(screen.getByRole('button', { name: /Annual fee review/i }));
    fireEvent.click(screen.getByText('Edit fee or milestone reminder'));
    expect(screen.getByRole('button', { name: 'Update reminder' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Delete reminder' })).toBeEnabled();
    fireEvent.click(screen.getByText('Set a utilization and reward rule'));
    fireEvent.change(screen.getByLabelText('Explicit reward rule'), {
      target: { value: 'Dining' },
    });
    fireEvent.change(screen.getByLabelText('Rate (%)'), {
      target: { value: '2' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save card guardrails' }));
    await waitFor(() =>
      expect(saveCardPreferences).toHaveBeenCalledWith('user-1', 'card-1', {
        preferred_payment_account_id: null,
        utilization_target_pct: 30,
        reward_rules: [{ label: 'Dining', rate_pct: 2 }],
      }),
    );
  });
});
