import { Store, TrendingUp } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Card, CardContent } from '@/components/ui/Card';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useMerchants } from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { ExplainAction } from '@/features/ai/ExplainAction';
import { formatCurrency } from '@/lib/format';

export function MerchantIntelligenceSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const merchants = useMerchants();
  const { setExplorerSearch, scrollTo } = useDashboardUi();
  const currency = user?.currency ?? 'INR';
  const top = merchants.data ?? [];

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Merchants"
          title="Merchant intelligence"
          description="Repeat spend, average ticket size, category defaults, and recurrence signals."
          action={
            top.length > 0 ? <Badge variant="info">{top.length} merchant(s)</Badge> : undefined
          }
        />
      ) : null}

      {merchants.isLoading ? (
        <div className="grid gap-3 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : top.length === 0 ? (
        <EmptyState
          icon={<Store />}
          title="No merchant intelligence yet"
          description="Merchant behavior appears after debit transactions are available."
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          {top.slice(0, 9).map((merchant) => (
            <Card key={merchant.merchant_key}>
              <CardContent className="grid h-full gap-3 p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-bold">{merchant.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {merchant.category || 'Uncategorized'} / {merchant.transaction_count} txn
                    </p>
                  </div>
                  <Badge
                    variant={merchant.recurrence_likelihood >= 0.9 ? 'warning' : 'outline'}
                    className="shrink-0"
                  >
                    {merchant.recurrence_likelihood >= 0.9 ? 'Recurring' : 'Merchant'}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Metric label="Total" value={formatCurrency(merchant.total_spend, currency)} />
                  <Metric label="Average" value={formatCurrency(merchant.avg_spend, currency)} />
                </div>
                <div className="flex items-center justify-between gap-2 border-t border-border pt-2">
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    {merchant.month_change_pct == null ? (
                      'No previous month'
                    ) : (
                      <>
                        <TrendingUp className="h-3.5 w-3.5" />
                        {merchant.month_change_pct > 0 ? '+' : ''}
                        {merchant.month_change_pct}%
                      </>
                    )}
                  </span>
                  <div className="flex gap-1">
                    <ExplainAction
                      payload={{
                        surface: 'merchant',
                        title: merchant.name,
                        description: `${merchant.transaction_count} transaction(s), total ${formatCurrency(merchant.total_spend, currency)}.`,
                        metrics: {
                          average_spend: formatCurrency(merchant.avg_spend, currency),
                          recurrence_likelihood: merchant.recurrence_likelihood,
                          category: merchant.category,
                        },
                      }}
                    />
                    <button
                      className="text-xs font-semibold text-primary hover:underline"
                      onClick={() => {
                        setExplorerSearch(merchant.name);
                        scrollTo('transactions');
                      }}
                    >
                      Transactions
                    </button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/35 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-bold">{value}</p>
    </div>
  );
}
