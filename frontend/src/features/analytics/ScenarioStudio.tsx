import { useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ArrowRight, CircleAlert, Gauge, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Label } from '@/components/ui/Input';
import { api } from '@/lib/api';
import { formatCurrency } from '@/lib/format';
import type { CashFlowProjection, ScenarioRequest } from '@/lib/types';
import { cn } from '@/lib/utils';

interface ScenarioStudioProps {
  userId: string;
  month: number;
  year: number;
  currency: string;
  baseline?: CashFlowProjection;
}

export function ScenarioStudio({ userId, month, year, currency, baseline }: ScenarioStudioProps) {
  const [flexibleReduction, setFlexibleReduction] = useState('');
  const [recurringReduction, setRecurringReduction] = useState('');
  const [additionalIncome, setAdditionalIncome] = useState('');
  const preview = useMutation({
    mutationFn: (payload: ScenarioRequest) => api.previewScenario(userId, payload),
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    preview.mutate({
      month,
      year,
      flexible_spend_reduction: amount(flexibleReduction),
      recurring_reduction: amount(recurringReduction),
      additional_income: amount(additionalIncome),
    });
  };

  const result = preview.data;
  const scenarioPositive = (result?.scenario_projected_net ?? baseline?.projected_net ?? 0) >= 0;
  const capped =
    result &&
    (result.requested_flexible_spend_reduction !== result.effective_flexible_spend_reduction ||
      result.requested_recurring_reduction !== result.effective_recurring_reduction);

  return (
    <section
      className="relative mt-6 overflow-hidden rounded-[1.75rem] bg-foreground px-5 py-6 text-background shadow-[0_22px_60px_-42px_hsl(var(--foreground))] sm:px-7 sm:py-8"
      aria-labelledby="scenario-studio-title"
    >
      <div
        className="pointer-events-none absolute -right-20 -top-28 h-72 w-72 rounded-full bg-primary/25 blur-3xl"
        aria-hidden="true"
      />
      <div className="relative grid gap-8 xl:grid-cols-[minmax(0,.72fr)_minmax(520px,1.28fr)]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="border-background/15 bg-background/10 text-background">
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" /> Deterministic preview
            </Badge>
            <span className="text-xs font-bold text-background/55">No records are changed</span>
          </div>
          <p className="mt-6 text-xs font-extrabold uppercase tracking-[0.18em] text-background/50">
            Decision studio
          </p>
          <h2
            id="scenario-studio-title"
            className="mt-2 max-w-xl text-3xl font-extrabold tracking-[-0.04em] sm:text-4xl"
          >
            Test one change before you commit to it.
          </h2>
          <p className="mt-3 max-w-lg text-sm leading-6 text-background/65">
            Adjust the month ahead. PFIS recalculates the same projection rules and shows the
            difference—never a promise.
          </p>
          <div className="mt-7 flex items-center gap-3">
            <div>
              <p className="text-xs font-bold text-background/50">Current month-end forecast</p>
              <p className="money-value mt-1 text-2xl">
                {baseline ? formatCurrency(baseline.projected_net, currency) : 'Preparing…'}
              </p>
            </div>
            <Gauge className="ml-auto h-8 w-8 text-primary-foreground/55" aria-hidden="true" />
          </div>
        </div>

        <div className="rounded-2xl bg-background p-4 text-foreground shadow-sm sm:p-6">
          <form onSubmit={submit} className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-3">
              <MoneyInput
                id="scenario-flexible"
                label="Trim flexible spend"
                value={flexibleReduction}
                onChange={setFlexibleReduction}
                hint="Dining, shopping, and other adjustable spend"
              />
              <MoneyInput
                id="scenario-recurring"
                label="Reduce recurring costs"
                value={recurringReduction}
                onChange={setRecurringReduction}
                hint="Limited to detected monthly commitments"
              />
              <MoneyInput
                id="scenario-income"
                label="Add expected income"
                value={additionalIncome}
                onChange={setAdditionalIncome}
                hint="User supplied and not verified by PFIS"
              />
            </div>
            <div className="flex flex-col gap-3 border-t border-border/70 pt-5 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-muted-foreground">
                Enter monthly amounts in {currency}. Empty fields are treated as zero.
              </p>
              <Button type="submit" disabled={!userId || !baseline || preview.isPending}>
                {preview.isPending ? 'Recalculating…' : 'Preview change'}
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </form>

          {preview.isError ? (
            <p
              className="mt-4 flex items-start gap-2 rounded-xl bg-danger/10 p-3 text-sm text-danger"
              role="alert"
            >
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {(preview.error as Error).message}
            </p>
          ) : null}

          {result ? (
            <div className="mt-6 border-t border-border/70 pt-5" aria-live="polite">
              <div className="grid items-center gap-4 sm:grid-cols-[1fr_auto_1fr]">
                <Outcome
                  label="Baseline"
                  value={formatCurrency(result.baseline_projected_net, currency)}
                />
                <ArrowRight
                  className="hidden h-5 w-5 text-muted-foreground sm:block"
                  aria-hidden="true"
                />
                <Outcome
                  label="Scenario month end"
                  value={formatCurrency(result.scenario_projected_net, currency)}
                  className={scenarioPositive ? 'text-success' : 'text-danger'}
                />
              </div>
              <p className="mt-5 text-sm font-bold">
                This scenario improves the month-end position by{' '}
                <span className="money-value text-success">
                  {formatCurrency(result.monthly_impact, currency)}
                </span>
                .
              </p>
              {capped ? (
                <p className="mt-2 text-xs leading-5 text-warning">
                  PFIS capped one or more reductions to the amount supported by the current
                  projection.
                </p>
              ) : null}
              <details className="mt-4 border-t border-border/70 pt-2 text-xs text-muted-foreground">
                <summary className="focus-ring cursor-pointer rounded py-2 font-bold text-foreground">
                  Effective adjustments and assumptions
                </summary>
                <div className="mt-2 grid gap-4 sm:grid-cols-2">
                  <dl className="space-y-2">
                    <Adjustment
                      label="Flexible spend reduction"
                      value={formatCurrency(result.effective_flexible_spend_reduction, currency)}
                    />
                    <Adjustment
                      label="Recurring reduction"
                      value={formatCurrency(result.effective_recurring_reduction, currency)}
                    />
                    <Adjustment
                      label="Additional income"
                      value={formatCurrency(result.additional_income, currency)}
                    />
                  </dl>
                  <ul className="list-disc space-y-1 pl-4 leading-5">
                    {result.assumptions.map((assumption) => (
                      <li key={assumption}>{assumption}</li>
                    ))}
                  </ul>
                </div>
              </details>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function MoneyInput({
  id,
  label,
  value,
  onChange,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint: string;
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        name={id}
        className="money-value mt-1"
        type="number"
        min={0}
        max={10_000_000}
        step="100"
        inputMode="decimal"
        autoComplete="off"
        placeholder="0"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={`${id}-hint`}
      />
      <p id={`${id}-hint`} className="mt-1.5 text-xs leading-5 text-muted-foreground">
        {hint}
      </p>
    </div>
  );
}

function Outcome({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div>
      <p className="text-xs font-bold text-muted-foreground">{label}</p>
      <p className={cn('money-value mt-1 text-2xl', className)}>{value}</p>
    </div>
  );
}

function Adjustment({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt>{label}</dt>
      <dd className="money-value text-foreground">{value}</dd>
    </div>
  );
}

function amount(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}
