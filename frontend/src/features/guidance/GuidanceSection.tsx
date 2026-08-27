import { useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  BrainCircuit,
  Clock3,
  ListChecks,
  Search,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  X,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { queryKeys, useGuidanceBrief } from '@/features/workspace/queries';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import type { GuidanceQueryResult, RecommendationFeedbackReason } from '@/lib/types';
import { RecommendationFollowUp } from './RecommendationFollowUp';

const EXAMPLES = [
  'How much did I spend this month?',
  'What is my current bank balance?',
  'Is it safe to spend before my next income?',
  'What is my current card outstanding?',
  'Can I pay my card and still cover upcoming cash needs?',
  'What is my current net worth?',
  'Show recurring charges',
  'How are my budgets doing?',
  'Compare this month with last month',
];

export function GuidanceSection() {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const { scrollTo } = useDashboardUi();
  const brief = useGuidanceBrief();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<GuidanceQueryResult | null>(null);
  const reduceMotion = useReducedMotion();

  const ask = useMutation({
    mutationFn: (value: string) => {
      if (!user) throw new Error('Sign in to ask a finance question');
      return api.guidanceQuery(user.id, value, month, year);
    },
    onSuccess: setResult,
    onError: (error) => notify((error as Error).message, 'error'),
  });

  const updateRecommendationState = useMutation({
    mutationFn: ({
      recommendationId,
      state,
      reason,
    }: {
      recommendationId: string;
      state: 'accepted' | 'not_relevant' | 'snoozed';
      reason?: RecommendationFeedbackReason;
    }) => {
      if (!user) throw new Error('Sign in to update guidance');
      const snoozedUntil =
        state === 'snoozed'
          ? new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
          : undefined;
      const asOf = `${year}-${String(month).padStart(2, '0')}-01`;
      if (reason && reason !== 'not_relevant') {
        return api.setGuidanceState(
          user.id,
          recommendationId,
          state,
          snoozedUntil,
          asOf,
          undefined,
          reason,
        );
      }
      return api.setGuidanceState(user.id, recommendationId, state, snoozedUntil, asOf);
    },
    onSuccess: (_, variables) => {
      if (user) {
        queryClient.invalidateQueries({ queryKey: queryKeys.guidanceBrief(user.id, month, year) });
        queryClient.invalidateQueries({ queryKey: ['guidance', 'decisions', user.id] });
      }
      notify(
        variables.state === 'snoozed'
          ? 'Guidance snoozed for 7 days'
          : variables.state === 'accepted'
            ? 'Action added to your decisions'
            : 'Marked as not relevant',
        'success',
      );
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  function submit(value = question) {
    const trimmed = value.trim();
    if (!trimmed) return;
    setQuestion(trimmed);
    ask.mutate(trimmed);
  }

  return (
    <div>
      <SectionTitle
        eyebrow="Daily brief"
        title="Clear guidance, no guesswork"
        description="PFIS explains its rules, uses aggregate financial data, and declines questions it cannot answer reliably."
        action={
          <Badge variant="info">
            <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" /> Deterministic
          </Badge>
        }
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <motion.div
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduceMotion ? 0 : 0.2 }}
        >
          <Card className="h-full overflow-hidden border-primary/15 bg-gradient-to-br from-card to-primary/5">
            <CardContent className="p-5 sm:p-6">
              {brief.isLoading ? (
                <Skeleton className="h-56" />
              ) : brief.data ? (
                <div className="grid gap-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-[0.14em] text-primary">
                        Today
                      </p>
                      <h3 className="mt-2 text-xl font-extrabold tracking-tight">
                        {brief.data.headline}
                      </h3>
                      <p className="mt-2 text-sm text-muted-foreground">{brief.data.summary}</p>
                    </div>
                    <div className="rounded-2xl border border-border bg-card px-3 py-2 text-center shadow-sm">
                      <p className="text-xs text-muted-foreground">Health</p>
                      <p className="text-2xl font-extrabold text-primary">
                        {brief.data.health_score}
                      </p>
                    </div>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {brief.data.changes.map((change) => (
                      <div
                        key={change}
                        className="rounded-xl border border-border/80 bg-card/80 p-3 text-sm"
                      >
                        {change}
                      </div>
                    ))}
                  </div>
                  <div className="grid gap-2">
                    {brief.data.actions.slice(0, 3).map((action) => (
                      <div
                        key={action.id}
                        className="flex items-start gap-3 rounded-xl border border-border bg-card p-3"
                      >
                        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-bold">{action.title}</p>
                          <p className="mt-1 text-xs text-muted-foreground">{action.description}</p>
                          {action.expected_impact && (
                            <p className="mt-2 text-xs text-info">{action.expected_impact}</p>
                          )}
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <Button
                              variant="link"
                              size="sm"
                              onClick={() => scrollTo(action.target)}
                            >
                              {action.action_label}{' '}
                              <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={updateRecommendationState.isPending}
                              onClick={() =>
                                updateRecommendationState.mutate({
                                  recommendationId: action.id,
                                  state: 'accepted',
                                })
                              }
                            >
                              Use this action
                            </Button>
                          </div>
                        </div>
                        <div className="flex shrink-0 gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Snooze ${action.title} for 7 days`}
                            onClick={() =>
                              updateRecommendationState.mutate({
                                recommendationId: action.id,
                                state: 'snoozed',
                              })
                            }
                          >
                            <Clock3 aria-hidden="true" className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`Mark ${action.title} as not relevant`}
                            onClick={() =>
                              updateRecommendationState.mutate({
                                recommendationId: action.id,
                                state: 'not_relevant',
                                reason: 'not_relevant',
                              })
                            }
                          >
                            <X aria-hidden="true" className="h-3.5 w-3.5" />
                          </Button>
                          <details className="relative">
                            <summary className="focus-ring flex h-11 cursor-pointer list-none items-center rounded-lg px-2 text-xs font-bold text-muted-foreground hover:bg-muted">
                              Why?
                            </summary>
                            <div className="absolute right-0 top-12 z-20 grid min-w-44 gap-1 rounded-xl border border-border bg-card p-2 shadow-lift">
                              {(
                                [
                                  ['not_feasible', 'Not feasible'],
                                  ['already_done', 'Already done'],
                                  ['too_risky', 'Too risky'],
                                  ['wrong_timing', 'Wrong timing'],
                                ] as const
                              ).map(([reason, label]) => (
                                <Button
                                  key={reason}
                                  variant="ghost"
                                  size="sm"
                                  className="justify-start"
                                  disabled={updateRecommendationState.isPending}
                                  onClick={() =>
                                    updateRecommendationState.mutate({
                                      recommendationId: action.id,
                                      state: 'not_relevant',
                                      reason,
                                    })
                                  }
                                >
                                  {label}
                                </Button>
                              ))}
                            </div>
                          </details>
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Clock3 aria-hidden="true" className="h-3.5 w-3.5" /> Data through{' '}
                    {brief.data.data_through} · {brief.data.ruleset_version}
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  The brief is temporarily unavailable.
                </p>
              )}
            </CardContent>
          </Card>
        </motion.div>

        <Card>
          <CardContent className="grid gap-4 p-5 sm:p-6">
            <div>
              <p className="flex items-center gap-2 font-bold">
                <BrainCircuit aria-hidden="true" className="h-4 w-4 text-primary" /> Ask PFIS
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Ask a supported question about the selected month.
              </p>
            </div>
            <form
              className="flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <Input
                name="guidance-question"
                aria-label="Ask PFIS about the selected month"
                autoComplete="off"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="How much did I spend this month?"
              />
              <Button type="submit" size="icon" disabled={ask.isPending} aria-label="Ask PFIS">
                <Search aria-hidden="true" className="h-4 w-4" />
              </Button>
            </form>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  className="focus-ring touch-manipulation rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground transition-[border-color,color] hover:border-primary/40 hover:text-foreground"
                  onClick={() => submit(example)}
                >
                  {example}
                </button>
              ))}
            </div>
            {ask.isPending && <Skeleton className="h-28" />}
            {result && !ask.isPending && (
              <div
                aria-live="polite"
                className={`rounded-2xl border p-4 ${result.supported ? 'border-primary/20 bg-primary/5' : 'border-warning/25 bg-warning/10'}`}
              >
                <p className="text-sm font-bold">
                  {result.supported ? 'Answer' : 'Supported questions only'}
                </p>
                <p className="mt-2 text-sm text-muted-foreground">{result.answer}</p>
                {result.metrics.length > 0 && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {result.metrics.map((metric) => (
                      <div key={metric.label} className="rounded-xl bg-card p-3">
                        <p className="text-xs text-muted-foreground">{metric.label}</p>
                        <p className="mt-1 font-extrabold">{metric.value}</p>
                      </div>
                    ))}
                  </div>
                )}
                <GuidanceEvidencePanel result={result} />
                {result.suggested_actions.length > 0 && (
                  <div className="mt-4 border-t border-border/60 pt-3">
                    <p className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
                      Next steps
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {result.suggested_actions.map((action) => (
                        <Button
                          key={action}
                          type="button"
                          variant="link"
                          size="sm"
                          onClick={() => scrollTo(guidanceActionTarget(action))}
                        >
                          {action} <ArrowRight aria-hidden="true" className="h-3.5 w-3.5" />
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
      <RecommendationFollowUp />
    </div>
  );
}

function GuidanceEvidencePanel({ result }: { result: GuidanceQueryResult }) {
  const plan = result.plan ?? [];
  const evidence = result.evidence ?? [];
  const uncertainty = result.uncertainty ?? [];
  const confidence = result.confidence ?? 0;

  if (plan.length === 0 && evidence.length === 0 && uncertainty.length === 0) return null;

  return (
    <section
      className="mt-4 border-t border-border/60 pt-4"
      aria-labelledby="guidance-evidence-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p
            id="guidance-evidence-title"
            className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground"
          >
            {result.supported ? 'Evidence & limits' : 'Why PFIS stopped'}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {formatGuidanceScope(result.temporal_scope)}
            {result.supported
              ? ` · Confidence ${formatGuidanceConfidence(confidence)}`
              : ' · Confidence not established'}
          </p>
        </div>
        {result.supported && (
          <Badge variant={confidence >= 0.8 ? 'success' : 'warning'}>
            <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />
            {confidence >= 0.8 ? 'Grounded' : 'Needs review'}
          </Badge>
        )}
      </div>

      {evidence.length > 0 && (
        <ul className="mt-3 grid gap-2 sm:grid-cols-2" aria-label="Evidence sources">
          {evidence.map((item, index) => (
            <li
              key={`${item.source_type}-${item.label}-${index}`}
              className="min-w-0 rounded-xl border border-border/80 bg-card/70 p-3"
            >
              <p className="text-xs font-bold text-foreground">{item.label}</p>
              <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">
                {item.value}
              </p>
              <p className="mt-2 text-[0.68rem] font-bold uppercase tracking-[0.08em] text-muted-foreground">
                {formatGuidanceSource(item.source_type)}
                {item.cutoff ? ` · through ${formatGuidanceCutoff(item.cutoff)}` : ''}
              </p>
            </li>
          ))}
        </ul>
      )}

      {uncertainty.length > 0 && (
        <div className="mt-3 rounded-xl border border-warning/25 bg-warning/10 p-3">
          <p className="flex items-center gap-2 text-xs font-bold text-foreground">
            <TriangleAlert aria-hidden="true" className="h-3.5 w-3.5 text-warning" />
            Known limits
          </p>
          <ul className="mt-2 grid gap-1.5 text-xs leading-5 text-muted-foreground">
            {uncertainty.map((item, index) => (
              <li
                key={`${item}-${index}`}
                className="break-words pl-4 before:mr-2 before:text-warning before:content-['•']"
              >
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan.length > 0 && (
        <details className="group mt-3">
          <summary className="focus-ring flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg px-2 text-xs font-bold text-muted-foreground hover:bg-muted [&::-webkit-details-marker]:hidden">
            <ListChecks aria-hidden="true" className="h-3.5 w-3.5 text-primary" />
            How PFIS reached this answer
          </summary>
          <ol className="mt-2 grid gap-2 border-l border-border/80 pl-4 text-xs leading-5 text-muted-foreground">
            {plan.map((step, index) => (
              <li key={`${step}-${index}`} className="relative break-words pl-2">
                <span className="absolute -left-[1.35rem] grid h-5 w-5 place-items-center rounded-full border border-border bg-card text-[0.65rem] font-bold text-primary">
                  {index + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}

function formatGuidanceConfidence(value: number) {
  return new Intl.NumberFormat(undefined, {
    style: 'percent',
    maximumFractionDigits: 0,
  }).format(Math.max(0, Math.min(1, value)));
}

function formatGuidanceScope(scope?: string | null) {
  const labels: Record<string, string> = {
    selected_calendar_month: 'Selected calendar month',
  };
  if (scope && labels[scope]) return labels[scope];
  return scope
    ? scope.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase())
    : 'Selected calendar month';
}

function formatGuidanceSource(sourceType: string) {
  return sourceType.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatGuidanceCutoff(cutoff: string) {
  const parsed = new Date(`${cutoff}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return cutoff;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeZone: 'UTC' }).format(
    parsed,
  );
}

function guidanceActionTarget(action: string) {
  const normalized = action.toLowerCase();
  if (normalized.includes('statement')) return 'statements';
  if (normalized.includes('card') || normalized.includes('payment')) return 'cards';
  if (normalized.includes('funding') || normalized.includes('position')) return 'cash-plan';
  return 'guidance';
}
