import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Search, CheckCircle2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Input, Select } from '@/components/ui/Input';
import { Segmented } from '@/components/ui/Segmented';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useTransactions, useCategories } from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { useToast } from '@/components/ui/Toast';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { api } from '@/lib/api';
import { formatCurrency } from '@/lib/format';
import type { Transaction, TransactionType } from '@/lib/types';
import { ReviewDetail } from './ReviewDetail';

const THRESHOLD = 0.85;

type ReviewFilter = 'pending' | 'all';

function confidenceVariant(score: number) {
  if (score >= THRESHOLD) return 'success' as const;
  if (score >= 0.65) return 'warning' as const;
  return 'danger' as const;
}

export function ReviewSection() {
  const { user } = useAuth();
  const transactions = useTransactions();
  const categories = useCategories();
  const { notify } = useToast();
  const { focusedReviewId, focusReview } = useDashboardUi();
  const queryClient = useQueryClient();
  const currency = user?.currency ?? 'INR';

  const [filter, setFilter] = useState<ReviewFilter>('pending');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkCategory, setBulkCategory] = useState('');
  const [bulkType, setBulkType] = useState('');

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['transactions'] });

  const items = useMemo(() => {
    const all = transactions.data ?? [];
    const base = filter === 'pending' ? all.filter((t) => !t.reviewed_flag) : all;
    const q = search.trim().toLowerCase();
    if (!q) return base;
    return base.filter((t) =>
      [t.merchant_normalized, t.merchant_raw, t.account_last4, t.reference_id]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q)),
    );
  }, [transactions.data, filter, search]);

  const focused = useMemo(
    () => transactions.data?.find((t) => t.id === focusedReviewId) ?? null,
    [transactions.data, focusedReviewId],
  );

  const pendingCount = (transactions.data ?? []).filter((t) => !t.reviewed_flag).length;

  const bulkMutation = useMutation({
    mutationFn: () => {
      if (!user) throw new Error('No active user.');
      return api.bulkUpdate(user.id, {
        transaction_ids: [...selected],
        category_id: bulkCategory || undefined,
        transaction_type: (bulkType as TransactionType) || undefined,
        reviewed_flag: true,
      });
    },
    onSuccess: (res) => {
      notify(`Updated ${res.updated_count} transaction(s)`, 'success');
      setSelected(new Set());
      setBulkCategory('');
      setBulkType('');
      invalidate();
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  function nextPending() {
    const pending = items.filter((t) => !t.reviewed_flag);
    const idx = pending.findIndex((t) => t.id === focusedReviewId);
    const next = pending[idx + 1] ?? pending.find((t) => t.id !== focusedReviewId);
    focusReview(next?.id ?? null);
  }

  return (
    <div>
      <SectionTitle
        eyebrow="Review"
        title="Review queue"
        description="Confirm or correct transactions that need a second look."
        action={
          <Badge variant={pendingCount > 0 ? 'warning' : 'success'}>
            {pendingCount > 0 ? `${pendingCount} pending` : 'Queue clear'}
          </Badge>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Queue */}
        <Card className="lg:col-span-2">
          <CardContent className="p-5">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Segmented
                aria-label="Review queue filter"
                value={filter}
                onChange={setFilter}
                options={[
                  { value: 'pending', label: 'Pending' },
                  { value: 'all', label: 'All' },
                ]}
              />
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-9"
                  placeholder="Search merchant, account, reference…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>

            {/* Bulk toolbar */}
            {selected.size > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/40 p-2">
                <span className="text-sm font-semibold">{selected.size} selected</span>
                <Select
                  className="h-9 w-auto"
                  value={bulkCategory}
                  onChange={(e) => setBulkCategory(e.target.value)}
                >
                  <option value="">Category…</option>
                  {categories.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
                <Select
                  className="h-9 w-auto"
                  value={bulkType}
                  onChange={(e) => setBulkType(e.target.value)}
                >
                  <option value="">Type…</option>
                  <option value="debit">Debit</option>
                  <option value="credit">Credit</option>
                  <option value="refund">Refund</option>
                </Select>
                <Button size="sm" onClick={() => bulkMutation.mutate()} disabled={bulkMutation.isPending}>
                  Apply &amp; mark reviewed
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                  Clear
                </Button>
              </div>
            )}

            {transactions.isLoading ? (
              <div className="grid gap-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-14" />
                ))}
              </div>
            ) : items.length === 0 ? (
              <EmptyState icon={<CheckCircle2 />} title="Nothing to review" description="This queue is clear." />
            ) : (
              <div className="grid max-h-[32rem] gap-1.5 overflow-y-auto pr-1">
                {items.map((t) => (
                  <ReviewRow
                    key={t.id}
                    txn={t}
                    currency={currency}
                    selected={selected.has(t.id)}
                    active={t.id === focusedReviewId}
                    onToggle={() => toggle(t.id)}
                    onFocus={() => focusReview(t.id)}
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Detail */}
        <ReviewDetail
          transaction={focused}
          categories={categories.data ?? []}
          currency={currency}
          onSaved={() => invalidate()}
          onNext={nextPending}
        />
      </div>
    </div>
  );
}

function ReviewRow({
  txn,
  currency,
  selected,
  active,
  onToggle,
  onFocus,
}: {
  txn: Transaction;
  currency: string;
  selected: boolean;
  active: boolean;
  onToggle: () => void;
  onFocus: () => void;
}) {
  return (
    <div
      className={`flex items-center gap-3 rounded-lg border p-2.5 transition-colors ${
        active ? 'border-primary bg-accent/40' : 'border-border hover:bg-muted/50'
      }`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        aria-label={`Select ${txn.merchant_normalized ?? 'transaction'}`}
        className="h-4 w-4 accent-[hsl(var(--primary))]"
      />
      <button onClick={onFocus} className="flex flex-1 items-center justify-between gap-2 text-left">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {txn.merchant_normalized || txn.merchant_raw || 'Unknown'}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {txn.category_name || 'Uncategorized'} · {txn.transaction_date}
            {txn.account_last4 ? ` · ••${txn.account_last4}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">{formatCurrency(txn.amount, currency)}</span>
          <Badge variant={confidenceVariant(txn.confidence_score)}>
            {Math.round(txn.confidence_score * 100)}%
          </Badge>
        </div>
      </button>
    </div>
  );
}
