import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Input, Label, Select } from '@/components/ui/Input';
import { EmptyState } from '@/components/ui/Skeleton';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { api } from '@/lib/api';
import { formatCurrency, formatTime } from '@/lib/format';
import type {
  Category,
  FinancialAccount,
  PaymentMethod,
  Transaction,
  TransactionType,
} from '@/lib/types';

interface ReviewDetailProps {
  transaction: Transaction | null;
  categories: Category[];
  accounts: FinancialAccount[];
  currency: string;
  onSaved: () => void;
  onNext: () => void;
}

export function ReviewDetail({
  transaction,
  categories,
  accounts,
  currency,
  onSaved,
  onNext,
}: ReviewDetailProps) {
  const { user } = useAuth();
  const { scrollTo } = useDashboardUi();
  const { notify } = useToast();
  const [merchant, setMerchant] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [amount, setAmount] = useState('');
  const [type, setType] = useState<TransactionType>('debit');
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>('other');
  const [note, setNote] = useState('');
  const [tags, setTags] = useState('');
  const [cashAccountId, setCashAccountId] = useState('');
  const [splitDrafts, setSplitDrafts] = useState([
    { label: '', amount: '', categoryId: '' },
    { label: '', amount: '', categoryId: '' },
  ]);
  const splitQuery = useQuery({
    queryKey: ['transactionSplits', user?.id ?? '', transaction?.id ?? ''],
    queryFn: () => api.transactionSplits(user!.id, transaction!.id),
    enabled: Boolean(user && transaction),
  });

  useEffect(() => {
    if (transaction) {
      setMerchant(transaction.merchant_normalized || transaction.merchant_raw || '');
      setCategoryId(transaction.category_id ?? '');
      setAmount(String(transaction.amount));
      setType(transaction.transaction_type);
      setPaymentMethod(transaction.payment_method ?? 'other');
      setNote(transaction.note ?? '');
      setTags((transaction.tags ?? []).join(', '));
      setCashAccountId('');
      setSplitDrafts([
        { label: '', amount: '', categoryId: '' },
        { label: '', amount: '', categoryId: '' },
      ]);
    }
  }, [transaction]);

  useEffect(() => {
    if (splitQuery.data?.length) {
      setSplitDrafts(
        splitQuery.data.map((split) => ({
          label: split.label,
          amount: String(split.amount),
          categoryId: split.category_id ?? '',
        })),
      );
    } else if (splitQuery.isSuccess) {
      setSplitDrafts([
        { label: '', amount: '', categoryId: '' },
        { label: '', amount: '', categoryId: '' },
      ]);
    }
  }, [splitQuery.data, splitQuery.isSuccess, transaction?.id]);

  const save = useMutation({
    mutationFn: async (markNext: boolean) => {
      if (!transaction) return;
      const value = Number(amount);
      if (!merchant.trim()) throw new Error('Merchant is required.');
      if (!Number.isFinite(value) || value <= 0) throw new Error('Amount must be positive.');
      await api.updateTransaction(transaction.id, {
        merchant_normalized: merchant.trim(),
        category_id: categoryId || null,
        amount: value,
        transaction_type: type,
        payment_method: paymentMethod,
        reviewed_flag: true,
        note: note.trim() || null,
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      return markNext;
    },
    onSuccess: (markNext) => {
      notify('Transaction saved', 'success');
      onSaved();
      if (markNext) onNext();
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });

  const saveSplits = useMutation({
    mutationFn: async () => {
      if (!user || !transaction) throw new Error('Choose a transaction first.');
      return api.replaceTransactionSplits(
        user.id,
        transaction.id,
        splitDrafts.map((split) => ({
          label: split.label.trim(),
          amount: Number(split.amount),
          category_id: split.categoryId || null,
        })),
      );
    },
    onSuccess: async () => {
      notify('Split allocations saved', 'success');
      await splitQuery.refetch();
      onSaved();
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });
  const linkAtmCash = useMutation({
    mutationFn: async () => {
      if (!user || !transaction) throw new Error('Choose a transaction first.');
      if (!cashAccountId) throw new Error('Choose a cash account.');
      return api.linkAtmWithdrawalToCash(user.id, transaction.id, cashAccountId);
    },
    onSuccess: () => {
      notify('ATM withdrawal moved into the cash pocket', 'success');
      onSaved();
    },
    onError: (err) => notify((err as Error).message, 'error'),
  });

  if (!transaction) {
    return (
      <Card className="lg:sticky lg:top-32 lg:self-start">
        <CardContent className="p-4 sm:p-5">
          <EmptyState
            title="Nothing selected"
            description="Pick a transaction from the queue to review its details."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="lg:sticky lg:top-32 lg:self-start">
      <CardContent className="grid gap-4 p-4 sm:p-5">
        <div className="flex flex-wrap gap-1.5 rounded-lg border border-border bg-muted/30 p-2">
          <Badge variant="info">Confidence {Math.round(transaction.confidence_score * 100)}%</Badge>
          <Badge variant="outline">{transaction.transaction_date}</Badge>
          <Badge variant="outline">{paymentMethodLabel(transaction.payment_method)}</Badge>
          <Badge variant="outline">{formatCurrency(transaction.amount, currency)}</Badge>
          <Badge variant="outline">
            {transaction.source_received_at
              ? `Received ${formatTime(transaction.source_received_at)}`
              : 'Time unavailable'}
          </Badge>
          {transaction.account_last4 && (
            <Badge variant="outline">••{transaction.account_last4}</Badge>
          )}
          {transaction.reference_id && (
            <Badge variant="outline">Ref {transaction.reference_id}</Badge>
          )}
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="rd-merchant">Merchant</Label>
          <Input id="rd-merchant" value={merchant} onChange={(e) => setMerchant(e.target.value)} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rd-note">Note</Label>
          <Input
            id="rd-note"
            value={note}
            maxLength={1000}
            autoComplete="off"
            placeholder="Add context…"
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rd-tags">Tags</Label>
          <Input
            id="rd-tags"
            value={tags}
            autoComplete="off"
            placeholder="Work, reimbursable…"
            onChange={(event) => setTags(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">Separate up to 20 tags with commas.</p>
        </div>

        {transaction.payment_rail === 'atm' && !transaction.is_transfer ? (
          <section
            className="bg-warning/8 grid gap-3 rounded-lg border border-warning/35 p-4"
            aria-labelledby="atm-cash-title"
          >
            <div>
              <h3 id="atm-cash-title" className="text-sm font-extrabold">
                Finish the ATM cash movement
              </h3>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                A withdrawal is not spending. Link it to a cash pocket so PFIS records one
                bank-to-cash transfer; later cash purchases reduce that pocket.
              </p>
            </div>
            {accounts.find((account) => account.id === transaction.financial_account_id)
              ?.account_type !== 'bank' ? (
              <div className="grid gap-2">
                <p className="text-xs font-bold text-warning">
                  First identify the funding instrument as a bank account.
                </p>
                <Button variant="outline" onClick={() => scrollTo('networth')}>
                  Identify account in Verified position
                </Button>
              </div>
            ) : accounts.some((account) => account.account_type === 'cash' && account.is_active) ? (
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                <div className="grid gap-1.5">
                  <Label htmlFor="rd-cash-account">Cash pocket</Label>
                  <Select
                    id="rd-cash-account"
                    value={cashAccountId}
                    onChange={(event) => setCashAccountId(event.target.value)}
                  >
                    <option value="">Choose cash account</option>
                    {accounts
                      .filter((account) => account.account_type === 'cash' && account.is_active)
                      .map((account) => (
                        <option key={account.id} value={account.id}>
                          {account.institution_name} · {account.masked_number}
                        </option>
                      ))}
                  </Select>
                </div>
                <Button
                  disabled={!cashAccountId || linkAtmCash.isPending}
                  onClick={() => linkAtmCash.mutate()}
                >
                  {linkAtmCash.isPending ? 'Linking…' : 'Move into cash pocket'}
                </Button>
              </div>
            ) : (
              <div className="grid gap-2">
                <p className="text-xs font-bold text-warning">
                  Add a cash account before completing this movement.
                </p>
                <Button variant="outline" onClick={() => scrollTo('networth')}>
                  Add cash account in Verified position
                </Button>
              </div>
            )}
          </section>
        ) : null}

        {!transaction.is_transfer ? (
          <section
            className="grid gap-3 rounded-lg border border-border p-3"
            aria-labelledby="split-title"
          >
            <div>
              <h3 id="split-title" className="text-sm font-extrabold">
                Split allocation
              </h3>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Allocations must equal {formatCurrency(transaction.amount, currency)}. They explain
                one ledger event and never create extra spending.
              </p>
            </div>
            {splitDrafts.map((split, index) => (
              <div key={index} className="grid gap-2 rounded-lg bg-muted/35 p-3 sm:grid-cols-3">
                <div className="grid gap-1">
                  <Label htmlFor={`split-label-${index}`}>Label {index + 1}</Label>
                  <Input
                    id={`split-label-${index}`}
                    value={split.label}
                    autoComplete="off"
                    onChange={(event) =>
                      setSplitDrafts((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, label: event.target.value } : item,
                        ),
                      )
                    }
                  />
                </div>
                <div className="grid gap-1">
                  <Label htmlFor={`split-amount-${index}`}>Amount</Label>
                  <Input
                    id={`split-amount-${index}`}
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={split.amount}
                    onChange={(event) =>
                      setSplitDrafts((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, amount: event.target.value } : item,
                        ),
                      )
                    }
                  />
                </div>
                <div className="grid gap-1">
                  <Label htmlFor={`split-category-${index}`}>Category</Label>
                  <Select
                    id={`split-category-${index}`}
                    value={split.categoryId}
                    onChange={(event) =>
                      setSplitDrafts((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, categoryId: event.target.value } : item,
                        ),
                      )
                    }
                  >
                    <option value="">Uncategorized</option>
                    {categories.map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.name}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>
            ))}
            <div className="flex flex-wrap justify-between gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() =>
                  setSplitDrafts((current) => [
                    ...current,
                    { label: '', amount: '', categoryId: '' },
                  ])
                }
                disabled={splitDrafts.length >= 20}
              >
                Add allocation
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => saveSplits.mutate()}
                disabled={
                  saveSplits.isPending ||
                  splitDrafts.some(
                    (split) =>
                      !split.label.trim() ||
                      !Number.isFinite(Number(split.amount)) ||
                      Number(split.amount) <= 0,
                  )
                }
              >
                {saveSplits.isPending ? 'Saving…' : 'Save splits'}
              </Button>
            </div>
          </section>
        ) : null}
        <div className="grid gap-1.5">
          <Label htmlFor="rd-category">Category</Label>
          <Select
            id="rd-category"
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
          >
            <option value="">Uncategorized</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} {c.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="rd-amount">Amount</Label>
            <Input
              id="rd-amount"
              type="number"
              min={0}
              step="any"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="rd-type">Type</Label>
            <Select
              id="rd-type"
              value={type}
              onChange={(e) => setType(e.target.value as TransactionType)}
            >
              <option value="debit">Debit</option>
              <option value="credit">Credit</option>
              <option value="refund">Refund</option>
            </Select>
          </div>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rd-payment-method">Payment method</Label>
          <Select
            id="rd-payment-method"
            value={paymentMethod}
            onChange={(e) => setPaymentMethod(e.target.value as PaymentMethod)}
          >
            <option value="upi">UPI</option>
            <option value="debit_card">Debit card</option>
            <option value="credit_card">Credit card</option>
            <option value="emi">EMI</option>
            <option value="pay_later">Pay later</option>
            <option value="wallet">Wallet</option>
            <option value="bank_transfer">Bank transfer</option>
            <option value="other">Other</option>
          </Select>
        </div>

        {/* Quick category chips */}
        <div className="flex flex-wrap gap-1.5">
          {categories.slice(0, 8).map((c) => (
            <button
              key={c.id}
              onClick={() => setCategoryId(c.id)}
              className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition-colors ${
                categoryId === c.id
                  ? 'border-primary bg-accent text-accent-foreground'
                  : 'border-border hover:bg-muted'
              }`}
            >
              {c.icon} {c.name}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3">
          <Button variant="secondary" onClick={() => save.mutate(false)} disabled={save.isPending}>
            Save
          </Button>
          <Button onClick={() => save.mutate(true)} disabled={save.isPending}>
            Save &amp; next
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function paymentMethodLabel(method?: PaymentMethod): string {
  const labels: Record<PaymentMethod, string> = {
    upi: 'UPI',
    debit_card: 'Debit card',
    credit_card: 'Credit card',
    emi: 'EMI',
    pay_later: 'Pay later',
    wallet: 'Wallet',
    bank_transfer: 'Bank transfer',
    other: 'Other',
  };
  return labels[method ?? 'other'];
}
