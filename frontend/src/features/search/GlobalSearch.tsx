import { useEffect, useMemo, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { useTransactions } from '@/features/workspace/queries';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { useAuth } from '@/features/auth/AuthContext';
import { formatCurrency } from '@/lib/format';
import type { Transaction } from '@/lib/types';

const MAX_RESULTS = 8;

/** Global search across merchants, categories, references, account last4, and text. */
export function GlobalSearch() {
  const { user } = useAuth();
  const transactions = useTransactions();
  const { focusReview, setCategoryDrill, scrollTo } = useDashboardUi();
  const currency = user?.currency ?? 'INR';

  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const all = transactions.data ?? [];
    return all
      .filter((t) => matches(t, q))
      .slice(0, MAX_RESULTS);
  }, [query, transactions.data]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  function selectTransaction(t: Transaction) {
    setOpen(false);
    setQuery('');
    if (!t.reviewed_flag) {
      focusReview(t.id);
    } else if (t.category_name) {
      setCategoryDrill({ categoryId: t.category_name, label: t.category_name });
      scrollTo('transactions');
    } else {
      scrollTo('transactions');
    }
  }

  return (
    <div ref={containerRef} className="relative w-full max-w-xs">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        className="h-9 pl-9 pr-8"
        placeholder="Search transactions…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        aria-label="Search transactions"
      />
      {query && (
        <button
          onClick={() => {
            setQuery('');
            setOpen(false);
          }}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          aria-label="Clear search"
        >
          <X className="h-4 w-4" />
        </button>
      )}

      {open && query.trim() && (
        <div className="absolute z-50 mt-1 w-[min(22rem,90vw)] overflow-hidden rounded-lg border border-border bg-card shadow-lg">
          {results.length === 0 ? (
            <p className="px-3 py-4 text-center text-sm text-muted-foreground">No matches found</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto py-1">
              {results.map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => selectTransaction(t)}
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-muted"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">
                        {t.merchant_normalized || t.merchant_raw || 'Unknown'}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {t.category_name || 'Uncategorized'} · {t.transaction_date}
                        {t.account_last4 ? ` · ••${t.account_last4}` : ''}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="text-sm font-semibold">
                        {formatCurrency(t.amount, currency)}
                      </span>
                      {!t.reviewed_flag && <Badge variant="warning">review</Badge>}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function matches(t: Transaction, q: string): boolean {
  return [
    t.merchant_normalized,
    t.merchant_raw,
    t.category_name,
    t.reference_id,
    t.account_last4,
    t.transaction_type,
  ]
    .filter(Boolean)
    .some((v) => String(v).toLowerCase().includes(q));
}
