import { Layers3 } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Card, CardContent } from '@/components/ui/Card';
import { EmptyState, Skeleton } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useCategoryIntelligence } from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { ExplainAction } from '@/features/ai/ExplainAction';
import { formatCurrency } from '@/lib/format';

export function CategoryIntelligenceSection() {
  const { user } = useAuth();
  const categories = useCategoryIntelligence();
  const { setCategoryDrill, scrollTo } = useDashboardUi();
  const currency = user?.currency ?? 'INR';
  const items = categories.data?.categories ?? [];

  return (
    <div>
      <SectionTitle
        eyebrow="Categories"
        title="Category intelligence"
        description="Budget usage, month-over-month movement, hierarchy, and the merchants driving each category."
        action={items.length > 0 ? <Badge variant="info">{items.length} categories</Badge> : undefined}
      />

      {categories.isLoading ? (
        <div className="grid gap-3 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Layers3 />}
          title="No category intelligence yet"
          description="Category intelligence appears once categorized debit transactions exist."
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((category) => {
            const usage = category.budget_usage_pct ?? 0;
            return (
              <Card key={category.category_id ?? category.name}>
                <CardContent className="grid gap-3 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-bold">
                        {category.icon} {category.name}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {category.parent_name ? `${category.parent_name} / ` : ''}
                        {category.transaction_count} transaction(s)
                      </p>
                    </div>
                    <Badge
                      variant={usage >= 100 ? 'danger' : usage >= 80 ? 'warning' : 'outline'}
                      className="shrink-0"
                    >
                      {category.budget_usage_pct == null ? 'No budget' : `${Math.round(usage)}%`}
                    </Badge>
                  </div>

                  <div className="grid grid-cols-3 gap-2">
                    <Metric label="Spend" value={formatCurrency(category.total_spend, currency)} />
                    <Metric
                      label="Budget"
                      value={
                        category.budget_limit == null
                          ? 'Unset'
                          : formatCurrency(category.budget_limit, currency)
                      }
                    />
                    <Metric
                      label="MoM"
                      value={
                        category.month_change_pct == null
                          ? 'New'
                          : `${category.month_change_pct > 0 ? '+' : ''}${category.month_change_pct}%`
                      }
                    />
                  </div>

                  <div className="grid gap-1.5">
                    {category.top_merchants.slice(0, 3).map((merchant) => (
                      <div
                        key={merchant.name}
                        className="flex items-center justify-between rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm"
                      >
                        <span className="truncate">{merchant.name}</span>
                        <span className="shrink-0 font-semibold">
                          {formatCurrency(merchant.total, currency)}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div className="flex justify-end gap-1 border-t border-border pt-2">
                    <ExplainAction
                      payload={{
                        surface: 'category',
                        title: category.name,
                        description: `${category.transaction_count} transaction(s), spend ${formatCurrency(category.total_spend, currency)}.`,
                        metrics: {
                          budget_usage_pct: category.budget_usage_pct,
                          month_change_pct: category.month_change_pct,
                        },
                      }}
                    />
                    <button
                      className="text-xs font-semibold text-primary hover:underline"
                      onClick={() => {
                        if (category.category_id) {
                          setCategoryDrill({
                            categoryId: category.category_id,
                            label: category.name,
                          });
                        } else {
                          setCategoryDrill({ categoryId: category.name, label: category.name });
                        }
                        scrollTo('transactions');
                      }}
                    >
                      Transactions
                    </button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/35 p-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate text-sm font-bold">{value}</p>
    </div>
  );
}
