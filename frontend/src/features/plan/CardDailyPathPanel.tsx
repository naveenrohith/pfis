import { Activity, AlertTriangle, CalendarRange, ShieldCheck } from 'lucide-react';
import { ChartFrame } from '@/components/system';
import { formatCurrency, formatDate } from '@/lib/format';
import type { CardStatementProjection, CardStatementProjectionPoint } from '@/lib/types';

const targetStatusCopy: Record<
  CardStatementProjectionPoint['target_status'],
  { label: string; tone: string }
> = {
  under_target: { label: 'Within target', tone: 'text-success' },
  at_risk: { label: 'Target at risk', tone: 'text-warning' },
  over_target: { label: 'Over target', tone: 'text-danger' },
  unavailable: { label: 'Target unavailable', tone: 'text-muted-foreground' },
};

const limitStatusCopy: Record<
  CardStatementProjectionPoint['credit_limit_status'],
  { label: string; tone: string }
> = {
  under_limit: { label: 'Within hard limit', tone: 'text-success' },
  at_risk: { label: 'Hard limit at risk', tone: 'text-warning' },
  over_limit: { label: 'Over hard limit', tone: 'text-danger' },
  unavailable: { label: 'Hard limit unavailable', tone: 'text-muted-foreground' },
};

function pointY(utilization: number, scale: number): number {
  return Math.max(8, Math.min(90, 90 - (utilization / scale) * 76));
}

function pointX(index: number, count: number): number {
  return count === 1 ? 50 : (index / (count - 1)) * 100;
}

function pointStatus<T extends keyof CardStatementProjectionPoint>(
  point: CardStatementProjectionPoint,
  key: T,
): CardStatementProjectionPoint[T] {
  return point[key];
}

function firstPointWithStatus(
  points: CardStatementProjectionPoint[],
  statusKey: 'target_status' | 'credit_limit_status',
): CardStatementProjectionPoint | undefined {
  return points.find((point) => {
    const status = pointStatus(point, statusKey);
    return status === 'at_risk' || status === 'over_target' || status === 'over_limit';
  });
}

function eventPoints(points: CardStatementProjectionPoint[]): CardStatementProjectionPoint[] {
  return points.filter((point) => point.event_labels.length > 0).slice(0, 6);
}

function balanceRange(point: CardStatementProjectionPoint, currency: string): string {
  return `${formatCurrency(point.range_low, currency)} - ${formatCurrency(point.range_high, currency)}`;
}

export function CardDailyPathPanel({
  projection,
  currency,
  targetPct,
  creditLimit,
}: {
  projection: CardStatementProjection;
  currency: string;
  targetPct?: number | null;
  creditLimit?: number | null;
}) {
  const points = projection.daily_path ?? [];
  if (projection.status !== 'available' || !points.length) return null;

  const first = points[0];
  const close = points[points.length - 1];
  const targetPressure = firstPointWithStatus(points, 'target_status');
  const limitPressure = firstPointWithStatus(points, 'credit_limit_status');
  const datedEvents = eventPoints(points);
  const hasLimitAnchor = creditLimit != null && creditLimit > 0;
  const maxUtilization = Math.max(
    100,
    Math.ceil(
      Math.max(
        ...points.map((point) =>
          Math.max(
            point.projected_utilization_pct,
            hasLimitAnchor ? (point.range_high / creditLimit!) * 100 : 0,
          ),
        ),
        0,
      ) / 10,
    ) * 10,
  );
  const chartPoints = points
    .map(
      (point, index) =>
        `${pointX(index, points.length).toFixed(2)},${pointY(point.projected_utilization_pct, maxUtilization).toFixed(2)}`,
    )
    .join(' ');
  const uncertaintyBand = hasLimitAnchor
    ? [
        ...points.map(
          (point, index) =>
            `${pointX(index, points.length).toFixed(2)},${pointY((point.range_high / creditLimit!) * 100, maxUtilization).toFixed(2)}`,
        ),
        ...points
          .map(
            (point, index) =>
              `${pointX(index, points.length).toFixed(2)},${pointY((point.range_low / creditLimit!) * 100, maxUtilization).toFixed(2)}`,
          )
          .reverse(),
      ].join(' ')
    : null;
  const limitY = pointY(100, maxUtilization).toFixed(2);
  const targetY =
    targetPct == null ? null : pointY(Math.max(targetPct, 0), maxUtilization).toFixed(2);
  const chartLabel = `Daily card path from ${formatDate(first.date)} through ${formatDate(close.date)}. Projected utilization closes at ${close.projected_utilization_pct.toFixed(1)} percent.`;
  const closeLimitCopy = limitStatusCopy[projection.credit_limit_status];
  const closeTargetCopy = targetStatusCopy[projection.target_status];

  return (
    <section
      className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
      aria-labelledby="card-daily-path-title"
      aria-live="polite"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-intelligence/10 text-intelligence">
            <CalendarRange className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              DAILY PATH TO STATEMENT CLOSE
            </p>
            <h2
              id="card-daily-path-title"
              className="mt-1 text-xl font-extrabold tracking-[-0.03em]"
            >
              A dated view of what may happen next
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              {hasLimitAnchor
                ? 'The shaded range is the projected balance range expressed against the credit limit on file.'
                : 'The estimate range is available in the day-by-day evidence below. A utilization band needs a credit limit on file.'}{' '}
              This is a PFIS estimate, not an issuer schedule or live available-credit value.
            </p>
          </div>
        </div>
        <p className="shrink-0 text-xs font-extrabold text-muted-foreground">
          {points.length} day{points.length === 1 ? '' : 's'} /{' '}
          {Math.round(projection.confidence * 100)}% confidence
        </p>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(16rem,0.65fr)] lg:items-start">
        <div className="min-w-0 rounded-lg border border-border/65 bg-muted/25 p-4">
          <ChartFrame
            title="Projected utilization by day"
            description={`Percent of the credit limit on file · ${formatDate(first.date)} to ${formatDate(close.date)} · scale 0–${maxUtilization}%`}
            summary={`${chartLabel} ${hasLimitAnchor ? 'The shaded band shows the low-to-high projected balance range as utilization of the credit limit on file.' : 'The utilization range is not plotted because no credit limit anchor is available.'}`}
          >
            <svg className="h-40 w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
              <title>Daily card utilization trajectory</title>
              <desc>
                The solid line is the central PFIS estimate. A shaded region shows the low-to-high
                projected balance range when a credit limit anchor is available. Dashed guides show
                the configured target and 100 percent hard limit.
              </desc>
              {uncertaintyBand ? (
                <polygon
                  points={uncertaintyBand}
                  fill="currentColor"
                  className="text-intelligence/15"
                  stroke="none"
                />
              ) : null}
              <line
                x1="0"
                y1={limitY}
                x2="100"
                y2={limitY}
                stroke="currentColor"
                className="text-danger/55"
                strokeWidth="0.8"
                strokeDasharray="2 2"
              />
              {targetY != null ? (
                <line
                  x1="0"
                  y1={targetY}
                  x2="100"
                  y2={targetY}
                  stroke="currentColor"
                  className="text-warning"
                  strokeWidth="0.8"
                  strokeDasharray="2 2"
                />
              ) : null}
              <polyline
                points={chartPoints}
                fill="none"
                stroke="currentColor"
                className="text-intelligence"
                strokeWidth="1.8"
                vectorEffect="non-scaling-stroke"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {points.map((point, index) => (
                <circle
                  key={point.date}
                  cx={pointX(index, points.length)}
                  cy={pointY(point.projected_utilization_pct, maxUtilization)}
                  r={point.event_labels.length ? 2.6 : 1.6}
                  fill="currentColor"
                  className={point.event_labels.length ? 'text-warning' : 'text-intelligence'}
                />
              ))}
            </svg>
          </ChartFrame>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-intelligence" aria-hidden="true" />
              Central estimate
            </span>
            {hasLimitAnchor ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="h-2 w-3 rounded-sm bg-intelligence/20" aria-hidden="true" />
                Projected range
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1.5">
              <span className="h-px w-3 border-t border-dashed border-danger" aria-hidden="true" />
              Hard limit / 100%
            </span>
            {targetPct != null ? (
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="h-px w-3 border-t border-dashed border-warning"
                  aria-hidden="true"
                />
                {targetPct.toFixed(0)}% target
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-warning" aria-hidden="true" />
              Known dated event
            </span>
          </div>
        </div>

        <aside className="rounded-lg bg-muted/35 p-4" aria-label="Daily path runway readout">
          <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
            RUNWAY READOUT
          </p>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Projected close</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {formatCurrency(close.projected_balance, currency)}
              </dd>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {formatDate(close.date)} / {close.projected_utilization_pct.toFixed(1)}% utilization
              </p>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Target runway</dt>
              <dd className={`mt-1 text-sm font-extrabold ${closeTargetCopy.tone}`}>
                {closeTargetCopy.label}
              </dd>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {targetPressure
                  ? `First pressure ${formatDate(targetPressure.date)} / day ${targetPressure.days_from_today}.`
                  : 'No target pressure on the central path before close.'}
              </p>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Hard-limit runway</dt>
              <dd className={`mt-1 text-sm font-extrabold ${closeLimitCopy.tone}`}>
                {closeLimitCopy.label}
              </dd>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {limitPressure
                  ? `First pressure ${formatDate(limitPressure.date)} / day ${limitPressure.days_from_today}.`
                  : 'No hard-limit pressure on the central path before close.'}
              </p>
            </div>
          </dl>
          <div className="mt-4 border-t border-border/65 pt-3 text-xs leading-5 text-muted-foreground">
            <p className="flex items-start gap-2">
              {projection.credit_limit_status === 'over_limit' ? (
                <AlertTriangle
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger"
                  aria-hidden="true"
                />
              ) : (
                <ShieldCheck
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 text-intelligence"
                  aria-hidden="true"
                />
              )}
              <span>
                {projection.credit_limit_status === 'over_limit'
                  ? 'The central estimate reaches or exceeds the observed limit before close; this is a risk signal, not a decline prediction.'
                  : projection.credit_limit_status === 'at_risk'
                    ? 'The uncertainty band crosses the observed limit; keep the range visible before making a decision.'
                    : 'The central path stays below the observed limit through the projected close.'}
              </span>
            </p>
          </div>
        </aside>
      </div>

      <div className="mt-4 rounded-lg border border-border/65 bg-card/65 p-4">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
            KNOWN DATED EVENTS
          </p>
          <p className="text-xs text-muted-foreground">{datedEvents.length} shown</p>
        </div>
        {datedEvents.length ? (
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {datedEvents.map((point) => (
              <li key={point.date} className="rounded-md bg-muted/45 p-3">
                <p className="text-xs font-extrabold">{formatDate(point.date)}</p>
                <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">
                  {point.event_labels.join(' / ')}
                </p>
                <p className="money-value mt-1 text-xs font-bold">
                  {point.event_amount < 0 ? 'Payment' : 'Charge'} /{' '}
                  {formatCurrency(Math.abs(point.event_amount), currency)}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-muted-foreground">
            No dated payment, scheduled-charge, or recurring-charge event is on this path.
          </p>
        )}
      </div>

      <details className="mt-4 rounded-lg border border-border/65 bg-card/55 p-4">
        <summary className="focus-ring cursor-pointer rounded text-sm font-extrabold">
          View {points.length} day-by-day evidence points
        </summary>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[62rem] border-collapse text-left text-sm">
            <caption className="sr-only">Daily card projection evidence points</caption>
            <thead>
              <tr className="border-b border-border/65 text-xs text-muted-foreground">
                <th scope="col" className="px-2 py-2 font-bold">
                  Date
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Projected balance range
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Utilization
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Target
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Hard limit
                </th>
                <th scope="col" className="px-2 py-2 font-bold">
                  Known event
                </th>
              </tr>
            </thead>
            <tbody>
              {points.map((point) => (
                <tr key={point.date} className="border-b border-border/45 last:border-0">
                  <th scope="row" className="whitespace-nowrap px-2 py-2 font-bold">
                    {formatDate(point.date)} / day {point.days_from_today}
                  </th>
                  <td className="money-value whitespace-nowrap px-2 py-2">
                    {balanceRange(point, currency)}
                  </td>
                  <td className="money-value whitespace-nowrap px-2 py-2 font-extrabold">
                    {point.projected_utilization_pct.toFixed(1)}%
                  </td>
                  <td
                    className={`whitespace-nowrap px-2 py-2 ${targetStatusCopy[point.target_status].tone}`}
                  >
                    {targetStatusCopy[point.target_status].label}
                  </td>
                  <td
                    className={`whitespace-nowrap px-2 py-2 ${limitStatusCopy[point.credit_limit_status].tone}`}
                  >
                    {limitStatusCopy[point.credit_limit_status].label}
                  </td>
                  <td className="max-w-[16rem] break-words px-2 py-2 text-xs text-muted-foreground">
                    {point.event_labels.length ? point.event_labels.join(' / ') : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-muted-foreground">
        <Activity className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>
          The path uses settled activity, retained plans, and explicit recurring evidence. It can
          inform a review, but it cannot confirm an issuer balance, available credit, or payment
          outcome.
        </span>
      </p>
    </section>
  );
}
