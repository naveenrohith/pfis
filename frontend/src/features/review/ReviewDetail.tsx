import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Input, Label, Select } from '@/components/ui/Input';
import { EmptyState } from '@/components/ui/Skeleton';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';
import type { Category, Transaction, TransactionType } from '@/lib/types';

interface ReviewDetailProps {
  transaction: Transaction | null;
  categories: Category[];
  currency: string;
  onSaved: () => void;
  onNext: () => void;
}

export function ReviewDetail({ transaction, categories, onSaved, onNext }: ReviewDetailProps) {
  const { notify } = useToast();
  const [merchant, setMerchant] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [amount, setAmount] = useState('');
  const [type, setType] = useState<TransactionType>('debit');

  useEffect(() => {
    if (transaction) {
      setMerchant(transaction.merchant_normalized || transaction.merchant_raw || '');
      setCategoryId(transaction.category_id ?? '');
      setAmount(String(transaction.amount));
      setType(transaction.transaction_type);
    }
  }, [transaction]);

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
        reviewed_flag: true,
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

  if (!transaction) {
    return (
      <Card>
        <CardContent className="p-5">
          <EmptyState
            title="Nothing selected"
            description="Pick a transaction from the queue to review its details."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="grid gap-3 p-5">
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="info">Confidence {Math.round(transaction.confidence_score * 100)}%</Badge>
          <Badge variant="outline">{transaction.transaction_date}</Badge>
          {transaction.account_last4 && <Badge variant="outline">••{transaction.account_last4}</Badge>}
          {transaction.reference_id && (
            <Badge variant="outline">Ref {transaction.reference_id}</Badge>
          )}
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor="rd-merchant">Merchant</Label>
          <Input id="rd-merchant" value={merchant} onChange={(e) => setMerchant(e.target.value)} />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="rd-category">Category</Label>
          <Select id="rd-category" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
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

        {/* Quick category chips */}
        <div className="flex flex-wrap gap-1.5">
          {categories.slice(0, 8).map((c) => (
            <button
              key={c.id}
              onClick={() => setCategoryId(c.id)}
              className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                categoryId === c.id
                  ? 'border-primary bg-accent text-accent-foreground'
                  : 'border-border hover:bg-muted'
              }`}
            >
              {c.icon} {c.name}
            </button>
          ))}
        </div>

        <div className="flex justify-end gap-2">
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
