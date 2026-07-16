import { useMemo } from 'react';
import { ArrowDownLeft, ArrowUpRight, CalendarClock, Repeat2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { WorkspaceEmptyState } from '@/components/cards/WorkspaceEmptyState';
import { useWorkspaceSnapshot } from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency } from '@/lib/format';
import type { TimelineEvent } from '@/lib/types';
import { cn } from '@/lib/utils';

/** Financial Timeline — income, bills, subscriptions, shopping, refunds. */
export function TimelineSection({ embedded = false }: { embedded?: boolean }) {
  const { user } = useAuth();
  const workspace = useWorkspaceSnapshot();
  const currency = user?.currency ?? 'INR';

  const events = useMemo(() => workspace.data?.timeline ?? [], [workspace.data]);
  const snapshot = workspace.data?.snapshot;

  const grouped = useMemo(() => groupByDate(events), [events]);

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Timeline"
          title="Financial timeline"
          description="Your money movement this month — income, bills, subscriptions, and spending."
          action={
            snapshot ? (
              <Badge variant={snapshot.net_cash_flow >= 0 ? 'success' : 'danger'}>
                Net {formatCurrency(snapshot.net_cash_flow, currency)}
              </Badge>
            ) : undefined
          }
        />
      ) : null}

      <Card>
        <CardContent className="p-4 sm:p-5">
          {embedded && snapshot ? (
            <div className="mb-6 flex flex-col justify-between gap-3 border-b border-border/70 pb-5 sm:flex-row sm:items-end">
              <div>
                <p className="text-xs font-bold text-muted-foreground">Activity stream</p>
                <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
                  The month in sequence
                </h2>
              </div>
              <Badge variant={snapshot.net_cash_flow >= 0 ? 'success' : 'danger'}>
                Net {formatCurrency(snapshot.net_cash_flow, currency)}
              </Badge>
            </div>
          ) : null}
          {workspace.isLoading ? (
            <div className="grid gap-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-14" />
              ))}
            </div>
          ) : events.length === 0 ? (
            <WorkspaceEmptyState
              icon={<CalendarClock />}
              title="No activity this month"
              description="Once transactions arrive, your financial timeline appears here."
            />
          ) : (
            <div className="grid gap-7">
              {grouped.map(([date, items]) => (
                <section key={date} className="grid gap-3 sm:grid-cols-[7rem_minmax(0,1fr)]">
                  <p className="pt-1 text-xs font-bold text-muted-foreground">{formatDate(date)}</p>
                  <ol className="relative border-l border-border/80 pl-5">
                    {items.map((event, i) => (
                      <TimelineEventRow key={`${date}-${i}`} event={event} currency={currency} />
                    ))}
                  </ol>
                </section>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function TimelineEventRow({ event, currency }: { event: TimelineEvent; currency: string }) {
  const incoming = event.direction === 'in';
  const Icon = event.type === 'subscription' ? Repeat2 : incoming ? ArrowDownLeft : ArrowUpRight;
  return (
    <li className="relative flex min-w-0 items-center gap-3 border-b border-border/60 py-3 first:pt-0 last:border-b-0 last:pb-0">
      <span
        className={cn(
          'absolute -left-[1.72rem] grid h-5 w-5 place-items-center rounded-full ring-4 ring-card',
          incoming ? 'bg-success text-success-foreground' : 'bg-secondary text-muted-foreground',
        )}
      >
        <Icon className="h-3 w-3" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-extrabold">
          {event.merchant || event.label}
        </span>
        <span className="mt-0.5 block truncate text-xs text-muted-foreground">
          {[event.category, event.payment_method?.replace('_', ' '), event.transaction_status]
            .filter(Boolean)
            .join(' · ')}
        </span>
      </span>
      <span
        className={cn(
          'money-value shrink-0 text-sm',
          incoming ? 'text-success' : 'text-foreground',
        )}
      >
        {incoming ? '+' : '−'}
        {formatCurrency(Math.abs(event.amount), currency)}
      </span>
    </li>
  );
}

function formatDate(value: string) {
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

function groupByDate(events: TimelineEvent[]): [string, TimelineEvent[]][] {
  const map = new Map<string, TimelineEvent[]>();
  for (const event of events) {
    const list = map.get(event.date) ?? [];
    list.push(event);
    map.set(event.date, list);
  }
  return [...map.entries()];
}
