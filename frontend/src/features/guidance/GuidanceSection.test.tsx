import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GuidanceSection } from './GuidanceSection';

const mocks = vi.hoisted(() => ({
  notify: vi.fn(),
  scrollTo: vi.fn(),
  guidanceQuery: vi.fn(),
  setGuidanceState: vi.fn(),
  guidanceDecisions: vi.fn(),
  guidanceOutcomes: vi.fn(),
  recordGuidanceOutcome: vi.fn(),
}));

vi.mock('motion/react', () => ({
  motion: {
    div: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  },
  useReducedMotion: () => true,
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'user-1' } }),
}));

vi.mock('@/features/workspace/WorkspaceContext', () => ({
  useWorkspace: () => ({ month: 7, year: 2026 }),
}));

vi.mock('@/app/DashboardUiContext', () => ({
  useDashboardUi: () => ({ scrollTo: mocks.scrollTo }),
}));

vi.mock('@/components/ui/Toast', () => ({
  useToast: () => ({ notify: mocks.notify }),
}));

vi.mock('@/features/workspace/queries', () => ({
  queryKeys: { guidanceBrief: (...parts: unknown[]) => ['guidance', ...parts] },
  useGuidanceBrief: () => ({
    isLoading: false,
    data: {
      headline: 'Review uncertain activity',
      summary: '1 transparent action is ready.',
      health_score: 64,
      changes: [],
      actions: [
        {
          id: 'recommendation-1',
          type: 'review',
          priority: 80,
          title: '1 transaction needs review',
          description: 'Confirm the uncertain record.',
          action_label: 'Open review queue',
          target: 'review',
          reason_codes: ['review', 'warning'],
          evidence: [],
          expected_impact: 'Improve the reliability of financial totals.',
        },
      ],
      data_through: '2026-07-31',
      ruleset_version: 'pfis-guidance-3',
    },
  }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    guidanceQuery: mocks.guidanceQuery,
    setGuidanceState: mocks.setGuidanceState,
    guidanceDecisions: mocks.guidanceDecisions,
    guidanceOutcomes: mocks.guidanceOutcomes,
    recordGuidanceOutcome: mocks.recordGuidanceOutcome,
  },
}));

function renderGuidance() {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <GuidanceSection />
    </QueryClientProvider>,
  );
}

describe('GuidanceSection recommendation decisions', () => {
  beforeEach(() => {
    mocks.notify.mockReset();
    mocks.scrollTo.mockReset();
    mocks.guidanceQuery.mockReset();
    mocks.setGuidanceState.mockReset();
    mocks.guidanceDecisions.mockReset();
    mocks.guidanceOutcomes.mockReset();
    mocks.recordGuidanceOutcome.mockReset();
    mocks.setGuidanceState.mockResolvedValue({ state: 'accepted' });
    mocks.guidanceDecisions.mockResolvedValue([]);
    mocks.guidanceOutcomes.mockResolvedValue([]);
  });

  it('records acceptance for the selected financial period', async () => {
    renderGuidance();

    fireEvent.click(screen.getByRole('button', { name: 'Use this action' }));

    await waitFor(() =>
      expect(mocks.setGuidanceState).toHaveBeenCalledWith(
        'user-1',
        'recommendation-1',
        'accepted',
        undefined,
        '2026-07-01',
      ),
    );
    expect(mocks.notify).toHaveBeenCalledWith('Action added to your decisions', 'success');
  });

  it('records not-relevant feedback and labels the question input', async () => {
    renderGuidance();

    expect(
      screen.getByRole('textbox', { name: 'Ask PFIS about the selected month' }),
    ).toHaveAttribute('autocomplete', 'off');
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Mark 1 transaction needs review as not relevant',
      }),
    );

    await waitFor(() =>
      expect(mocks.setGuidanceState).toHaveBeenCalledWith(
        'user-1',
        'recommendation-1',
        'not_relevant',
        undefined,
        '2026-07-01',
      ),
    );
    expect(mocks.notify).toHaveBeenCalledWith('Marked as not relevant', 'success');
  });

  it('shows the grounded sources, limits, and explainable query plan', async () => {
    mocks.guidanceQuery.mockResolvedValue({
      supported: true,
      intent: 'monthly_spend',
      answer: 'You spent ₹12,000 this month.',
      metrics: [],
      filters: { month: 7, year: 2026 },
      plan: ['Classify a typed financial intent', 'Read transactions with a 2026-07 cutoff'],
      evidence: [
        {
          source_type: 'transactions',
          source_id: null,
          label: 'Grounded source',
          value: 'transactions read model for 2026-07',
          cutoff: '2026-07-01',
        },
      ],
      uncertainty: ['The answer is limited to eligible records.'],
      confidence: 0.9,
      temporal_scope: 'selected_calendar_month',
      suggested_actions: [],
      supported_examples: [],
      ruleset_version: 'pfis-guidance-3',
    });

    renderGuidance();
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask PFIS about the selected month' }), {
      target: { value: 'How much did I spend this month?' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Ask PFIS' }));

    await waitFor(() => expect(screen.getByText('Evidence & limits')).toBeInTheDocument());
    expect(screen.getByText(/Confidence/)).toBeInTheDocument();
    expect(screen.getByText(/Transactions · through/)).toBeInTheDocument();
    expect(screen.getByText('Known limits')).toBeInTheDocument();
    expect(screen.getByText('How PFIS reached this answer')).toBeInTheDocument();
  });
});
