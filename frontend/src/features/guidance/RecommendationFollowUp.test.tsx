import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RecommendationFollowUp } from './RecommendationFollowUp';

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  guidanceDecisions: vi.fn(),
  guidanceOutcomes: vi.fn(),
  recordGuidanceOutcome: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1' } }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify: mocks.notify }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    guidanceDecisions: mocks.guidanceDecisions,
    guidanceOutcomes: mocks.guidanceOutcomes,
    recordGuidanceOutcome: mocks.recordGuidanceOutcome,
  },
}));

function renderFollowUp() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <RecommendationFollowUp />
    </QueryClientProvider>,
  );
}

describe('RecommendationFollowUp', () => {
  beforeEach(() => {
    mocks.notify.mockReset();
    mocks.guidanceDecisions.mockReset();
    mocks.guidanceOutcomes.mockReset();
    mocks.recordGuidanceOutcome.mockReset();
    mocks.guidanceDecisions.mockResolvedValue([
      {
        id: 'decision-1',
        recommendation_id: 'recommendation-1',
        state: 'accepted',
        title: 'Review uncertain activity',
        expected_impact: 'Improve the reliability of financial totals.',
        baseline_metric_value: 3,
        baseline_metric_unit: 'records',
        updated_at: '2026-07-31T10:00:00Z',
      },
    ]);
    mocks.guidanceOutcomes.mockResolvedValue([]);
    mocks.recordGuidanceOutcome.mockResolvedValue({ decision_id: 'decision-1' });
  });

  it('shows the captured baseline and records a one-time outcome', async () => {
    renderFollowUp();

    expect(await screen.findByText(/Baseline:\s+3 records/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'It helped' }));

    await waitFor(() =>
      expect(mocks.recordGuidanceOutcome).toHaveBeenCalledWith('user-1', 'decision-1', 'helped'),
    );
    expect(mocks.notify).toHaveBeenCalledWith('Outcome recorded', 'success');
  });

  it('shows the measured result after an outcome is recorded', async () => {
    mocks.guidanceOutcomes.mockResolvedValue([
      {
        id: 'outcome-1',
        decision_id: 'decision-1',
        outcome: 'helped',
        baseline_metric_value: 3,
        observed_metric_value: 1,
        automatic_impact_value: 2,
        metric_key: 'unresolved_review_count',
        metric_unit: 'records',
        outcome_ruleset_version: 'pfis-recommendation-outcome-1',
        observed_at: '2026-07-31T11:00:00Z',
      },
    ]);
    renderFollowUp();

    expect(await screen.findByText('Helped')).toBeInTheDocument();
    expect(screen.getByText('2 records measured improvement')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'It helped' })).not.toBeInTheDocument();
  });

  it('does not show outcome choices when saved outcomes cannot be verified', async () => {
    mocks.guidanceOutcomes.mockRejectedValueOnce(new Error('temporarily unavailable'));
    renderFollowUp();

    expect(await screen.findByText('Outcome history is unavailable')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'It helped' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Retry outcome history' }));
    expect(await screen.findByRole('button', { name: 'It helped' })).toBeInTheDocument();
  });

  it('offers a retry instead of disappearing when decisions cannot be loaded', async () => {
    mocks.guidanceDecisions.mockRejectedValueOnce(new Error('temporarily unavailable'));
    renderFollowUp();

    expect(await screen.findByText('Action history is unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry action history' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'It helped' })).not.toBeInTheDocument();
  });
});
