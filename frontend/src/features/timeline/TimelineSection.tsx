import { useMemo } from 'react';
import { CalendarClock } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { TimelineCard } from '@/components/cards/TimelineCard';
import { WorkspaceEmptyState } from '@/components/cards/WorkspaceEmptyState';
import { useWorkspaceSnapshot } from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency } from '@/lib/format';
import type { TimelineEvent } from '@/lib/types';

/** Financial Timeline — income, bills, subscriptions, shopping, refunds. */
export function TimelineSection() {
  const { user } = useAuth();
  const workspace = useWorkspaceSnapshot();
  const currency = user?.currency ?? 'INR';

  const events = useMemo(() => workspace.data?.timeline ?? [], [workspace.data]);
  const snapshot = workspace.data?.snapshot;

  const grouped = useMemo(() => groupByDate(events), [events]);

  return (
    <div>
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

      <Card>
        <CardContent className="p-4 sm:p-5">
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
            <div className="grid gap-4">
              {grouped.map(([date, items]) => (
                <div key={date}>
                  <p className="mb-1.5 text-xs font-bold uppercase tracking-wide text-muted-foreground">
                    {date}
                  </p>
                  <div className="grid gap-1.5">
                    {items.map((event, i) => (
                      <TimelineCard key={`${date}-${i}`} event={event} currency={currency} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
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
