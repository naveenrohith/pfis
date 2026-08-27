import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Minus,
  ShieldCheck,
} from 'lucide-react';
import { formatCurrency, formatDate } from '@/lib/format';
import type { CardUtilizationHistory, CardUtilizationHistoryPoint } from '@/lib/types';

const trendCopy: Record<
  CardUtilizationHistory['trend'],
  { label: string; detail: string; tone: string }
> = {
  improving: {
    label: 'Moving down',
    detail: 'The latest evidence is below the earliest point in this window.',
    tone: 'text-success',
  },
  worsening: {
    label: 'Moving up',
    detail: 'The latest evidence is above the earliest point in this window.',
    tone: 'text-warning',
  },
  stable: {
    label: 'Holding steady',
    detail: 'The change stays within PFIS’s small-movement threshold.',
    tone: 'text-muted-foreground',
  },
  insufficient_history: {
    label: 'One statement on file',
    detail: 'Import another statement to compare issuer-stated cycles.',
    tone: 'text-muted-foreground',
  },
  unavailable: {
    label: 'History unavailable',
    detail: 'Import a statement before PFIS can plot utilization evidence.',
    tone: 'text-muted-foreground',
  },
};

const statusCopy: Record<CardUtilizationHistoryPoint['status'], string> = {
  within_target: 'Within target',
  within_limit: 'Within limit',
  over_target: 'Over target',
  over_limit: 'Over hard limit',
  unavailable: 'Unavailable',
};

function trendIcon(trend: CardUtilizationHistory['trend']) {
  if (trend === 'improving') return ArrowDownRight;
  if (trend === 'worsening') return ArrowUpRight;
  if (trend === 'stable' || trend === 'insufficient_history') return Minus;
  return Activity;
}

function chartCoordinates(points: CardUtilizationHistoryPoint[], scale: number): string {
  if (points.length === 1) return '50,50';
  return points
    .map((point, index) => {
      const x = (index / (points.length - 1)) * 100;
      const y = 90 - ((point.utilization_pct ?? 0) / scale) * 76;
      return `${x.toFixed(2)},${Math.max(8, Math.min(90, y)).toFixed(2)}`;
    })
    .join(' ');
}

function latestPoint(history: CardUtilizationHistory): CardUtilizationHistoryPoint | null {
  const daily = history.daily_points[history.daily_points.length - 1];
  const statement = history.statement_points[history.statement_points.length - 1];
  return daily ?? statement ?? null;
}

function pointBasis(point: CardUtilizationHistoryPoint): string {
  return point.basis === 'issuer_statement' ? 'Issuer statement' : 'Settled-ledger estimate';
}

function pointValue(point: CardUtilizationHistoryPoint): string {
  return point.utilization_pct == null ? '—' : `${point.utilization_pct.toFixed(1)}%`;
}

export function CardUtilizationHistoryPanel({
  history,
  currency,
  isLoading = false,
  error,
}: {
  history?: CardUtilizationHistory;
  currency: string;
  isLoading?: boolean;
  error?: unknown;
}) {
  if (isLoading) {
    return (
      <section
        className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
        aria-label="Loading utilization history…"
        role="status"
      >
        <div className="animate-soft-pulse space-y-3">
          <div className="h-3 w-36 rounded bg-muted" />
          <div className="h-7 w-64 rounded bg-muted" />
          <div className="h-36 rounded-lg bg-muted/70" />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section
        className="rounded-xl border border-warning/35 bg-warning/5 p-5 sm:p-6"
        aria-label="Utilization history needs review"
        role="alert"
      >
        <p className="text-xs font-extrabold tracking-[0.08em] text-warning">UTILIZATION HISTORY</p>
        <h2 className="mt-1 text-lg font-extrabold">History needs a refresh</h2>
        <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
          PFIS could not read the card’s historical evidence. Refresh the workspace or import the
          latest statement; no issuer balance has been inferred.
        </p>
      </section>
    );
  }

  if (!history || (!history.statement_points.length && !history.daily_points.length)) {
    return (
      <section
        className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
        aria-labelledby="utilization-history-title"
      >
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              UTILIZATION HISTORY
            </p>
            <h2 id="utilization-history-title" className="mt-1 text-lg font-extrabold">
              Import a statement to see the cycle story
            </h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
              PFIS keeps issuer-stated utilization separate from any later settled-ledger estimate.
              There is no history to plot yet.
            </p>
          </div>
        </div>
      </section>
    );
  }

  const copy = trendCopy[history.trend];
  const Icon = trendIcon(history.trend);
  const chartPoints = [...history.statement_points, ...history.daily_points].filter(
    (point) => point.utilization_pct != null,
  );
  const maxUtilization = Math.max(
    100,
    Math.ceil(Math.max(...chartPoints.map((point) => point.utilization_pct ?? 0), 0) / 10) * 10,
  );
  const latest = latestPoint(history);
  const evidencePoints = [...history.statement_points, ...history.daily_points].slice(-8);
  const targetY =
    history.utilization_target_pct == null
      ? null
      : 90 - (history.utilization_target_pct / maxUtilization) * 76;
  const chartLabel =
    chartPoints.length > 1
      ? `Utilization moved from ${pointValue(chartPoints[0])} on ${formatDate(chartPoints[0].as_of)} to ${pointValue(chartPoints[chartPoints.length - 1])} on ${formatDate(chartPoints[chartPoints.length - 1].as_of)}.`
      : `Utilization was ${pointValue(chartPoints[0])} on ${formatDate(chartPoints[0].as_of)}.`;

  return (
    <section
      className="rounded-xl border border-intelligence/20 bg-intelligence/5 p-5 sm:p-6"
      aria-labelledby="utilization-history-title"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-card text-intelligence">
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              UTILIZATION HISTORY
            </p>
            <h2
              id="utilization-history-title"
              className="mt-1 text-xl font-extrabold tracking-[-0.03em]"
            >
              {copy.label}
            </h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{copy.detail}</p>
          </div>
        </div>
        <div className="shrink-0 rounded-lg bg-card/80 px-3 py-2 text-left sm:text-right">
          <p className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
            Change across window
          </p>
          <p className={`money-value mt-1 text-lg font-extrabold ${copy.tone}`}>
            {history.trend_delta_pct == null
              ? '—'
              : `${history.trend_delta_pct > 0 ? '+' : ''}${history.trend_delta_pct.toFixed(1)} pp`}
          </p>
        </div>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(15rem,0.65fr)] lg:items-start">
        <div className="rounded-lg border border-border/65 bg-card/75 p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                STATEMENT TO TODAY
              </p>
              <p className="mt-1 text-sm font-extrabold">{chartLabel}</p>
            </div>
            <p className="text-xs text-muted-foreground">Scale: 0–{maxUtilization}%</p>
          </div>
          <div className="mt-4 overflow-hidden rounded-md bg-muted/35 px-2 py-3">
            <svg
              className="h-40 w-full"
              viewBox="0 0 100 100"
              role="img"
              aria-label={chartLabel}
              preserveAspectRatio="none"
            >
              <title>Card utilization history</title>
              <desc>
                {chartLabel} Statement points are issuer evidence; the final daily points are
                settled-ledger estimates.
              </desc>
              <line
                x1="0"
                y1="90"
                x2="100"
                y2="90"
                stroke="currentColor"
                className="text-border"
                strokeWidth="0.6"
              />
              <line
                x1="0"
                y1="14"
                x2="100"
                y2="14"
                stroke="currentColor"
                className="text-border/60"
                strokeWidth="0.6"
                strokeDasharray="1.5 2"
              />
              {targetY != null ? (
                <line
                  x1="0"
                  y1={Math.max(8, Math.min(90, targetY))}
                  x2="100"
                  y2={Math.max(8, Math.min(90, targetY))}
                  stroke="currentColor"
                  className="text-warning"
                  strokeWidth="0.8"
                  strokeDasharray="2 2"
                />
              ) : null}
              <polyline
                points={chartCoordinates(chartPoints, maxUtilization)}
                fill="none"
                stroke="currentColor"
                className="text-intelligence"
                strokeWidth="1.8"
                vectorEffect="non-scaling-stroke"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {chartPoints.map((point, index) => {
                const x = chartPoints.length === 1 ? 50 : (index / (chartPoints.length - 1)) * 100;
                const y = Math.max(
                  8,
                  Math.min(90, 90 - ((point.utilization_pct ?? 0) / maxUtilization) * 76),
                );
                const isStatement = point.basis === 'issuer_statement';
                return (
                  <circle
                    key={`${point.as_of}-${point.basis}`}
                    cx={x}
                    cy={y}
                    r={isStatement ? 2.4 : 1.8}
                    fill="currentColor"
                    className={isStatement ? 'text-intelligence' : 'text-muted-foreground'}
                  />
                );
              })}
            </svg>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-intelligence" aria-hidden="true" />
              Issuer statement
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-muted-foreground" aria-hidden="true" />
              Settled-ledger estimate
            </span>
            {history.utilization_target_pct != null ? (
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="h-px w-3 border-t border-dashed border-warning"
                  aria-hidden="true"
                />
                {history.utilization_target_pct.toFixed(0)}% target
              </span>
            ) : null}
          </div>
        </div>

        <aside className="rounded-lg bg-card/85 p-4" aria-label="Utilization history summary">
          <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
            WHAT THE EVIDENCE SAYS
          </p>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Latest point</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {latest?.utilization_pct == null
                  ? 'Unavailable'
                  : `${latest.utilization_pct.toFixed(1)}%`}
                {latest ? ` · ${formatDate(latest.as_of)}` : ''}
              </dd>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {latest ? pointBasis(latest) : 'No utilization value'}
              </p>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Peak in window</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {history.peak_daily_utilization_pct == null &&
                history.peak_statement_utilization_pct == null
                  ? 'Unavailable'
                  : `${Math.max(history.peak_statement_utilization_pct ?? 0, history.peak_daily_utilization_pct ?? 0).toFixed(1)}%`}
              </dd>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Issuer and daily evidence combined
              </p>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Target / hard limit</dt>
              <dd className="mt-1 text-sm font-extrabold">
                {history.target_breach_count} target · {history.credit_limit_breach_count}{' '}
                hard-limit breach{history.credit_limit_breach_count === 1 ? '' : 'es'}
              </dd>
            </div>
          </dl>
          <p className="mt-4 border-t border-border/65 pt-3 text-xs leading-5 text-muted-foreground">
            Issuer points are observed facts. Daily points roll settled activity forward from the
            latest statement and never claim live available credit.
          </p>
        </aside>
      </div>

      <details className="mt-4 rounded-lg border border-border/65 bg-card/55 p-4">
        <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
          View {evidencePoints.length} recent evidence points
        </summary>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[42rem] border-collapse text-left text-sm">
            <caption className="sr-only">Recent card utilization evidence points</caption>
            <thead>
              <tr className="border-b border-border/65 text-xs text-muted-foreground">
                <th scope="col" className="px-2 py-2 font-bold">
                  Date
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Basis
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Utilization
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Balance
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Status
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Confidence
                </th>
              </tr>
            </thead>
            <tbody>
              {evidencePoints.map((point) => (
                <tr
                  key={`${point.as_of}-${point.basis}`}
                  className="border-b border-border/45 last:border-0"
                >
                  <td className="whitespace-nowrap px-2 py-2 font-bold">
                    {formatDate(point.as_of)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-muted-foreground">
                    {pointBasis(point)}
                  </td>
                  <td className="money-value whitespace-nowrap px-2 py-2 font-extrabold">
                    {pointValue(point)}
                  </td>
                  <td className="money-value whitespace-nowrap px-2 py-2">
                    {point.balance == null ? '—' : formatCurrency(point.balance, currency)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2">{statusCopy[point.status]}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-muted-foreground">
                    {Math.round(point.confidence * 100)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      {history.reason_codes.length ? (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          {history.reason_codes.includes('unreviewed_activity_included')
            ? 'Some settled rows still need review; the estimate’s confidence is reduced.'
            : history.reason_codes.includes('pending_activity_excluded')
              ? 'Pending activity is excluded until settlement is observed.'
              : 'The history reflects the evidence currently retained for this card.'}
        </p>
      ) : null}
    </section>
  );
}
