import { AlertTriangle, CalendarClock, CheckCircle2, CreditCard, Eye } from 'lucide-react';
import { formatCurrency, formatDate } from '@/lib/format';
import type {
  CardPortfolioUpcomingCard,
  CardPortfolioUpcomingState,
  CardUpcomingEvent,
} from '@/lib/types';

const stateCopy: Record<
  CardPortfolioUpcomingState['state'],
  { label: string; detail: string; tone: string }
> = {
  no_active_cards: {
    label: 'No active cards',
    detail: 'Add a card account to build a portfolio timeline.',
    tone: 'text-muted-foreground',
  },
  monitor_cycle: {
    label: 'Monitor the portfolio',
    detail: 'No higher-priority due or pressure event is currently evidenced.',
    tone: 'text-success',
  },
  payment_due: {
    label: 'Payment due next',
    detail: 'One or more issuer due dates are the next dated obligation.',
    tone: 'text-warning',
  },
  target_pressure: {
    label: 'Target pressure',
    detail: "A card's estimated path is approaching or above its utilization target.",
    tone: 'text-warning',
  },
  limit_pressure: {
    label: 'Limit pressure',
    detail: "A card's evidence indicates hard-limit pressure; review before new spend.",
    tone: 'text-danger',
  },
  review_evidence: {
    label: 'Review the evidence',
    detail: 'One or more cards lack enough evidence for a reliable next state.',
    tone: 'text-warning',
  },
  no_upcoming_evidence: {
    label: 'No upcoming evidence',
    detail: 'The active cards do not currently expose a dated next event.',
    tone: 'text-muted-foreground',
  },
};

const cardStateLabel: Record<CardPortfolioUpcomingCard['state'], string> = {
  monitor_cycle: 'Monitor cycle',
  payment_due: 'Payment due',
  target_pressure: 'Target pressure',
  limit_pressure: 'Limit pressure',
  review_evidence: 'Review evidence',
  no_upcoming_evidence: 'No upcoming event',
};

function eventSourceLabel(sourceKind?: string): string {
  switch (sourceKind) {
    case 'issuer':
      return 'Issuer evidence';
    case 'user':
      return 'User plan';
    case 'ledger':
      return 'Ledger evidence';
    case 'forecast':
      return 'PFIS estimate';
    default:
      return 'Evidence pending';
  }
}

const eventTypeCopy: Record<CardUpcomingEvent['event_type'], string> = {
  payment_due: 'Payment due',
  statement_close: 'Statement close',
  planned_payment: 'Planned payment',
  projected_charge: 'Projected charge',
  utilization_target_breach: 'Utilization target pressure',
  credit_limit_breach: 'Credit-limit pressure',
  calendar_event: 'Calendar reminder',
  pending_refund: 'Pending refund',
};

const eventStatusCopy: Record<CardUpcomingEvent['status'], string> = {
  observed: 'Observed',
  planned: 'Planned',
  estimated: 'Estimate',
  risk: 'Risk signal',
};

function relativeDayLabel(days: number): string {
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days > 1) return `In ${days} days`;
  if (days === -1) return 'Yesterday';
  return `${Math.abs(days)} days ago`;
}

function reasonLabel(reason: string): string {
  return reason.replaceAll('_', ' ');
}

function eventTone(status: CardUpcomingEvent['status']): string {
  if (status === 'risk') return 'border-warning/35 bg-warning/5';
  if (status === 'observed') return 'border-success/20 bg-success/5';
  return 'border-border/65 bg-card/60';
}

function PortfolioEventTimeline({
  events,
  currency,
}: {
  events: CardUpcomingEvent[];
  currency: string;
}) {
  if (!events.length) return null;

  const visibleEvents = [...events]
    .sort((left, right) => left.date.localeCompare(right.date) || left.id.localeCompare(right.id))
    .slice(0, 18);
  const riskCount = events.filter((event) => event.status === 'risk').length;

  return (
    <details className="mt-4 rounded-lg border border-border/65 bg-card/45">
      <summary className="focus-ring flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg p-4 text-sm font-extrabold [&::-webkit-details-marker]:hidden">
        <span>Review {events.length} dated events</span>
        <span className="text-xs text-muted-foreground">
          {riskCount ? `${riskCount} risk signal${riskCount === 1 ? '' : 's'}` : 'No risk signals'}
        </span>
      </summary>
      <div className="border-t border-border/65 px-4 pb-4">
        <ol className="mt-4 space-y-2" aria-label="Portfolio dated event evidence">
          {visibleEvents.map((event) => (
            <li key={event.id} className={`rounded-lg border p-3 ${eventTone(event.status)}`}>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="text-xs font-extrabold tracking-[0.04em] text-muted-foreground">
                    <time dateTime={event.date}>{formatDate(event.date)}</time> /{' '}
                    {relativeDayLabel(event.days_from_today)}
                  </p>
                  <p className="mt-1 text-sm font-extrabold">
                    {eventTypeCopy[event.event_type]}: {event.label}
                  </p>
                </div>
                <div className="shrink-0 text-left sm:text-right">
                  <p className="text-xs font-extrabold">{eventStatusCopy[event.status]}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {eventSourceLabel(event.source_kind)} / {Math.round(event.confidence * 100)}%
                    confidence
                  </p>
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {event.amount != null ? (
                  <span className="money-value font-bold">
                    {formatCurrency(event.amount, currency)}
                  </span>
                ) : null}
                {event.reason_codes.slice(0, 2).map((reason) => (
                  <span key={reason}>Evidence: {reasonLabel(reason)}</span>
                ))}
              </div>
            </li>
          ))}
        </ol>
        {events.length > visibleEvents.length ? (
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            Showing the first {visibleEvents.length} dated events. The remaining events stay in the
            portfolio response but are not expanded here.
          </p>
        ) : null}
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          This is evidence for planning only. PFIS does not schedule, submit, reserve, or confirm a
          payment from this timeline.
        </p>
      </div>
    </details>
  );
}

export function CardPortfolioUpcomingPanel({
  portfolio,
  currency,
  isLoading = false,
  error,
}: {
  portfolio?: CardPortfolioUpcomingState;
  currency: string;
  isLoading?: boolean;
  error?: unknown;
}) {
  if (isLoading) {
    return (
      <section
        className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
        aria-label="Loading portfolio next state..."
        role="status"
      >
        <div className="animate-soft-pulse space-y-3">
          <div className="h-3 w-40 rounded bg-muted" />
          <div className="h-7 w-72 rounded bg-muted" />
          <div className="h-24 rounded-lg bg-muted/70" />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section
        className="rounded-xl border border-warning/35 bg-warning/5 p-5 sm:p-6"
        aria-labelledby="portfolio-upcoming-title"
        role="alert"
      >
        <p className="text-xs font-extrabold tracking-[0.08em] text-warning">
          PORTFOLIO NEXT STATE
        </p>
        <h2 id="portfolio-upcoming-title" className="mt-1 text-lg font-extrabold">
          Portfolio timeline needs a refresh
        </h2>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Refresh the Cards workspace to compare the active cards. No payment or balance action was
          taken.
        </p>
      </section>
    );
  }

  if (!portfolio || portfolio.card_count < 2) return null;

  const copy = stateCopy[portfolio.state];
  const nextEvent = portfolio.next_event;
  const visibleCards = portfolio.cards.slice(0, 20);

  return (
    <section
      className="rounded-xl border border-intelligence/20 bg-intelligence/5 p-5 sm:p-6"
      aria-labelledby="portfolio-upcoming-title"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-card text-intelligence">
            <CalendarClock className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              PORTFOLIO NEXT STATE
            </p>
            <h2
              id="portfolio-upcoming-title"
              className="mt-1 text-xl font-extrabold tracking-[-0.03em]"
            >
              {copy.label}
            </h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{copy.detail}</p>
          </div>
        </div>
        <p className={`shrink-0 text-xs font-extrabold ${copy.tone}`}>
          {Math.round(portfolio.confidence * 100)}% confidence / {formatDate(portfolio.as_of)}
        </p>
      </div>

      <dl className="mt-5 grid gap-px overflow-hidden rounded-lg border border-border/70 bg-border/70 sm:grid-cols-3">
        <div className="bg-card px-4 py-3.5">
          <dt className="text-xs font-bold text-muted-foreground">Issuer total due</dt>
          <dd className="money-value mt-1 text-lg font-extrabold">
            {portfolio.issuer_total_due == null
              ? 'Unavailable'
              : formatCurrency(portfolio.issuer_total_due, currency)}
          </dd>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {portfolio.issuer_total_due_cards} of {portfolio.card_count} cards with due evidence
          </p>
        </div>
        <div className="bg-card px-4 py-3.5">
          <dt className="text-xs font-bold text-muted-foreground">Earliest dated event</dt>
          <dd className="mt-1 text-sm font-extrabold">
            {nextEvent ? formatDate(nextEvent.date) : 'No dated event'}
          </dd>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {nextEvent ? eventSourceLabel(nextEvent.source_kind) : 'Evidence unavailable'}
          </p>
        </div>
        <div className="bg-card px-4 py-3.5">
          <dt className="text-xs font-bold text-muted-foreground">Evidence coverage</dt>
          <dd className="mt-1 text-sm font-extrabold">
            {portfolio.cards_needing_review
              ? `${portfolio.cards_needing_review} card${portfolio.cards_needing_review === 1 ? '' : 's'} need review`
              : 'All cards have a next-state read'}
          </dd>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {portfolio.issuer_total_due_complete ? 'Issuer dues complete' : 'Issuer dues partial'}
          </p>
        </div>
      </dl>

      {nextEvent ? (
        <div className="mt-4 flex items-start gap-3 rounded-lg border border-border/65 bg-card/75 p-4">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
            {nextEvent.status === 'risk' ? (
              <AlertTriangle className="h-4 w-4 text-warning" aria-hidden="true" />
            ) : nextEvent.source_kind === 'issuer' ? (
              <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
            ) : (
              <Eye className="h-4 w-4" aria-hidden="true" />
            )}
          </span>
          <div className="min-w-0">
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              NEXT SHARED ATTENTION
            </p>
            <p className="mt-1 text-sm font-extrabold">{nextEvent.label}</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {formatDate(nextEvent.date)} / {eventSourceLabel(nextEvent.source_kind)} /{' '}
              {Math.round(nextEvent.confidence * 100)}% confidence
              {nextEvent.amount != null ? ` / ${formatCurrency(nextEvent.amount, currency)}` : ''}
            </p>
          </div>
        </div>
      ) : null}

      <div className="mt-4 divide-y divide-border/65 rounded-lg border border-border/65 bg-card/55">
        {visibleCards.map((card) => (
          <article
            key={card.financial_account_id}
            className="flex min-w-0 flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex min-w-0 items-start gap-3">
              <CreditCard
                className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              <div className="min-w-0">
                <h3 className="truncate text-sm font-extrabold">{card.label}</h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {card.next_event
                    ? `${card.next_event.label} / ${formatDate(card.next_event.date)}`
                    : 'No dated event in retained evidence'}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-4 sm:text-right">
              <div>
                <p className="text-xs font-bold text-muted-foreground">State</p>
                <p className="mt-0.5 text-xs font-extrabold">{cardStateLabel[card.state]}</p>
              </div>
              <div>
                <p className="text-xs font-bold text-muted-foreground">Due</p>
                <p className="money-value mt-0.5 text-xs font-extrabold">
                  {card.total_due == null
                    ? 'Not available'
                    : formatCurrency(card.total_due, currency)}
                </p>
              </div>
            </div>
          </article>
        ))}
      </div>

      <PortfolioEventTimeline events={portfolio.events} currency={currency} />

      <p className="mt-4 text-xs leading-5 text-muted-foreground">
        This view aggregates only known issuer dues. Estimated outstanding remains per-card and is
        not merged into a synthetic live balance or available-credit total.
      </p>
    </section>
  );
}
