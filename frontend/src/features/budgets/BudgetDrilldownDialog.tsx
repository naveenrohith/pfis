import { useState } from 'react';
import { ReceiptText } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { useBudgetDrilldown } from '@/features/workspace/queries';
import { formatCurrency, formatDate } from '@/lib/format';
import type { BudgetTracker } from '@/lib/types';

interface BudgetDrilldownDialogProps {
  budget: BudgetTracker;
  currency: string;
}

function signedCurrency(value: number, currency: string): string {
  return value > 0 ? `+${formatCurrency(value, currency)}` : formatCurrency(value, currency);
}

export function BudgetDrilldownDialog({ budget, currency }: BudgetDrilldownDialogProps) {
  const [open, setOpen] = useState(false);
  const drilldown = useBudgetDrilldown(budget.id, open);
  const details = drilldown.data;
  const label = details?.budget.category_name ?? budget.category;
  const remaining = details?.budget.remaining ?? budget.remaining;

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <ReceiptText className="h-3.5 w-3.5" aria-hidden="true" /> Inspect spend
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={`${label} spend evidence`}
        description="Transactions that contribute to this budget’s monthly actual spend."
        className="max-w-3xl"
      >
        {drilldown.isLoading ? (
          <div className="grid gap-3" aria-label="Loading budget spend evidence">
            <Skeleton className="h-20" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        ) : drilldown.isError ? (
          <div className="rounded-xl border border-danger/25 bg-danger/10 p-4 text-sm text-danger">
            Budget evidence could not be loaded. Close this panel and try again.
          </div>
        ) : details ? (
          <div className="grid gap-5">
            <section
              aria-label="Budget month summary"
              className="grid gap-3 rounded-xl border border-border bg-muted/30 p-4 sm:grid-cols-3"
            >
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
                  Remaining
                </p>
                <p className="mt-1 text-xl font-extrabold tabular-nums">
                  {formatCurrency(remaining, currency)}
                </p>
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
                  Month spend
                </p>
                <p className="mt-1 text-xl font-extrabold tabular-nums">
                  {formatCurrency(details.budget.actual_spend, currency)}
                </p>
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
                  Limit
                </p>
                <p className="mt-1 text-xl font-extrabold tabular-nums">
                  {formatCurrency(details.budget.monthly_limit, currency)}
                </p>
              </div>
            </section>

            {details.has_more ? (
              <p className="rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
                Showing the newest {details.transactions.length} of {details.transaction_count}{' '}
                contributing transactions. Totals still cover the whole month.
              </p>
            ) : null}

            {details.transactions.length === 0 ? (
              <EmptyState
                icon={<ReceiptText />}
                title="No contributing transactions"
                description="This budget has no settled spending rows for the selected month."
              />
            ) : (
              <ul className="grid gap-3" aria-label="Contributing transactions">
                {details.transactions.map((transaction) => {
                  const netsSpend = transaction.spend_effect < 0;
                  const transactionCurrency = transaction.currency || currency;
                  return (
                    <li
                      key={transaction.id}
                      className="grid gap-3 rounded-xl border border-border bg-card p-4 min-[361px]:grid-cols-[minmax(0,1fr)_auto] min-[361px]:items-start"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-bold">
                          {transaction.merchant || 'Unlabelled merchant'}
                        </p>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {formatDate(transaction.transaction_date)} ·{' '}
                          {transaction.transaction_type.replace('_', ' ')}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Ledger amount: {formatCurrency(transaction.amount, transactionCurrency)}
                        </p>
                      </div>
                      <div className="min-[361px]:text-right">
                        <p
                          className={
                            netsSpend
                              ? 'font-extrabold tabular-nums text-success'
                              : 'font-extrabold tabular-nums text-foreground'
                          }
                        >
                          {signedCurrency(transaction.spend_effect, transactionCurrency)}
                        </p>
                        <Badge variant={netsSpend ? 'success' : 'outline'} className="mt-2">
                          {netsSpend ? 'Nets against spend' : 'Adds to spend'}
                        </Badge>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ) : null}
      </Dialog>
    </>
  );
}
