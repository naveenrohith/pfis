import { Brain, CalendarClock, ShieldCheck, Store, Trash2, TrendingUp } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import {
  useDeleteLearnedMerchantRule,
  useLearnedMerchantRules,
  useMerchants,
} from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useToast } from '@/components/ui/Toast';
import { formatCurrency } from '@/lib/format';
import type { MerchantSummary } from '@/lib/types';

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

export function MerchantIntelligenceSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const merchants = useMerchants();
  const rules = useLearnedMerchantRules();
  const deleteRule = useDeleteLearnedMerchantRule();
  const { notify } = useToast();
  const { setExplorerSearch, scrollTo } = useDashboardUi();
  const currency = user?.currency ?? 'INR';
  const top = merchants.data ?? [];

  const forgetRule = async (ruleId: string, descriptor: string) => {
    if (!window.confirm(`Forget the learned mapping for “${descriptor}”?`)) return;
    try {
      await deleteRule.mutateAsync(ruleId);
      notify('Learned merchant mapping removed', 'success');
    } catch (error) {
      notify((error as Error).message, 'error');
    }
  };

  return (
    <div className="space-y-6">
      {!embedded ? (
        <SectionTitle
          eyebrow="Merchants"
          title="Merchant intelligence"
          description="See what PFIS recognizes, which payment rhythms are credible, and what it learned from your corrections."
          action={top.length > 0 ? <Badge variant="info">{top.length} merchants</Badge> : undefined}
        />
      ) : null}

      <section
        aria-labelledby="merchant-knowledge-title"
        className="grid gap-4 border-y border-border/70 py-5 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-center"
      >
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 text-primary">
          <ShieldCheck className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 id="merchant-knowledge-title" className="text-pretty font-extrabold">
            One evidence trail, from bank description to financial pattern
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Corrections stay private to your account. Recurrence needs a real cadence; similar
            purchases alone are not treated as subscriptions.
          </p>
        </div>
        <Badge variant="outline">Ruleset pfis-recurring-2</Badge>
      </section>

      {merchants.isLoading ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-44" />
          ))}
        </div>
      ) : top.length === 0 ? (
        <EmptyState
          icon={<Store />}
          title="No merchant intelligence yet"
          description="Merchant behavior appears after debit transactions are available."
        />
      ) : (
        <section aria-labelledby="merchant-patterns-title">
          <div className="mb-3 flex items-end justify-between gap-3">
            <div>
              <p className="text-xs font-bold text-muted-foreground">Pattern ledger</p>
              <h2 id="merchant-patterns-title" className="mt-1 text-xl font-extrabold">
                Merchant behavior this month
              </h2>
            </div>
            <p className="text-xs text-muted-foreground">Observed → calculated → expected</p>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {top.slice(0, 10).map((merchant) => (
              <Card key={`${merchant.merchant_key}-${merchant.category_id ?? 'none'}`}>
                <CardContent className="grid h-full min-w-0 gap-4 p-4 sm:p-5">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-extrabold">{merchant.name}</p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {merchant.category || 'Uncategorized'} · {merchant.transaction_count}{' '}
                        transactions
                      </p>
                    </div>
                    <Badge variant={statusVariant(merchant)} className="shrink-0">
                      {statusLabel(merchant)}
                    </Badge>
                  </div>

                  <dl className="grid grid-cols-2 gap-x-5 gap-y-3 border-y border-border/70 py-3">
                    <Metric
                      label="Observed spend"
                      value={formatCurrency(merchant.total_spend, currency)}
                    />
                    <Metric
                      label="Average ticket"
                      value={formatCurrency(merchant.avg_spend, currency)}
                    />
                    <Metric
                      label="Cadence confidence"
                      value={`${Math.round(merchant.recurrence_confidence * 100)}%`}
                    />
                    <Metric
                      label="Next expected"
                      value={formatExpectedDate(merchant.next_expected_date)}
                    />
                  </dl>

                  <div className="flex min-w-0 items-center justify-between gap-3">
                    <span className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
                      {merchant.recurrence_cadence ? (
                        <CalendarClock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      ) : (
                        <TrendingUp className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      )}
                      <span className="truncate">
                        {merchant.recurrence_cadence ||
                          formatMonthChange(merchant.month_change_pct)}
                      </span>
                    </span>
                    <Button
                      variant="link"
                      size="sm"
                      onClick={() => {
                        setExplorerSearch(merchant.name);
                        scrollTo('transactions');
                      }}
                    >
                      View Transactions
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      <section aria-labelledby="learned-rules-title" className="border-t border-border/70 pt-6">
        <div className="mb-4 flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Brain className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 id="learned-rules-title" className="font-extrabold">
              Learned From Your Corrections
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              These exact mappings improve future imports for you only. You can make PFIS forget any
              mapping.
            </p>
          </div>
        </div>

        {rules.isLoading ? (
          <Skeleton className="h-28" />
        ) : rules.data?.length ? (
          <div className="divide-y divide-border rounded-xl border border-border">
            {rules.data.map((rule) => (
              <div
                key={rule.id}
                className="grid min-w-0 gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold">
                    {rule.raw_descriptor} <span className="text-muted-foreground">→</span>{' '}
                    {rule.normalized_name}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Explicit correction · {Math.round(rule.confidence * 100)}% confidence
                  </p>
                </div>
                <time className="text-xs text-muted-foreground" dateTime={rule.updated_at}>
                  Updated {DATE_FORMAT.format(new Date(rule.updated_at))}
                </time>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Forget learned mapping for ${rule.raw_descriptor}`}
                  disabled={deleteRule.isPending}
                  onClick={() => void forgetRule(rule.id, rule.raw_descriptor)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
            No learned mappings yet. Correct a merchant in Activity and the mapping will appear
            here.
          </p>
        )}
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate font-bold tabular-nums" title={value}>
        {value}
      </dd>
    </div>
  );
}

function statusVariant(merchant: MerchantSummary): 'success' | 'warning' | 'outline' {
  if (merchant.recurrence_status === 'mature') return 'success';
  if (merchant.recurrence_status === 'early' || merchant.recurrence_status === 'missed') {
    return 'warning';
  }
  return 'outline';
}

function statusLabel(merchant: MerchantSummary): string {
  if (merchant.recurrence_status === 'mature') return 'Confirmed Rhythm';
  if (merchant.recurrence_status === 'early') return 'Early Signal';
  if (merchant.recurrence_status === 'missed') return 'Possibly Missed';
  return 'Observed Merchant';
}

function formatExpectedDate(value?: string | null): string {
  return value ? DATE_FORMAT.format(new Date(`${value}T00:00:00`)) : 'Not enough evidence';
}

function formatMonthChange(value?: number | null): string {
  if (value == null) return 'No previous-month comparison';
  return `${value > 0 ? '+' : ''}${value}% from last month`;
}
