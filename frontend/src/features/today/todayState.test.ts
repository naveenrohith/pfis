import { describe, expect, it } from 'vitest';
import type { WorkspaceResponse } from '@/lib/types';
import { deriveTodayState, STALE_SYNC_AFTER_MS, type TodayStateInput } from './todayState';

const NOW = Date.parse('2026-07-20T12:00:00Z');

function workspace(
  overrides: {
    net?: number;
    count?: number;
    sufficiency?: 'low' | 'medium' | 'high';
    projectedNet?: number;
    budgetRisk?: number;
    recurringBurden?: number;
    severity?: 'info' | 'success' | 'warning' | 'danger';
    lastSyncedAt?: string | null;
    latestStatus?: string | null;
  } = {},
): WorkspaceResponse {
  return {
    snapshot: {
      net_cash_flow: overrides.net ?? 1000,
      transaction_count: overrides.count ?? 12,
      budget_risk_count: overrides.budgetRisk ?? 0,
    },
    projection:
      overrides.projectedNet === undefined ? undefined : { projected_net: overrides.projectedNet },
    financial_health: {
      data_sufficiency: overrides.sufficiency ?? 'high',
      recurring_burden: overrides.recurringBurden ?? 10,
    },
    insights: overrides.severity
      ? [{ title: 't', description: 'd', severity: overrides.severity }]
      : [],
    sync_summary: {
      last_synced_at: overrides.lastSyncedAt ?? null,
      latest_status: overrides.latestStatus ?? null,
      processed_total: 0,
      unprocessed_total: 0,
    },
  } as unknown as WorkspaceResponse;
}

function derive(input: Partial<TodayStateInput>) {
  return deriveTodayState({
    workspaceLoading: false,
    workspaceError: false,
    cashPlanError: false,
    decisionsError: false,
    syncRunning: false,
    now: NOW,
    ...input,
  });
}

describe('deriveTodayState', () => {
  it('distinguishes loading from a full error when no workspace data exists', () => {
    expect(derive({ workspaceLoading: true }).kind).toBe('loading');
    expect(derive({ workspaceError: true }).kind).toBe('full-error');
  });

  it('classifies financial narratives from existing workspace values', () => {
    expect(derive({ data: workspace() }).kind).toBe('healthy');
    expect(derive({ data: workspace({ projectedNet: -1 }) }).kind).toBe('attention');
    expect(derive({ data: workspace({ budgetRisk: 1 }) }).kind).toBe('attention');
    expect(derive({ data: workspace({ recurringBurden: 40 }) }).kind).toBe('attention');
    expect(derive({ data: workspace({ severity: 'warning' }) }).kind).toBe('attention');
    expect(derive({ data: workspace({ net: -1, projectedNet: -5 }) }).kind).toBe('deficit');
    expect(derive({ data: workspace({ count: 0 }) }).kind).toBe('low-data');
    expect(derive({ data: workspace({ sufficiency: 'low', net: -1 }) }).kind).toBe('low-data');
  });

  it('marks sync as stale after the age threshold or a failed latest run', () => {
    const recent = new Date(NOW - STALE_SYNC_AFTER_MS).toISOString();
    const old = new Date(NOW - STALE_SYNC_AFTER_MS - 1).toISOString();

    expect(derive({ data: workspace({ lastSyncedAt: recent }) }).stale).toBeNull();
    expect(derive({ data: workspace({ lastSyncedAt: old }) })).toMatchObject({
      kind: 'stale',
      financial: 'healthy',
      stale: { reason: 'age', lastSyncedAt: old },
    });
    expect(derive({ data: workspace({ latestStatus: 'failed' }) }).stale).toEqual({
      reason: 'failed',
      lastSyncedAt: null,
    });
    expect(derive({ data: workspace({ lastSyncedAt: old }), syncRunning: true }).stale).toBeNull();
  });

  it('keeps usable data visible and lists unavailable signals as a partial error', () => {
    const state = derive({
      data: workspace({ net: -10 }),
      workspaceError: true,
      cashPlanError: true,
      decisionsError: true,
    });

    expect(state).toMatchObject({
      kind: 'partial-error',
      financial: 'deficit',
      unavailable: ['summary', 'safe-to-spend', 'action-status'],
    });
  });

  it('applies documented precedence: low data, then stale, then partial error', () => {
    const old = new Date(NOW - STALE_SYNC_AFTER_MS * 2).toISOString();
    expect(
      derive({ data: workspace({ count: 0, lastSyncedAt: old }), cashPlanError: true }).kind,
    ).toBe('low-data');
    expect(derive({ data: workspace({ lastSyncedAt: old }), cashPlanError: true }).kind).toBe(
      'stale',
    );
  });
});
