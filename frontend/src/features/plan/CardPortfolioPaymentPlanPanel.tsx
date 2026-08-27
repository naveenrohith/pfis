import { AlertTriangle, Banknote, CheckCircle2, CreditCard, Eye, WalletCards } from 'lucide-react';
import { formatCurrency, formatDate } from '@/lib/format';
import type {
  CardPortfolioPaymentPlan,
  CardPortfolioPaymentPlanCard,
  CardPortfolioPaymentPlanFundingPath,
  CardPortfolioPaymentPlanStrategy,
} from '@/lib/types';

const planStateCopy: Record<
  CardPortfolioPaymentPlan['state'],
  { label: string; detail: string; tone: string }
> = {
  no_active_cards: {
    label: 'No active cards',
    detail: 'Add an active card statement before comparing payment obligations.',
    tone: 'text-muted-foreground',
  },
  ready: {
    label: 'Plan is covered',
    detail: 'Known issuer targets have a mapped funding path inside the conservative lower band.',
    tone: 'text-success',
  },
  partial: {
    label: 'Plan needs attention',
    detail: 'At least one lower-band funding path may fall short before the issuer due date.',
    tone: 'text-warning',
  },
  needs_review: {
    label: 'Review the inputs',
    detail:
      'A statement, funding account, or balance anchor is missing for part of the comparison.',
    tone: 'text-warning',
  },
};

const strategyStatusCopy: Record<CardPortfolioPaymentPlanStrategy['status'], string> = {
  covered: 'Covered',
  at_risk: 'At risk',
  needs_statement: 'Statement needed',
  needs_payment_account: 'Funding account needed',
  needs_review: 'Review evidence',
  unavailable: 'Unavailable',
};

const runwayStatusCopy: Record<CardPortfolioPaymentPlanCard['runway_status'], string> = {
  covered: 'Covered',
  at_risk: 'At risk',
  needs_statement: 'Statement needed',
  needs_payment_account: 'Funding account needed',
  needs_funding_anchor: 'Balance anchor needed',
  needs_review: 'Review evidence',
  due_passed: 'Due date passed',
};

function statusTone(status: CardPortfolioPaymentPlanStrategy['status']): string {
  if (status === 'covered') return 'text-success';
  if (status === 'at_risk') return 'text-danger';
  return 'text-warning';
}

function pathStatusLabel(path: CardPortfolioPaymentPlanFundingPath): string {
  if (path.status === 'covered') return 'Covered path';
  if (path.status === 'at_risk') return 'Shortfall risk';
  if (path.status === 'unavailable') return 'Path unavailable';
  return 'Path needs review';
}

function amount(value: number | null | undefined, currency: string): string {
  return value == null ? 'Not available' : formatCurrency(value, currency);
}

function strategyAmount(
  strategy: CardPortfolioPaymentPlanStrategy,
  field: 'issuer_payment_target_total' | 'additional_payment_total',
  currency: string,
): string {
  return amount(strategy[field], currency);
}

function StrategyStatus({ strategy }: { strategy: CardPortfolioPaymentPlanStrategy }) {
  return (
    <span className={`text-xs font-extrabold ${statusTone(strategy.status)}`}>
      {strategyStatusCopy[strategy.status]}
    </span>
  );
}

export function CardPortfolioPaymentPlanPanel({
  plan,
  currency,
  isLoading = false,
  error,
}: {
  plan?: CardPortfolioPaymentPlan;
  currency: string;
  isLoading?: boolean;
  error?: unknown;
}) {
  if (isLoading) {
    return (
      <section
        className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
        aria-label="Loading payment plan"
        role="status"
      >
        <div className="animate-soft-pulse space-y-3">
          <div className="h-3 w-36 rounded bg-muted" />
          <div className="h-7 w-80 rounded bg-muted" />
          <div className="h-28 rounded-lg bg-muted/70" />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section
        className="rounded-xl border border-warning/35 bg-warning/5 p-5 sm:p-6"
        aria-labelledby="portfolio-payment-plan-title"
        role="alert"
      >
        <p className="text-xs font-extrabold tracking-[0.08em] text-warning">
          PAYMENT PLAN COMPASS
        </p>
        <h2 id="portfolio-payment-plan-title" className="mt-1 text-lg font-extrabold">
          Payment comparison needs a refresh
        </h2>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Refresh the Cards workspace before relying on the minimum or total due comparison. No
          payment was scheduled or submitted.
        </p>
      </section>
    );
  }

  if (!plan || plan.card_count < 2) return null;

  const copy = planStateCopy[plan.state];
  const minimum = plan.minimum_due_plan;
  const total = plan.total_due_plan;
  const paths = total.funding_paths.length ? total.funding_paths : minimum.funding_paths;
  const cards = plan.cards.slice(0, 20);

  return (
    <section
      className="rounded-xl border border-intelligence/20 bg-intelligence/5 p-5 sm:p-6"
      aria-labelledby="portfolio-payment-plan-title"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-card text-intelligence">
            <WalletCards className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              PAYMENT PLAN COMPASS
            </p>
            <h2
              id="portfolio-payment-plan-title"
              className="mt-1 text-xl font-extrabold tracking-[-0.03em]"
            >
              Minimum due or total due?
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{copy.detail}</p>
          </div>
        </div>
        <p className={`shrink-0 text-xs font-extrabold ${copy.tone}`}>
          {copy.label} / {Math.round(plan.confidence * 100)}% confidence / {formatDate(plan.as_of)}
        </p>
      </div>

      <dl className="mt-5 grid gap-px overflow-hidden rounded-lg border border-border/70 bg-border/70 sm:grid-cols-3">
        <div className="bg-card px-4 py-3.5">
          <dt className="text-xs font-bold text-muted-foreground">Minimum due target</dt>
          <dd className="money-value mt-1 text-lg font-extrabold">
            {strategyAmount(minimum, 'issuer_payment_target_total', currency)}
          </dd>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {minimum.cards_with_target} of {plan.card_count} cards with a target
          </p>
        </div>
        <div className="bg-card px-4 py-3.5">
          <dt className="text-xs font-bold text-muted-foreground">Total due target</dt>
          <dd className="money-value mt-1 text-lg font-extrabold">
            {strategyAmount(total, 'issuer_payment_target_total', currency)}
          </dd>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {total.cards_with_target} of {plan.card_count} cards with a target
          </p>
        </div>
        <div className="bg-card px-4 py-3.5">
          <dt className="text-xs font-bold text-muted-foreground">Funding paths</dt>
          <dd className="mt-1 text-sm font-extrabold">
            {total.cards_with_funding_path} of {plan.card_count} cards mapped
          </dd>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {total.cards_at_risk
              ? `${total.cards_at_risk} card(s) at lower-band risk`
              : 'No lower-band shortfall flagged'}
          </p>
        </div>
      </dl>

      <div className="mt-5 overflow-x-auto rounded-lg border border-border/65 bg-card/65">
        <table
          className="w-full min-w-[42rem] text-left text-sm"
          aria-label="Payment plan comparison"
        >
          <caption className="sr-only">Minimum due and total due payment scenarios</caption>
          <thead className="border-b border-border/65 text-xs font-extrabold text-muted-foreground">
            <tr>
              <th scope="col" className="px-4 py-3">
                Plan
              </th>
              <th scope="col" className="px-4 py-3">
                Issuer target
              </th>
              <th scope="col" className="px-4 py-3">
                Additional after planned
              </th>
              <th scope="col" className="px-4 py-3">
                Lower-band coverage
              </th>
              <th scope="col" className="px-4 py-3">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/65">
            {[minimum, total].map((strategy) => (
              <tr key={strategy.strategy}>
                <th scope="row" className="px-4 py-3 font-extrabold">
                  {strategy.strategy === 'minimum_due' ? 'Minimum due' : 'Total due'}
                </th>
                <td className="money-value px-4 py-3 font-extrabold">
                  {strategyAmount(strategy, 'issuer_payment_target_total', currency)}
                </td>
                <td className="money-value px-4 py-3 font-extrabold">
                  {strategyAmount(strategy, 'additional_payment_total', currency)}
                </td>
                <td className="px-4 py-3 text-xs font-bold">
                  {strategy.cards_covered_on_lower_band} covered / {strategy.cards_at_risk} at risk
                </td>
                <td className="px-4 py-3">
                  <StrategyStatus strategy={strategy} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border/65 bg-card/60 p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
              {total.status === 'at_risk' ? (
                <AlertTriangle className="h-4 w-4 text-warning" aria-hidden="true" />
              ) : total.status === 'covered' ? (
                <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
              ) : (
                <Eye className="h-4 w-4" aria-hidden="true" />
              )}
            </span>
            <div className="min-w-0">
              <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                TOTAL-DUE DECISION
              </p>
              <p className="mt-1 text-sm font-extrabold">
                {total.effective_payment_total == null
                  ? strategyStatusCopy[total.status]
                  : `${formatCurrency(total.effective_payment_total, currency)} planned in total`}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {total.planned_payment_total > 0
                  ? `${formatCurrency(total.planned_payment_total, currency)} already exists in recorded intentions; the comparison adds only the remainder.`
                  : 'No existing payment intention is credited toward this comparison.'}
              </p>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-border/65 bg-card/60 p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground">
              <Banknote className="h-4 w-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                FUNDING EVIDENCE
              </p>
              <p className="mt-1 text-sm font-extrabold">
                {paths.length
                  ? `${paths.length} shared funding path${paths.length === 1 ? '' : 's'}`
                  : 'No mapped funding path'}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {paths.length
                  ? 'Each path replays obligations in due-date order against one conservative forecast.'
                  : 'Select a paying bank account and provide a verified or estimated balance anchor before relying on coverage.'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {paths.length ? (
        <div className="mt-4 divide-y divide-border/65 rounded-lg border border-border/65 bg-card/55">
          {paths.map((path) => (
            <article
              key={path.funding_account_id}
              className="flex min-w-0 flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex min-w-0 items-start gap-3">
                <Banknote
                  className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                  aria-hidden="true"
                />
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-extrabold">{path.funding_account_label}</h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {pathStatusLabel(path)} / {path.cards_covered_on_lower_band} covered /{' '}
                    {path.cards_at_risk} at risk
                  </p>
                </div>
              </div>
              <div className="grid shrink-0 grid-cols-2 gap-x-5 gap-y-2 text-right sm:grid-cols-3">
                <div>
                  <p className="text-xs font-bold text-muted-foreground">Lowest lower band</p>
                  <p className="money-value mt-0.5 text-xs font-extrabold">
                    {amount(path.lowest_lower_band_balance_after, currency)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-bold text-muted-foreground">Cash gap</p>
                  <p className="money-value mt-0.5 text-xs font-extrabold">
                    {path.lower_band_cash_gap
                      ? formatCurrency(path.lower_band_cash_gap, currency)
                      : 'None'}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-bold text-muted-foreground">Shortfall date</p>
                  <p className="mt-0.5 text-xs font-extrabold">
                    {path.first_lower_band_shortfall_date
                      ? formatDate(path.first_lower_band_shortfall_date)
                      : 'None'}
                  </p>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      <details className="group mt-4 rounded-lg border border-border/65 bg-card/55">
        <summary className="focus-ring flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-extrabold [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-2">
            <CreditCard className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            Review per-card payment evidence
          </span>
          <span className="text-xs text-muted-foreground">{cards.length} cards</span>
        </summary>
        <div className="overflow-x-auto border-t border-border/65">
          <table
            className="w-full min-w-[44rem] text-left text-sm"
            aria-label="Per-card payment evidence"
          >
            <caption className="sr-only">Per-card dues, funding account, and runway status</caption>
            <thead className="border-b border-border/65 text-xs font-extrabold text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-3">
                  Card
                </th>
                <th scope="col" className="px-4 py-3">
                  Due date
                </th>
                <th scope="col" className="px-4 py-3">
                  Minimum / total
                </th>
                <th scope="col" className="px-4 py-3">
                  Funding account
                </th>
                <th scope="col" className="px-4 py-3">
                  Runway
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/65">
              {cards.map((card) => (
                <tr key={card.financial_account_id}>
                  <th scope="row" className="px-4 py-3 font-extrabold">
                    {card.label}
                  </th>
                  <td className="px-4 py-3 text-xs font-bold">
                    {card.due_date ? formatDate(card.due_date) : 'Not available'}
                  </td>
                  <td className="money-value px-4 py-3 text-xs font-extrabold">
                    {amount(card.minimum_due, card.currency)} /{' '}
                    {amount(card.total_due, card.currency)}
                  </td>
                  <td className="px-4 py-3 text-xs font-bold">
                    {card.funding_account_label ?? 'Not selected'}
                  </td>
                  <td className="px-4 py-3 text-xs font-extrabold">
                    {runwayStatusCopy[card.runway_status]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <p className="mt-4 text-xs leading-5 text-muted-foreground">
        This is a read-only planning comparison. It does not schedule, submit, reserve, or confirm a
        payment. Lower-band coverage is a conservative forecast signal, not a bank guarantee.
      </p>
    </section>
  );
}
