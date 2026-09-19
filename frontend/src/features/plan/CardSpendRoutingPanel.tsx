import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, BadgePercent, CreditCard, Eye, Route, ShieldCheck } from 'lucide-react';
import { useAuth } from '@/features/auth/AuthContext';
import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/format';
import type {
  CardSpendRoutingOption,
  CardSpendRoutingPriority,
  CardSpendRoutingResponse,
} from '@/lib/types';

const priorityCopy: Record<CardSpendRoutingPriority, { label: string; detail: string }> = {
  utilization_safety: {
    label: 'Utilization safety',
    detail: 'Prefer the card with the most comfortable target and limit headroom.',
  },
  rewards: {
    label: 'Explicit rewards',
    detail: 'Prefer a matching user-entered reward rule, while still respecting the hard limit.',
  },
  balanced: {
    label: 'Balanced',
    detail: 'Balance utilization headroom, explicit rewards, and deterministic tie-breakers.',
  },
};

const optionStatusCopy: Record<CardSpendRoutingOption['status'], string> = {
  recommended: 'Recommended',
  eligible: 'Eligible',
  over_target: 'Over target',
  over_limit: 'Over hard limit',
  needs_review: 'Review evidence',
  unavailable: 'Unavailable',
};

function optionStatusTone(status: CardSpendRoutingOption['status']): string {
  if (status === 'recommended' || status === 'eligible') return 'text-success';
  if (status === 'over_target') return 'text-warning';
  return 'text-danger';
}

function amount(value: number | null | undefined, currency: string): string {
  return value == null ? 'Not available' : formatCurrency(value, currency);
}

function percent(value: number | null | undefined): string {
  return value == null ? 'Not available' : `${value.toFixed(1)}%`;
}

function rewardLabel(option: CardSpendRoutingOption, currency: string): string {
  if (option.reward_status !== 'explicit' || option.reward_rate_pct == null) {
    return option.reward_status === 'category_mismatch'
      ? 'No matching category rule'
      : 'No explicit rule';
  }
  const reward = amount(option.estimated_reward, currency);
  return `${option.reward_label ?? 'User rule'} / ${option.reward_rate_pct.toFixed(2)}% / ${reward}`;
}

function sourceLabel(source: CardSpendRoutingOption['source_kind']): string {
  if (source === 'provider') return 'Provider evidence';
  if (source === 'ledger_estimate') return 'Settled-ledger estimate';
  return 'No position evidence';
}

function resultCopy(result: CardSpendRoutingResponse): string {
  if (result.state === 'ready') {
    return 'A card can carry this hypothetical purchase within the current hard-limit evidence.';
  }
  if (result.state === 'partial') {
    return 'A recommendation exists, but another card still needs evidence review.';
  }
  if (result.state === 'no_active_cards') return 'Add an active card before previewing a route.';
  return 'No card can be recommended until current position, limit, and currency evidence are reviewable.';
}

export function CardSpendRoutingPanel({
  cardCount,
  currency,
}: {
  cardCount: number;
  currency: string;
}) {
  const { user } = useAuth();
  const [amountDraft, setAmountDraft] = useState('');
  const [category, setCategory] = useState('');
  const [priority, setPriority] = useState<CardSpendRoutingPriority>('balanced');
  const preview = useMutation({
    mutationFn: () => {
      if (!user) throw new Error('A signed-in user is required to preview card routing.');
      const numericAmount = Number(amountDraft);
      return api.cardSpendRouting(user.id, {
        amount: numericAmount,
        category: category.trim() || null,
        priority,
      });
    },
  });

  if (cardCount < 1) return null;

  const result = preview.data;
  const selectedPriority = priorityCopy[priority];
  const recommended = result?.recommended_card_id
    ? result.options.find((option) => option.financial_account_id === result.recommended_card_id)
    : undefined;

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const numericAmount = Number(amountDraft);
    if (!Number.isFinite(numericAmount) || numericAmount <= 0 || preview.isPending) return;
    preview.mutate();
  }

  return (
    <section
      className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
      aria-labelledby="card-spend-routing"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-intelligence/10 text-intelligence">
            <Route className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              PURCHASE ROUTING PREVIEW
            </p>
            <h2 id="card-spend-routing" className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
              Where would this purchase land?
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              Compare one hypothetical purchase across active cards using current position, target,
              hard-limit, and explicit reward evidence.
            </p>
          </div>
        </div>
        <p className="shrink-0 text-xs font-extrabold text-muted-foreground">READ-ONLY PREVIEW</p>
      </div>

      <form
        className="mt-5 grid gap-4 rounded-lg border border-border/65 bg-muted/25 p-4 lg:grid-cols-[minmax(9rem,0.7fr)_minmax(10rem,0.9fr)_minmax(13rem,1.2fr)_auto] lg:items-end"
        onSubmit={submit}
      >
        <div>
          <label htmlFor="routing-amount" className="text-xs font-bold text-muted-foreground">
            Purchase amount
          </label>
          <input
            id="routing-amount"
            name="routing_amount"
            type="number"
            min="0.01"
            step="0.01"
            inputMode="decimal"
            autoComplete="off"
            value={amountDraft}
            onChange={(event) => setAmountDraft(event.target.value)}
            placeholder="0.00"
            aria-describedby="routing-amount-help"
            className="focus-ring mt-1 h-11 w-full rounded-lg border border-input bg-card px-3 text-sm tabular-nums"
          />
          <p id="routing-amount-help" className="mt-1 text-xs text-muted-foreground">
            Currency: {currency}
          </p>
        </div>
        <div>
          <label htmlFor="routing-category" className="text-xs font-bold text-muted-foreground">
            Category (optional)
          </label>
          <input
            id="routing-category"
            name="routing_category"
            type="text"
            autoComplete="off"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            placeholder="Travel or groceries"
            className="focus-ring mt-1 h-11 w-full rounded-lg border border-input bg-card px-3 text-sm"
          />
        </div>
        <div>
          <label htmlFor="routing-priority" className="text-xs font-bold text-muted-foreground">
            Priority
          </label>
          <select
            id="routing-priority"
            name="routing_priority"
            value={priority}
            onChange={(event) => setPriority(event.target.value as CardSpendRoutingPriority)}
            className="focus-ring mt-1 h-11 w-full rounded-lg border border-input bg-card px-3 text-sm"
          >
            {Object.entries(priorityCopy).map(([value, option]) => (
              <option key={value} value={value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{selectedPriority.detail}</p>
        </div>
        <button
          type="submit"
          disabled={preview.isPending || !amountDraft}
          className="focus-ring min-h-11 rounded-lg bg-primary px-4 text-sm font-extrabold text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {preview.isPending ? 'Previewing' : 'Preview routing'}
        </button>
      </form>

      {preview.error ? (
        <div
          className="mt-4 flex items-start gap-3 rounded-lg border border-warning/35 bg-warning/5 p-4"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          <p className="text-sm leading-6 text-muted-foreground">
            Routing preview is unavailable. Confirm the amount and refresh the Cards workspace. No
            transaction or payment was created.
          </p>
        </div>
      ) : null}

      <div className="mt-4" aria-live="polite">
        {result ? (
          <div className="rounded-lg border border-intelligence/20 bg-intelligence/5 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-card text-intelligence">
                  {recommended ? (
                    <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Eye className="h-4 w-4" aria-hidden="true" />
                  )}
                </span>
                <div>
                  <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                    ROUTING RESULT
                  </p>
                  <h3 className="mt-1 text-lg font-extrabold">
                    {recommended ? `Recommended: ${recommended.label}` : 'No recommendation'}
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    {resultCopy(result)}
                  </p>
                </div>
              </div>
              <p className="shrink-0 text-xs font-extrabold text-muted-foreground">
                {Math.round(result.confidence * 100)}% confidence / {formatDate(result.as_of)}
              </p>
            </div>

            <div className="mt-4 overflow-x-auto rounded-lg border border-border/65 bg-card/70">
              <table
                className="w-full min-w-[60rem] text-left text-sm"
                aria-label="Hypothetical card routing options"
              >
                <caption className="sr-only">Card options for this hypothetical purchase</caption>
                <thead className="border-b border-border/65 text-xs font-extrabold text-muted-foreground">
                  <tr>
                    <th scope="col" className="px-4 py-3">
                      Card
                    </th>
                    <th scope="col" className="px-4 py-3">
                      Current / projected utilization
                    </th>
                    <th scope="col" className="px-4 py-3">
                      Target / hard headroom
                    </th>
                    <th scope="col" className="px-4 py-3">
                      Reward evidence
                    </th>
                    <th scope="col" className="px-4 py-3">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/65">
                  {result.options.map((option) => (
                    <tr key={option.financial_account_id}>
                      <th scope="row" className="px-4 py-3">
                        <div className="flex items-start gap-2">
                          <CreditCard
                            className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                            aria-hidden="true"
                          />
                          <span>
                            <span className="block font-extrabold">{option.label}</span>
                            <span className="mt-1 block text-xs text-muted-foreground">
                              {sourceLabel(option.source_kind)} /{' '}
                              {Math.round(option.confidence * 100)}% confidence
                            </span>
                          </span>
                        </div>
                      </th>
                      <td className="px-4 py-3 text-xs font-bold tabular-nums">
                        {percent(option.current_utilization_pct)} /{' '}
                        {percent(option.projected_statement_utilization_pct)}
                      </td>
                      <td className="px-4 py-3 text-xs font-bold">
                        {amount(option.target_headroom_amount, option.currency)} /{' '}
                        {amount(option.hard_headroom_amount, option.currency)}
                      </td>
                      <td className="px-4 py-3 text-xs font-bold">
                        <span className="flex items-center gap-1.5">
                          <BadgePercent
                            className="h-3.5 w-3.5 text-muted-foreground"
                            aria-hidden="true"
                          />
                          {rewardLabel(option, option.currency)}
                        </span>
                      </td>
                      <td
                        className={`px-4 py-3 text-xs font-extrabold ${optionStatusTone(option.status)}`}
                      >
                        {optionStatusCopy[option.status]}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-4 text-xs leading-5 text-muted-foreground">
              Reward values use only explicit user-entered rules. This preview does not quote issuer
              rewards, authorize a purchase, reserve cash, or create a transaction.
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-border/65 bg-muted/25 p-4 text-sm leading-6 text-muted-foreground">
            Enter an amount to compare the active cards. A blank result does not change any
            financial record.
          </div>
        )}
      </div>
    </section>
  );
}
