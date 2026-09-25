import { Suspense } from 'react';
import { ListChecks, Wallet } from 'lucide-react';
import { PageIntro, WorkspaceContextBar } from '@/components/system';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Tabs } from '@/components/ui/Tabs';
import { useDashboardUi } from '@/app/DashboardUiContext';
import {
  useAccounts,
  useCashPocketBalance,
  useTransactions,
} from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency, formatDate } from '@/lib/format';
import { lazyWithRetry } from '@/lib/lazyWithRetry';

const ReviewSection = lazyWithRetry(
  () =>
    import('@/features/review/ReviewSection').then((module) => ({
      default: module.ReviewSection,
    })),
  'activity-review',
);
const TimelineSection = lazyWithRetry(
  () =>
    import('@/features/timeline/TimelineSection').then((module) => ({
      default: module.TimelineSection,
    })),
  'activity-timeline',
);
const TransactionsSection = lazyWithRetry(
  () =>
    import('@/features/transactions/TransactionsSection').then((module) => ({
      default: module.TransactionsSection,
    })),
  'activity-transactions',
);

type ActivityView = 'transactions' | 'review' | 'timeline';

export function ActivityExperience() {
  const { user } = useAuth();
  const transactions = useTransactions();
  const accounts = useAccounts();
  const { activeSection, scrollTo } = useDashboardUi();
  const pendingTransactionCount = (transactions.data ?? []).filter(
    (transaction) => !transaction.reviewed_flag,
  ).length;
  const cashAccount = (accounts.data ?? []).find(
    (account) => account.is_active && account.account_type === 'cash',
  );
  const cashPocket = useCashPocketBalance(cashAccount?.id);
  const view: ActivityView =
    activeSection === 'review' || activeSection === 'timeline' ? activeSection : 'transactions';

  return (
    <div className="space-y-6">
      <PageIntro
        eyebrow="Activity"
        title="Follow every movement of money."
        description="Search, verify, and explain transactions without losing their source context."
        action={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => scrollTo('review')}>
              <ListChecks className="h-4 w-4" aria-hidden="true" />
              {pendingTransactionCount > 0
                ? `Review ${pendingTransactionCount} transactions`
                : 'Open review queue'}
            </Button>
          </div>
        }
      />

      <WorkspaceContextBar label="Activity views">
        <Tabs
          ariaLabel="Activity views"
          value={view}
          onValueChange={(value) => scrollTo(value)}
          options={[
            { value: 'transactions', label: 'Transactions' },
            { value: 'review', label: 'Review' },
            { value: 'timeline', label: 'Timeline' },
          ]}
          className="w-full max-w-full sm:w-auto sm:max-w-max"
        />
      </WorkspaceContextBar>

      {cashAccount ? (
        <Card>
          <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
            <div className="flex min-w-0 items-start gap-3">
              <span className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Wallet className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <p className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
                  Cash in hand
                </p>
                <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.03em] tabular-nums">
                  {cashPocket.isLoading
                    ? 'Loading…'
                    : formatCurrency(cashPocket.data?.balance, cashPocket.data?.currency ?? user?.currency)}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  ATM withdrawals are transfers into this pocket, not spend. Manual cash purchases
                  linked to the cash account are counted as spend.
                </p>
              </div>
            </div>
            <dl className="grid min-w-[14rem] grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs font-semibold text-muted-foreground">Transfers in</dt>
                <dd className="font-bold tabular-nums">
                  {formatCurrency(
                    cashPocket.data?.transfers_in,
                    cashPocket.data?.currency ?? user?.currency,
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold text-muted-foreground">Cash spend</dt>
                <dd className="font-bold tabular-nums">
                  {formatCurrency(
                    cashPocket.data?.cash_spend,
                    cashPocket.data?.currency ?? user?.currency,
                  )}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs font-semibold text-muted-foreground">As of</dt>
                <dd>{formatDate(cashPocket.data?.as_of)}</dd>
              </div>
            </dl>
          </CardContent>
        </Card>
      ) : null}

      <div id={view} className="animate-fade-in scroll-mt-[10.5rem] lg:scroll-mt-[11.5rem]">
        <Suspense
          fallback={
            <div
              role="status"
              aria-label={`Loading ${view}`}
              className="h-72 animate-soft-pulse rounded-xl bg-muted"
            />
          }
        >
          {view === 'transactions' ? <TransactionsSection embedded /> : null}
          {view === 'review' ? <ReviewSection embedded /> : null}
          {view === 'timeline' ? <TimelineSection embedded /> : null}
        </Suspense>
      </div>
    </div>
  );
}
