import { useState } from 'react';
import { CheckCircle2, Eye, Landmark, ShieldAlert } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/Button';
import { Label, Select } from '@/components/ui/Input';
import { useAuth } from '@/features/auth/AuthContext';
import { queryKeys, useDepositStatementReviewItems } from '@/features/workspace/queries';
import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/format';
import type { DepositStatementReviewItem } from '@/lib/types';

const railOptions: Array<{
  value: NonNullable<DepositStatementReviewItem['payment_rail']>;
  label: string;
}> = [
  { value: 'upi', label: 'UPI' },
  { value: 'debit_card', label: 'Debit card' },
  { value: 'atm', label: 'ATM cash' },
  { value: 'transfer', label: 'Bank transfer' },
];

export function DepositStatementReviewPanel() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const review = useDepositStatementReviewItems();
  const [railByLine, setRailByLine] = useState<Record<string, string>>({});
  const [errorByLine, setErrorByLine] = useState<Record<string, string>>({});
  const resolve = useMutation({
    mutationFn: ({
      lineId,
      decision,
      paymentRail,
    }: {
      lineId: string;
      decision: 'ignore' | 'import';
      paymentRail?: string;
    }) => {
      if (!user) throw new Error('Sign in before reviewing a bank statement row');
      return api.reviewDepositStatementLine(user.id, lineId, {
        decision,
        payment_rail:
          decision === 'import'
            ? (paymentRail as 'upi' | 'debit_card' | 'atm' | 'transfer' | undefined)
            : null,
        note: 'User-confirmed deposit statement rail review.',
      });
    },
    onSuccess: async (_, variables) => {
      if (!user) return;
      setErrorByLine((current) => {
        const next = { ...current };
        delete next[variables.lineId];
        return next;
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.depositStatementReview(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) }),
        queryClient.invalidateQueries({ queryKey: ['transactions', user.id] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.statementReview(user.id) }),
      ]);
    },
    onError: (error, variables) => {
      setErrorByLine((current) => ({ ...current, [variables.lineId]: error.message }));
    },
  });

  if (review.isLoading) {
    return (
      <section
        className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
        aria-label="Loading deposit statement review queue…"
        role="status"
      >
        <div className="animate-soft-pulse space-y-3">
          <div className="h-3 w-40 rounded bg-muted" />
          <div className="h-6 w-72 rounded bg-muted" />
          <div className="h-16 rounded-lg bg-muted/70" />
        </div>
      </section>
    );
  }

  if (review.error) {
    return (
      <section
        className="rounded-xl border border-warning/35 bg-warning/5 p-5 sm:p-6"
        aria-labelledby="deposit-review-title"
        role="alert"
      >
        <p className="text-xs font-extrabold tracking-[0.08em] text-warning">
          BANK STATEMENT REVIEW
        </p>
        <h2 id="deposit-review-title" className="mt-1 text-lg font-extrabold">
          Review queue needs a refresh
        </h2>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Refresh the workspace to read unresolved bank rows. No ledger decision was made.
        </p>
      </section>
    );
  }

  const items = (review.data ?? []).slice(0, 50);
  if (!items.length) return null;

  return (
    <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="deposit-review-title">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-warning/10 text-warning">
          <ShieldAlert className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
            BANK STATEMENT REVIEW
          </p>
          <h2 id="deposit-review-title" className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
            {items.length} row{items.length === 1 ? '' : 's'} need a payment rail
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            PFIS found a bank transaction but could not prove whether it was UPI, a debit card, ATM
            cash, or a transfer. Choose the rail before importing, or hold the row outside the
            ledger.
          </p>
        </div>
      </div>

      <ul className="mt-5 divide-y divide-border/65 border-y border-border/65">
        {items.map((item) => {
          const selectedRail = railByLine[item.id] ?? '';
          const pending = resolve.isPending && resolve.variables?.lineId === item.id;
          return (
            <li key={item.id} className="py-4 first:pt-0 last:pb-0">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="flex items-start gap-2">
                    <Eye
                      className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-extrabold">
                        {item.account_label} · {item.masked_number}
                      </p>
                      <p className="mt-1 break-words text-sm text-foreground">{item.description}</p>
                    </div>
                  </div>
                  <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div>
                      <dt className="text-xs font-bold text-muted-foreground">Transaction date</dt>
                      <dd className="mt-0.5 text-xs font-extrabold">
                        {formatDate(item.transaction_date)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-bold text-muted-foreground">Amount</dt>
                      <dd className="money-value mt-0.5 text-xs font-extrabold">
                        {formatCurrency(item.amount, user?.currency ?? 'INR')}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-bold text-muted-foreground">Direction</dt>
                      <dd className="mt-0.5 text-xs font-extrabold">
                        {item.transaction_type === 'credit' ? 'Money in' : 'Money out'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs font-bold text-muted-foreground">Statement period</dt>
                      <dd className="mt-0.5 text-xs font-extrabold">
                        {formatDate(item.period_start)} – {formatDate(item.period_end)}
                      </dd>
                    </div>
                  </dl>
                </div>

                <div className="w-full shrink-0 space-y-2 lg:max-w-[18rem]">
                  <Label htmlFor={`deposit-rail-${item.id}`}>Payment rail</Label>
                  <Select
                    id={`deposit-rail-${item.id}`}
                    name={`deposit_rail_${item.id}`}
                    value={selectedRail}
                    onChange={(event) =>
                      setRailByLine((current) => ({ ...current, [item.id]: event.target.value }))
                    }
                    disabled={pending}
                  >
                    <option value="">Choose a rail</option>
                    {railOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      disabled={!selectedRail || pending}
                      onClick={() =>
                        resolve.mutate({
                          lineId: item.id,
                          decision: 'import',
                          paymentRail: selectedRail,
                        })
                      }
                    >
                      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      {pending ? 'Saving…' : 'Import row'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={pending}
                      onClick={() => resolve.mutate({ lineId: item.id, decision: 'ignore' })}
                    >
                      <Landmark className="h-4 w-4" aria-hidden="true" />
                      Hold outside ledger
                    </Button>
                  </div>
                  {errorByLine[item.id] ? (
                    <p role="alert" className="text-xs font-bold text-danger">
                      {errorByLine[item.id]}
                    </p>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {(review.data?.length ?? 0) > items.length ? (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          Showing the first 50 unresolved rows. Resolve these before continuing with the rest.
        </p>
      ) : null}
    </section>
  );
}
