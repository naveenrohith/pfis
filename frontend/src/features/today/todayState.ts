import type { WorkspaceResponse } from '@/lib/types';

export type TodayFinancialState = 'healthy' | 'attention' | 'deficit' | 'low-data';

export type TodayStateKind =
  TodayFinancialState | 'stale' | 'loading' | 'partial-error' | 'full-error';

export type TodayUnavailableSignal = 'summary' | 'safe-to-spend' | 'action-status';

export interface TodayStaleSync {
  reason: 'age' | 'failed';
  lastSyncedAt: string | null;
}

export interface TodayState {
  /** The single state that leads the Today narrative, in documented precedence order. */
  kind: TodayStateKind;
  financial: TodayFinancialState | null;
  stale: TodayStaleSync | null;
  unavailable: TodayUnavailableSignal[];
}

export interface TodayStateInput {
  data?: WorkspaceResponse;
  workspaceLoading: boolean;
  workspaceError: boolean;
  cashPlanError: boolean;
  decisionsError: boolean;
  syncRunning: boolean;
  now: number;
}

export const STALE_SYNC_AFTER_MS = 24 * 60 * 60 * 1000;
const RECURRING_BURDEN_ATTENTION_PCT = 35;

export function deriveTodayState(input: TodayStateInput): TodayState {
  const { data } = input;
  if (!data) {
    return {
      kind: input.workspaceLoading || !input.workspaceError ? 'loading' : 'full-error',
      financial: null,
      stale: null,
      unavailable: [],
    };
  }

  const unavailable: TodayUnavailableSignal[] = [];
  if (input.workspaceError) unavailable.push('summary');
  if (input.cashPlanError) unavailable.push('safe-to-spend');
  if (input.decisionsError) unavailable.push('action-status');

  const financial = deriveFinancialState(data);
  const stale = input.syncRunning ? null : deriveStaleSync(data, input.now);

  let kind: TodayStateKind = financial;
  if (financial !== 'low-data') {
    if (stale) kind = 'stale';
    else if (unavailable.length) kind = 'partial-error';
  }

  return { kind, financial, stale, unavailable };
}

function deriveFinancialState(data: WorkspaceResponse): TodayFinancialState {
  const snapshot = data.snapshot;
  if (
    (snapshot?.transaction_count ?? 0) === 0 ||
    data.financial_health?.data_sufficiency === 'low'
  ) {
    return 'low-data';
  }
  if ((snapshot?.net_cash_flow ?? 0) < 0) return 'deficit';

  const projectedShortfall = (data.projection?.projected_net ?? 0) < 0;
  const budgetPressure = (snapshot?.budget_risk_count ?? 0) > 0;
  const recurringPressure =
    (data.financial_health?.recurring_burden ?? 0) > RECURRING_BURDEN_ATTENTION_PCT;
  const warningEvidence = (data.insights ?? []).some(
    (insight) => insight.severity === 'warning' || insight.severity === 'danger',
  );
  return projectedShortfall || budgetPressure || recurringPressure || warningEvidence
    ? 'attention'
    : 'healthy';
}

function deriveStaleSync(data: WorkspaceResponse, now: number): TodayStaleSync | null {
  const summary = data.sync_summary;
  const lastSyncedAt = summary?.last_synced_at ?? null;
  if (summary?.latest_status === 'failed') return { reason: 'failed', lastSyncedAt };
  if (!lastSyncedAt) return null;
  const syncedAt = new Date(lastSyncedAt).getTime();
  if (Number.isNaN(syncedAt) || now - syncedAt <= STALE_SYNC_AFTER_MS) return null;
  return { reason: 'age', lastSyncedAt };
}
