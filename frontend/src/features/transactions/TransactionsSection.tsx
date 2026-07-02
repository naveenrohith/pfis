import { useMemo, useState } from 'react';
import { Search, Download, FileText, X } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Input } from '@/components/ui/Input';
import { Segmented } from '@/components/ui/Segmented';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useTransactions } from '@/features/workspace/queries';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { useAuth } from '@/features/auth/AuthContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { api } from '@/lib/api';
import { formatSignedAmount, initials, relativeDateGroup } from '@/lib/format';
import type { Transaction } from '@/lib/types';

type TypeFilter = 'all' | 'review' | 'debit' | 'credit' | 'refund';

const GROUP_ORDER = ['Today', 'Yesterday', 'This week', 'Earlier'] as const;

const TONE_CLASS: Record<string, string> = {
  positive: 'text-success',
  negative: 'text-danger',
  neutral: 'text-warning',
};

export function TransactionsSection() {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const transactions = useTransactions();
  const { categoryDrill, setCategoryDrill, explorerSearch, setExplorerSearch, focusReview } =
    useDashboardUi();
  const currency = user?.currency ?? 'INR';

  const [type, setType] = useState<TypeFilter>('all');

  const filtered = useMemo(() => {
    let list = transactions.data ?? [];
    if (categoryDrill) {
      list = list.filter(
        (t) => t.category_name === categoryDrill.label || t.category_id === categoryDrill.categoryId,
      );
    }
    if (type === 'review') list = list.filter((t) => !t.reviewed_flag);
    else if (type !== 'all') list = list.filter((t) => t.transaction_type === type);

    const q = explorerSearch.trim().toLowerCase();
    if (q) {
      list = list.filter((t) =>
        [t.merchant_normalized, t.merchant_raw, t.account_last4, t.reference_id]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(q)),
      );
    }
    return list;
  }, [transactions.data, categoryDrill, type, explorerSearch]);

  const groups = useMemo(() => {
    const map = new Map<string, Transaction[]>();
    for (const t of filtered) {
      const key = relativeDateGroup(t.transaction_date);
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(t);
    }
    return GROUP_ORDER.filter((g) => map.has(g)).map((g) => ({ group: g, items: map.get(g)! }));
  }, [filtered]);

  const hasFilters = !!categoryDrill || type !== 'all' || explorerSearch.trim() !== '';

  return (
    <div>
      <SectionTitle
        eyebrow="Transactions"
        title="Explorer"
        description={`${filtered.length} transaction(s)`}
        action={
          <div className="flex gap-2">
            {user && (
              <>
                <a href={api.csvUrl(user.id, month, year)}>
                  <Button variant="outline" size="sm">
                    <Download className="mr-1 h-3.5 w-3.5" /> CSV
                  </Button>
                </a>
                <a href={api.reportUrl(user.id, month, year)} target="_blank" rel="noreferrer">
                  <Button variant="outline" size="sm">
                    <FileText className="mr-1 h-3.5 w-3.5" /> Report
                  </Button>
                </a>
              </>
            )}
          </div>
        }
      />

      <Card>
        <CardContent className="p-4 sm:p-5">
          <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center">
            <Segmented
              aria-label="Transaction type filters"
              value={type}
              onChange={setType}
              options={[
                { value: 'all', label: 'All' },
                { value: 'review', label: 'Needs review' },
                { value: 'debit', label: 'Debits' },
                { value: 'credit', label: 'Credits' },
                { value: 'refund', label: 'Refunds' },
              ]}
            />
            <div className="relative min-w-[12rem] flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Search transactions..."
                value={explorerSearch}
                onChange={(e) => setExplorerSearch(e.target.value)}
              />
            </div>
          </div>

          {hasFilters && (
            <div className="mb-3 flex flex-wrap gap-2">
              {categoryDrill && (
                <FilterChip label={`Category: ${categoryDrill.label}`} onClear={() => setCategoryDrill(null)} />
              )}
              {type !== 'all' && <FilterChip label={`Type: ${type}`} onClear={() => setType('all')} />}
              {explorerSearch.trim() && (
                <FilterChip label={`Search: ${explorerSearch}`} onClear={() => setExplorerSearch('')} />
              )}
            </div>
          )}

          {transactions.isLoading ? (
            <div className="grid gap-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-14" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon="🔎"
              title="No transactions match"
              description="Try clearing filters or syncing your inbox."
            />
          ) : (
            <div className="grid gap-4">
              {groups.map(({ group, items }) => (
                <div key={group}>
                  <p className="mb-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">
                    {group}
                  </p>
                  <div className="grid gap-1.5">
                    {items.map((t) => {
                      const amount = formatSignedAmount(t.amount, t.transaction_type, currency);
                      return (
                        <button
                          key={t.id}
                          onClick={() => focusReview(t.id)}
                          className="dashboard-row grid w-full grid-cols-[auto_minmax(0,1fr)] items-center gap-3 text-left sm:grid-cols-[auto_minmax(0,1fr)_auto_auto]"
                        >
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent text-xs font-bold text-accent-foreground">
                            {initials(t.merchant_normalized || t.merchant_raw || '?')}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-semibold">
                              {t.merchant_normalized || t.merchant_raw || 'Unknown'}
                            </p>
                            <p className="truncate text-xs text-muted-foreground">
                              {t.category_name || 'Uncategorized'} / {t.transaction_date}
                            </p>
                          </div>
                          <span className={`text-sm font-bold ${TONE_CLASS[amount.tone]}`}>
                            {amount.text}
                          </span>
                          {!t.reviewed_flag && (
                            <Badge variant="warning" className="hidden sm:inline-flex">
                              Review
                            </Badge>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted px-2.5 py-1 text-xs">
      {label}
      <button onClick={onClear} aria-label={`Clear ${label}`}>
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}
