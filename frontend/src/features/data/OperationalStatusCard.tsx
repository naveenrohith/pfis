import { CheckCircle2, CircleAlert, TriangleAlert, Wrench } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { useOperationalHealth } from '@/features/workspace/queries';
import type { OperationalHealthStatus } from '@/lib/types';

type RecoveryTarget = 'inbox' | 'pipeline' | 'statements' | 'settings';

interface OperationalIssue {
  code: string;
  copy: string;
  target: RecoveryTarget;
  targetLabel: string;
}

const statusCopy: Record<OperationalHealthStatus, string> = {
  healthy: 'All systems steady',
  degraded: 'Needs attention',
  needs_repair: 'Repair required',
};

const statusVariant: Record<OperationalHealthStatus, 'success' | 'warning' | 'danger'> = {
  healthy: 'success',
  degraded: 'warning',
  needs_repair: 'danger',
};

const statusIcon: Record<OperationalHealthStatus, typeof CheckCircle2> = {
  healthy: CheckCircle2,
  degraded: TriangleAlert,
  needs_repair: Wrench,
};

const statusClassName: Record<OperationalHealthStatus, string> = {
  healthy: 'border-success/25 bg-success/[0.035]',
  degraded: 'border-warning/35 bg-warning/[0.035]',
  needs_repair: 'border-danger/35 bg-danger/[0.035]',
};

const serviceIssues: Record<string, Omit<OperationalIssue, 'code'>> = {
  ledger_currency_needs_repair: {
    copy: 'A ledger integrity check needs repair before balances can be trusted.',
    target: 'settings',
    targetLabel: 'Open preferences',
  },
  unresolved_parse_failures: {
    copy: 'Some imported records still need parser recovery.',
    target: 'pipeline',
    targetLabel: 'Open diagnostics',
  },
  parser_source_drift: {
    copy: 'A parser source is behaving differently from its recent baseline.',
    target: 'pipeline',
    targetLabel: 'Open diagnostics',
  },
  statement_layout_drift: {
    copy: 'Statement layout rejection is above the monitoring threshold.',
    target: 'statements',
    targetLabel: 'Review statements',
  },
  failed_background_jobs: {
    copy: 'A background job needs attention.',
    target: 'pipeline',
    targetLabel: 'Open diagnostics',
  },
};

const dataWarnings: Record<string, Omit<OperationalIssue, 'code'>> = {
  provider_query_coverage_is_partial: {
    copy: 'The latest provider query may not cover the full inbox.',
    target: 'inbox',
    targetLabel: 'Review connections',
  },
  latest_provider_query_was_capped: {
    copy: 'The latest provider query hit its configured cap.',
    target: 'inbox',
    targetLabel: 'Review connections',
  },
  historical_sync_runs_failed: {
    copy: 'A previous sync failed; review the latest completed run.',
    target: 'inbox',
    targetLabel: 'Review connections',
  },
};

export function OperationalStatusCard({ onNavigate }: { onNavigate: (target: string) => void }) {
  const health = useOperationalHealth();

  if (health.isLoading || health.isError || !health.data) return null;

  const { data } = health;
  const issues = toIssues(data.status_reasons, serviceIssues);
  const warnings = toIssues(data.data_warnings, dataWarnings);
  if (data.status === 'healthy' && warnings.length === 0) return null;

  const Icon = statusIcon[data.status];
  return (
    <Card
      className={statusClassName[data.status]}
      aria-labelledby="operational-status-title"
      role="status"
      aria-live="polite"
    >
      <CardContent className="grid gap-4 p-4 sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 rounded-lg bg-card/80 p-2 text-foreground shadow-sm">
              <Icon aria-hidden="true" className="h-4 w-4" />
            </span>
            <div>
              <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-muted-foreground">
                Operational status
              </p>
              <h2 id="operational-status-title" className="mt-1 text-lg font-extrabold">
                {data.status === 'healthy'
                  ? 'Your data is available, with a coverage note.'
                  : 'A few checks need your attention.'}
              </h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                Service health and data completeness are shown separately so a warning never looks
                like a silent failure.
              </p>
            </div>
          </div>
          <Badge variant={statusVariant[data.status]}>
            <Icon aria-hidden="true" className="h-3.5 w-3.5" />
            {statusCopy[data.status]}
          </Badge>
        </div>

        {issues.length > 0 ? (
          <IssueGroup
            title="Service checks"
            icon={<CircleAlert aria-hidden="true" className="h-4 w-4 text-danger" />}
            issues={issues}
            onNavigate={onNavigate}
          />
        ) : null}
        {warnings.length > 0 ? (
          <IssueGroup
            title="Data completeness"
            icon={<TriangleAlert aria-hidden="true" className="h-4 w-4 text-warning" />}
            issues={warnings}
            onNavigate={onNavigate}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

function IssueGroup({
  title,
  icon,
  issues,
  onNavigate,
}: {
  title: string;
  icon: React.ReactNode;
  issues: OperationalIssue[];
  onNavigate: (target: string) => void;
}) {
  return (
    <section
      className="rounded-xl border border-border/70 bg-card/70 p-3 sm:p-4"
      aria-label={title}
    >
      <div className="flex items-center gap-2 text-sm font-extrabold">
        {icon}
        {title}
      </div>
      <ul className="mt-3 grid gap-2">
        {issues.map((issue) => (
          <li
            key={issue.code}
            className="flex flex-col gap-2 border-t border-border/60 pt-2 first:border-t-0 first:pt-0 sm:flex-row sm:items-center sm:justify-between"
          >
            <p className="text-sm leading-5 text-muted-foreground">{issue.copy}</p>
            <Button
              variant="ghost"
              size="sm"
              className="h-auto shrink-0 justify-start px-0 py-1 text-xs sm:justify-center"
              onClick={() => onNavigate(issue.target)}
            >
              {issue.targetLabel}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function toIssues(
  codes: string[],
  copy: Record<string, Omit<OperationalIssue, 'code'>>,
): OperationalIssue[] {
  return codes.map((code) => ({ code, ...(copy[code] ?? fallbackIssue(code)) }));
}

function fallbackIssue(_code: string): Omit<OperationalIssue, 'code'> {
  return {
    copy: 'An operational check needs review.',
    target: 'pipeline',
    targetLabel: 'Open diagnostics',
  };
}
