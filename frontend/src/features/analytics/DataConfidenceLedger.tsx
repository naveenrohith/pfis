import { ArrowRight, CheckCircle2, CircleAlert } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import type { DataConfidenceDimension, SourceCoverage } from '@/lib/types';

const STATUS_COPY = {
  strong: { label: 'Strong', badge: 'success' as const },
  watch: { label: 'Watch', badge: 'warning' as const },
  limited: { label: 'Limited', badge: 'danger' as const },
};

const COVERAGE_STATUS_COPY = {
  current: { label: 'Current', badge: 'success' as const },
  partial: { label: 'Partial', badge: 'warning' as const },
  stale: { label: 'Stale', badge: 'warning' as const },
  error: { label: 'Needs attention', badge: 'danger' as const },
  disconnected: { label: 'Not connected', badge: 'outline' as const },
  unknown: { label: 'Unknown', badge: 'outline' as const },
};

export function DataConfidenceLedger({
  dimensions,
  sourceCoverage = [],
  sourceCoverageScore,
  onNavigate,
}: {
  dimensions: DataConfidenceDimension[];
  sourceCoverage?: SourceCoverage[];
  sourceCoverageScore?: number;
  onNavigate: (target: string) => void;
}) {
  if (dimensions.length === 0) {
    return (
      <p className="border-t border-border pt-4 text-sm text-muted-foreground">
        Confidence evidence is being prepared.
      </p>
    );
  }

  return (
    <section aria-labelledby="confidence-evidence-title" className="border-t border-border pt-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-xs font-bold text-muted-foreground">Confidence evidence</p>
          <h4 id="confidence-evidence-title" className="mt-1 text-pretty font-extrabold">
            What PFIS can verify
          </h4>
        </div>
        <p className="max-w-xs text-xs leading-5 text-muted-foreground">
          Scores describe observed records, not inbox completeness.
        </p>
      </div>

      <ul className="divide-y divide-border/70 border-y border-border/70">
        {dimensions.map((dimension) => {
          const status = STATUS_COPY[dimension.status];
          const remediationTarget = dimension.remediation_target;
          return (
            <li key={dimension.key} className="grid gap-3 py-4 sm:grid-cols-[1fr_auto]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  {dimension.status === 'strong' ? (
                    <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
                  ) : (
                    <CircleAlert
                      className={
                        dimension.status === 'limited'
                          ? 'h-4 w-4 text-danger'
                          : 'h-4 w-4 text-warning'
                      }
                      aria-hidden="true"
                    />
                  )}
                  <h5 className="font-bold">{dimension.label}</h5>
                  <Badge variant={status.badge}>{status.label}</Badge>
                </div>
                <p className="mt-1 text-sm leading-5 text-muted-foreground">{dimension.summary}</p>
                <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {dimension.evidence.map((item) => (
                    <div key={item.label} className="flex gap-1">
                      <dt>{item.label}:</dt>
                      <dd className="break-words font-bold text-foreground">{item.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>

              <div className="flex min-w-24 items-center justify-between gap-3 sm:flex-col sm:items-end">
                <span
                  className="text-xl font-extrabold tabular-nums"
                  aria-label={`${dimension.label} score ${dimension.score} out of 100`}
                >
                  {dimension.score}
                  <span className="text-xs font-medium text-muted-foreground">/100</span>
                </span>
                {dimension.remediation_label && remediationTarget ? (
                  <Button variant="link" size="sm" onClick={() => onNavigate(remediationTarget)}>
                    {dimension.remediation_label}
                    <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>

      {sourceCoverage.length ? (
        <section aria-labelledby="source-coverage-title" className="mt-5 border-t border-border pt-4">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
            <div>
              <p className="text-xs font-bold text-muted-foreground">Source register</p>
              <h4 id="source-coverage-title" className="mt-1 font-extrabold">
                What has actually arrived
              </h4>
            </div>
            <Badge variant="outline">Observed coverage {sourceCoverageScore ?? 0}/100</Badge>
          </div>
          <p className="mb-3 text-xs leading-5 text-muted-foreground">
            Coverage describes records PFIS has seen. It never claims a provider inbox or account
            universe is complete.
          </p>
          <ul className="divide-y divide-border/70 border-y border-border/70">
            {sourceCoverage.map((source) => {
              const status = COVERAGE_STATUS_COPY[source.status];
              const range =
                source.coverage_start && source.coverage_end
                  ? `${source.coverage_start.slice(0, 10)} → ${source.coverage_end.slice(0, 10)}`
                  : 'No dated range yet';
              return (
                <li key={source.key} className="grid gap-3 py-3 sm:grid-cols-[1fr_auto] sm:items-start">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h5 className="font-bold">{source.label}</h5>
                      <Badge variant={status.badge}>{status.label}</Badge>
                    </div>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      {source.observed_count} observed · {range} · {source.completeness} completeness
                    </p>
                    {source.limitations[0] ? (
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        {source.limitations[0]}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex items-center justify-between gap-3 sm:flex-col sm:items-end">
                    <span
                      className="text-lg font-extrabold tabular-nums"
                      aria-label={`${source.label} score ${source.score} out of 100`}
                    >
                      {source.score}
                      <span className="text-xs font-medium text-muted-foreground">/100</span>
                    </span>
                    {source.remediation_label && source.remediation_target ? (
                      <Button
                        variant="link"
                        size="sm"
                        onClick={() => onNavigate(source.remediation_target ?? '')}
                      >
                        {source.remediation_label}
                        <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                      </Button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
