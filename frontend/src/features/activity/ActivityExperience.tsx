import { Suspense } from 'react';
import { ListChecks } from 'lucide-react';
import { PageIntro, WorkspaceContextBar } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Tabs } from '@/components/ui/Tabs';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useTransactions } from '@/features/workspace/queries';
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
  const transactions = useTransactions();
  const { activeSection, scrollTo } = useDashboardUi();
  const pendingCount = (transactions.data ?? []).filter(
    (transaction) => !transaction.reviewed_flag,
  ).length;
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
            {pendingCount > 0 ? (
              <Button variant="outline" onClick={() => scrollTo('review')}>
                <ListChecks className="h-4 w-4" /> Review {pendingCount}
              </Button>
            ) : (
              <Badge variant="success">Queue clear</Badge>
            )}
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
            { value: 'review', label: pendingCount ? `Review (${pendingCount})` : 'Review' },
            { value: 'timeline', label: 'Timeline' },
          ]}
          className="w-full max-w-full sm:w-auto sm:max-w-max"
        />
      </WorkspaceContextBar>

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
