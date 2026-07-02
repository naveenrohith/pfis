import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Gauge, RefreshCcw, RotateCcw, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import {
  queryKeys,
  usePipelineFailures,
  usePipelineMetrics,
} from '@/features/workspace/queries';
import { api } from '@/lib/api';
import type { PipelineFailure, PipelineMetrics } from '@/lib/types';

export function PipelineHealthSection() {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const metrics = usePipelineMetrics();
  const failures = usePipelineFailures(false);
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const userId = user?.id ?? '';

  const invalidatePipeline = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.pipelineMetrics(userId, month, year) });
    queryClient.invalidateQueries({ queryKey: queryKeys.pipelineFailures(userId, false) });
    queryClient.invalidateQueries({ queryKey: queryKeys.transactions(userId, month, year) });
    queryClient.invalidateQueries({ queryKey: queryKeys.workspace(userId, month, year) });
  };

  const retry = useMutation({
    mutationFn: (failureId: string) => api.retryPipelineFailure(userId, failureId),
    onSuccess: () => {
      notify('DLQ item retried', 'success');
      invalidatePipeline();
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });

  const replay = useMutation({
    mutationFn: () => api.reprocessPipeline(userId, { dry_run: true, limit: 50 }),
    onSuccess: (result) => {
      notify(`Replay dry run compared ${result.email_count} email${result.email_count === 1 ? '' : 's'}`, 'success');
      invalidatePipeline();
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });

  return (
    <div>
      <SectionTitle
        eyebrow="Pipeline"
        title="Parser health"
        description="Operational view of parser quality, failure queue, duplicate detection, and replay readiness."
        action={
          <Button
            variant="secondary"
            onClick={() => replay.mutate()}
            disabled={!userId || replay.isPending}
          >
            <RotateCcw className="h-4 w-4" /> Dry-run replay
          </Button>
        }
      />

      {metrics.isLoading ? (
        <Skeleton className="h-44" />
      ) : metrics.data ? (
        <MetricsGrid metrics={metrics.data} />
      ) : (
        <EmptyState
          icon={<Gauge />}
          title="Pipeline metrics unavailable"
          description="Run sync or process inbox emails to populate parser health metrics."
        />
      )}

      <Card className="mt-4">
        <CardContent className="grid gap-4 p-4 sm:p-5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="flex items-center gap-2 font-bold">
                <AlertTriangle className="h-4 w-4 text-warning" /> Dead-letter queue
              </h3>
              <p className="text-sm text-muted-foreground">
                Failed parser items with retry metadata and non-secret diagnostics.
              </p>
            </div>
            {failures.data && <Badge variant={failures.data.total > 0 ? 'warning' : 'success'}>{failures.data.total} open</Badge>}
          </div>

          {failures.isLoading ? (
            <Skeleton className="h-32" />
          ) : failures.data && failures.data.failures.length > 0 ? (
            <div className="grid gap-2">
              {failures.data.failures.map((failure) => (
                <FailureRow
                  key={failure.id}
                  failure={failure}
                  retrying={retry.isPending}
                  onRetry={() => retry.mutate(failure.id)}
                />
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<ShieldCheck />}
              title="No parser failures"
              description="The active DLQ is empty for this workspace."
              className="py-8"
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MetricsGrid({ metrics }: { metrics: PipelineMetrics }) {
  const items = [
    { label: 'Success', value: `${metrics.parse_success_rate}%`, tone: metrics.parse_success_rate >= 90 ? 'success' : 'warning' },
    { label: 'Avg confidence', value: `${Math.round(metrics.average_confidence * 100)}%`, tone: metrics.average_confidence >= 0.85 ? 'success' : 'warning' },
    { label: 'Fallback', value: `${metrics.fallback_rate}%`, tone: metrics.fallback_rate <= 20 ? 'info' : 'warning' },
    { label: 'Unknown merchant', value: `${metrics.unknown_merchant_rate}%`, tone: metrics.unknown_merchant_rate <= 25 ? 'info' : 'warning' },
    { label: 'Duplicate', value: `${metrics.duplicate_rate}%`, tone: 'info' },
    { label: 'DLQ size', value: String(metrics.dlq_size), tone: metrics.dlq_size === 0 ? 'success' : 'danger' },
    { label: 'Retries', value: String(metrics.retry_count), tone: 'info' },
    { label: 'Parse time', value: `${metrics.average_parse_time_ms} ms`, tone: 'info' },
  ] as const;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {items.map((item) => (
        <Card key={item.label}>
          <CardContent className="p-4">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm text-muted-foreground">{item.label}</p>
              <Badge variant={item.tone}>{item.tone}</Badge>
            </div>
            <p className="mt-3 text-2xl font-extrabold">{item.value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function FailureRow({
  failure,
  retrying,
  onRetry,
}: {
  failure: PipelineFailure;
  retrying: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="grid gap-3 rounded-lg border border-border bg-muted/25 p-3 md:grid-cols-[1fr_auto] md:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate font-semibold">{failure.subject || 'Untitled email'}</p>
          <Badge variant="warning">{failure.failure_code || 'parse_failed'}</Badge>
          {failure.parser_name && <Badge variant="outline">{failure.parser_name}</Badge>}
        </div>
        <p className="mt-1 truncate text-sm text-muted-foreground">
          {failure.sender || 'Unknown sender'} · {failure.error_message || 'No message'}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Stage {failure.failure_stage || 'parse'} · retries {failure.retry_count}
          {failure.transaction_id ? ` · transaction ${failure.transaction_id.slice(0, 8)}` : ''}
        </p>
      </div>
      <Button variant="secondary" size="sm" onClick={onRetry} disabled={retrying}>
        <RefreshCcw className="h-4 w-4" /> Retry
      </Button>
    </div>
  );
}
