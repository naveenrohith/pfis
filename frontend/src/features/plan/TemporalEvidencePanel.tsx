import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarClock, CheckCircle2, CircleAlert, XCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { queryKeys } from '@/features/workspace/queries';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/format';
import type { TemporalFinancialEvent } from '@/lib/types';

const ACTIONABLE_STATES = new Set(['conflict', 'overdue', 'missed']);

export function TemporalEvidencePanel() {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const events = useQuery({
    queryKey: queryKeys.temporalEvents(user?.id ?? 'signed-out'),
    queryFn: () => api.temporalEvents(user!.id),
    enabled: Boolean(user),
  });
  const decide = useMutation({
    mutationFn: ({
      event,
      decision,
    }: {
      event: TemporalFinancialEvent;
      decision: 'observed' | 'cancelled';
    }) => {
      if (!user) throw new Error('Sign in to resolve financial evidence');
      return api.updateTemporalEventDecision(user.id, event.id, {
        decision,
        ...(decision === 'observed' ? { observed_date: event.expected_date } : {}),
        note: decision === 'observed' ? 'Confirmed from the temporal evidence review.' : undefined,
      });
    },
    onSuccess: async () => {
      if (user) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.temporalEvents(user.id) });
        await queryClient.invalidateQueries({
          queryKey: queryKeys.workspace(user.id, month, year),
        });
      }
      notify('Evidence decision saved', 'success');
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  if (!user) return null;
  if (events.isLoading) return <Skeleton className="h-56" />;
  if (events.isError || !events.data) {
    return (
      <Card>
        <CardContent className="p-5">
          <p className="text-sm text-muted-foreground">
            The dated evidence timeline is temporarily unavailable. No financial event was changed.
          </p>
        </CardContent>
      </Card>
    );
  }

  const actionable = events.data.events.filter((event) => ACTIONABLE_STATES.has(event.state));
  const visible = (actionable.length ? actionable : events.data.events).slice(0, 6);

  return (
    <Card className="mt-5" aria-labelledby="temporal-evidence-title">
      <CardContent className="grid gap-4 p-5 sm:p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="flex items-center gap-2 text-xs font-extrabold uppercase tracking-[0.14em] text-muted-foreground">
              <CalendarClock aria-hidden="true" className="h-4 w-4 text-primary" /> Dated evidence
            </p>
            <h2 id="temporal-evidence-title" className="mt-1 text-xl font-extrabold">
              Confirm what is expected before it becomes a surprise.
            </h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
              PFIS keeps expected, observed, missed, cancelled, and conflicting events separate. A
              similar amount is never silently linked to a ledger record.
            </p>
          </div>
          <Badge variant={actionable.length ? 'warning' : 'success'}>
            {actionable.length ? `${actionable.length} needs review` : 'No conflicts'}
          </Badge>
        </div>

        {visible.length ? (
          <div className="divide-y divide-border/70 rounded-xl border border-border/70">
            {visible.map((event) => (
              <TemporalEventRow
                key={event.id}
                event={event}
                busy={decide.isPending}
                onDecision={(decision) => decide.mutate({ event, decision })}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<CalendarClock className="h-5 w-5" />}
            title="No dated events yet"
            description="Confirmed income, obligations, reserves, and recurring evidence will appear here when the source facts are available."
          />
        )}

        <p className="text-xs leading-5 text-muted-foreground">
          Range: {formatDate(events.data.range_start)} to {formatDate(events.data.range_end)} ·
          Ruleset {events.data.ruleset_version}
        </p>
      </CardContent>
    </Card>
  );
}

function TemporalEventRow({
  event,
  busy,
  onDecision,
}: {
  event: TemporalFinancialEvent;
  busy: boolean;
  onDecision: (decision: 'observed' | 'cancelled') => void;
}) {
  const amount = event.amount.expected ?? event.amount.high ?? event.amount.low;
  const actionable = ACTIONABLE_STATES.has(event.state);
  return (
    <article className="grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {event.state === 'conflict' ? (
            <CircleAlert className="h-4 w-4 text-warning" aria-hidden="true" />
          ) : event.state === 'cancelled' ? (
            <XCircle className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          ) : (
            <CalendarClock className="h-4 w-4 text-primary" aria-hidden="true" />
          )}
          <h3 className="truncate font-bold">{event.label}</h3>
          <Badge variant={event.state === 'conflict' ? 'warning' : 'outline'}>{event.state}</Badge>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Expected {formatDate(event.expected_date)}
          {amount != null ? ` · ${formatCurrency(amount, event.currency)}` : ''}
          {event.cadence ? ` · ${event.cadence}` : ''}
        </p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {event.conflict_reason ?? event.assumptions[0] ?? 'Source evidence is retained.'} ·{' '}
          {Math.round(event.confidence * 100)}% confidence
        </p>
      </div>
      {actionable ? (
        <div className="flex flex-wrap gap-2 sm:justify-end">
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onDecision('observed')}
          >
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Confirm occurred
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDecision('cancelled')}>
            Mark cancelled
          </Button>
        </div>
      ) : null}
    </article>
  );
}
