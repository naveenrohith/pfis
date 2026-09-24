import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Search, CheckCircle2, FileCheck2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Input, Select } from '@/components/ui/Input';
import { Segmented } from '@/components/ui/Segmented';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import {
  queryKeys,
  useAccounts,
  useCategories,
  useLinkTransferMatch,
  useStatementReviewItems,
  useTransferMatchCandidates,
  useTransactions,
} from '@/features/workspace/queries';
import { useAuth } from '@/features/auth/AuthContext';
import { useToast } from '@/components/ui/Toast';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { api } from '@/lib/api';
import { formatCurrency, formatDate, formatTime } from '@/lib/format';
import type {
  StatementReviewItem,
  Transaction,
  TransactionType,
  TransferMatchCandidate,
} from '@/lib/types';
import { ReviewDetail } from './ReviewDetail';

const THRESHOLD = 0.85;

type ReviewFilter = 'pending' | 'all';

function confidenceVariant(score: number) {
  if (score >= THRESHOLD) return 'success' as const;
  if (score >= 0.65) return 'warning' as const;
  return 'danger' as const;
}

export function ReviewSection({ embedded = false }: { embedded?: boolean }) {
  const { user } = useAuth();
  const transactions = useTransactions();
  const categories = useCategories();
  const statementReview = useStatementReviewItems();
  const transferCandidates = useTransferMatchCandidates();
  const accounts = useAccounts();
  const { notify } = useToast();
  const { focusedReviewId, focusReview, scrollTo } = useDashboardUi();
  const queryClient = useQueryClient();
  const currency = user?.currency ?? 'INR';

  const [filter, setFilter] = useState<ReviewFilter>('pending');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkCategory, setBulkCategory] = useState('');
  const [bulkType, setBulkType] = useState('');
  const detailHeadingRef = useRef<HTMLHeadingElement>(null);

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['transactions'] }),
      queryClient.invalidateQueries({ queryKey: ['cardOverview'] }),
      queryClient.invalidateQueries({ queryKey: ['accountPosition'] }),
      queryClient.invalidateQueries({ queryKey: ['balanceForecast'] }),
      queryClient.invalidateQueries({ queryKey: ['cardDueRunway'] }),
    ]);
  };

  const items = useMemo(() => {
    const all = transactions.data ?? [];
    const base = filter === 'pending' ? all.filter((t) => !t.reviewed_flag) : all;
    const q = search.trim().toLowerCase();
    const filtered = !q
      ? base
      : base.filter((t) =>
          [t.merchant_normalized, t.merchant_raw, t.account_last4, t.reference_id]
            .filter(Boolean)
            .some((v) => String(v).toLowerCase().includes(q)),
        );
    // Low-confidence, unreviewed transactions are the primary workflow — surface them first.
    return [...filtered].sort((a, b) => {
      if (a.reviewed_flag !== b.reviewed_flag) return a.reviewed_flag ? 1 : -1;
      return a.confidence_score - b.confidence_score;
    });
  }, [transactions.data, filter, search]);

  const focused = useMemo(
    () => transactions.data?.find((t) => t.id === focusedReviewId) ?? null,
    [transactions.data, focusedReviewId],
  );
  const focusedTransactionId = focused?.id;

  const transactionPendingCount = (transactions.data ?? []).filter((t) => !t.reviewed_flag).length;
  const supplementalPendingCount =
    (statementReview.data?.length ?? 0) + (transferCandidates.data?.length ?? 0);
  const pendingCount = transactionPendingCount + supplementalPendingCount;
  const supplementalQueuesLoading = statementReview.isLoading || transferCandidates.isLoading;

  useEffect(() => {
    if (!focusedReviewId || focusedTransactionId !== focusedReviewId) return;

    const heading = detailHeadingRef.current;
    if (!heading) return;

    heading.focus({ preventScroll: true });
    heading.scrollIntoView({
      behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      block: 'start',
    });
  }, [focusedReviewId, focusedTransactionId]);

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
      {!embedded ? (
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
      ) : null}

      {embedded ? (
        <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <p className="text-xs font-bold text-muted-foreground">Focused review</p>
            <h2 className="mt-1 text-2xl font-extrabold tracking-[-0.035em]">
              {transactions.isLoading || supplementalQueuesLoading
                ? 'Checking review queues'
                : transactionPendingCount > 0
                  ? 'Resolve uncertain activity'
                  : supplementalPendingCount > 0
                    ? 'Other review items need attention'
                    : 'Everything is ready'}
            </h2>
          </div>
          <Badge
            variant={
              transactions.isLoading || supplementalQueuesLoading
                ? 'info'
                : pendingCount > 0
                  ? 'warning'
                  : 'success'
            }
          >
            {transactions.isLoading || supplementalQueuesLoading
              ? 'Checking…'
              : pendingCount > 0
                ? `${pendingCount} pending`
                : 'Queue clear'}
          </Badge>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Queue */}
        <Card className={items.length === 0 ? 'lg:col-span-3' : 'lg:col-span-2'}>
          <CardContent className="p-4 sm:p-5">
            <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
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
                  placeholder="Search merchant, account, reference..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>

            {/* Bulk toolbar */}
            {selected.size > 0 && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-primary/25 bg-primary/5 p-2">
                <span className="text-sm font-semibold">{selected.size} selected</span>
                <Select
                  className="h-11 w-auto"
                  value={bulkCategory}
                  onChange={(e) => setBulkCategory(e.target.value)}
                >
                  <option value="">Category...</option>
                  {categories.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
                <Select
                  className="h-11 w-auto"
                  value={bulkType}
                  onChange={(e) => setBulkType(e.target.value)}
                >
                  <option value="">Type...</option>
                  <option value="debit">Debit</option>
                  <option value="credit">Credit</option>
                  <option value="refund">Refund</option>
                </Select>
                <Button
                  size="sm"
                  onClick={() => bulkMutation.mutate()}
                  disabled={bulkMutation.isPending}
                >
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
            ) : items.length === 0 && supplementalQueuesLoading ? (
              <p
                role="status"
                className="rounded-lg bg-muted/30 px-4 py-6 text-sm text-muted-foreground"
              >
                Checking for statement and transfer items…
              </p>
            ) : items.length === 0 ? (
              <EmptyState
                icon={<CheckCircle2 />}
                title={
                  supplementalPendingCount > 0 ? 'No transactions need review' : 'Everything is ready'
                }
                description={
                  supplementalPendingCount > 0
                    ? 'Other evidence still needs attention below.'
                    : 'PFIS found no uncertain transactions in this period. You can return here whenever a new item needs confirmation.'
                }
                action={
                  supplementalPendingCount === 0 ? (
                    <Button variant="outline" onClick={() => scrollTo('transactions')}>
                      Browse the ledger
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <div className="max-h-[34rem] divide-y divide-border/70 overflow-y-auto rounded-xl bg-secondary/35 px-2">
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
        {items.length > 0 ? (
          <div className="min-w-0">
            <h2
              ref={detailHeadingRef}
              id="review-detail-heading"
              tabIndex={-1}
              className="focus-ring mb-3 scroll-mt-[10.5rem] rounded text-lg font-extrabold lg:scroll-mt-[11.5rem]"
            >
              Transaction detail
            </h2>
            <ReviewDetail
              transaction={focused}
              categories={categories.data ?? []}
              accounts={accounts.data ?? []}
              currency={currency}
              onSaved={() => invalidate()}
              onNext={nextPending}
            />
          </div>
        ) : null}
      </div>

      <StatementEvidenceQueue
        items={statementReview.data ?? []}
        isLoading={statementReview.isLoading}
        bankAccounts={(accounts.data ?? []).filter((account) => account.account_type === 'bank')}
      />
      <TransferMatchQueue
        candidates={transferCandidates.data ?? []}
        isLoading={transferCandidates.isLoading}
      />
    </div>
  );
}

function TransferMatchQueue({
  candidates,
  isLoading,
}: {
  candidates: TransferMatchCandidate[];
  isLoading: boolean;
}) {
  const { notify } = useToast();
  const link = useLinkTransferMatch();

  if (isLoading) {
    return <Skeleton className="mb-4 h-32" />;
  }
  if (!candidates.length) return null;

  const visible = candidates.slice(0, 12);
  return (
    <section
      className="mb-4 rounded-xl border border-primary/20 bg-primary/5 p-4 sm:p-5"
      aria-labelledby="transfer-match-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="transfer-match-title" className="font-extrabold">
            Possible paired movements
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
            PFIS found settled bank/card or internal-transfer legs with matching amounts and dates.
            Confirm only pairs you recognize; this never moves money externally.
          </p>
        </div>
        <Badge variant="warning">{candidates.length} to review</Badge>
      </div>
      <div className="mt-4 grid gap-2">
        {visible.map((candidate) => (
          <article
            key={candidate.candidate_id}
            className="rounded-lg border border-border/70 bg-background/80 p-3"
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="break-words text-sm font-extrabold">
                  {candidate.debit_account_label} <span aria-hidden="true">→</span>{' '}
                  {candidate.credit_account_label}
                </p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {formatDate(candidate.debit_date)} → {formatDate(candidate.credit_date)} ·{' '}
                  {candidate.kind === 'card_payment' ? 'Card payment' : 'Account transfer'} ·{' '}
                  {Math.round(candidate.confidence * 100)}% evidence
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge variant={candidate.ambiguous ? 'warning' : 'outline'}>
                    {candidate.ambiguous ? 'Ambiguous counterparty' : 'Reviewable match'}
                  </Badge>
                  {candidate.reason_codes.slice(0, 3).map((reason) => (
                    <Badge key={reason} variant="outline">
                      {reason.replaceAll('_', ' ')}
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="money-value text-sm font-extrabold">
                  {formatCurrency(candidate.amount, candidate.currency)}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={link.isPending}
                  onClick={() =>
                    link.mutate(
                      {
                        debitTransactionId: candidate.debit_transaction_id,
                        counterpartyTransactionId: candidate.credit_transaction_id,
                        kind: candidate.kind,
                      },
                      {
                        onSuccess: () => notify('Paired movement linked', 'success'),
                        onError: (error) => notify((error as Error).message, 'error'),
                      },
                    )
                  }
                >
                  Link pair
                </Button>
              </div>
            </div>
          </article>
        ))}
      </div>
      {candidates.length > visible.length ? (
        <p className="mt-3 text-xs text-muted-foreground">
          Showing the 12 highest-confidence candidates. Resolve these before reviewing lower
          confidence pairs.
        </p>
      ) : null}
    </section>
  );
}

function StatementEvidenceQueue({
  items,
  isLoading,
  bankAccounts,
}: {
  items: StatementReviewItem[];
  isLoading: boolean;
  bankAccounts: Array<{
    id: string;
    institution_name: string;
    masked_number: string;
  }>;
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [candidateByLine, setCandidateByLine] = useState<Record<string, string>>({});
  const [bankByLine, setBankByLine] = useState<Record<string, string>>({});
  const resolve = useMutation({
    mutationFn: ({
      item,
      decision,
    }: {
      item: StatementReviewItem;
      decision: 'ignore' | 'match' | 'import' | 'record_card_payment';
    }) =>
      api.reviewStatementLine(user!.id, item.id, {
        decision,
        matched_transaction_id: decision === 'match' ? candidateByLine[item.id] || null : null,
        paying_account_id: decision === 'record_card_payment' ? bankByLine[item.id] || null : null,
      }),
    onSuccess: async (_, variables) => {
      notify('Statement evidence resolved', 'success');
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.statementReview(user!.id),
        }),
        queryClient.invalidateQueries({ queryKey: ['transactions'] }),
        queryClient.invalidateQueries({
          queryKey: ['cardOverview', user!.id, variables.item.financial_account_id],
        }),
        queryClient.invalidateQueries({ queryKey: ['balanceForecast'] }),
        queryClient.invalidateQueries({ queryKey: ['cardDueRunway'] }),
      ]);
    },
    onError: (error) => notify(error.message, 'error'),
  });

  if (isLoading) {
    return <Skeleton className="mb-4 h-32" />;
  }
  if (!items.length) return null;

  return (
    <section
      className="mb-4 rounded-xl border border-warning/25 bg-warning/5 p-4 sm:p-5"
      aria-labelledby="statement-evidence-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="bg-warning/12 grid h-10 w-10 shrink-0 place-items-center rounded-lg text-warning">
            <FileCheck2 className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 id="statement-evidence-title" className="font-extrabold">
              Statement evidence
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              PFIS creates no additional ledger event while this evidence is unresolved.
            </p>
          </div>
        </div>
        <Badge variant="warning">{items.length} to review</Badge>
      </div>
      <div className="mt-4 divide-y divide-border/70">
        {items.map((item) => {
          const canImport = [
            'purchase',
            'refund',
            'cashback',
            'fee',
            'tax',
            'interest',
            'reversal',
          ].includes(item.card_event);
          return (
            <article key={item.id} className="py-5 first:pt-0 last:pb-0">
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
                <div className="min-w-0">
                  <p className="break-words font-extrabold">{item.description}</p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    {item.account_label} · {item.masked_number} ·{' '}
                    {formatDate(item.transaction_date)} · {item.card_event}
                  </p>
                </div>
                <p className="money-value text-base font-extrabold">
                  {formatCurrency(item.amount, user?.currency ?? 'INR')}
                </p>
              </div>
              <div className="mt-3 flex flex-col gap-3">
                {item.candidate_transactions.length ? (
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                    <div className="min-w-0 flex-1">
                      <label
                        htmlFor={`candidate-${item.id}`}
                        className="text-xs font-bold text-muted-foreground"
                      >
                        Existing ledger candidate
                      </label>
                      <Select
                        id={`candidate-${item.id}`}
                        className="mt-1"
                        value={candidateByLine[item.id] ?? ''}
                        onChange={(event) =>
                          setCandidateByLine((current) => ({
                            ...current,
                            [item.id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">Choose a candidate</option>
                        {item.candidate_transactions.map((candidate) => (
                          <option key={candidate.id} value={candidate.id}>
                            {formatDate(candidate.transaction_date)} · {candidate.label} ·{' '}
                            {formatCurrency(candidate.amount, user?.currency ?? 'INR')}
                          </option>
                        ))}
                      </Select>
                    </div>
                    <Button
                      variant="outline"
                      onClick={() => resolve.mutate({ item, decision: 'match' })}
                      disabled={!candidateByLine[item.id] || resolve.isPending}
                    >
                      Match existing
                    </Button>
                  </div>
                ) : null}
                {item.card_event === 'payment' ? (
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                    <div className="min-w-0 flex-1">
                      <label
                        htmlFor={`paying-bank-${item.id}`}
                        className="text-xs font-bold text-muted-foreground"
                      >
                        Paying bank account
                      </label>
                      <Select
                        id={`paying-bank-${item.id}`}
                        className="mt-1"
                        value={bankByLine[item.id] ?? ''}
                        onChange={(event) =>
                          setBankByLine((current) => ({
                            ...current,
                            [item.id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">Choose the bank leg</option>
                        {bankAccounts.map((account) => (
                          <option key={account.id} value={account.id}>
                            {account.institution_name} · {account.masked_number}
                          </option>
                        ))}
                      </Select>
                    </div>
                    <Button
                      variant="outline"
                      onClick={() => resolve.mutate({ item, decision: 'record_card_payment' })}
                      disabled={!bankByLine[item.id] || resolve.isPending}
                    >
                      Record paired transfer
                    </Button>
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  {canImport ? (
                    <Button
                      variant="outline"
                      onClick={() => resolve.mutate({ item, decision: 'import' })}
                      disabled={resolve.isPending}
                    >
                      Import as new
                    </Button>
                  ) : null}
                  <Button
                    variant="ghost"
                    onClick={() => resolve.mutate({ item, decision: 'ignore' })}
                    disabled={resolve.isPending}
                  >
                    Ignore by rule
                  </Button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
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
      className={`flex items-center gap-3 px-2 py-3 transition-colors ${
        active ? 'bg-primary/10' : 'hover:bg-muted/45'
      }`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        aria-label={`Select ${txn.merchant_normalized ?? 'transaction'}`}
        className="h-4 w-4 accent-[hsl(var(--primary))]"
      />
      <button
        onClick={onFocus}
        className="grid min-w-0 flex-1 gap-2 text-left sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
      >
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">
            {txn.merchant_normalized || txn.merchant_raw || 'Unknown'}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {txn.category_name || 'Uncategorized'} / {txn.transaction_date}
            {txn.source_received_at ? ` / ${formatTime(txn.source_received_at)}` : ''}
            {txn.account_last4 ? ` / **${txn.account_last4}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2 sm:justify-end">
          <span className="text-sm font-semibold">{formatCurrency(txn.amount, currency)}</span>
          <Badge variant={confidenceVariant(txn.confidence_score)}>
            {Math.round(txn.confidence_score * 100)}%
          </Badge>
        </div>
      </button>
    </div>
  );
}
