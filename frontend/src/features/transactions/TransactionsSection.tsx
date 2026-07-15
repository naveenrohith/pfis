import { useMemo, useState } from 'react';
import {
  Search,
  Download,
  FileText,
  X,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
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

export function TransactionsSection({ embedded = false }: { embedded?: boolean }) {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const transactions = useTransactions();
  const { categoryDrill, setCategoryDrill, explorerSearch, setExplorerSearch, focusReview } =
    useDashboardUi();
  const currency = user?.currency ?? 'INR';

  const [type, setType] = useState<TypeFilter>('all');
  const [sorting, setSorting] = useState<SortingState>([{ id: 'transaction_date', desc: true }]);

  const filtered = useMemo(() => {
    let list = transactions.data ?? [];
    if (categoryDrill) {
      list = list.filter(
        (t) =>
          t.category_name === categoryDrill.label || t.category_id === categoryDrill.categoryId,
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

  const columns = useMemo<ColumnDef<Transaction>[]>(
    () => [
      {
        accessorKey: 'merchant_normalized',
        header: 'Merchant',
        cell: ({ row }) => (
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent text-xs font-bold text-accent-foreground">
              {initials(row.original.merchant_normalized || row.original.merchant_raw || '?')}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">
                {row.original.merchant_normalized || row.original.merchant_raw || 'Unknown'}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {row.original.category_name || 'Uncategorized'}
              </p>
            </div>
          </div>
        ),
      },
      { accessorKey: 'transaction_date', header: 'Date' },
      {
        accessorKey: 'payment_method',
        header: 'Method',
        cell: ({ getValue }) => (
          <span className="capitalize text-muted-foreground">
            {String(getValue()).replace('_', ' ')}
          </span>
        ),
      },
      {
        accessorKey: 'amount',
        header: 'Amount',
        cell: ({ row }) => {
          const amount = formatSignedAmount(
            row.original.amount,
            row.original.transaction_type,
            currency,
          );
          return <span className={`font-bold ${TONE_CLASS[amount.tone]}`}>{amount.text}</span>;
        },
      },
      {
        id: 'status',
        header: 'Status',
        cell: ({ row }) =>
          row.original.is_transfer ? (
            <Badge variant="info">Transfer</Badge>
          ) : row.original.reviewed_flag ? (
            <Badge variant="success">Ready</Badge>
          ) : (
            <Badge variant="warning">Review</Badge>
          ),
        enableSorting: false,
      },
    ],
    [currency],
  );
  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 12 } },
  });

  const hasFilters = !!categoryDrill || type !== 'all' || explorerSearch.trim() !== '';
  const exportActions = user ? (
    <div className="flex gap-2">
      <a href={api.csvUrl(user.id, month, year)}>
        <Button variant="outline" size="sm">
          <Download className="h-3.5 w-3.5" /> CSV
        </Button>
      </a>
      <a href={api.reportUrl(user.id, month, year)} target="_blank" rel="noreferrer">
        <Button variant="outline" size="sm">
          <FileText className="h-3.5 w-3.5" /> Report
        </Button>
      </a>
    </div>
  ) : null;

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Transactions"
          title="Explorer"
          description={`${filtered.length} transaction(s)`}
          action={exportActions}
        />
      ) : null}

      <Card>
        <CardContent className="p-4 sm:p-5">
          {embedded ? (
            <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
              <div>
                <p className="text-xs font-bold text-muted-foreground">Ledger</p>
                <h2 className="mt-1 text-xl font-extrabold tracking-[-0.03em]">
                  {filtered.length} transaction{filtered.length === 1 ? '' : 's'}
                </h2>
              </div>
              {exportActions}
            </div>
          ) : null}
          <div
            data-testid="transaction-toolbar"
            className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center"
          >
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
                <FilterChip
                  label={`Category: ${categoryDrill.label}`}
                  onClear={() => setCategoryDrill(null)}
                />
              )}
              {type !== 'all' && (
                <FilterChip label={`Type: ${type}`} onClear={() => setType('all')} />
              )}
              {explorerSearch.trim() && (
                <FilterChip
                  label={`Search: ${explorerSearch}`}
                  onClear={() => setExplorerSearch('')}
                />
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
            <>
              <div className="grid gap-4 lg:hidden">
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
              <div className="hidden overflow-x-auto lg:block">
                <table className="w-full min-w-[720px] border-collapse text-left text-sm">
                  <thead>
                    {table.getHeaderGroups().map((headerGroup) => (
                      <tr key={headerGroup.id}>
                        {headerGroup.headers.map((header) => (
                          <th
                            key={header.id}
                            className="px-3 py-2 text-xs font-bold uppercase tracking-wide text-muted-foreground"
                          >
                            {header.isPlaceholder ? null : header.column.getCanSort() ? (
                              <button
                                type="button"
                                className="inline-flex items-center gap-1 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                onClick={header.column.getToggleSortingHandler()}
                              >
                                {flexRender(header.column.columnDef.header, header.getContext())}
                                <ArrowUpDown className="h-3 w-3" />
                              </button>
                            ) : (
                              flexRender(header.column.columnDef.header, header.getContext())
                            )}
                          </th>
                        ))}
                      </tr>
                    ))}
                  </thead>
                  <tbody>
                    {table.getRowModel().rows.map((row) => (
                      <tr
                        key={row.id}
                        tabIndex={0}
                        aria-label={`Review transaction ${row.original.merchant_normalized || row.original.merchant_raw}`}
                        onClick={() => focusReview(row.original.id)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            focusReview(row.original.id);
                          }
                        }}
                        className="cursor-pointer border-b border-border/70 transition-colors last:border-b-0 hover:bg-muted/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="px-3 py-3">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="mt-3 flex items-center justify-between text-sm text-muted-foreground">
                  <span>
                    Page {table.getState().pagination.pageIndex + 1} of{' '}
                    {Math.max(table.getPageCount(), 1)}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => table.previousPage()}
                      disabled={!table.getCanPreviousPage()}
                      aria-label="Previous transaction page"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => table.nextPage()}
                      disabled={!table.getCanNextPage()}
                      aria-label="Next transaction page"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </div>
            </>
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
