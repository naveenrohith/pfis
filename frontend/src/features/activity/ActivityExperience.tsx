import { lazy, Suspense } from 'react';
import { ListChecks, Plus } from 'lucide-react';
import { PageIntro } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Tabs } from '@/components/ui/Tabs';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useTransactions } from '@/features/workspace/queries';

const ReviewSection = lazy(() =>
  import('@/features/review/ReviewSection').then((module) => ({ default: module.ReviewSection })),
);
const TimelineSection = lazy(() =>
  import('@/features/timeline/TimelineSection').then((module) => ({
    default: module.TimelineSection,
  })),
);
const TransactionsSection = lazy(() =>
  import('@/features/transactions/TransactionsSection').then((module) => ({
    default: module.TransactionsSection,
  })),
);

type ActivityView = 'transactions' | 'review' | 'timeline';

export function ActivityExperience() {
  const transactions = useTransactions();
  const { activeSection, scrollTo, setQuickAddOpen } = useDashboardUi();
  const pendingCount = (transactions.data ?? []).filter(
    (transaction) => !transaction.reviewed_flag,
  ).length;
  const view: ActivityView =
    activeSection === 'review' || activeSection === 'timeline' ? activeSection : 'transactions';

  return (
    <div className="space-y-8">
      <PageIntro
        eyebrow="Activity"
        title="Follow every movement of money."
        description="Search, verify, and explain transactions without losing their source context."
        action={
          <div className="flex flex-wrap gap-2">
            {pendingCount > 0 ? (
              <Button variant="outline" onClick={() => scrollTo('review')}>
                <ListChecks className="h-4 w-4" /> Review {pendingCount}
              </Button>
            ) : (
              <Badge variant="success">Queue clear</Badge>
            )}
            <Button onClick={() => setQuickAddOpen(true)}>
              <Plus className="h-4 w-4" /> Add activity
            </Button>
          </div>
        }
      />

      <Tabs
        ariaLabel="Activity views"
        value={view}
        onValueChange={(value) => scrollTo(value)}
        options={[
          { value: 'transactions', label: 'Transactions' },
          { value: 'review', label: pendingCount ? `Review · ${pendingCount}` : 'Review' },
          { value: 'timeline', label: 'Timeline' },
        ]}
        className="max-w-max"
      />

      <div id={view} className="animate-fade-in scroll-mt-28">
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
