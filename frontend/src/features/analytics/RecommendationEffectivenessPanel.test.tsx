import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RecommendationEffectivenessPanel } from './RecommendationEffectivenessPanel';

const mocks = vi.hoisted(() => ({ guidanceEffectiveness: vi.fn() }));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1' } }),
}));

vi.mock('@/lib/api', () => ({
  api: { guidanceEffectiveness: mocks.guidanceEffectiveness },
}));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RecommendationEffectivenessPanel />
    </QueryClientProvider>,
  );
}

describe('RecommendationEffectivenessPanel', () => {
  beforeEach(() => {
    mocks.guidanceEffectiveness.mockReset();
  });

  it('explains the privacy threshold instead of exposing a small cohort', async () => {
    mocks.guidanceEffectiveness.mockResolvedValue({
      evidence_status: 'insufficient_sample',
      minimum_sample_size: 10,
      minimum_unique_users: 5,
      window_days: 180,
      eligible_outcome_count: 0,
      suppressed_cohort_count: 1,
      cohorts: [],
    });

    renderPanel();

    expect(await screen.findByText('Evidence is still accumulating')).toBeInTheDocument();
    expect(
      screen.getByText(/at least 10 immutable outcomes from 5 different users/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/review recommendation evidence/i)).not.toBeInTheDocument();
  });

  it('keeps reported and measured effectiveness visibly separate', async () => {
    mocks.guidanceEffectiveness.mockResolvedValue({
      evidence_status: 'available',
      minimum_sample_size: 10,
      minimum_unique_users: 5,
      window_days: 180,
      eligible_outcome_count: 10,
      suppressed_cohort_count: 0,
      cohorts: [
        {
          recommendation_type: 'review',
          guidance_ruleset_version: 'pfis-guidance-3',
          outcome_ruleset_version: 'pfis-recommendation-outcome-1',
          metric_key: 'unresolved_review_count',
          metric_unit: 'records',
          sample_size: 10,
          unique_users: 5,
          completed_rate: 1,
          helped_rate: 0.6,
          measured_evidence_status: 'available',
          measured_sample_size: 10,
          measured_improvement_rate: 0.5,
          mean_automatic_impact: 1.2,
          user_measurement_agreement_rate: 0.7,
        },
      ],
    });

    renderPanel();

    expect(
      await screen.findByRole('region', { name: 'Review recommendation evidence' }),
    ).toBeInTheDocument();
    expect(screen.getByText('60%')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByText('1.2 records')).toBeInTheDocument();
    expect(screen.getByText(/agreed in 70%/i)).toBeInTheDocument();
  });
});
