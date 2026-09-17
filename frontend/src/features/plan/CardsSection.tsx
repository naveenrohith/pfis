import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Copy,
  CreditCard,
  Landmark,
  ReceiptText,
  RotateCcw,
  ShieldCheck,
} from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FinancialHero, LedgerRow } from '@/components/system';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input, Label, Select } from '@/components/ui/Input';
import { EmptyState } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthContext';
import {
  useAccountBalanceForecast,
  useAccounts,
  useCardDueRunway,
  useCardPortfolioPaymentPlan,
  useCardPortfolioUpcomingState,
  useCardUtilizationHistory,
} from '@/features/workspace/queries';
import { BalancePathPanel } from './FinancialPositionSection';
import { CardDailyPathPanel } from './CardDailyPathPanel';
import { CardPaymentScenarioPanel } from './CardPaymentScenarioPanel';
import { CardPortfolioPaymentPlanPanel } from './CardPortfolioPaymentPlanPanel';
import { CardPortfolioUpcomingPanel } from './CardPortfolioUpcomingPanel';
import { CardSpendRoutingPanel } from './CardSpendRoutingPanel';
import { api } from '@/lib/api';
import { dateInputValueInTimezone, formatCurrency, formatDate, formatTime } from '@/lib/format';
import type {
  CardCalendarEvent,
  CardDueRunway,
  CardEmiPlan,
  CardOverview,
  CardRefundTracker,
  CardStatementProjection,
  CardStatementLine,
} from '@/lib/types';
import { CardUtilizationHistoryPanel } from './CardUtilizationHistoryPanel';

const projectionStatusCopy: Record<
  Exclude<CardStatementProjection['status'], 'available'>,
  { title: string; detail: string }
> = {
  needs_recent_statement: {
    title: 'A current statement cycle is needed',
    detail: 'Import the latest statement before PFIS projects the next closing balance.',
  },
  needs_current_position: {
    title: 'A current balance anchor is needed',
    detail: 'Add a verified balance or fresh provider observation before forecasting.',
  },
  needs_credit_limit: {
    title: 'The credit limit is missing',
    detail: 'PFIS cannot calculate projected utilisation without issuer limit evidence.',
  },
  needs_activity: {
    title: 'More cycle activity is needed',
    detail: 'PFIS waits for at least three settled non-payment events before extrapolating.',
  },
};

const projectionActionCopy: Record<CardStatementProjection['next_state'], string> = {
  monitor_cycle: 'Keep monitoring this billing cycle.',
  reduce_spend_or_pay: 'Reduce new spend or plan a payment before the statement closes.',
  prepare_statement_payment: 'Prepare for the projected statement amount.',
  review_evidence: 'Review or refresh the missing evidence.',
};

const projectionTargetStatusCopy: Record<
  CardStatementProjection['target_status'],
  { label: string; tone: string }
> = {
  under_target: { label: 'Under target', tone: 'text-success' },
  at_risk: { label: 'At risk', tone: 'text-warning' },
  over_target: { label: 'Over target', tone: 'text-danger' },
  unavailable: { label: 'Target not set', tone: 'text-muted-foreground' },
};

const eventLabels: Record<CardStatementLine['card_event'], string> = {
  purchase: 'Purchase',
  payment: 'Card payment',
  refund: 'Refund',
  cashback: 'Cashback',
  fee: 'Fee',
  tax: 'Tax',
  interest: 'Interest',
  reversal: 'Reversal',
};

const outcomeLabels: Record<CardStatementLine['review_outcome'], string> = {
  matched: 'Matched',
  newly_imported: 'Imported',
  ignored_by_rule: 'Ignored',
  needs_review: 'Review',
};

function statementEventLabel(line: CardStatementLine): string {
  if (line.component_kind && line.component_kind !== 'ordinary') {
    return line.component_kind
      .replace(/^emi_/, 'EMI ')
      .replaceAll('_', ' ')
      .replace(/\b\w/g, (value) => value.toUpperCase());
  }
  return eventLabels[line.card_event];
}

function balanceStatusLabel(card: CardOverview): string {
  if (card.observed_source === 'connector') {
    if (card.coverage_status === 'fresh' && card.coverage_complete) {
      return 'Provider-observed · fresh';
    }
    if (card.coverage_status === 'overdue') {
      return 'Provider refresh is overdue';
    }
    return 'Provider observation needs review';
  }
  switch (card.balance_status) {
    case 'estimated':
      return 'Estimated from settled activity';
    case 'observed':
      return 'Observed anchor';
    case 'needs_review':
      return 'Estimate needs review';
    case 'stale':
      return 'Observed anchor is stale';
    case 'incomplete':
      return 'History is incomplete';
    default:
      return 'Needs a verified anchor';
  }
}

function StatementAmount({
  label,
  value,
  currency,
  operator,
}: {
  label: string;
  value?: number | null;
  currency: string;
  operator?: 'minus' | 'plus' | 'equals';
}) {
  return (
    <div className="relative min-w-0 border-b border-border/65 py-4 sm:border-b-0 sm:border-r sm:px-4 sm:first:pl-0 sm:last:border-r-0 sm:last:pr-0">
      {operator ? (
        <span
          aria-hidden="true"
          className="absolute -left-2.5 top-1/2 hidden h-5 w-5 -translate-y-1/2 place-items-center rounded-full bg-muted text-xs font-extrabold text-muted-foreground sm:grid"
        >
          {operator === 'minus' ? '−' : operator === 'plus' ? '+' : '='}
        </span>
      ) : null}
      <p className="text-xs font-bold leading-5 text-muted-foreground">{label}</p>
      <p className="money-value mt-1 text-base font-extrabold">
        {value == null ? '—' : formatCurrency(value, currency)}
      </p>
    </div>
  );
}

function CardStatementProjectionPanel({
  projection,
  currency,
  targetPct,
}: {
  projection: CardStatementProjection;
  currency: string;
  targetPct?: number | null;
}) {
  if (projection.status !== 'available') {
    const copy = projectionStatusCopy[projection.status];
    return (
      <section
        className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
        aria-labelledby="next-statement-forecast"
      >
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
            <CalendarDays className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              NEXT STATEMENT FORECAST
            </p>
            <h2 id="next-statement-forecast" className="mt-1 text-lg font-extrabold">
              {copy.title}
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{copy.detail}</p>
          </div>
        </div>
      </section>
    );
  }

  const targetCopy = projectionTargetStatusCopy[projection.target_status];
  const targetLabel =
    targetPct == null ? 'your utilization target' : `${targetPct.toFixed(1)}% target`;
  const targetRunwayDetail =
    projection.target_status === 'under_target'
      ? `${formatCurrency(projection.target_headroom_amount ?? 0, currency)} projected headroom at close against your ${targetLabel}.`
      : projection.target_status === 'at_risk'
        ? `The uncertainty range crosses your ${targetLabel}; ${formatCurrency(projection.target_headroom_amount ?? 0, currency)} central headroom remains.`
        : projection.target_status === 'over_target'
          ? `Projected ${formatCurrency(projection.target_excess_amount ?? 0, currency)} above your ${targetLabel} at close.`
          : 'Set a utilization target to see statement-close headroom.';
  const targetBreachDetail =
    projection.target_breach_date != null
      ? projection.target_breach_days === 0
        ? 'The central path is already at or above this target today.'
        : `The central path reaches this target in ${projection.target_breach_days} day${projection.target_breach_days === 1 ? '' : 's'} · ${formatDate(projection.target_breach_date)}.`
      : projection.target_status === 'at_risk'
        ? 'The central path stays below target, but the upper uncertainty band crosses it before close.'
        : 'The central path does not cross this target before the projected close.';

  return (
    <section
      className="rounded-xl border border-intelligence/20 bg-intelligence/5 p-5 sm:p-6"
      aria-labelledby="next-statement-forecast"
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(17rem,0.55fr)] lg:items-start">
        <div>
          <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
            NEXT STATEMENT FORECAST
          </p>
          <h2
            id="next-statement-forecast"
            className="mt-1 text-xl font-extrabold tracking-[-0.03em]"
          >
            {projection.projected_balance == null
              ? 'Projection unavailable'
              : formatCurrency(projection.projected_balance, currency)}
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Estimated closing balance for{' '}
            {projection.projected_statement_date
              ? formatDate(projection.projected_statement_date)
              : 'the next statement'}
            . This is a pace-based estimate, not an issuer amount.
          </p>
          <p
            className="mt-2 text-xs leading-5 text-muted-foreground"
            aria-label="Forecast calibration"
          >
            {projection.calibration === 'historical_blend'
              ? `Calibrated against ${projection.historical_sample_count} prior settled card cycles.`
              : 'Uses current-cycle settled activity only.'}
            {projection.known_future_payment_total > 0
              ? ` Includes a ${formatCurrency(projection.known_future_payment_total, currency)} planned payment before close.`
              : ''}
            {projection.known_future_charge_total > 0
              ? ` Includes ${formatCurrency(projection.known_future_charge_total, currency)} of scheduled card charges.`
              : ''}
            {projection.known_future_recurring_charge_total > 0
              ? ` Includes ${formatCurrency(projection.known_future_recurring_charge_total, currency)} from ${projection.recurring_charge_candidates.length} recurring charge candidate${projection.recurring_charge_candidates.length === 1 ? '' : 's'}.`
              : ''}
          </p>
          {projection.potential_pending_refund_total > 0 ? (
            <p
              className="mt-2 text-xs leading-5 text-muted-foreground"
              aria-label="Pending refund projection"
            >
              Pending refund evidence may lower the range by up to{' '}
              {formatCurrency(projection.potential_pending_refund_total, currency)}. The central
              estimate excludes it until settlement is observed.
            </p>
          ) : null}
          {projection.recurring_charge_candidates.length > 0 ? (
            <section
              className="mt-4 rounded-lg border border-border/65 bg-card/65 p-3"
              aria-label="Recurring charge candidates"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                  PREDICTABLE CARD CHARGES
                </p>
                <p className="text-xs font-bold text-muted-foreground">Estimate only</p>
              </div>
              <ul className="mt-2 space-y-2">
                {projection.recurring_charge_candidates.slice(0, 4).map((candidate) => (
                  <li
                    key={`${candidate.merchant}-${candidate.expected_date}`}
                    className="flex items-start justify-between gap-3 text-sm"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-bold">{candidate.merchant}</span>
                      <span className="block text-xs text-muted-foreground">
                        {candidate.expected_date_low !== candidate.expected_date_high
                          ? `Expected ${formatDate(candidate.expected_date_low)}–${formatDate(candidate.expected_date_high)}`
                          : `Expected ${formatDate(candidate.expected_date)}`}{' '}
                        · {candidate.cadence ?? 'recurring'} ·{' '}
                        {Math.round(candidate.confidence * 100)}% confidence
                      </span>
                    </span>
                    <span className="money-value shrink-0 font-extrabold">
                      {candidate.expected_amount_low !== candidate.expected_amount ||
                      candidate.expected_amount_high !== candidate.expected_amount
                        ? `${formatCurrency(candidate.expected_amount_low, currency)}–${formatCurrency(candidate.expected_amount_high, currency)}`
                        : formatCurrency(candidate.expected_amount, currency)}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                PFIS found these merchant cadences in settled card history. They can shift the
                projection. When the history moves in amount, the displayed band widens the
                estimate. When the history moves in timing, the displayed date window keeps the
                central path unchanged; these are not issuer-confirmed charges or payment
                instructions.
              </p>
            </section>
          ) : null}
          <dl className="mt-5 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg bg-card/80 p-3">
              <dt className="text-xs font-bold text-muted-foreground">Uncertainty range</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {projection.range_low == null || projection.range_high == null
                  ? 'Unavailable'
                  : `${formatCurrency(projection.range_low, currency)} - ${formatCurrency(projection.range_high, currency)}`}
              </dd>
            </div>
            <div className="rounded-lg bg-card/80 p-3">
              <dt className="text-xs font-bold text-muted-foreground">Projected utilisation</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {projection.projected_utilization_pct == null
                  ? 'Unavailable'
                  : `${projection.projected_utilization_pct.toFixed(1)}%`}
              </dd>
            </div>
            <div className="rounded-lg bg-card/80 p-3">
              <dt className="text-xs font-bold text-muted-foreground">Confidence</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {Math.round(projection.confidence * 100)}%
              </dd>
            </div>
          </dl>
          <div
            className="mt-4 rounded-lg border border-border/65 bg-card/65 p-3"
            aria-label="Utilization target runway"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                UTILIZATION TARGET RUNWAY
              </p>
              <p className={`text-xs font-extrabold ${targetCopy.tone}`}>{targetCopy.label}</p>
            </div>
            <p className="mt-1 text-sm font-bold leading-6">{targetRunwayDetail}</p>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">{targetBreachDetail}</p>
          </div>
        </div>
        <aside className="rounded-lg bg-card/85 p-4" aria-label="Forecast evidence and next action">
          <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
            RECOMMENDED NEXT STATE
          </p>
          <p className="mt-2 text-sm font-extrabold leading-6">
            {projectionActionCopy[projection.next_state]}
          </p>
          <dl className="mt-4 space-y-3 border-t border-border/65 pt-4">
            {projection.evidence.map((item) => (
              <div key={item.label}>
                <dt className="text-xs font-bold text-muted-foreground">{item.label}</dt>
                <dd className="mt-0.5 text-sm font-extrabold">{item.value}</dd>
              </div>
            ))}
          </dl>
        </aside>
      </div>
    </section>
  );
}

function OutcomeBadge({ outcome }: { outcome: CardStatementLine['review_outcome'] }) {
  const className =
    outcome === 'needs_review'
      ? 'bg-warning/12 text-warning'
      : outcome === 'matched'
        ? 'bg-success/12 text-success'
        : 'bg-muted text-muted-foreground';
  return (
    <span
      className={`inline-flex min-h-6 items-center rounded-full px-2 text-xs font-bold ${className}`}
    >
      {outcomeLabels[outcome]}
    </span>
  );
}

const refundStatusCopy: Record<
  CardRefundTracker['status'],
  { label: string; tone: string; iconTone: string }
> = {
  clear: { label: 'No pending refunds', tone: 'text-success', iconTone: 'text-success' },
  pending: { label: 'Refunds in flight', tone: 'text-warning', iconTone: 'text-warning' },
  needs_review: { label: 'Review refund evidence', tone: 'text-danger', iconTone: 'text-danger' },
};

function CardRefundTrackerPanel({
  tracker,
  currency,
}: {
  tracker: CardRefundTracker;
  currency: string;
}) {
  const copy = refundStatusCopy[tracker.status];
  const pendingDetail =
    tracker.pending_count > 0
      ? `${formatCurrency(tracker.pending_amount, currency)} across ${tracker.pending_count} pending refund${tracker.pending_count === 1 ? '' : 's'}${tracker.oldest_pending_date ? ` · oldest ${formatDate(tracker.oldest_pending_date)}` : ''}.`
      : 'No explicit pending refund lifecycle is present in the retained card ledger.';
  const reviewDetail =
    tracker.needs_review_count > 0
      ? `${tracker.needs_review_count} refund row${tracker.needs_review_count === 1 ? '' : 's'} need lifecycle review before PFIS treats the credit as settled.`
      : 'Posted totals are bounded to the latest 90 days and do not predict an unrecorded refund.';

  return (
    <section
      className="rounded-lg border border-border/65 bg-muted/30 p-4"
      aria-labelledby="refund-tracker-title"
    >
      <div className="flex items-start gap-3">
        <span
          className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-card ${copy.iconTone}`}
        >
          {tracker.status === 'clear' ? (
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
          ) : (
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                REFUND LIFECYCLE
              </p>
              <h3 id="refund-tracker-title" className="mt-1 text-base font-extrabold">
                Refund tracker
              </h3>
            </div>
            <span className={`text-xs font-extrabold ${copy.tone}`}>{copy.label}</span>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{pendingDetail}</p>
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="rounded-md bg-card/75 p-3">
              <dt className="text-xs font-bold text-muted-foreground">Pending credit</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {tracker.pending_amount > 0
                  ? formatCurrency(tracker.pending_amount, currency)
                  : 'None identified'}
              </dd>
            </div>
            <div className="rounded-md bg-card/75 p-3">
              <dt className="text-xs font-bold text-muted-foreground">Posted, last 90 days</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {tracker.posted_amount_90d > 0
                  ? formatCurrency(tracker.posted_amount_90d, currency)
                  : 'None identified'}
              </dd>
            </div>
          </dl>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            {reviewDetail} As of {formatDate(tracker.as_of)}.
          </p>
        </div>
      </div>
    </section>
  );
}

function dueRunwayStatusLabel(status: CardDueRunway['status']): string {
  switch (status) {
    case 'covered':
      return 'Conservative path covers total due';
    case 'at_risk':
      return 'Funding path needs attention';
    case 'needs_statement':
      return 'Statement due is missing';
    case 'needs_payment_account':
      return 'Choose a funding account';
    case 'needs_funding_anchor':
      return 'Funding account needs an anchor';
    case 'due_passed':
      return 'Due date has passed';
    default:
      return 'Runway needs review';
  }
}

function DueRunwayBadge({ status }: { status: CardDueRunway['status'] }) {
  const className =
    status === 'covered'
      ? 'bg-success/12 text-success'
      : status === 'at_risk' || status === 'due_passed'
        ? 'bg-warning/12 text-warning'
        : 'bg-intelligence/12 text-intelligence';
  return (
    <span
      className={`inline-flex min-h-7 items-center rounded-full px-2.5 text-xs font-bold ${className}`}
    >
      {dueRunwayStatusLabel(status)}
    </span>
  );
}

function runwayMoney(value: number | null, currency: string): string {
  return value == null ? '—' : formatCurrency(value, currency);
}

function CardDueRunwayPanel({ runway, isLoading }: { runway?: CardDueRunway; isLoading: boolean }) {
  if (!runway && !isLoading) return null;
  if (!runway) {
    return (
      <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="card-due-runway">
        <div className="flex items-center gap-3">
          <span className="bg-intelligence/12 grid h-10 w-10 place-items-center rounded-lg text-intelligence">
            <CreditCard className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              PAYMENT RUNWAY
            </p>
            <h2 id="card-due-runway" className="mt-1 text-lg font-extrabold">
              Checking the funding path…
            </h2>
          </div>
        </div>
        <div className="mt-5 h-20 animate-soft-pulse rounded-lg bg-muted" role="status" />
      </section>
    );
  }

  const isReady = runway.status === 'covered' || runway.status === 'at_risk';
  const dueLabel = runway.due_date
    ? runway.days_until_due === 0
      ? 'Due today'
      : runway.days_until_due != null && runway.days_until_due > 0
        ? `Due in ${runway.days_until_due} days`
        : `Due ${formatDate(runway.due_date)}`
    : 'No due date';

  return (
    <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="card-due-runway">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="bg-intelligence/12 grid h-10 w-10 shrink-0 place-items-center rounded-lg text-intelligence">
            <CreditCard className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              PAYMENT RUNWAY
            </p>
            <h2 id="card-due-runway" className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
              Fund the issuer due from a known bank path
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              PFIS compares the statement total due with the selected funding account’s conservative
              forecast. It does not schedule, send, or confirm a bank payment.
            </p>
          </div>
        </div>
        <DueRunwayBadge status={runway.status} />
      </div>

      <div className="mt-5 grid gap-3 border-y border-border/65 py-4 sm:grid-cols-3">
        <div>
          <p className="text-xs font-bold text-muted-foreground">Issuer total due</p>
          <p className="money-value mt-1 text-2xl font-extrabold">
            {runwayMoney(runway.total_due, runway.currency)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {runway.minimum_due == null
              ? 'Minimum due unavailable'
              : `Minimum due ${formatCurrency(runway.minimum_due, runway.currency)}`}
          </p>
        </div>
        <div>
          <p className="text-xs font-bold text-muted-foreground">Payment timing</p>
          <p className="mt-1 text-base font-extrabold">{dueLabel}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {runway.due_date ? formatDate(runway.due_date) : 'Import an issuer statement'}
          </p>
        </div>
        <div>
          <p className="text-xs font-bold text-muted-foreground">Funding account</p>
          <p className="mt-1 truncate text-base font-extrabold">
            {runway.funding_account_label ?? 'Not selected'}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {runway.funding_balance_basis
              ? `${runway.funding_balance_basis} balance · ${Math.round(runway.confidence * 100)}% confidence`
              : 'Explicit account selection required'}
          </p>
        </div>
      </div>

      {isReady ? (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg bg-muted/55 p-3">
              <p className="text-xs text-muted-foreground">Cash before due</p>
              <p className="money-value mt-1 text-lg font-extrabold">
                {runwayMoney(runway.funding_balance_before_due_low, runway.currency)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">lower forecast band</p>
            </div>
            <div className="rounded-lg bg-muted/55 p-3">
              <p className="text-xs text-muted-foreground">After total due</p>
              <p className="money-value mt-1 text-lg font-extrabold">
                {runwayMoney(runway.expected_balance_after_total_due, runway.currency)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">expected funding balance</p>
            </div>
            <div className="rounded-lg bg-muted/55 p-3">
              <p className="text-xs text-muted-foreground">Conservative gap</p>
              <p
                className={`money-value mt-1 text-lg font-extrabold ${runway.lower_band_cash_gap ? 'text-warning' : 'text-success'}`}
              >
                {runway.lower_band_cash_gap
                  ? formatCurrency(runway.lower_band_cash_gap, runway.currency)
                  : 'None'}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">against total due</p>
            </div>
          </div>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            The lower-band figure is deliberately conservative. A covered result means the forecast
            stays above the full billed amount; it is not a live available-balance or
            payment-success signal.
          </p>
        </>
      ) : (
        <div className="mt-4 rounded-lg bg-muted/55 p-4 text-sm leading-6 text-muted-foreground">
          <p className="font-extrabold text-foreground">{dueRunwayStatusLabel(runway.status)}</p>
          <p className="mt-1">
            {runway.status === 'needs_statement'
              ? 'Import or confirm the latest issuer statement to establish total due and due date.'
              : runway.status === 'needs_payment_account'
                ? 'Select the bank account that will fund this card. PFIS will not infer one from unrelated balances.'
                : runway.status === 'needs_funding_anchor'
                  ? 'Record or sync a verified balance for the selected funding account before relying on this runway.'
                  : runway.status === 'due_passed'
                    ? 'The date has passed. Confirm settlement separately; PFIS does not assume that a planned payment succeeded.'
                    : 'The evidence is incomplete or stale, so PFIS is keeping affordability fail-closed.'}
          </p>
        </div>
      )}

      {runway.evidence.length ? (
        <p className="mt-4 text-xs leading-5 text-muted-foreground">
          Evidence: {runway.evidence.map((item) => `${item.label} ${item.value}`).join(' · ')}
        </p>
      ) : null}
    </section>
  );
}

function EmiEvidenceRow({ plan, currency }: { plan: CardEmiPlan; currency: string }) {
  return (
    <details className="group border-t border-border/65 first:border-t-0">
      <summary className="focus-ring grid min-h-16 cursor-pointer list-none grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded py-3 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="flex flex-wrap items-center gap-2">
            <span className="truncate font-extrabold">{plan.merchant}</span>
            <span className="bg-intelligence/12 rounded-full px-2 py-0.5 text-xs font-bold text-intelligence">
              {plan.status}
            </span>
          </span>
          <span className="mt-1 block text-xs text-muted-foreground">
            Issuer plan {plan.issuer_plan_reference}
            {plan.latest_installment_number
              ? ` · latest observed instalment ${plan.latest_installment_number}`
              : ' · instalment number not supplied'}
          </span>
        </span>
        <span className="text-right">
          <span className="money-value block font-extrabold">
            {formatCurrency(plan.latest_installment_amount, currency)}
          </span>
          <span className="text-xs text-muted-foreground">latest principal + charges</span>
        </span>
      </summary>
      <div className="pb-5">
        <p className="text-xs font-extrabold tracking-[0.07em] text-muted-foreground">
          LATEST STATEMENT ANATOMY
          {plan.latest_statement_date ? ` · ${formatDate(plan.latest_statement_date)}` : ''}
        </p>
        <dl className="mt-2 grid grid-cols-2 border-y border-border/65 sm:grid-cols-4">
          {[
            ['Principal', plan.latest_principal],
            ['Interest', plan.latest_interest],
            ['Tax on charges', plan.latest_tax],
            ['One-time fees', plan.latest_fees],
          ].map(([label, value]) => (
            <div
              key={String(label)}
              className="border-border/65 px-3 py-3 even:border-l sm:border-l sm:first:border-l-0"
            >
              <dt className="text-xs font-bold text-muted-foreground">{label}</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {value == null ? '—' : formatCurrency(Number(value), currency)}
              </dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
          <span>
            Conversion{' '}
            <strong className="text-foreground">
              {plan.original_amount == null
                ? 'unknown'
                : formatCurrency(plan.original_amount, currency)}
            </strong>
          </span>
          <span>
            Cumulative interest seen{' '}
            <strong className="text-foreground">
              {formatCurrency(plan.observed_interest, currency)}
            </strong>
          </span>
          <span>
            Evidence <strong className="text-foreground">{plan.evidence_line_count} lines</strong>
          </span>
          <span>
            Missing{' '}
            <strong className="text-foreground">
              {plan.missing_fields.map((field) => field.replaceAll('_', ' ')).join(', ')}
            </strong>
          </span>
        </div>
        <p className="mt-3 border-l-2 border-intelligence/35 pl-3 text-xs leading-5 text-muted-foreground">
          {plan.limitation}
        </p>
        <div
          className="mt-4 divide-y divide-border/65"
          aria-label={`${plan.merchant} EMI evidence`}
        >
          {plan.components.map((component) => (
            <div
              key={component.statement_line_id}
              className="grid min-h-11 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-2 text-sm"
            >
              <span className="min-w-0">
                <span className="block font-bold">
                  {component.component_kind.replace(/^emi_/, '').replaceAll('_', ' ')}
                  {component.installment_number
                    ? ` · instalment ${component.installment_number}`
                    : ''}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {formatDate(component.transaction_date)} · {component.description}
                </span>
              </span>
              <span className="money-value whitespace-nowrap font-extrabold">
                {formatCurrency(component.amount, currency)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

export function CardsSection() {
  const { user } = useAuth();
  const financialToday = dateInputValueInTimezone(user?.timezone ?? 'Asia/Kolkata');
  const queryClient = useQueryClient();
  const accounts = useAccounts();
  const cards = useMemo(
    () => (accounts.data ?? []).filter((account) => account.account_type === 'credit_card'),
    [accounts.data],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [disputeDraft, setDisputeDraft] = useState({
    statement_line_id: '',
    label: '',
    amount: '',
    complaint_date: financialToday,
    reference_number: '',
  });
  const [preferenceDraft, setPreferenceDraft] = useState({
    utilization_target_pct: '',
    reward_label: '',
    reward_rate: '',
  });
  const [calendarDraft, setCalendarDraft] = useState({
    event_type: 'annual_fee' as CardCalendarEvent['event_type'],
    label: '',
    event_date: financialToday,
  });
  const [editingCalendarId, setEditingCalendarId] = useState<string | null>(null);
  const [calendarDeleteTarget, setCalendarDeleteTarget] = useState<CardCalendarEvent | null>(null);
  const [paymentDraft, setPaymentDraft] = useState({
    paying_account_id: '',
    amount: '',
    planned_for: financialToday,
  });
  const cardId = selectedId ?? cards[0]?.id ?? '';
  const balanceForecast = useAccountBalanceForecast(cardId, 30);
  const dueRunway = useCardDueRunway(cardId);
  const utilizationHistory = useCardUtilizationHistory(cardId);
  const portfolioUpcoming = useCardPortfolioUpcomingState(cards.length > 1);
  const portfolioPaymentPlan = useCardPortfolioPaymentPlan(cards.length > 1);
  const overview = useQuery({
    queryKey: ['cardOverview', user?.id ?? '', cardId],
    queryFn: () => api.cardOverview(user!.id, cardId),
    enabled: Boolean(user && cardId),
    staleTime: 5 * 60 * 1000,
  });
  const disputes = useQuery({
    queryKey: ['cardDisputes', user?.id ?? '', cardId],
    queryFn: () => api.cardDisputes(user!.id, cardId),
    enabled: Boolean(user && cardId),
    staleTime: 5 * 60 * 1000,
  });
  const createDispute = useMutation({
    mutationFn: () =>
      api.createCardDispute(user!.id, cardId, {
        statement_line_id: disputeDraft.statement_line_id || null,
        label: disputeDraft.label,
        amount: Number(disputeDraft.amount),
        complaint_date: disputeDraft.complaint_date,
        reference_number: disputeDraft.reference_number || null,
      }),
    onSuccess: async () => {
      setDisputeDraft((current) => ({
        ...current,
        statement_line_id: '',
        label: '',
        amount: '',
        reference_number: '',
      }));
      await queryClient.invalidateQueries({
        queryKey: ['cardDisputes', user!.id, cardId],
      });
    },
  });
  const resolveDispute = useMutation({
    mutationFn: (disputeId: string) =>
      api.updateCardDispute(user!.id, disputeId, { status: 'resolved' }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['cardDisputes', user!.id, cardId],
      });
    },
  });
  const savePreferences = useMutation({
    mutationFn: () =>
      api.saveCardPreferences(user!.id, cardId, {
        preferred_payment_account_id:
          paymentDraft.paying_account_id || overview.data?.preferred_payment_account_id || null,
        utilization_target_pct: preferenceDraft.utilization_target_pct
          ? Number(preferenceDraft.utilization_target_pct)
          : (overview.data?.utilization_target_pct ?? null),
        reward_rules:
          preferenceDraft.reward_label.trim() && preferenceDraft.reward_rate
            ? [
                {
                  label: preferenceDraft.reward_label.trim(),
                  rate_pct: Number(preferenceDraft.reward_rate),
                },
              ]
            : (overview.data?.reward_rules ?? []),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['cardOverview', user!.id, cardId],
      });
      await queryClient.invalidateQueries({
        queryKey: ['cardDueRunway', user!.id, cardId],
      });
    },
  });
  const saveCalendar = useMutation({
    mutationFn: () =>
      editingCalendarId
        ? api.updateCardCalendarEvent(user!.id, cardId, editingCalendarId, calendarDraft)
        : api.createCardCalendarEvent(user!.id, cardId, calendarDraft),
    onSuccess: async () => {
      setEditingCalendarId(null);
      setCalendarDraft((current) => ({ ...current, label: '' }));
      await queryClient.invalidateQueries({
        queryKey: ['cardOverview', user!.id, cardId],
      });
    },
  });
  const deleteCalendar = useMutation({
    mutationFn: (eventId: string) => api.deleteCardCalendarEvent(user!.id, cardId, eventId),
    onSuccess: async (_, deletedId) => {
      setCalendarDeleteTarget(null);
      if (editingCalendarId === deletedId) {
        setEditingCalendarId(null);
        setCalendarDraft((current) => ({ ...current, label: '' }));
      }
      await queryClient.invalidateQueries({
        queryKey: ['cardOverview', user!.id, cardId],
      });
    },
  });
  const createPayment = useMutation({
    mutationFn: () =>
      api.createCardPaymentIntent(user!.id, cardId, {
        paying_account_id:
          paymentDraft.paying_account_id || overview.data?.preferred_payment_account_id || null,
        amount: Number(paymentDraft.amount),
        planned_for: paymentDraft.planned_for,
        note: 'User-recorded payment intention; no bank action initiated.',
      }),
    onSuccess: async () => {
      setPaymentDraft((current) => ({ ...current, amount: '' }));
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['cardOverview', user!.id, cardId],
        }),
        queryClient.invalidateQueries({
          queryKey: ['balanceForecast', user!.id, cardId],
        }),
        queryClient.invalidateQueries({
          queryKey: ['cardDueRunway', user!.id, cardId],
        }),
      ]);
    },
  });
  const updatePayment = useMutation({
    mutationFn: ({
      intentId,
      status,
      payingAccountId,
    }: {
      intentId: string;
      status: 'recorded' | 'cancelled';
      payingAccountId?: string | null;
    }) => api.updateCardPaymentIntent(user!.id, cardId, intentId, status, payingAccountId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['cardOverview', user!.id, cardId],
        }),
        queryClient.invalidateQueries({ queryKey: ['transactions'] }),
        queryClient.invalidateQueries({ queryKey: ['workspace'] }),
        queryClient.invalidateQueries({ queryKey: ['accountPosition'] }),
        queryClient.invalidateQueries({ queryKey: ['balanceForecast', user!.id, cardId] }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway', user!.id, cardId] }),
      ]);
    },
  });

  if (!cards.length && !accounts.isLoading) {
    return (
      <EmptyState
        icon={<CreditCard className="h-5 w-5" aria-hidden="true" />}
        title="Add a credit card first"
        description="A card workspace starts with a masked card account and a verified statement."
      />
    );
  }
  if (!overview.data) {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-label="Loading card workspace…"
        className="h-80 animate-soft-pulse rounded-xl bg-muted"
      />
    );
  }

  const card = overview.data;
  const bankAccounts = (accounts.data ?? []).filter((account) => account.account_type === 'bank');
  const statementLines = card.statement_lines ?? [];
  const statementHistory = card.statement_history ?? [];
  const coverageTotal = Object.values(card.coverage).reduce((total, count) => total + count, 0);
  const settledCount = card.coverage.matched + card.coverage.newly_imported;
  const utilization = Math.min(Math.max(card.statement_utilization_pct ?? 0, 0), 100);
  const utilizationNeedsAttention =
    card.statement_utilization_pct != null &&
    card.utilization_target_pct != null &&
    card.statement_utilization_pct > card.utilization_target_pct;
  const providerObserved =
    (card.provider_source === 'connector' || card.observed_source === 'connector') &&
    card.coverage_status === 'fresh' &&
    (card.provider_coverage_complete ?? card.coverage_complete) === true;
  const providerOutstanding = card.provider_current_outstanding ?? card.observed_balance;
  const observedProof =
    (card.provider_current_outstanding_as_of ?? card.observed_balance_as_of) &&
    providerOutstanding != null
      ? providerObserved
        ? `Provider observed ${formatCurrency(providerOutstanding, card.currency)} on ${formatDate(card.provider_current_outstanding_as_of ?? card.observed_balance_as_of!)}${(card.provider_observed_at ?? card.observed_at) ? ` · retrieved ${formatTime(card.provider_observed_at ?? card.observed_at!)}` : ''}; the position is inside its refresh window.`
        : `Observed ${formatCurrency(providerOutstanding, card.currency)} on ${formatDate(card.provider_current_outstanding_as_of ?? card.observed_balance_as_of!)}; settled activity is rolled forward to ${card.estimated_current_as_of ? formatDate(card.estimated_current_as_of) : 'today'}.`
      : 'Import a statement or record a verified card balance before PFIS estimates current outstanding.';

  return (
    <div className="space-y-6">
      <CardPortfolioUpcomingPanel
        portfolio={portfolioUpcoming.data}
        currency={card.currency}
        isLoading={portfolioUpcoming.isLoading}
        error={portfolioUpcoming.error}
      />

      <CardPortfolioPaymentPlanPanel
        plan={portfolioPaymentPlan.data}
        currency={card.currency}
        isLoading={portfolioPaymentPlan.isLoading}
        error={portfolioPaymentPlan.error}
      />

      <CardSpendRoutingPanel cardCount={cards.length} currency={card.currency} />

      {cards.length > 1 ? (
        <div className="flex gap-2 overflow-x-auto pb-1" aria-label="Credit cards">
          {cards.map((item) => (
            <button
              type="button"
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              aria-pressed={item.id === cardId}
              className="focus-ring min-h-11 shrink-0 rounded-lg border border-border px-3 text-sm font-bold hover:bg-muted"
            >
              {item.institution_name} · {item.masked_number}
            </button>
          ))}
        </div>
      ) : null}

      <FinancialHero className="bg-intelligence/10">
        <div className="grid gap-7 lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)] lg:items-end">
          <div>
            <div className="flex items-center gap-2 text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              <ShieldCheck className="h-4 w-4 text-intelligence" aria-hidden="true" />
              OFFICIAL STATEMENT POSITION
            </div>
            <p className="money-value mt-3 text-4xl font-extrabold tracking-[-0.06em] sm:text-5xl">
              {card.total_due == null
                ? 'No statement imported'
                : formatCurrency(card.total_due, card.currency)}
            </p>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
              {card.due_date
                ? `Total due by ${formatDate(card.due_date)}. This is issuer-stated evidence, not a live card balance.`
                : 'Import a supported statement to see due dates, limits, and reconciled coverage.'}
            </p>
            <div
              className="mt-5 border-t border-border/70 pt-4"
              aria-live="polite"
              aria-label="Estimated current card position"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <div>
                  <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                    {providerObserved
                      ? 'CURRENT POSITION · PROVIDER OBSERVED'
                      : 'CURRENT POSITION · ESTIMATE'}
                  </p>
                  <p className="mt-1 text-sm font-extrabold">{balanceStatusLabel(card)}</p>
                </div>
                <p className="money-value text-2xl font-extrabold tracking-[-0.04em]">
                  {providerOutstanding == null && card.estimated_current_balance == null
                    ? 'Needs anchor'
                    : formatCurrency(
                        providerOutstanding ?? card.estimated_current_balance!,
                        card.currency,
                      )}
                </p>
              </div>
              <p className="mt-2 max-w-2xl text-xs leading-5 text-muted-foreground">
                {observedProof}
                {(card.pending_increase ?? 0) > 0 || (card.pending_decrease ?? 0) > 0
                  ? ` Pending activity of ${formatCurrency((card.pending_increase ?? 0) + (card.pending_decrease ?? 0), card.currency)} is shown separately.`
                  : ''}
                {card.coverage_status === 'overdue'
                  ? ' Provider refresh is overdue; PFIS keeps this amount reviewable rather than calling it live.'
                  : card.coverage_complete === false
                    ? ' Provider history is incomplete; PFIS keeps this amount reviewable rather than treating it as safe current truth.'
                    : ''}
              </p>
              {card.billed_total_due != null ? (
                <dl
                  className="mt-4 grid grid-cols-1 gap-3 border-t border-border/65 pt-4 sm:grid-cols-3"
                  aria-label="Current outstanding proof"
                >
                  <div>
                    <dt className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
                      Billed at statement
                    </dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {formatCurrency(card.billed_total_due, card.currency)}
                      {card.billed_total_due_as_of
                        ? ` · ${formatDate(card.billed_total_due_as_of)}`
                        : ''}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
                      Paid since statement
                    </dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {card.paid_since_statement == null
                        ? '—'
                        : formatCurrency(card.paid_since_statement, card.currency)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
                      Net unbilled activity
                    </dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {card.unbilled_activity == null
                        ? '—'
                        : formatCurrency(card.unbilled_activity, card.currency)}
                    </dd>
                  </div>
                </dl>
              ) : null}
              {card.provider_current_outstanding != null ? (
                <dl
                  className="mt-4 grid grid-cols-2 gap-3 border-t border-border/65 pt-4 sm:grid-cols-4"
                  aria-label="Issuer card facts"
                >
                  <div>
                    <dt className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
                      Issuer outstanding
                    </dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {formatCurrency(card.provider_current_outstanding, card.currency)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
                      Issuer pending
                    </dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {card.provider_pending_amount == null
                        ? '—'
                        : formatCurrency(card.provider_pending_amount, card.currency)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
                      Available credit
                    </dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {card.provider_available_credit == null
                        ? '—'
                        : formatCurrency(card.provider_available_credit, card.currency)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
                      Issuer limit
                    </dt>
                    <dd className="mt-1 text-sm font-extrabold">
                      {card.provider_credit_limit == null
                        ? '—'
                        : formatCurrency(card.provider_credit_limit, card.currency)}
                    </dd>
                  </div>
                </dl>
              ) : null}
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-5 gap-y-4 border-t border-border/70 pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Minimum due</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {card.minimum_due == null ? '—' : formatCurrency(card.minimum_due, card.currency)}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Statement date</dt>
              <dd className="mt-1 text-sm font-extrabold">
                {card.statement_date ? formatDate(card.statement_date) : '—'}
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-xs font-bold text-muted-foreground">Billing period</dt>
              <dd className="mt-1 text-sm font-extrabold">
                {card.period_start && card.period_end
                  ? `${formatDate(card.period_start)} – ${formatDate(card.period_end)}`
                  : '—'}
              </dd>
            </div>
          </dl>
        </div>
      </FinancialHero>

      <BalancePathPanel forecast={balanceForecast.data} isLoading={balanceForecast.isLoading} />

      <CardStatementProjectionPanel
        projection={card.next_statement_projection}
        currency={card.currency}
        targetPct={card.utilization_target_pct}
      />

      <CardDailyPathPanel
        projection={card.next_statement_projection}
        currency={card.currency}
        targetPct={card.utilization_target_pct}
      />

      <CardUtilizationHistoryPanel
        history={utilizationHistory.data}
        currency={card.currency}
        isLoading={utilizationHistory.isLoading}
        error={utilizationHistory.error}
      />

      <CardDueRunwayPanel runway={dueRunway.data} isLoading={dueRunway.isLoading} />

      <CardPaymentScenarioPanel runway={dueRunway.data} />

      <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="statement-anatomy">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              ISSUER CALCULATION
            </p>
            <h2 id="statement-anatomy" className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
              How this statement arrived at the due
            </h2>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            Values retain the statement-date provenance.
          </p>
        </div>
        <div
          className="mt-5 grid sm:grid-cols-5"
          aria-label="Previous dues minus payments and credits plus purchases and debits plus finance charges equals total amount due"
        >
          <StatementAmount
            label="Previous dues"
            value={card.previous_due}
            currency={card.currency}
          />
          <StatementAmount
            label="Payments / credits"
            value={card.payments_credits}
            currency={card.currency}
            operator="minus"
          />
          <StatementAmount
            label="Purchases / debits"
            value={card.purchases_debits}
            currency={card.currency}
            operator="plus"
          />
          <StatementAmount
            label="Finance charges"
            value={card.finance_charges}
            currency={card.currency}
            operator="plus"
          />
          <StatementAmount
            label="Total due"
            value={card.total_due}
            currency={card.currency}
            operator="equals"
          />
        </div>
      </section>

      {(card.emi_plans ?? []).length ? (
        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="emi-anatomy">
          <div className="flex items-start gap-3">
            <span className="bg-intelligence/12 grid h-10 w-10 shrink-0 place-items-center rounded-lg text-intelligence">
              <Landmark className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                EMI EVIDENCE
              </p>
              <h2 id="emi-anatomy" className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
                Principal, interest, tax and fees—separated
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                PFIS groups issuer loan references across statements. It shows only observed
                components and does not invent a tenure, annual rate, or remaining schedule.
              </p>
            </div>
          </div>
          <div className="mt-5">
            {(card.emi_plans ?? []).map((plan) => (
              <EmiEvidenceRow
                key={plan.issuer_plan_reference}
                plan={plan}
                currency={card.currency}
              />
            ))}
          </div>
        </section>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(19rem,0.65fr)]">
        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="statement-coverage">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                RECONCILIATION
              </p>
              <h2
                id="statement-coverage"
                className="mt-1 text-lg font-extrabold tracking-[-0.025em]"
              >
                {settledCount} of {coverageTotal} lines settled
              </h2>
            </div>
            <span
              className={`grid h-10 w-10 shrink-0 place-items-center rounded-lg ${
                card.coverage.needs_review
                  ? 'bg-warning/12 text-warning'
                  : 'bg-success/12 text-success'
              }`}
            >
              {card.coverage.needs_review ? (
                <Clock3 className="h-4 w-4" aria-hidden="true" />
              ) : (
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              )}
            </span>
          </div>
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['Matched', card.coverage.matched],
              ['Imported', card.coverage.newly_imported],
              ['Needs review', card.coverage.needs_review],
              ['Ignored', card.coverage.ignored_by_rule],
            ].map(([label, count]) => (
              <div key={label} className="rounded-lg bg-muted/55 p-3">
                <p className="money-value text-lg font-extrabold">{count}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            Review items do not create duplicate spending. They stay outside the ledger until their
            evidence is resolved.
          </p>
        </section>

        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="limit-snapshot">
          <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
            STATEMENT-DATE LIMITS
          </p>
          <h2 id="limit-snapshot" className="mt-1 text-lg font-extrabold tracking-[-0.025em]">
            {card.statement_utilization_pct == null
              ? 'Utilisation unavailable'
              : `${card.statement_utilization_pct.toFixed(1)}% utilised`}
          </h2>
          <div
            className="mt-5 h-2 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-label="Statement utilisation"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(utilization)}
          >
            <div
              className={`h-full rounded-full ${
                utilizationNeedsAttention ? 'bg-warning' : 'bg-intelligence'
              }`}
              style={{ width: `${utilization}%` }}
            />
          </div>
          <dl className="mt-5 space-y-3 text-sm">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-muted-foreground">Total credit limit</dt>
              <dd className="money-value font-extrabold">
                {card.credit_limit == null ? '—' : formatCurrency(card.credit_limit, card.currency)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-muted-foreground">Available credit</dt>
              <dd className="money-value font-extrabold">
                {card.available_credit_limit == null
                  ? '—'
                  : formatCurrency(card.available_credit_limit, card.currency)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-muted-foreground">Available cash</dt>
              <dd className="money-value font-extrabold">
                {card.available_cash_limit == null
                  ? '—'
                  : formatCurrency(card.available_cash_limit, card.currency)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-muted-foreground">Estimated utilisation</dt>
              <dd className="money-value font-extrabold">
                {card.estimated_utilization_pct == null
                  ? '—'
                  : `${card.estimated_utilization_pct.toFixed(1)}%`}
              </dd>
            </div>
          </dl>
          <p className="mt-4 text-xs leading-5 text-muted-foreground">
            Limits are not live and remain labelled by the statement date. Estimated utilisation
            uses the settled position and may differ from issuer holds or blocked EMI limit.
          </p>
          <details className="mt-4 border-t border-border/65 pt-4">
            <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
              Set a utilization and reward rule
            </summary>
            <form
              className="mt-4 space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                savePreferences.mutate();
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="utilization-target">Utilization threshold (%)</Label>
                <Input
                  id="utilization-target"
                  type="number"
                  min="0.01"
                  max="100"
                  step="0.01"
                  placeholder={String(card.utilization_target_pct ?? 30)}
                  value={preferenceDraft.utilization_target_pct}
                  onChange={(event) =>
                    setPreferenceDraft((current) => ({
                      ...current,
                      utilization_target_pct: event.target.value,
                    }))
                  }
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_7rem]">
                <div className="space-y-1.5">
                  <Label htmlFor="reward-label">Explicit reward rule</Label>
                  <Input
                    id="reward-label"
                    placeholder="Dining"
                    value={preferenceDraft.reward_label}
                    onChange={(event) =>
                      setPreferenceDraft((current) => ({
                        ...current,
                        reward_label: event.target.value,
                      }))
                    }
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="reward-rate">Rate (%)</Label>
                  <Input
                    id="reward-rate"
                    type="number"
                    min="0"
                    step="0.01"
                    value={preferenceDraft.reward_rate}
                    onChange={(event) =>
                      setPreferenceDraft((current) => ({
                        ...current,
                        reward_rate: event.target.value,
                      }))
                    }
                  />
                </div>
              </div>
              <Button
                type="submit"
                size="sm"
                variant="outline"
                disabled={savePreferences.isPending}
              >
                Save card guardrails
              </Button>
            </form>
          </details>
        </section>
      </div>

      <section className="overflow-hidden rounded-xl bg-card" aria-labelledby="statement-ledger">
        <div className="border-b border-border/65 p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
              <ReceiptText className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <h2 id="statement-ledger" className="text-lg font-extrabold tracking-[-0.025em]">
                Latest statement ledger
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                Issuer rows with their ledger classification and reconciliation outcome.
              </p>
            </div>
          </div>
        </div>
        {statementLines.length ? (
          <>
            <ul className="divide-y divide-border/65 sm:hidden">
              {statementLines.map((line) => {
                const reducesLiability =
                  line.transaction_type === 'credit' || line.transaction_type === 'refund';
                return (
                  <li key={line.id} className="p-5">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs text-muted-foreground">
                        {formatDate(line.transaction_date)}
                      </span>
                      <OutcomeBadge outcome={line.review_outcome} />
                    </div>
                    <p className="mt-3 break-words text-sm font-extrabold leading-6">
                      {line.merchant_normalized || line.description}
                    </p>
                    {line.merchant_normalized &&
                    line.merchant_normalized.toLowerCase() !== line.description.toLowerCase() ? (
                      <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">
                        Statement evidence: {line.description}
                      </p>
                    ) : null}
                    <div className="mt-2 flex items-baseline justify-between gap-4">
                      <span className="text-xs text-muted-foreground">
                        {statementEventLabel(line)}
                      </span>
                      <span
                        className={`money-value text-sm font-extrabold ${
                          reducesLiability ? 'text-success' : ''
                        }`}
                      >
                        {reducesLiability ? '−' : '+'}
                        {formatCurrency(line.amount, card.currency)}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
            <div className="hidden overflow-x-auto sm:block">
              <table className="w-full min-w-[720px] border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-border/65 text-xs text-muted-foreground">
                    <th scope="col" className="px-5 py-3 font-bold sm:px-6">
                      Date
                    </th>
                    <th scope="col" className="px-3 py-3 font-bold">
                      Merchant / statement evidence
                    </th>
                    <th scope="col" className="px-3 py-3 font-bold">
                      Event
                    </th>
                    <th scope="col" className="px-3 py-3 font-bold">
                      Outcome
                    </th>
                    <th scope="col" className="px-5 py-3 text-right font-bold sm:px-6">
                      Amount
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/65">
                  {statementLines.map((line) => {
                    const reducesLiability =
                      line.transaction_type === 'credit' || line.transaction_type === 'refund';
                    return (
                      <tr key={line.id} className="align-top hover:bg-muted/35">
                        <td className="whitespace-nowrap px-5 py-4 text-xs text-muted-foreground sm:px-6">
                          {formatDate(line.transaction_date)}
                        </td>
                        <td className="max-w-md px-3 py-4">
                          <span className="block font-bold">
                            {line.merchant_normalized || line.description}
                          </span>
                          {line.merchant_normalized &&
                          line.merchant_normalized.toLowerCase() !==
                            line.description.toLowerCase() ? (
                            <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                              {line.description}
                            </span>
                          ) : null}
                        </td>
                        <td className="whitespace-nowrap px-3 py-4 text-xs text-muted-foreground">
                          {statementEventLabel(line)}
                        </td>
                        <td className="px-3 py-4">
                          <OutcomeBadge outcome={line.review_outcome} />
                        </td>
                        <td className="money-value whitespace-nowrap px-5 py-4 text-right font-extrabold sm:px-6">
                          <span className={reducesLiability ? 'text-success' : undefined}>
                            {reducesLiability ? '−' : '+'}
                            {formatCurrency(line.amount, card.currency)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="p-6 text-sm text-muted-foreground">No statement ledger rows available.</p>
        )}
      </section>

      {statementHistory.length ? (
        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="statement-history">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
              <CalendarDays className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <h2 id="statement-history" className="text-lg font-extrabold tracking-[-0.025em]">
                Statement history
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Verified monthly snapshots, newest first.
              </p>
            </div>
          </div>
          <div className="mt-4 divide-y divide-border/65">
            {statementHistory.map((statement) => (
              <div
                key={statement.id}
                className="grid gap-2 py-4 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center sm:gap-6"
              >
                <div>
                  <p className="font-extrabold">{formatDate(statement.statement_date)}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {statement.line_count} lines · {statement.needs_review_count} need review
                  </p>
                </div>
                <p className="text-xs text-muted-foreground">
                  {statement.due_date ? `Due ${formatDate(statement.due_date)}` : 'No due date'}
                </p>
                <p className="money-value font-extrabold">
                  {statement.total_due == null
                    ? '—'
                    : formatCurrency(statement.total_due, card.currency)}
                </p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-xl bg-card p-5 sm:p-6">
        <h2 className="text-lg font-extrabold tracking-[-0.025em]">Activity centre</h2>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Deterministic checks from PFIS evidence. Review with your issuer; PFIS cannot block,
          reverse, or dispute card activity.
        </p>
        <div className="mt-5">
          <CardRefundTrackerPanel tracker={card.refund_tracker} currency={card.currency} />
        </div>
        {card.activity_signals.length ? (
          <ul className="mt-4 divide-y divide-border/65">
            {card.activity_signals.map((signal) => {
              const Icon =
                signal.signal_type === 'duplicate_candidate'
                  ? Copy
                  : signal.signal_type === 'pending_reversal'
                    ? RotateCcw
                    : AlertTriangle;
              return (
                <li key={signal.id} className="flex min-w-0 gap-3 py-4 first:pt-0 last:pb-0">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-warning/10 text-warning">
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <h3 className="font-extrabold tracking-[-0.015em]">{signal.title}</h3>
                      <span className="money-value text-sm">
                        {formatCurrency(signal.amount, card.currency)}
                      </span>
                    </div>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">
                      {signal.description}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      {formatDate(signal.activity_date)} · {signal.basis}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-4 rounded-lg bg-muted/55 p-4 text-sm text-muted-foreground">
            No duplicate, high-value, or pending-reversal signals in the available evidence.
          </p>
        )}
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="card-calendar-title">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
              <CalendarDays className="h-4 w-4" aria-hidden="true" />
            </span>
            <div>
              <h2 id="card-calendar-title" className="text-lg font-extrabold tracking-[-0.025em]">
                Fees and milestones
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                User-entered reminders; they do not represent issuer actions.
              </p>
            </div>
          </div>
          <div className="mt-4">
            {card.calendar.length ? (
              card.calendar.map((event) => (
                <LedgerRow
                  key={event.id}
                  leading={<CalendarDays className="h-4 w-4" aria-hidden="true" />}
                  title={event.label}
                  subtitle={`${event.event_type.replaceAll('_', ' ')} · ${event.source_kind}`}
                  amount={formatDate(event.event_date)}
                  selected={editingCalendarId === event.id}
                  onSelect={() => {
                    setEditingCalendarId(event.id);
                    setCalendarDraft({
                      event_type: event.event_type,
                      label: event.label,
                      event_date: event.event_date,
                    });
                  }}
                />
              ))
            ) : (
              <p className="rounded-lg bg-muted/55 p-4 text-sm text-muted-foreground">
                No fee, renewal, or milestone reminders recorded.
              </p>
            )}
          </div>
          <details className="mt-4 rounded-lg border border-border/70 p-4">
            <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
              {editingCalendarId
                ? 'Edit fee or milestone reminder'
                : 'Add a fee or milestone reminder'}
            </summary>
            <form
              className="mt-4 space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (calendarDraft.label.trim()) saveCalendar.mutate();
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="calendar-label">Reminder label</Label>
                <Input
                  id="calendar-label"
                  value={calendarDraft.label}
                  onChange={(event) =>
                    setCalendarDraft((current) => ({
                      ...current,
                      label: event.target.value,
                    }))
                  }
                  required
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="calendar-type">Type</Label>
                  <Select
                    id="calendar-type"
                    value={calendarDraft.event_type}
                    onChange={(event) =>
                      setCalendarDraft((current) => ({
                        ...current,
                        event_type: event.target.value as CardCalendarEvent['event_type'],
                      }))
                    }
                  >
                    <option value="annual_fee">Annual fee</option>
                    <option value="renewal">Renewal</option>
                    <option value="fee_reversal">Fee reversal</option>
                    <option value="milestone">Milestone</option>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="calendar-date">Date</Label>
                  <Input
                    id="calendar-date"
                    type="date"
                    value={calendarDraft.event_date}
                    onChange={(event) =>
                      setCalendarDraft((current) => ({
                        ...current,
                        event_date: event.target.value,
                      }))
                    }
                    required
                  />
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="submit"
                  size="sm"
                  variant="outline"
                  disabled={saveCalendar.isPending || deleteCalendar.isPending}
                >
                  {editingCalendarId ? 'Update reminder' : 'Save reminder'}
                </Button>
                {editingCalendarId ? (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={saveCalendar.isPending || deleteCalendar.isPending}
                      onClick={() => {
                        setEditingCalendarId(null);
                        setCalendarDraft((current) => ({ ...current, label: '' }));
                      }}
                    >
                      Cancel edit
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="danger"
                      disabled={saveCalendar.isPending || deleteCalendar.isPending}
                      onClick={() => {
                        const target = card.calendar.find(
                          (event) => event.id === editingCalendarId,
                        );
                        if (target) setCalendarDeleteTarget(target);
                      }}
                    >
                      Delete reminder
                    </Button>
                  </>
                ) : null}
              </div>
              {saveCalendar.error || deleteCalendar.error ? (
                <p role="alert" className="text-sm font-bold text-danger">
                  {(saveCalendar.error ?? deleteCalendar.error)?.message}
                </p>
              ) : null}
            </form>
          </details>
          <Dialog
            open={Boolean(calendarDeleteTarget)}
            onClose={() => {
              if (!deleteCalendar.isPending) setCalendarDeleteTarget(null);
            }}
            title="Delete this reminder?"
            description="This removes the personal reminder only; issuer statement evidence remains unchanged."
          >
            <p className="text-sm leading-6 text-muted-foreground">
              {calendarDeleteTarget
                ? `${calendarDeleteTarget.label} will no longer appear in the card timeline.`
                : 'The selected reminder will no longer appear in the card timeline.'}
            </p>
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                data-dialog-initial-focus
                variant="ghost"
                onClick={() => setCalendarDeleteTarget(null)}
                disabled={deleteCalendar.isPending}
              >
                Keep reminder
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  if (calendarDeleteTarget) deleteCalendar.mutate(calendarDeleteTarget.id);
                }}
                disabled={!calendarDeleteTarget || deleteCalendar.isPending}
              >
                {deleteCalendar.isPending ? 'Deleting…' : 'Delete reminder'}
              </Button>
            </div>
          </Dialog>
        </section>

        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="card-disputes-title">
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              USER-RECORDED CASES
            </p>
            <h2
              id="card-disputes-title"
              className="mt-1 text-lg font-extrabold tracking-[-0.025em]"
            >
              Dispute tracker
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Track a case you raised with the issuer. PFIS does not submit disputes.
            </p>
          </div>
          <div className="mt-4 divide-y divide-border/65">
            {(disputes.data ?? []).map((dispute) => (
              <div key={dispute.id} className="py-4 first:pt-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="font-extrabold">{dispute.label}</p>
                  <span className="money-value text-sm font-extrabold">
                    {formatCurrency(dispute.amount, card.currency)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {formatDate(dispute.complaint_date)} · {dispute.status}
                  {dispute.reference_number ? ` · ${dispute.reference_number}` : ''}
                </p>
                {dispute.status !== 'resolved' ? (
                  <Button
                    className="mt-2"
                    size="sm"
                    variant="outline"
                    disabled={resolveDispute.isPending}
                    onClick={() => resolveDispute.mutate(dispute.id)}
                  >
                    Record resolved
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
          <details className="mt-4 rounded-lg border border-border/70 p-4">
            <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
              Record an issuer dispute
            </summary>
            <form
              className="mt-4 grid gap-4 sm:grid-cols-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (disputeDraft.label.trim() && Number(disputeDraft.amount) > 0) {
                  createDispute.mutate();
                }
              }}
            >
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="dispute-line">Statement line (optional)</Label>
                <Select
                  id="dispute-line"
                  value={disputeDraft.statement_line_id}
                  onChange={(event) =>
                    setDisputeDraft((current) => ({
                      ...current,
                      statement_line_id: event.target.value,
                    }))
                  }
                >
                  <option value="">No linked line</option>
                  {statementLines.map((line) => (
                    <option key={line.id} value={line.id}>
                      {formatDate(line.transaction_date)} · {line.description}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dispute-label">Case label</Label>
                <Input
                  id="dispute-label"
                  value={disputeDraft.label}
                  onChange={(event) =>
                    setDisputeDraft((current) => ({
                      ...current,
                      label: event.target.value,
                    }))
                  }
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dispute-amount">Amount</Label>
                <Input
                  id="dispute-amount"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  step="0.01"
                  value={disputeDraft.amount}
                  onChange={(event) =>
                    setDisputeDraft((current) => ({
                      ...current,
                      amount: event.target.value,
                    }))
                  }
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dispute-date">Complaint date</Label>
                <Input
                  id="dispute-date"
                  type="date"
                  value={disputeDraft.complaint_date}
                  onChange={(event) =>
                    setDisputeDraft((current) => ({
                      ...current,
                      complaint_date: event.target.value,
                    }))
                  }
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dispute-reference">Issuer reference</Label>
                <Input
                  id="dispute-reference"
                  value={disputeDraft.reference_number}
                  onChange={(event) =>
                    setDisputeDraft((current) => ({
                      ...current,
                      reference_number: event.target.value,
                    }))
                  }
                />
              </div>
              <div className="sm:col-span-2">
                <Button type="submit" disabled={createDispute.isPending}>
                  Save dispute record
                </Button>
              </div>
              {createDispute.error ? (
                <p role="alert" className="text-sm font-bold text-danger sm:col-span-2">
                  {createDispute.error.message}
                </p>
              ) : null}
            </form>
          </details>
        </section>
      </div>

      <section className="rounded-xl bg-card p-5 sm:p-6">
        <h2 className="text-lg font-extrabold tracking-[-0.025em]">
          Payment intentions & manual records
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Plan first. After you actually pay, record the bank-to-card movement in PFIS. Neither
          action contacts your bank or issuer.
        </p>
        <div className="mt-3">
          {card.planned_payments.length ? (
            card.planned_payments.map((payment) => (
              <div key={payment.id} className="border-b border-border/65 py-2 last:border-b-0">
                <LedgerRow
                  leading={<CreditCard className="h-4 w-4" aria-hidden="true" />}
                  title={`${payment.status === 'planned' ? 'Planned' : payment.status === 'recorded' ? 'Recorded' : 'Cancelled'} ${formatCurrency(payment.amount, card.currency)}`}
                  subtitle={
                    payment.status === 'recorded'
                      ? `Manual ledger transfer dated ${formatDate(payment.planned_for)} · no bank action`
                      : `Planned for ${formatDate(payment.planned_for)}`
                  }
                  amount={payment.status}
                  className="border-b-0"
                />
                {payment.status === 'planned' ? (
                  <div className="flex flex-col gap-2 px-2 pb-3 sm:flex-row sm:items-center sm:justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={
                        updatePayment.isPending ||
                        !(payment.paying_account_id || card.preferred_payment_account_id)
                      }
                      onClick={() =>
                        updatePayment.mutate({
                          intentId: payment.id,
                          status: 'recorded',
                          payingAccountId:
                            payment.paying_account_id || card.preferred_payment_account_id,
                        })
                      }
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      Record manual transfer
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={updatePayment.isPending}
                      onClick={() =>
                        updatePayment.mutate({
                          intentId: payment.id,
                          status: 'cancelled',
                        })
                      }
                    >
                      Cancel intent
                    </Button>
                  </div>
                ) : null}
                {payment.status === 'planned' &&
                !(payment.paying_account_id || card.preferred_payment_account_id) ? (
                  <p className="px-2 pb-3 text-xs leading-5 text-muted-foreground">
                    Choose and save a preferred paying bank account before recording the transfer.
                  </p>
                ) : null}
              </div>
            ))
          ) : (
            <p className="py-4 text-sm text-muted-foreground">No payment intentions recorded.</p>
          )}
        </div>
        {updatePayment.error ? (
          <p role="alert" className="mt-3 text-sm font-bold text-danger">
            {updatePayment.error.message}
          </p>
        ) : null}
        <details className="mt-4 rounded-lg border border-border/70 p-4">
          <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
            Plan a manual payment
          </summary>
          <form
            className="mt-4 grid gap-4 sm:grid-cols-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (Number(paymentDraft.amount) > 0) createPayment.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="payment-account">Paying account</Label>
              <Select
                id="payment-account"
                value={paymentDraft.paying_account_id || card.preferred_payment_account_id || ''}
                onChange={(event) =>
                  setPaymentDraft((current) => ({
                    ...current,
                    paying_account_id: event.target.value,
                  }))
                }
              >
                <option value="">Not selected yet</option>
                {bankAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.institution_name} · {account.masked_number}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="payment-amount">Intended amount</Label>
              <Input
                id="payment-amount"
                type="number"
                min="0.01"
                step="0.01"
                value={paymentDraft.amount}
                onChange={(event) =>
                  setPaymentDraft((current) => ({
                    ...current,
                    amount: event.target.value,
                  }))
                }
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="payment-date">Planned date</Label>
              <Input
                id="payment-date"
                type="date"
                value={paymentDraft.planned_for}
                onChange={(event) =>
                  setPaymentDraft((current) => ({
                    ...current,
                    planned_for: event.target.value,
                  }))
                }
                required
              />
            </div>
            <div className="sm:col-span-3">
              <Button type="submit" disabled={createPayment.isPending}>
                Save payment intention
              </Button>
            </div>
          </form>
        </details>
      </section>
    </div>
  );
}
