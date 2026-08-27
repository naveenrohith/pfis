import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BadgeCheck } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Input, Label, Select } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { queryKeys } from '@/features/workspace/queries';
import { api } from '@/lib/api';
import type { AccountProductType, FinancialAccount } from '@/lib/types';
import { formatDate } from '@/lib/format';

const productOptions: Array<{ value: Exclude<AccountProductType, 'unknown'>; label: string }> = [
  { value: 'bank', label: 'Bank account' },
  { value: 'credit_card', label: 'Credit card' },
  { value: 'loan', label: 'Loan' },
  { value: 'pay_later', label: 'Pay later' },
  { value: 'cash', label: 'Cash pocket' },
  { value: 'investment', label: 'Investment' },
];

function balanceKindFor(type: Exclude<AccountProductType, 'unknown'>) {
  return ['credit_card', 'loan', 'pay_later'].includes(type) ? 'liability' : 'asset';
}

export function AccountIdentityDialog({
  account,
  onClose,
  onResolved,
}: {
  account: FinancialAccount | null;
  onClose: () => void;
  onResolved?: (account: FinancialAccount) => void;
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [name, setName] = useState('');
  const [masked, setMasked] = useState('');
  const [type, setType] = useState<Exclude<AccountProductType, 'unknown'>>('bank');
  const history = useQuery({
    queryKey: queryKeys.accountIdentityHistory(user?.id ?? '', account?.id ?? ''),
    queryFn: () => api.accountIdentityHistory(user!.id, account!.id),
    enabled: Boolean(user && account),
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!account) return;
    setName(account.institution_name === 'Unknown' ? '' : account.institution_name);
    setMasked(account.masked_number);
    setType(
      account.account_type === 'unknown'
        ? 'bank'
        : (account.account_type as Exclude<AccountProductType, 'unknown'>),
    );
  }, [account]);

  const suffix = useMemo(() => masked.replace(/\D/g, '').slice(-4), [masked]);
  const identityStatus =
    account?.identity_status ?? (account?.account_type === 'unknown' ? 'unresolved' : 'confirmed');
  const identityConfidence = Math.round(
    (account?.identity_confidence ?? (identityStatus === 'confirmed' ? 0.95 : 0.35)) * 100,
  );
  const resolveIdentity = useMutation({
    mutationFn: async () => {
      if (!user || !account) throw new Error('Choose an account to identify');
      return api.updateAccount(user.id, account.id, {
        institution_name: name.trim(),
        account_type: type,
        balance_kind: balanceKindFor(type),
        masked_number: masked.trim(),
      });
    },
    onSuccess: async (updated) => {
      if (user) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.netWorth(user.id) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.cashPlan(user.id) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.liabilityOverview(user.id) }),
        ]);
      }
      notify('Account identity confirmed', 'success');
      onResolved?.(updated);
      onClose();
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  return (
    <Dialog open={Boolean(account)} onClose={onClose} title="Confirm account identity">
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          resolveIdentity.mutate();
        }}
      >
        <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
          <div className="flex gap-3">
            <BadgeCheck className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
            <div>
              <p className="text-sm font-bold">You decide what this instrument is</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                PFIS found the masked identifier {account?.masked_number}. Confirming it allows
                future activity with the same unique identifier to use this product identity.
              </p>
            </div>
          </div>
        </div>
        <section
          className="rounded-lg border border-border/70 bg-muted/30 p-4"
          aria-label="Identity evidence"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
              Identity evidence
            </p>
            <p className="text-xs font-bold text-muted-foreground">
              {identityConfidence}% confidence · {identityStatus}
            </p>
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            Confidence describes how strongly the current institution and product type are
            supported; it never represents a live balance.
          </p>
          {account?.identity_evidence?.length ? (
            <ul className="mt-3 grid gap-2 text-xs" aria-label="Evidence trail">
              {account.identity_evidence.slice(-3).map((item) => (
                <li
                  key={`${item.source_type}-${item.source_id}-${item.role}-${item.observed_at ?? ''}`}
                >
                  <span className="font-bold">{item.role.replaceAll('_', ' ')}</span>
                  {item.note ? <span className="text-muted-foreground"> · {item.note}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">
              No durable identity evidence has been recorded yet.
            </p>
          )}
          {history.data && history.data.length > 1 ? (
            <details className="mt-3 rounded-md border border-border/70 p-2">
              <summary className="focus-ring cursor-pointer text-xs font-bold">
                View identity changes
              </summary>
              <ul className="mt-2 grid gap-2 text-xs text-muted-foreground">
                {history.data.slice(-4).map((snapshot) => (
                  <li key={`${snapshot.captured_at}-${snapshot.identity_status}`}>
                    {formatDate(snapshot.effective_date)} · {snapshot.identity_status} ·{' '}
                    {Math.round(snapshot.identity_confidence * 100)}% confidence
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>
        <div className="grid gap-1.5">
          <Label htmlFor="identity-name">Institution or account label</Label>
          <Input
            id="identity-name"
            name="institution_name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="HDFC primary account"
            autoComplete="organization"
            autoFocus
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="identity-product">Financial product</Label>
          <Select
            id="identity-product"
            name="account_type"
            value={type}
            onChange={(event) => setType(event.target.value as typeof type)}
          >
            {productOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="identity-masked">Masked identifier</Label>
          <Input
            id="identity-masked"
            name="masked_number"
            value={masked}
            onChange={(event) => setMasked(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder="••••1234"
          />
          <p className="text-xs leading-5 text-muted-foreground">
            Keep only a masked label. PFIS never needs or stores a full account or card number.
          </p>
        </div>
        {suffix.length !== 4 ? (
          <p role="alert" className="text-xs font-bold text-warning">
            Include the last four digits so imported activity can be linked safely.
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={
              !name.trim() ||
              masked.trim().length < 2 ||
              suffix.length !== 4 ||
              resolveIdentity.isPending
            }
          >
            Confirm identity
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
