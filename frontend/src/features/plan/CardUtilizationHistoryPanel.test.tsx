import { fireEvent, render, screen } from '@testing-library/react';
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
    expect(screen.getByRole('img', { name: /Utilization moved from 18.0%/i })).toBeInTheDocument();
    expect(screen.getByText(/Some settled rows still need review/)).toBeInTheDocument();

    fireEvent.click(screen.getByText('View 2 recent evidence points'));

    expect(
      screen.getByRole('table', { name: 'Recent card utilization evidence points' }),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Settled-ledger estimate')).not.toHaveLength(0);
    expect(screen.getByText('Over target')).toBeInTheDocument();
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
