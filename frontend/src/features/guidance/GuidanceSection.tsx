import { useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, BrainCircuit, Clock3, Search, ShieldCheck, Sparkles, X } from 'lucide-react';
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
import type { GuidanceQueryResult } from '@/lib/types';

const EXAMPLES = [
  'How much did I spend this month?',
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
    mutationFn: ({ recommendationId, state }: { recommendationId: string; state: 'dismissed' | 'snoozed' }) => {
      if (!user) throw new Error('Sign in to update guidance');
      const snoozedUntil = state === 'snoozed'
        ? new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
        : undefined;
      return api.setGuidanceState(user.id, recommendationId, state, snoozedUntil);
    },
    onSuccess: (_, variables) => {
      if (user) queryClient.invalidateQueries({ queryKey: queryKeys.guidanceBrief(user.id, month, year) });
      notify(variables.state === 'snoozed' ? 'Guidance snoozed for 7 days' : 'Guidance dismissed', 'success');
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
        action={<Badge variant="info"><ShieldCheck className="h-3.5 w-3.5" /> Deterministic</Badge>}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <motion.div initial={reduceMotion ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reduceMotion ? 0 : 0.2 }}>
        <Card className="h-full overflow-hidden border-primary/15 bg-gradient-to-br from-card to-primary/5">
          <CardContent className="p-5 sm:p-6">
            {brief.isLoading ? (
              <Skeleton className="h-56" />
            ) : brief.data ? (
              <div className="grid gap-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-bold uppercase tracking-[0.14em] text-primary">Today</p>
                    <h3 className="mt-2 text-xl font-extrabold tracking-tight">{brief.data.headline}</h3>
                    <p className="mt-2 text-sm text-muted-foreground">{brief.data.summary}</p>
                  </div>
                  <div className="rounded-2xl border border-border bg-card px-3 py-2 text-center shadow-sm">
                    <p className="text-xs text-muted-foreground">Health</p>
                    <p className="text-2xl font-extrabold text-primary">{brief.data.health_score}</p>
                  </div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {brief.data.changes.map((change) => (
                    <div key={change} className="rounded-xl border border-border/80 bg-card/80 p-3 text-sm">
                      {change}
                    </div>
                  ))}
                </div>
                <div className="grid gap-2">
                  {brief.data.actions.slice(0, 3).map((action) => (
                    <div key={action.id} className="flex items-start gap-3 rounded-xl border border-border bg-card p-3">
                      <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-bold">{action.title}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{action.description}</p>
                        {action.expected_impact && <p className="mt-2 text-xs text-info">{action.expected_impact}</p>}
                        <Button variant="link" size="sm" className="mt-2" onClick={() => scrollTo(action.target)}>
                          {action.action_label} <ArrowRight className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <Button variant="ghost" size="icon" aria-label={`Snooze ${action.title} for 7 days`} onClick={() => updateRecommendationState.mutate({ recommendationId: action.id, state: 'snoozed' })}>
                          <Clock3 className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" aria-label={`Dismiss ${action.title}`} onClick={() => updateRecommendationState.mutate({ recommendationId: action.id, state: 'dismissed' })}>
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Clock3 className="h-3.5 w-3.5" /> Data through {brief.data.data_through} · {brief.data.ruleset_version}
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">The brief is temporarily unavailable.</p>
            )}
          </CardContent>
        </Card>
        </motion.div>

        <Card>
          <CardContent className="grid gap-4 p-5 sm:p-6">
            <div>
              <p className="flex items-center gap-2 font-bold"><BrainCircuit className="h-4 w-4 text-primary" /> Ask PFIS</p>
              <p className="mt-1 text-sm text-muted-foreground">Ask a supported question about the selected month.</p>
            </div>
            <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); submit(); }}>
              <Input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="How much did I spend this month?" />
              <Button type="submit" size="icon" disabled={ask.isPending} aria-label="Ask PFIS"><Search className="h-4 w-4" /></Button>
            </form>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" className="rounded-full border border-border px-3 py-1.5 text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground" onClick={() => submit(example)}>
                  {example}
                </button>
              ))}
            </div>
            {ask.isPending && <Skeleton className="h-28" />}
            {result && !ask.isPending && (
              <div className={`rounded-2xl border p-4 ${result.supported ? 'border-primary/20 bg-primary/5' : 'border-warning/25 bg-warning/10'}`}>
                <p className="text-sm font-bold">{result.supported ? 'Answer' : 'Supported questions only'}</p>
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
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
