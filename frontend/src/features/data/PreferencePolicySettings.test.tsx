import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PreferencePolicySettings } from './PreferencePolicySettings';

const mocks = vi.hoisted(() => ({
  current: vi.fn(),
  history: vi.fn(),
  save: vi.fn(),
  rollback: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', currency: 'INR' },
  }),
}));

vi.mock('@/lib/api', () => ({
  preferencePolicyApi: mocks,
}));

function renderPolicy() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PreferencePolicySettings />
    </QueryClientProvider>,
  );
}

describe('PreferencePolicySettings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.current.mockResolvedValue({
      id: 'policy-2',
      user_id: 'user-1',
      version: 2,
      based_on_version: 1,
      created_at: '2026-09-24T10:00:00Z',
      policy: {
        alert_threshold_pct: 25,
        briefing_cadence: 'weekly',
        reserve_floor: 5000,
        dismissed_recommendation_kinds: ['recurring'],
        excluded_recommendation_types: ['budget'],
        excluded_merchants: ['fuel'],
        excluded_categories: ['shopping'],
      },
    });
    mocks.history.mockResolvedValue([
      {
        id: 'policy-2',
        user_id: 'user-1',
        version: 2,
        based_on_version: 1,
        created_at: '2026-09-24T10:00:00Z',
        policy: {
          alert_threshold_pct: 25,
          briefing_cadence: 'weekly',
          reserve_floor: 5000,
          dismissed_recommendation_kinds: ['recurring'],
          excluded_recommendation_types: ['budget'],
          excluded_merchants: ['fuel'],
          excluded_categories: ['shopping'],
        },
      },
      {
        id: 'policy-1',
        user_id: 'user-1',
        version: 1,
        based_on_version: null,
        created_at: '2026-09-20T10:00:00Z',
        policy: {
          alert_threshold_pct: 20,
          briefing_cadence: 'daily',
          reserve_floor: 0,
          dismissed_recommendation_kinds: [],
          excluded_recommendation_types: [],
          excluded_merchants: [],
          excluded_categories: [],
        },
      },
    ]);
    mocks.save.mockResolvedValue({
      id: 'policy-3',
      user_id: 'user-1',
      version: 3,
      policy: {
        alert_threshold_pct: 30,
        briefing_cadence: 'weekly',
        reserve_floor: 7500,
        dismissed_recommendation_kinds: ['recurring'],
        excluded_recommendation_types: ['budget'],
        excluded_merchants: ['fuel', 'rent'],
        excluded_categories: ['shopping'],
      },
    });
    mocks.rollback.mockResolvedValue({
      id: 'policy-3',
      user_id: 'user-1',
      version: 3,
      based_on_version: 1,
      policy: {
        alert_threshold_pct: 20,
        briefing_cadence: 'daily',
        reserve_floor: 0,
        dismissed_recommendation_kinds: [],
        excluded_recommendation_types: [],
        excluded_merchants: [],
        excluded_categories: [],
      },
    });
  });

  it('shows the explicit policy and saves a validated new version', async () => {
    const user = userEvent.setup();
    renderPolicy();

    const threshold = await screen.findByLabelText('Alert threshold');
    expect(threshold).toHaveValue(25);
    expect(screen.getByText(/rules you choose, not learned behaviour/i)).toBeVisible();

    await user.clear(threshold);
    await user.type(threshold, '30');
    const reserve = screen.getByLabelText('Reserve floor');
    await user.clear(reserve);
    await user.type(reserve, '7500');
    const merchants = screen.getByLabelText('Excluded merchants');
    await user.clear(merchants);
    await user.type(merchants, 'fuel, rent, fuel');
    await user.click(screen.getByRole('button', { name: /save rules/i }));

    await waitFor(() => expect(mocks.save).toHaveBeenCalledTimes(1));
    expect(mocks.save).toHaveBeenCalledWith('user-1', {
      alert_threshold_pct: 30,
      briefing_cadence: 'weekly',
      reserve_floor: 7500,
      dismissed_recommendation_kinds: ['recurring'],
      excluded_recommendation_types: ['budget'],
      excluded_merchants: ['fuel', 'rent'],
      excluded_categories: ['shopping'],
    });
  });

  it('keeps schema-bound validation inline before saving', async () => {
    const user = userEvent.setup();
    renderPolicy();

    const threshold = await screen.findByLabelText('Alert threshold');
    await user.clear(threshold);
    await user.type(threshold, '101');
    await user.click(screen.getByRole('button', { name: /save rules/i }));

    expect(await screen.findByText('Enter a threshold from 1 to 100.')).toBeVisible();
    expect(threshold).toHaveAttribute('aria-describedby', expect.stringContaining('error'));
    expect(mocks.save).not.toHaveBeenCalled();
  });

  it('confirms rollback and appends a copied policy version', async () => {
    const user = userEvent.setup();
    renderPolicy();

    await screen.findByText('Version 1');
    await user.click(screen.getAllByRole('button', { name: /roll back/i })[1]);
    expect(screen.getByRole('dialog', { name: 'Roll back preference rules?' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: /create rollback version/i }));

    await waitFor(() => expect(mocks.rollback).toHaveBeenCalledWith('user-1', 1));
  });
});
