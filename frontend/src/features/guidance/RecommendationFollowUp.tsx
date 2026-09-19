import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, ClipboardCheck, Scale } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { api } from '@/lib/api';
import type {
  RecommendationDecision,
  RecommendationOutcome,
  RecommendationOutcomeKind,
} from '@/lib/types';

const decisionKey = (userId: string) => ['guidance', 'decisions', userId] as const;
const outcomeKey = (userId: string) => ['guidance', 'outcomes', userId] as const;

const OUTCOME_OPTIONS: Array<{ value: RecommendationOutcomeKind; label: string }> = [
  { value: 'helped', label: 'It helped' },
  { value: 'no_change', label: 'No clear change' },
  { value: 'worse', label: 'It got worse' },
  { value: 'not_completed', label: 'Not completed' },
];

const OUTCOME_LABELS: Record<RecommendationOutcomeKind, string> = {
  helped: 'Helped',
  no_change: 'No clear change',
  worse: 'Got worse',
  not_completed: 'Not completed',
};

function formatMeasurement(value: number, unit?: string | null) {
  const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
  if (unit === 'percentage_points') return `${formatted} percentage points`;
  if (unit === 'records') return `${formatted} ${Math.abs(value) === 1 ? 'record' : 'records'}`;
  return unit ? `${formatted} ${unit}` : formatted;
}

function measuredChange(outcome: RecommendationOutcome) {
  if (outcome.automatic_impact_value == null) return null;
  const direction =
    outcome.automatic_impact_value > 0
      ? 'improvement'
      : outcome.automatic_impact_value < 0
        ? 'decline'
        : 'change';
  return `${formatMeasurement(Math.abs(outcome.automatic_impact_value), outcome.metric_unit)} measured ${direction}`;
}

export function RecommendationFollowUp() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const decisions = useQuery({
    queryKey: decisionKey(user?.id ?? 'signed-out'),
    queryFn: () => api.guidanceDecisions(user!.id),
    enabled: Boolean(user),
  });
  const outcomes = useQuery({
    queryKey: outcomeKey(user?.id ?? 'signed-out'),
    queryFn: () => api.guidanceOutcomes(user!.id),
    enabled: Boolean(user),
  });
  const recordOutcome = useMutation({
    mutationFn: ({
      decisionId,
      outcome,
    }: {
      decisionId: string;
      outcome: RecommendationOutcomeKind;
    }) => {
      if (!user) throw new Error('Sign in to review an outcome');
      return api.recordGuidanceOutcome(user.id, decisionId, outcome);
    },
    onSuccess: async () => {
      if (user) await queryClient.invalidateQueries({ queryKey: outcomeKey(user.id) });
      notify('Outcome recorded', 'success');
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  const accepted = (decisions.data ?? []).filter(
    (decision: RecommendationDecision) => decision.state === 'accepted',
  );
  if (!user || decisions.isLoading || outcomes.isLoading || accepted.length === 0) return null;
  const outcomesByDecision = new Map(
    (outcomes.data ?? []).map((outcome: RecommendationOutcome) => [outcome.decision_id, outcome]),
  );

  return (
    <Card className="mt-4 border-primary/15">
      <CardContent className="grid gap-4 p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="flex items-center gap-2 font-bold">
              <ClipboardCheck aria-hidden="true" className="h-4 w-4 text-primary" /> Action
              follow-up
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              Review accepted guidance once. PFIS keeps your answer beside the measured baseline.
            </p>
          </div>
          <Badge variant="info">Evidence log</Badge>
        </div>

        <div className="grid gap-3">
          {accepted.map((decision: RecommendationDecision) => {
            const outcome = outcomesByDecision.get(decision.id);
            const automaticChange = outcome ? measuredChange(outcome) : null;
            return (
              <section key={decision.id} className="rounded-xl border border-border bg-card p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-sm font-bold">{decision.title ?? 'Accepted action'}</h3>
                    {decision.expected_impact && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {decision.expected_impact}
                      </p>
                    )}
                    {decision.smallest_action && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        <span className="font-bold text-foreground">Smallest feasible step:</span>{' '}
                        {decision.smallest_action}
                      </p>
                    )}
                    {decision.resolution && (
                      <p className="mt-2 text-xs text-muted-foreground">
                        <span className="font-bold text-foreground">
                          {decision.resolution.label}:
                        </span>{' '}
                        {decision.resolution.next_step}
                      </p>
                    )}
                    {(decision.conflicts ?? []).slice(0, 2).map((conflict) => (
                      <p key={conflict.code} className="mt-2 text-xs text-warning">
                        <span className="font-bold">{conflict.title}:</span> {conflict.description}
                      </p>
                    ))}
                    {decision.baseline_metric_value != null && (
                      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
                        <Scale aria-hidden="true" className="h-3.5 w-3.5" /> Baseline:{' '}
                        {formatMeasurement(
                          decision.baseline_metric_value,
                          decision.baseline_metric_unit,
                        )}
                      </p>
                    )}
                  </div>
                  {outcome && (
                    <Badge variant="success">
                      <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />
                      {OUTCOME_LABELS[outcome.outcome]}
                    </Badge>
                  )}
                </div>

                {outcome ? (
                  <div className="mt-3 rounded-lg bg-muted/55 px-3 py-2 text-xs text-muted-foreground">
                    {automaticChange ??
                      'PFIS recorded your response; no comparable metric was available.'}
                  </div>
                ) : (
                  <div className="mt-4">
                    <p className="text-xs font-bold">What happened after you used this action?</p>
                    <div
                      className="mt-2 flex flex-wrap gap-2"
                      aria-label={`Outcome for ${decision.title ?? 'accepted action'}`}
                    >
                      {OUTCOME_OPTIONS.map((option) => (
                        <Button
                          key={option.value}
                          variant="outline"
                          size="sm"
                          disabled={recordOutcome.isPending}
                          onClick={() =>
                            recordOutcome.mutate({ decisionId: decision.id, outcome: option.value })
                          }
                        >
                          {option.label}
                        </Button>
                      ))}
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      This response is final so the outcome history remains trustworthy.
                    </p>
                  </div>
                )}
              </section>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
