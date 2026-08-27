import { AlertTriangle, CreditCard, ShieldCheck } from 'lucide-react';
import { formatCurrency, formatDate } from '@/lib/format';
import type { CardDueRunway, CardPaymentScenario } from '@/lib/types';

const scenarioCopy: Record<CardPaymentScenario['scenario'], string> = {
  minimum_due: 'Minimum due',
  total_due: 'Total due',
};

const statusCopy: Record<CardPaymentScenario['status'], { label: string; tone: string }> = {
  covered: { label: 'Covered on lower band', tone: 'text-success' },
  at_risk: { label: 'Cash path at risk', tone: 'text-warning' },
  unavailable: { label: 'Funding path unavailable', tone: 'text-muted-foreground' },
};

function money(value: number | null | undefined, currency: string): string {
  return value == null ? 'Unavailable' : formatCurrency(value, currency);
}

function scenarioOrder(scenario: CardPaymentScenario['scenario']): number {
  return scenario === 'minimum_due' ? 0 : 1;
}

function lowerBandSummary(scenario: CardPaymentScenario, currency: string): string {
  if (scenario.lower_band_covered == null) return 'Unavailable';
  if (scenario.lower_band_covered) return 'Covered';
  return `Gap ${money(scenario.lower_band_cash_gap, currency)}`;
}

export function CardPaymentScenarioPanel({ runway }: { runway?: CardDueRunway }) {
  const scenarios = [...(runway?.payment_scenarios ?? [])].sort(
    (left, right) => scenarioOrder(left.scenario) - scenarioOrder(right.scenario),
  );
  if (!runway || !scenarios.length) return null;

  return (
    <section
      className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
      aria-labelledby="card-payment-scenarios-title"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-intelligence/10 text-intelligence">
            <CreditCard className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              PAYMENT SCENARIOS
            </p>
            <h2
              id="card-payment-scenarios-title"
              className="mt-1 text-xl font-extrabold tracking-[-0.03em]"
            >
              Minimum due vs total due
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              Compare two hypothetical issuer targets against the same conservative funding path.
              Existing payment intentions are shown as planned, not confirmed settlement.
            </p>
          </div>
        </div>
        <p className="shrink-0 text-xs font-extrabold text-muted-foreground">
          READ-ONLY COMPARISON
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
        <span>
          Due date:{' '}
          <strong className="text-foreground">
            {scenarios[0].payment_date ? formatDate(scenarios[0].payment_date) : 'Unavailable'}
          </strong>
        </span>
        <span>
          Planned before due:{' '}
          <strong className="money-value text-foreground">
            {money(runway.planned_payment_total, runway.currency)}
          </strong>
        </span>
        <span>
          Confidence:{' '}
          <strong className="text-foreground">{Math.round(runway.confidence * 100)}%</strong>
        </span>
      </div>

      <div className="mt-4 overflow-x-auto rounded-lg border border-border/65 bg-muted/20">
        <table className="w-full min-w-[68rem] border-collapse text-left text-sm">
          <caption className="sr-only">Card payment scenario comparison</caption>
          <thead>
            <tr className="border-b border-border/65 text-xs text-muted-foreground">
              <th scope="col" className="px-3 py-3 font-bold">
                Strategy
              </th>
              <th scope="col" className="px-3 py-3 font-bold">
                Issuer target
              </th>
              <th scope="col" className="px-3 py-3 font-bold">
                Additional beyond planned
              </th>
              <th scope="col" className="px-3 py-3 font-bold">
                Effective cash leaving
              </th>
              <th scope="col" className="px-3 py-3 font-bold">
                Billed due remaining
              </th>
              <th scope="col" className="px-3 py-3 font-bold">
                Lower-band funding after
              </th>
              <th scope="col" className="px-3 py-3 font-bold">
                Coverage
              </th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map((scenario) => {
              const status = statusCopy[scenario.status];
              return (
                <tr key={scenario.scenario} className="border-b border-border/45 last:border-0">
                  <th scope="row" className="px-3 py-3">
                    <span className="block font-extrabold">{scenarioCopy[scenario.scenario]}</span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {money(scenario.planned_payment_applied, runway.currency)} credited from
                      intention
                    </span>
                  </th>
                  <td className="money-value whitespace-nowrap px-3 py-3 font-extrabold">
                    {money(scenario.payment_amount, runway.currency)}
                  </td>
                  <td className="money-value whitespace-nowrap px-3 py-3">
                    {money(scenario.additional_payment_amount, runway.currency)}
                  </td>
                  <td className="money-value whitespace-nowrap px-3 py-3 font-extrabold">
                    {money(scenario.effective_payment_amount, runway.currency)}
                  </td>
                  <td className="money-value whitespace-nowrap px-3 py-3">
                    {money(scenario.remaining_total_due, runway.currency)}
                  </td>
                  <td className="px-3 py-3">
                    <span className="money-value block whitespace-nowrap">
                      {money(scenario.lower_band_funding_balance_after, runway.currency)}
                    </span>
                    {scenario.lower_band_covered === false ? (
                      <span className="mt-1 block text-xs text-warning">
                        Gap {money(scenario.lower_band_cash_gap, runway.currency)}
                      </span>
                    ) : null}
                  </td>
                  <td className={`px-3 py-3 text-xs font-extrabold ${status.tone}`}>
                    {lowerBandSummary(scenario, runway.currency)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {scenarios.map((scenario) => {
          const status = statusCopy[scenario.status];
          const StatusIcon = scenario.status === 'covered' ? ShieldCheck : AlertTriangle;
          return (
            <div key={`${scenario.scenario}-readout`} className="rounded-lg bg-muted/35 p-3">
              <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
                {scenarioCopy[scenario.scenario].toUpperCase()} READOUT
              </p>
              <p className={`mt-1 flex items-start gap-2 text-sm font-extrabold ${status.tone}`}>
                <StatusIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                {status.label}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {scenario.lower_band_covered == null
                  ? 'PFIS cannot evaluate the funding path until the selected account has a usable forecast anchor.'
                  : scenario.lower_band_covered
                    ? 'The conservative forecast remains above this hypothetical payment target.'
                    : 'The conservative forecast crosses below this hypothetical payment target; the gap is shown for review.'}
              </p>
            </div>
          );
        })}
      </div>

      <p className="mt-4 text-xs leading-5 text-muted-foreground">
        These are deterministic planning comparisons. PFIS does not schedule, submit, reserve, or
        confirm a payment, and it does not model issuer interest, fees, settlement timing, or
        delinquency policy.
      </p>
    </section>
  );
}
