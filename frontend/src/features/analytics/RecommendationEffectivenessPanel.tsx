import { useQuery } from '@tanstack/react-query';
import { BarChart3, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Card, CardContent } from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthContext';
import { api } from '@/lib/api';
import type { RecommendationEffectivenessCohort } from '@/lib/types';

function percent(value?: number | null) {
  return value == null ? 'Held back' : `${Math.round(value * 100)}%`;
}

function cohortLabel(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

function impactLabel(cohort: RecommendationEffectivenessCohort) {
  if (cohort.mean_automatic_impact == null) return 'Held back';
  const value = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(
    cohort.mean_automatic_impact,
  );
  if (cohort.metric_unit === 'percentage_points') return `${value} percentage points`;
  if (cohort.metric_unit === 'records') return `${value} records`;
  return cohort.metric_unit ? `${value} ${cohort.metric_unit}` : value;
}

export function RecommendationEffectivenessPanel() {
  const { user } = useAuth();
  const report = useQuery({
    queryKey: ['guidance', 'effectiveness', user?.id ?? 'signed-out'],
    queryFn: () => api.guidanceEffectiveness(user!.id),
    enabled: Boolean(user),
  });

  if (!user) return null;

  return (
    <Card className="mt-4" aria-labelledby="recommendation-effectiveness-title">
      <CardContent className="grid gap-4 p-4 sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3
              id="recommendation-effectiveness-title"
              className="flex items-center gap-2 font-bold"
            >
              <BarChart3 aria-hidden="true" className="h-4 w-4 text-intelligence" />
              Recommendation evidence
            </h3>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              User-reported outcomes and automatic financial measures stay separate. PFIS never
              reports a small cohort or treats association as proof that an action caused a result.
            </p>
          </div>
          <Badge variant="info">
            <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" /> Cohort protected
          </Badge>
        </div>

        {report.isLoading ? (
          <Skeleton className="h-28" />
        ) : report.isError || !report.data ? (
          <p className="rounded-xl border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
            Recommendation evidence is temporarily unavailable. Individual decisions remain
            unchanged.
          </p>
        ) : report.data.evidence_status === 'insufficient_sample' ? (
          <div className="rounded-xl border border-border bg-muted/30 p-4">
            <p className="font-bold">Evidence is still accumulating</p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              A recommendation type appears only after at least {report.data.minimum_sample_size}{' '}
              immutable outcomes from {report.data.minimum_unique_users} different users within the
              last {report.data.window_days} days. Smaller cohorts remain hidden.
            </p>
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {report.data.cohorts.map((cohort) => (
              <section
                key={`${cohort.recommendation_type}-${cohort.guidance_ruleset_version}-${cohort.outcome_ruleset_version}-${cohort.metric_key ?? 'reported'}`}
                className="rounded-xl border border-border bg-muted/20 p-4"
                aria-label={`${cohortLabel(cohort.recommendation_type)} recommendation evidence`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h4 className="font-bold">{cohortLabel(cohort.recommendation_type)}</h4>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {cohort.sample_size} outcomes across {cohort.unique_users} users
                    </p>
                  </div>
                  <Badge variant="outline">Last {report.data.window_days} days</Badge>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Metric label="Completed" value={percent(cohort.completed_rate)} />
                  <Metric label="Reported helped" value={percent(cohort.helped_rate)} />
                  <Metric
                    label="Measured better"
                    value={percent(cohort.measured_improvement_rate)}
                  />
                  <Metric label="Average change" value={impactLabel(cohort)} />
                </dl>
                {cohort.measured_evidence_status === 'insufficient_sample' ? (
                  <p className="mt-3 text-xs leading-5 text-muted-foreground">
                    Automatic impact remains hidden until its measured subset independently meets
                    the cohort safeguard.
                  </p>
                ) : (
                  <p className="mt-3 text-xs leading-5 text-muted-foreground">
                    Reported and measured direction agreed in{' '}
                    {percent(cohort.user_measurement_agreement_rate)} of comparable outcomes.
                  </p>
                )}
              </section>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-bold tabular-nums">{value}</dd>
    </div>
  );
}
