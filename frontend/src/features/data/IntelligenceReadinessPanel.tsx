import {
  CheckCircle2,
  CircleAlert,
  Clock3,
  LockKeyhole,
  ShieldCheck,
} from 'lucide-react';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthContext';
import { useIntelligenceReadiness } from '@/features/workspace/queries';
import type { IntelligenceReadinessGate, IntelligenceReadinessStatus } from '@/lib/types';

const statusCopy: Record<IntelligenceReadinessStatus, string> = {
  ready: 'Ready',
  collecting: 'Collecting evidence',
  blocked: 'Needs repair',
  deferred: 'Release evidence',
};

const statusVariant: Record<IntelligenceReadinessStatus, 'success' | 'warning' | 'danger' | 'info'> =
  {
    ready: 'success',
    collecting: 'warning',
    blocked: 'danger',
    deferred: 'info',
  };

export function IntelligenceReadinessPanel() {
  const { user } = useAuth();
  const { scrollTo } = useDashboardUi();
  const readiness = useIntelligenceReadiness();

  if (!user) return null;

  return (
    <Card className="border border-border/70 shadow-sm" aria-labelledby="intelligence-readiness-title">
      <CardContent className="grid gap-5 p-5 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-3xl">
            <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-intelligence">
              Product evidence
            </p>
            <h2 id="intelligence-readiness-title" className="mt-2 text-xl font-extrabold">
              Intelligence readiness, in plain sight
            </h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              This view separates what is working for your workspace from the representative proof
              PFIS still needs before a rule can be promoted broadly.
            </p>
          </div>
          {readiness.data ? (
            <div className="flex shrink-0 items-center gap-2">
              <Badge variant={statusVariant[readiness.data.overall_status]}>
                <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />
                {statusCopy[readiness.data.overall_status]}
              </Badge>
              <span className="text-sm font-extrabold tabular-nums">
                {readiness.data.evidence_readiness_score}/100
              </span>
            </div>
          ) : null}
        </div>

        {readiness.isLoading ? (
          <Skeleton className="h-44" />
        ) : readiness.isError || !readiness.data ? (
          <p className="rounded-xl border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
            Readiness evidence is temporarily unavailable. Your financial calculations are
            unchanged.
          </p>
        ) : (
          <>
            <div className="grid gap-3 md:grid-cols-2">
              {readiness.data.gates.map((gate) => (
                <ReadinessGate key={gate.key} gate={gate} onNavigate={scrollTo} />
              ))}
            </div>
            <div className="grid gap-3 rounded-xl border border-border/70 bg-muted/20 p-4 text-sm sm:grid-cols-2 lg:grid-cols-5">
              <Metric
                label="Observed source coverage"
                value={`${readiness.data.source_coverage_score}/100`}
              />
              <Metric
                label="Temporal source history"
                value={`${readiness.data.temporal_history.transaction_coverage_pct.toFixed(0)}% tx · ${readiness.data.temporal_history.statement_line_coverage_pct.toFixed(0)}% issuer`}
              />
              <Metric
                label="Card intent history"
                value={`${readiness.data.temporal_history.card_payment_intent_coverage_pct.toFixed(0)}% covered`}
              />
              <Metric
                label="Forecast horizons"
                value={`${readiness.data.forecast.eligible_horizons} eligible`}
              />
              <Metric
                label="Cross-source reconciliation"
                value={`${readiness.data.reconciliation.evidence_score}/100`}
              />
            </div>
            <details className="text-sm">
              <summary className="focus-ring cursor-pointer rounded py-2 font-bold">
                Read the boundaries
              </summary>
              <ul className="mt-2 list-disc space-y-1.5 pl-5 leading-6 text-muted-foreground">
                {readiness.data.assumptions.map((assumption) => (
                  <li key={assumption}>{assumption}</li>
                ))}
              </ul>
            </details>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function ReadinessGate({
  gate,
  onNavigate,
}: {
  gate: IntelligenceReadinessGate;
  onNavigate: (target: string) => void;
}) {
  const Icon =
    gate.status === 'ready'
      ? CheckCircle2
      : gate.status === 'blocked'
        ? CircleAlert
        : gate.status === 'deferred'
          ? LockKeyhole
          : Clock3;
  return (
    <article className="rounded-xl border border-border/70 bg-card p-4">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 rounded-lg bg-muted p-2 text-muted-foreground">
          <Icon aria-hidden="true" className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3 className="font-extrabold">{gate.label}</h3>
            <Badge variant={statusVariant[gate.status]}>{statusCopy[gate.status]}</Badge>
          </div>
          <p className="mt-2 text-sm leading-5 text-muted-foreground">{gate.summary}</p>
          <details className="mt-3 text-xs">
            <summary className="focus-ring cursor-pointer rounded py-1 font-bold text-foreground">
              Evidence and next step
            </summary>
            <ul className="mt-2 space-y-1.5 leading-5 text-muted-foreground">
              {gate.evidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
              <li className="font-semibold text-foreground">{gate.next_step}</li>
            </ul>
          </details>
          {gate.target &&
          ['inbox', 'pipeline', 'analytics', 'guidance', 'settings', 'review', 'insights'].includes(gate.target) ? (
            <Button
              variant="ghost"
              className="mt-3 h-auto px-0 py-1 text-xs"
              onClick={() => onNavigate(gate.target!)}
            >
              Open {gate.target}
            </Button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-extrabold tabular-nums">{value}</p>
    </div>
  );
}
