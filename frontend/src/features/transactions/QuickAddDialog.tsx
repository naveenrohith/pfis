import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight, RotateCcw } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { Dialog } from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { queryKeys, useAccounts, useCategories } from '@/features/workspace/queries';
import { api } from '@/lib/api';
import type { PaymentMethod, TransactionType } from '@/lib/types';

const schema = z
  .object({
    entryType: z.enum(['expense', 'income', 'refund', 'transfer']),
    amount: z.number().positive('Enter an amount greater than zero'),
    merchant: z.string().trim().max(160),
    transactionDate: z.string().min(1, 'Choose a date'),
    categoryId: z.string(),
    paymentMethod: z.enum([
      'upi',
      'debit_card',
      'credit_card',
      'emi',
      'pay_later',
      'wallet',
      'bank_transfer',
      'other',
    ]),
    accountLast4: z.string().trim().regex(/^$|^\d{4}$/, 'Use exactly four digits'),
    fromAccountId: z.string(),
    toAccountId: z.string(),
  })
  .superRefine((value, ctx) => {
    if (value.entryType !== 'transfer' && !value.merchant) {
      ctx.addIssue({ code: 'custom', path: ['merchant'], message: 'Enter a merchant or source' });
    }
    if (
      value.entryType === 'transfer' &&
      (!value.fromAccountId || !value.toAccountId || value.fromAccountId === value.toAccountId)
    ) {
      ctx.addIssue({ code: 'custom', path: ['toAccountId'], message: 'Choose two different accounts' });
    }
  });

type FormValues = z.infer<typeof schema>;

const ENTRY_OPTIONS = [
  { value: 'expense', label: 'Expense', icon: ArrowUpRight },
  { value: 'income', label: 'Income', icon: ArrowDownLeft },
  { value: 'refund', label: 'Refund', icon: RotateCcw },
  { value: 'transfer', label: 'Transfer', icon: ArrowLeftRight },
] as const;

function todayValue() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

export function QuickAddDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const { month, year } = useWorkspace();
  const categories = useCategories();
  const accounts = useAccounts();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      entryType: 'expense',
      amount: 0,
      merchant: '',
      transactionDate: todayValue(),
      categoryId: '',
      paymentMethod: 'other',
      accountLast4: '',
      fromAccountId: '',
      toAccountId: '',
    },
  });
  const entryType = form.watch('entryType');

  const create = useMutation({
    mutationFn: async (values: FormValues) => {
      if (!user) throw new Error('Sign in to add activity');
      if (values.entryType === 'transfer') {
        return api.createTransfer(user.id, {
          from_account_id: values.fromAccountId,
          to_account_id: values.toAccountId,
          amount: values.amount,
          currency: user.currency,
          transaction_date: values.transactionDate,
          description: values.merchant || 'Account transfer',
        });
      }
      const transactionType: TransactionType =
        values.entryType === 'expense' ? 'debit' : values.entryType === 'income' ? 'credit' : 'refund';
      return api.createTransaction(user.id, {
        amount: values.amount,
        currency: user.currency,
        transaction_type: transactionType,
        payment_method: values.paymentMethod as PaymentMethod,
        transaction_date: values.transactionDate,
        merchant_raw: values.merchant,
        merchant_normalized: values.merchant,
        category_id: values.categoryId || null,
        account_last4: values.accountLast4 || null,
        confidence_score: 1,
      });
    },
    onSuccess: async () => {
      if (!user) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.transactions(user.id, month, year) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.summary(user.id, month, year) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.workspace(user.id, month, year) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.guidanceBrief(user.id, month, year) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.netWorth(user.id) }),
      ]);
      notify(entryType === 'transfer' ? 'Transfer recorded' : 'Activity added', 'success');
      form.reset({
        ...form.getValues(),
        amount: 0,
        merchant: '',
        accountLast4: '',
      });
      onClose();
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  return (
    <Dialog open={open} onClose={onClose} title="Quick add" className="max-w-xl">
      <form className="grid gap-4" onSubmit={form.handleSubmit((values) => create.mutate(values))}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup" aria-label="Activity type">
          {ENTRY_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={entryType === value}
              onClick={() => form.setValue('entryType', value)}
              className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold transition-colors ${
                entryType === value ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-muted'
              }`}
            >
              <Icon className="h-4 w-4" /> {label}
            </button>
          ))}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Amount" error={form.formState.errors.amount?.message}>
            <Input data-dialog-initial-focus type="number" min="0.01" step="0.01" {...form.register('amount', { valueAsNumber: true })} />
          </Field>
          <Field label="Date" error={form.formState.errors.transactionDate?.message}>
            <Input type="date" {...form.register('transactionDate')} />
          </Field>
        </div>

        {entryType === 'transfer' ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="From account" error={form.formState.errors.fromAccountId?.message}>
              <Select {...form.register('fromAccountId')}>
                <option value="">Choose account</option>
                {(accounts.data ?? []).filter((account) => account.is_active).map((account) => (
                  <option key={account.id} value={account.id}>{account.institution_name} {account.masked_number}</option>
                ))}
              </Select>
            </Field>
            <Field label="To account" error={form.formState.errors.toAccountId?.message}>
              <Select {...form.register('toAccountId')}>
                <option value="">Choose account</option>
                {(accounts.data ?? []).filter((account) => account.is_active).map((account) => (
                  <option key={account.id} value={account.id}>{account.institution_name} {account.masked_number}</option>
                ))}
              </Select>
            </Field>
          </div>
        ) : (
          <>
            <Field label={entryType === 'income' ? 'Source' : 'Merchant'} error={form.formState.errors.merchant?.message}>
              <Input placeholder={entryType === 'income' ? 'Employer or source' : 'Merchant name'} {...form.register('merchant')} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Category">
                <Select {...form.register('categoryId')}>
                  <option value="">Uncategorized</option>
                  {(categories.data ?? []).map((category) => (
                    <option key={category.id} value={category.id}>{category.name}</option>
                  ))}
                </Select>
              </Field>
              <Field label="Payment method">
                <Select {...form.register('paymentMethod')}>
                  <option value="upi">UPI</option>
                  <option value="debit_card">Debit card</option>
                  <option value="credit_card">Credit card</option>
                  <option value="bank_transfer">Bank transfer</option>
                  <option value="wallet">Wallet</option>
                  <option value="other">Other</option>
                </Select>
              </Field>
            </div>
            <Field label="Account last four" error={form.formState.errors.accountLast4?.message}>
              <Input inputMode="numeric" maxLength={4} placeholder="Optional" {...form.register('accountLast4')} />
            </Field>
          </>
        )}

        {entryType === 'transfer' && (accounts.data?.length ?? 0) < 2 && (
          <p className="rounded-xl border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
            Add at least two accounts in Net Worth before recording a transfer.
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={create.isPending}>{create.isPending ? 'Saving…' : 'Add activity'}</Button>
        </div>
      </form>
    </Dialog>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5">
      <span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">{label}</span>
      {children}
      {error && <span className="text-xs text-danger">{error}</span>}
    </label>
  );
}
