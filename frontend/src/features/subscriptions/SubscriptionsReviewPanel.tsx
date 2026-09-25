import { CalendarClock, CheckCircle2, CircleSlash2, Repeat2, XCircle } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { useToast } from '@/components/ui/Toast';
import { formatCurrency, formatDate } from '@/lib/format';
import type {
  SubscriptionReviewAction,
  SubscriptionReviewItem,
  SubscriptionReviewLifecycle,
} from '@/lib/types';
import { useRecordSubscriptionReviewAction, useSubscriptionReview } from './queries';

const lifecycleCopy: Record<
  SubscriptionReviewLifecycle,
  { label: string; meaning: string; variant: 'info' | 'success' | 'warning' | 'outline' }
> = {
  candidate: {
    label: 'Candidate',
    meaning: 'PFIS has a signal, but needs stronger rhythm evidence before planning around it.',
    variant: 'info',
  },
  mature: {
    label: 'Mature',
    meaning: 'The stream repeats with enough evidence to expect the next charge.',
    variant: 'success',
  },
  missed: {
    label: 'Possibly missed',
    meaning: 'The usual window has passed, so confirm whether the stream still exists.',
    variant: 'warning',
  },
  inactive: {
    label: 'Inactive',
    meaning: 'Several expected cycles appear absent; review before treating it as ongoing.',
    variant: 'outline',
  },
};

const withheldReasonCopy: Record<string, string> = {
  cadence_not_regular: 'PFIS has not found a regular cadence yet.',
  insufficient_occurrences: 'PFIS needs at least three observations before dating the next charge.',
  cadence_confidence_below_mature_threshold: 'The cadence is not reliable enough to show a date.',
  payment_past_expected_grace: 'The expected window has already passed.',
  stream_inactive_after_multiple_missed_cycles: 'The stream appears inactive after missed cycles.',
};

const actions: Array<{
  action: SubscriptionReviewAction;
  label: string;
  icon: typeof CheckCircle2;
  variant: 'primary' | 'outline' | 'secondary';
}> = [
  { action: 'confirm', label: 'Confirm', icon: CheckCircle2, variant: 'primary' },
  { action: 'mark_not_recurring', label: 'Not recurring', icon: CircleSlash2, variant: 'outline' },
  { action: 'cancelled', label: 'Cancelled', icon: XCircle, variant: 'secondary' },
];

export function SubscriptionsReviewPanel() {
  const review = useSubscriptionReview();
  const recordAction = useRecordSubscriptionReviewAction();
  const { notify } = useToast();

  const items = review.data?.items ?? [];

  function act(item: SubscriptionReviewItem, action: SubscriptionReviewAction) {
    recordAction.mutate(
      { streamKey: item.stream_key, action },
      {
        onSuccess: () => notify(`${item.merchant} review saved.`, 'success'),
        onError: (error) =>
          notify(
            error instanceof Error
              ? error.message
              : 'The subscription review decision could not be saved.',
            'error',
          ),
      },
    );
  }

  return (
    <section
      aria-labelledby="subscriptions-review-title"
      className="mb-5 rounded-3xl border border-warning/20 bg-warning/5 p-4 sm:p-5"
    >
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div className="max-w-2xl">
          <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-warning">
            Commitment review
          </p>
          <h3
            id="subscriptions-review-title"
            className="mt-1 text-xl font-extrabold tracking-[-0.035em]"
          >
            Subscriptions review
          </h3>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Confirm the recurring streams PFIS has detected before they influence your planning
            rhythm. Dates are withheld when cadence evidence is not strong enough.
          </p>
        </div>
        {review.data ? (
          <Badge variant={items.length > 0 ? 'warning' : 'success'}>
            {items.length > 0 ? `${items.length} stream${items.length === 1 ? '' : 's'}` : 'Clear'}
          </Badge>
        ) : null}
      </div>

      {review.isLoading ? (
        <Skeleton className="mt-5 h-52" role="status" aria-label="Loading subscriptions review" />
      ) : null}

      {review.isError ? (
        <div className="mt-5 rounded-2xl border border-danger/25 bg-danger/5 p-4" role="alert">
          <p className="font-extrabold">Subscription review could not load</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Your transaction review queue remains available. Retry when the recurring-pattern read
            model responds.
          </p>
          <Button className="mt-3" variant="outline" onClick={() => void review.refetch()}>
            Retry review
          </Button>
        </div>
      ) : null}

      {!review.isLoading && !review.isError && items.length === 0 ? (
        <EmptyState
          className="mt-5 bg-card/65"
          icon={<Repeat2 aria-hidden="true" />}
          title="No subscriptions need review"
          description={
            review.data?.excluded_count
              ? `${review.data.excluded_count} stream${review.data.excluded_count === 1 ? '' : 's'} already dismissed or cancelled.`
              : 'PFIS will surface recurring merchants here when evidence is strong enough to review.'
          }
        />
      ) : null}

      {items.length > 0 ? (
        <div className="mt-5 grid gap-3">
          {items.map((item) => (
            <SubscriptionReviewRow
              key={item.stream_key}
              item={item}
              onAction={act}
              pending={recordAction.isPending}
            />
          ))}
        </div>
      ) : null}

      {recordAction.isError ? (
        <p className="mt-3 text-sm font-bold text-danger" role="status">
          The last decision was not saved. No optimistic change was applied.
        </p>
      ) : null}
    </section>
  );
}

function SubscriptionReviewRow({
  item,
  onAction,
  pending,
}: {
  item: SubscriptionReviewItem;
  onAction: (item: SubscriptionReviewItem, action: SubscriptionReviewAction) => void;
  pending: boolean;
}) {
  const lifecycle = lifecycleCopy[item.lifecycle_status];
  const nextExpected = item.next_expected
    ? formatDate(item.next_expected)
    : reasonLabel(item.next_expected_null_reason);

  return (
    <article className="rounded-2xl border border-border/70 bg-card/80 p-4 shadow-sm">
      <div className="grid min-w-0 gap-4 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1.4fr)_auto] md:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="min-w-0 truncate text-base font-extrabold">{item.merchant}</h4>
            <Badge variant={lifecycle.variant}>{lifecycle.label}</Badge>
            {item.user_action === 'confirm' ? <Badge variant="success">Confirmed</Badge> : null}
          </div>
          <p className="mt-2 text-sm leading-5 text-muted-foreground">{lifecycle.meaning}</p>
        </div>

        <dl className="grid grid-cols-2 gap-3 text-sm min-[360px]:grid-cols-2 sm:grid-cols-3">
          <Fact label="Cadence" value={item.cadence ?? 'Irregular'} />
          <Fact
            label="Typical amount"
            value={formatCurrency(item.typical_amount, item.currency)}
            emphasis
          />
          <Fact label="Amount change" value={item.amount_change_detected ? 'Changed' : 'Stable'} />
          <Fact label="Last seen" value={formatDate(item.last_seen)} />
          <Fact label="Next expected" value={nextExpected} />
          <Fact label="Evidence" value={`${item.evidence_transaction_ids.length} entries`} />
        </dl>

        <div
          className="flex flex-col gap-2 min-[360px]:flex-row min-[360px]:flex-wrap md:min-w-40 md:justify-end"
          role="group"
          aria-label={`Review ${item.merchant} subscription stream`}
        >
          {actions.map(({ action, label, icon: Icon, variant }) => (
            <Button
              key={action}
              size="sm"
              variant={item.user_action === action ? 'secondary' : variant}
              disabled={pending}
              aria-pressed={item.user_action === action}
              onClick={() => onAction(item, action)}
              className="min-[360px]:flex-1 md:flex-none"
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {label}
            </Button>
          ))}
        </div>
      </div>

      <p className="mt-3 flex items-start gap-2 border-t border-border/60 pt-3 text-xs leading-5 text-muted-foreground">
        <CalendarClock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>
          Expected dates are shown only for mature streams. Ruleset {item.ruleset_version}; list
          excludes streams you marked not recurring or cancelled.
        </span>
      </p>
    </article>
  );
}

function Fact({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-bold text-muted-foreground">{label}</dt>
      <dd
        className={
          emphasis
            ? 'money-value mt-1 truncate font-extrabold tabular-nums'
            : 'mt-1 truncate font-bold'
        }
      >
        {value}
      </dd>
    </div>
  );
}

function reasonLabel(reason?: string | null): string {
  if (!reason) return 'Date withheld';
  return withheldReasonCopy[reason] ?? reason.replaceAll('_', ' ');
}
