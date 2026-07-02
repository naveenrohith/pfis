import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, Target } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useBudgets, useCategories } from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { useToast } from '@/components/ui/Toast';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { api } from '@/lib/api';
import { formatCurrency } from '@/lib/format';
import type { BudgetTracker } from '@/lib/types';
import { BudgetModal } from './BudgetModal';

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'danger'> = {
  under: 'success',
  warning: 'warning',
  over: 'danger',
};

const RING_COLOR: Record<string, string> = {
  under: 'hsl(var(--success))',
  warning: 'hsl(var(--warning))',
  over: 'hsl(var(--danger))',
};

export function BudgetsSection() {
  const { user } = useAuth();
  const budgets = useBudgets();
  const categories = useCategories();
  const { notify } = useToast();
  const { setCategoryDrill, scrollTo } = useDashboardUi();
  const queryClient = useQueryClient();
  const currency = user?.currency ?? 'INR';

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<BudgetTracker | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['budgets'] });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteBudget(id),
    onSuccess: () => {
      notify('Budget deleted', 'success');
      invalidate();
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });

  return (
    <div>
      <SectionTitle
        eyebrow="Budgets"
        title="Budget board"
        description="Track spending against your monthly limits."
        action={
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setModalOpen(true);
            }}
          >
            <Plus className="mr-1 h-4 w-4" /> Create budget
          </Button>
        }
      />

      {budgets.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-40" />
          ))}
        </div>
      ) : !budgets.data?.length ? (
        <EmptyState
          icon={<Target />}
          title="No budgets configured"
          description="Create a budget to track category spending."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {budgets.data.map((b) => {
            const pct = Math.min(b.usage_pct, 100);
            return (
              <Card key={b.id}>
                <CardContent className="grid gap-4 p-4 sm:p-5">
                  <div className="flex items-start gap-4">
                    <div
                      className="relative flex h-20 w-20 shrink-0 items-center justify-center rounded-full"
                      style={{
                        background: `conic-gradient(${RING_COLOR[b.status]} ${pct * 3.6}deg, hsl(var(--muted)) 0deg)`,
                      }}
                    >
                      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-card text-sm font-bold">
                        {Math.round(b.usage_pct)}%
                      </div>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-bold">
                            {b.category_icon} {b.category}
                          </p>
                          <p className="mt-1 text-sm text-muted-foreground">
                            {formatCurrency(b.actual_spend, currency)} of{' '}
                            {formatCurrency(b.limit, currency)}
                          </p>
                        </div>
                        <Badge variant={STATUS_VARIANT[b.status]} className="capitalize">
                          {b.status}
                        </Badge>
                      </div>
                      <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${pct}%`,
                            background: RING_COLOR[b.status],
                          }}
                        />
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {b.remaining >= 0
                          ? `${formatCurrency(b.remaining, currency)} remaining`
                          : `${formatCurrency(-b.remaining, currency)} over limit`}
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5 border-t border-border pt-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditing(b);
                        setModalOpen(true);
                      }}
                    >
                      <Pencil className="mr-1 h-3 w-3" /> Edit
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => deleteMutation.mutate(b.id)}
                    >
                      <Trash2 className="mr-1 h-3 w-3" /> Delete
                    </Button>
                    <Button
                      variant="link"
                      size="sm"
                      onClick={() => {
                        setCategoryDrill({ categoryId: b.category, label: b.category });
                        scrollTo('transactions');
                      }}
                    >
                      View
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <BudgetModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        editing={editing}
        categories={categories.data ?? []}
        onSaved={() => {
          setModalOpen(false);
          invalidate();
        }}
      />
    </div>
  );
}
