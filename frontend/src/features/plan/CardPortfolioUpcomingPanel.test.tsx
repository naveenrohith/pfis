import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CardPortfolioUpcomingPanel } from './CardPortfolioUpcomingPanel';
import type { CardPortfolioUpcomingState } from '@/lib/types';

const portfolio: CardPortfolioUpcomingState = {
  as_of: '2026-08-10',
  state: 'payment_due',
  card_count: 2,
  cards_with_due: 1,
  issuer_total_due: 13000,
  issuer_total_due_cards: 1,
  issuer_total_due_complete: false,
  earliest_due_date: '2026-08-25',
  estimated_outstanding_total: null,
  estimated_outstanding_cards: 1,
  estimated_outstanding_complete: false,
  next_event: {
    id: 'portfolio:card-1:payment_due',
    event_type: 'payment_due',
    date: '2026-08-25',
    days_from_today: 15,
    label: 'HDFC ending 9913: Payment due',
    amount: 13000,
    source_kind: 'issuer',
    status: 'observed',
    confidence: 1,
    reason_codes: ['issuer_due_date'],
  },
  events: [
    {
      id: 'portfolio:card-1:payment_due',
      event_type: 'payment_due',
      date: '2026-08-25',
      days_from_today: 15,
      label: 'HDFC ending 9913: Payment due',
      amount: 13000,
      source_kind: 'issuer',
      status: 'observed',
      confidence: 1,
      reason_codes: ['issuer_due_date'],
    },
    {
      id: 'portfolio:card-1:projected_charge',
      event_type: 'projected_charge',
      date: '2026-08-28',
      days_from_today: 18,
      label: 'Streaming renewal',
      amount: 899,
      source_kind: 'forecast',
      status: 'estimated',
      confidence: 0.66,
      reason_codes: ['same_card_recurring_candidate'],
    },
    {
      id: 'portfolio:card-2:target_breach',
      event_type: 'utilization_target_breach',
      date: '2026-08-30',
      days_from_today: 20,
      label: 'ICICI ending 4421: target pressure',
      amount: null,
      source_kind: 'forecast',
      status: 'risk',
      confidence: 0.58,
      reason_codes: ['projected_utilization_target_breach'],
    },
  ],
  cards_needing_review: 1,
  confidence: 0.72,
  reason_codes: ['partial_issuer_due_coverage'],
  evidence: [],
  assumptions: [],
  cards: [
    {
      financial_account_id: 'card-1',
      label: 'HDFC ending 9913',
      state: 'payment_due',
      next_event: {
        id: 'payment_due:card-1',
        event_type: 'payment_due',
        date: '2026-08-25',
        days_from_today: 15,
        label: 'Payment due',
        amount: 13000,
        source_kind: 'issuer',
        status: 'observed',
        confidence: 1,
        reason_codes: ['issuer_due_date'],
      },
      confidence: 1,
      total_due: 13000,
      due_date: '2026-08-25',
      estimated_current_outstanding: 14500,
      estimated_current_as_of: '2026-08-10',
      balance_status: 'estimated',
      projection_status: 'available',
      projected_statement_date: '2026-09-05',
      target_status: 'under_target',
      credit_limit_status: 'under_limit',
      reason_codes: [],
    },
    {
      financial_account_id: 'card-2',
      label: 'ICICI ending 4421',
      state: 'review_evidence',
      next_event: null,
      confidence: 0.44,
      total_due: null,
      due_date: null,
      estimated_current_outstanding: null,
      estimated_current_as_of: null,
      balance_status: 'needs_observation',
      projection_status: 'needs_current_position',
      projected_statement_date: null,
      target_status: 'unavailable',
      credit_limit_status: 'unavailable',
      reason_codes: ['missing_current_position'],
    },
  ],
  ruleset_version: 'pfis-card-portfolio-upcoming-1',
};

describe('CardPortfolioUpcomingPanel', () => {
  it('keeps the shared due view issuer-backed and per-card', () => {
    render(<CardPortfolioUpcomingPanel portfolio={portfolio} currency="INR" />);

    expect(screen.getByRole('heading', { name: 'Payment due next' })).toBeInTheDocument();
    expect(screen.getByText('Issuer total due')).toBeInTheDocument();
    expect(screen.getByText('NEXT SHARED ATTENTION')).toBeInTheDocument();
    expect(screen.getByText('HDFC ending 9913')).toBeInTheDocument();
    expect(screen.getByText('ICICI ending 4421')).toBeInTheDocument();
    expect(screen.getByText('No dated event in retained evidence')).toBeInTheDocument();
    expect(screen.getByText('Review 3 dated events')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Review 3 dated events'));
    expect(screen.getByText('Projected charge: Streaming renewal')).toBeInTheDocument();
    expect(screen.getByText('Evidence: same card recurring candidate')).toBeInTheDocument();
    expect(screen.getByText('1 risk signal')).toBeInTheDocument();
    expect(
      screen.getByText(/is not merged into a synthetic live balance or available-credit total/i),
    ).toBeInTheDocument();
  });

  it('stays hidden for a single-card portfolio and explains refresh failures', () => {
    const { container, rerender } = render(
      <CardPortfolioUpcomingPanel
        portfolio={{ ...portfolio, card_count: 1, cards: portfolio.cards.slice(0, 1) }}
        currency="INR"
      />,
    );

    expect(container).toBeEmptyDOMElement();

    rerender(<CardPortfolioUpcomingPanel currency="INR" error={new Error('network')} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Portfolio timeline needs a refresh');
  });
});
