import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CardUtilizationHistoryPanel } from './CardUtilizationHistoryPanel';
import type { CardUtilizationHistory } from '@/lib/types';

const history: CardUtilizationHistory = {
  financial_account_id: 'card-1',
  as_of: '2026-08-10',
  utilization_target_pct: 30,
  statement_points: [
    {
      as_of: '2026-07-01',
      basis: 'issuer_statement',
      statement_id: 'statement-1',
      balance: 18000,
      credit_limit: 100000,
      utilization_pct: 18,
      status: 'within_target',
      source_transaction_count: 0,
      confidence: 1,
      reason_codes: ['issuer_statement_total_due'],
    },
  ],
  daily_points: [
    {
      as_of: '2026-08-10',
      basis: 'ledger_estimate',
      statement_id: 'statement-1',
      balance: 34500,
      credit_limit: 100000,
      utilization_pct: 34.5,
      status: 'over_target',
      source_transaction_count: 4,
      confidence: 0.64,
      reason_codes: ['unreviewed_activity_included'],
    },
  ],
  trend: 'worsening',
  trend_basis: 'issuer_to_current_estimate',
  trend_delta_pct: 16.5,
  peak_statement_utilization_pct: 18,
  peak_daily_utilization_pct: 34.5,
  target_breach_count: 1,
  credit_limit_breach_count: 0,
  reason_codes: ['unreviewed_activity_included'],
  assumptions: [],
  ruleset_version: 'pfis-card-utilization-history-1',
};

describe('CardUtilizationHistoryPanel', () => {
  it('shows a semantic evidence table when expanded', () => {
    render(<CardUtilizationHistoryPanel history={history} currency="INR" />);

    expect(screen.getByRole('heading', { name: 'Moving up' })).toBeInTheDocument();
    expect(screen.getAllByText(/Utilization moved from 18.0%/i)).toHaveLength(2);
    expect(screen.getByText(/Some settled rows still need review/)).toBeInTheDocument();

    fireEvent.click(screen.getByText('View all 2 plotted evidence points'));

    expect(
      screen.getByRole('table', { name: 'All plotted card utilization evidence points' }),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Settled-ledger estimate')).not.toHaveLength(0);
    expect(screen.getByText('Over target')).toBeInTheDocument();
  });

  it('keeps every plotted source point in chronological order in the evidence table', () => {
    const completeHistory: CardUtilizationHistory = {
      ...history,
      statement_points: Array.from({ length: 12 }, (_, index) => ({
        ...history.statement_points[0],
        as_of: `2025-01-${String(index + 1).padStart(2, '0')}`,
        statement_id: `statement-${index + 1}`,
        utilization_pct: 10 + index,
      })),
      daily_points: Array.from({ length: 10 }, (_, index) => ({
        ...history.daily_points[0],
        as_of: `2026-08-${String(index + 1).padStart(2, '0')}`,
        utilization_pct: 20 + index,
      })),
    };
    render(<CardUtilizationHistoryPanel history={completeHistory} currency="INR" />);

    fireEvent.click(screen.getByText('View all 22 plotted evidence points'));

    const table = screen.getByRole('table', {
      name: 'All plotted card utilization evidence points',
    });
    const rows = within(table).getAllByRole('row');
    expect(rows).toHaveLength(23);
    expect(rows[1]).toHaveTextContent('Issuer statement');
    expect(rows[22]).toHaveTextContent('Settled-ledger estimate');
    expect(rows[1]).toHaveTextContent('2025');
    expect(rows[22]).toHaveTextContent('2026');
  });

  it('plots statement and ledger estimates as separate evidence segments', () => {
    const segmentedHistory: CardUtilizationHistory = {
      ...history,
      statement_points: [
        ...history.statement_points,
        {
          ...history.statement_points[0],
          as_of: '2026-06-01',
          statement_id: 'statement-0',
          balance: 15000,
          utilization_pct: 15,
        },
      ],
      daily_points: [
        ...history.daily_points,
        {
          ...history.daily_points[0],
          as_of: '2026-08-12',
          balance: 35000,
          utilization_pct: 35,
        },
      ],
    };
    const { container } = render(
      <CardUtilizationHistoryPanel history={segmentedHistory} currency="INR" />,
    );

    expect(container.querySelectorAll('polyline')).toHaveLength(2);
    expect(container.querySelector('polyline.text-muted-foreground')).toHaveAttribute(
      'stroke-dasharray',
      '3 2',
    );
  });

  it('gives the user a next step when history is empty or unavailable', () => {
    const { rerender } = render(<CardUtilizationHistoryPanel currency="INR" />);

    expect(
      screen.getByRole('heading', { name: 'Import a statement to see the cycle story' }),
    ).toBeInTheDocument();

    rerender(<CardUtilizationHistoryPanel currency="INR" error={new Error('network')} />);

    expect(
      screen.getByRole('alert', { name: 'Utilization history needs review' }),
    ).toHaveTextContent('Refresh the workspace or import the latest statement');
  });
});
