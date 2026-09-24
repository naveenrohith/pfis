import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CardDailyPathPanel } from './CardDailyPathPanel';
import { formatChartDate } from '@/lib/format';
import type { CardStatementProjection } from '@/lib/types';

const projection: CardStatementProjection = {
  status: 'available',
  as_of: '2026-08-10',
  projected_statement_date: '2026-08-20',
  projected_balance: 105000,
  range_low: 98000,
  range_high: 110000,
  projected_utilization_pct: 105,
  confidence: 0.72,
  next_state: 'reduce_spend_or_pay',
  target_status: 'over_target',
  target_headroom_amount: null,
  target_excess_amount: 75000,
  target_breach_date: '2026-08-14',
  target_breach_days: 4,
  credit_limit_status: 'over_limit',
  credit_limit_headroom_amount: 0,
  credit_limit_excess_amount: 5000,
  credit_limit_breach_date: '2026-08-19',
  credit_limit_breach_days: 9,
  calibration: 'historical_blend',
  historical_sample_count: 3,
  seasonal_sample_count: 2,
  seasonal_days_covered: 1,
  known_future_payment_total: 0,
  known_future_charge_total: 15000,
  known_future_recurring_charge_total: 5000,
  potential_pending_refund_total: 0,
  recurring_charge_candidates: [],
  daily_path: [
    {
      date: '2026-08-11',
      days_from_today: 1,
      projected_balance: 90000,
      range_low: 89000,
      range_high: 92000,
      projected_utilization_pct: 90,
      target_status: 'at_risk',
      credit_limit_status: 'under_limit',
      event_amount: 0,
      event_labels: [],
    },
    {
      date: '2026-08-14',
      days_from_today: 4,
      projected_balance: 97000,
      range_low: 95000,
      range_high: 100500,
      projected_utilization_pct: 97,
      target_status: 'over_target',
      credit_limit_status: 'at_risk',
      event_amount: 5000,
      event_labels: ['Recurring: TRAVELCO'],
    },
    {
      date: '2026-08-20',
      days_from_today: 10,
      projected_balance: 105000,
      range_low: 98000,
      range_high: 110000,
      projected_utilization_pct: 105,
      target_status: 'over_target',
      credit_limit_status: 'over_limit',
      event_amount: 10000,
      event_labels: ['Scheduled: Card EMI'],
    },
  ],
  reason_codes: ['daily_projection_path', 'credit_limit_exceeded'],
  evidence: [],
  ruleset_version: 'pfis-card-statement-projection-9',
};

describe('CardDailyPathPanel', () => {
  it('renders dated trajectory, event markers, target pressure, and hard-limit runway', () => {
    const { container } = render(
      <CardDailyPathPanel
        projection={projection}
        currency="INR"
        targetPct={40}
        creditLimit={100000}
      />,
    );

    expect(screen.getByText('DAILY PATH TO STATEMENT CLOSE')).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Projected utilization by day' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Daily card path from 11 Aug 2026 through 20 Aug 2026/i),
    ).toBeInTheDocument();
    expect(screen.getByText('Projected range')).toBeInTheDocument();
    expect(screen.getAllByText(/First pressure/)).not.toHaveLength(0);
    expect(screen.getAllByText('Over hard limit')).not.toHaveLength(0);
    expect(screen.getAllByText('Recurring: TRAVELCO')).not.toHaveLength(0);
    expect(screen.getAllByText('Scheduled: Card EMI')).not.toHaveLength(0);
    expect(screen.getByText('View 3 day-by-day evidence points')).toBeInTheDocument();
    expect(screen.getAllByText('Over hard limit')).not.toHaveLength(0);
    expect(
      screen.getByText(/cannot confirm an issuer balance, available credit, or payment outcome/i),
    ).toBeInTheDocument();
    const chartLabels = Array.from(container.querySelectorAll('svg text')).map((label) =>
      label.textContent?.trim(),
    );
    expect(chartLabels).toEqual(
      expect.arrayContaining([
        '0%',
        '110%',
        `Today · ${formatChartDate('2026-08-11')}`,
        `Close · ${formatChartDate('2026-08-20')}`,
      ]),
    );
  });

  it('does not draw a utilization band without a credit-limit anchor', () => {
    const { container } = render(<CardDailyPathPanel projection={projection} currency="INR" />);

    expect(
      screen.getByText(/A utilization band needs a credit limit on file/i),
    ).toBeInTheDocument();
    expect(container.querySelector('polygon')).not.toBeInTheDocument();
  });

  it('does not render a path panel when the projection is unavailable', () => {
    const { container } = render(
      <CardDailyPathPanel
        projection={{ ...projection, status: 'needs_activity', daily_path: [] }}
        currency="INR"
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
