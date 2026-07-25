import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Building2, Landmark, Plus, Scale, TrendingUp } from 'lucide-react';
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Dialog } from '@/components/ui/Dialog';
import { Input, Label, Select } from '@/components/ui/Input';
import { Skeleton, EmptyState } from '@/components/ui/Skeleton';
import { SectionTitle } from '@/components/SectionTitle';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { queryKeys, useAccounts, useNetWorth } from '@/features/workspace/queries';
import { api } from '@/lib/api';
import { formatChartCurrency, formatCurrency } from '@/lib/format';

function todayValue() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

export function NetWorthSection({ embedded = false }: { embedded?: boolean } = {}) {
  const { user } = useAuth();
  const accounts = useAccounts();
  const netWorth = useNetWorth();
  const [accountOpen, setAccountOpen] = useState(false);
  const [balanceAccountId, setBalanceAccountId] = useState<string | null>(null);
  const currency = user?.currency ?? 'INR';

  return (
    <div>
      {!embedded ? (
        <SectionTitle
          eyebrow="Accounts"
          title="Net worth"
          description="Assets minus liabilities, calculated only from balance snapshots you own and provide."
          action={
            <Button size="sm" onClick={() => setAccountOpen(true)}>
              <Plus className="h-4 w-4" /> Add account
            </Button>
          }
        />
      ) : (
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-xl font-extrabold tracking-[-0.025em]">Your financial position</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Owned balances only—no guessed market values.
            </p>
          </div>
          <Button size="sm" onClick={() => setAccountOpen(true)}>
            <Plus className="h-4 w-4" /> Add account
          </Button>
        </div>
      )}

      {netWorth.isLoading || accounts.isLoading ? (
        <Skeleton className="h-80" />
      ) : (accounts.data?.length ?? 0) === 0 ? (
        <Card>
          <CardContent className="p-6">
            <EmptyState
              icon={<Landmark />}
              title="No accounts yet"
              description="Add an asset or liability account, then record a balance to calculate true net worth."
            />
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric
              label="Assets"
              value={formatCurrency(netWorth.data?.assets ?? 0, currency)}
              icon={<TrendingUp className="text-success" />}
            />
            <Metric
              label="Liabilities"
              value={formatCurrency(netWorth.data?.liabilities ?? 0, currency)}
              icon={<Scale className="text-warning" />}
            />
            <Metric
              label="Net worth"
              value={formatCurrency(netWorth.data?.net_worth ?? 0, currency)}
              icon={<Landmark className="text-primary" />}
            />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
            <Card>
              <CardContent className="p-5">
                <h3 className="font-bold">Net-worth history</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Append-only balance snapshots; no market-price estimates.
                </p>
                {(netWorth.data?.points.length ?? 0) === 0 ? (
                  <div className="mt-4">
                    <EmptyState
                      icon={<TrendingUp />}
                      title="Add your first balance"
                      description="History begins when an account has a dated balance snapshot."
                    />
                  </div>
                ) : (
                  <div className="mt-4" role="img" aria-label="Net worth history line chart">
                    <ResponsiveContainer width="100%" height={260}>
                      <LineChart data={netWorth.data?.points}>
                        <XAxis
                          dataKey="date"
                          tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                        />
                        <YAxis
                          tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
                          tickFormatter={(value) => `${Math.round(value / 1000)}k`}
                        />
                        <Tooltip
                          formatter={(value) => formatChartCurrency(value, currency)}
                          contentStyle={{
                            background: 'hsl(var(--card))',
                            border: '1px solid hsl(var(--border))',
                            borderRadius: 12,
                          }}
                        />
                        <Line
                          type="monotone"
                          dataKey="net_worth"
                          stroke="hsl(var(--primary))"
                          strokeWidth={3}
                          dot={{ r: 3 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                    <table className="sr-only">
                      <caption>Net worth history data</caption>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Assets</th>
                          <th>Liabilities</th>
                          <th>Net worth</th>
                        </tr>
                      </thead>
                      <tbody>
                        {netWorth.data?.points.map((point) => (
                          <tr key={point.date}>
                            <td>{point.date}</td>
                            <td>{point.assets}</td>
                            <td>{point.liabilities}</td>
                            <td>{point.net_worth}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="grid gap-3 p-5">
                <h3 className="font-bold">Your accounts</h3>
                {(accounts.data ?? []).map((account) => (
                  <button
                    key={account.id}
                    type="button"
                    onClick={() => setBalanceAccountId(account.id)}
                    className="dashboard-row flex w-full items-center gap-3 text-left"
                  >
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted">
                      <Building2 className="h-4 w-4 text-primary" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-bold">
                        {account.institution_name}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {account.account_type} · {account.masked_number}
                      </span>
                    </span>
                    <span className="text-right">
                      <span className="block text-sm font-bold">
                        {account.latest_balance == null
                          ? 'Add balance'
                          : formatCurrency(account.latest_balance, account.currency)}
                      </span>
                      <Badge variant={account.balance_kind === 'asset' ? 'success' : 'warning'}>
                        {account.balance_kind}
                      </Badge>
                    </span>
                  </button>
                ))}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <AccountDialog open={accountOpen} onClose={() => setAccountOpen(false)} />
      <BalanceDialog accountId={balanceAccountId} onClose={() => setBalanceAccountId(null)} />
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-5">
        <div>
          <p className="text-xs font-semibold text-muted-foreground">{label}</p>
          <p className="mt-2 text-2xl font-extrabold">{value}</p>
        </div>
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted [&_svg]:h-5 [&_svg]:w-5">
          {icon}
        </span>
      </CardContent>
    </Card>
  );
}

function AccountDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [name, setName] = useState('');
  const [masked, setMasked] = useState('');
  const [type, setType] = useState('bank');
  const [kind, setKind] = useState<'asset' | 'liability'>('asset');
  const create = useMutation({
    mutationFn: () => {
      if (!user) throw new Error('Sign in to add an account');
      return api.createAccount(user.id, {
        institution_name: name,
        account_type: type,
        balance_kind: kind,
        masked_number: masked,
        currency: user.currency,
      });
    },
    onSuccess: () => {
      if (user) queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) });
      notify('Account added', 'success');
      setName('');
      setMasked('');
      onClose();
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  return (
    <Dialog open={open} onClose={onClose} title="Add financial account">
      <div className="grid gap-3">
        <div className="grid gap-1">
          <Label htmlFor="account-name">Account name</Label>
          <Input
            id="account-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Primary bank"
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="account-masked">Masked identifier</Label>
          <Input
            id="account-masked"
            value={masked}
            onChange={(event) => setMasked(event.target.value)}
            placeholder="••••1234 or Home"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="grid gap-1">
            <Label htmlFor="account-type">Type</Label>
            <Select
              id="account-type"
              value={type}
              onChange={(event) => setType(event.target.value)}
            >
              <option value="bank">Bank</option>
              <option value="cash">Cash</option>
              <option value="investment">Investment</option>
              <option value="credit">Credit card</option>
              <option value="loan">Loan</option>
            </Select>
          </div>
          <div className="grid gap-1">
            <Label htmlFor="account-kind">Balance kind</Label>
            <Select
              id="account-kind"
              value={kind}
              onChange={(event) => setKind(event.target.value as typeof kind)}
            >
              <option value="asset">Asset</option>
              <option value="liability">Liability</option>
            </Select>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => create.mutate()}
            disabled={!name.trim() || !masked.trim() || create.isPending}
          >
            Add account
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function BalanceDialog({ accountId, onClose }: { accountId: string | null; onClose: () => void }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [amount, setAmount] = useState('');
  const [asOf, setAsOf] = useState(todayValue());
  const save = useMutation({
    mutationFn: () => {
      if (!user || !accountId) throw new Error('Choose an account');
      return api.addBalance(user.id, accountId, Number(amount), asOf);
    },
    onSuccess: () => {
      if (user) {
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) });
        queryClient.invalidateQueries({ queryKey: queryKeys.netWorth(user.id) });
      }
      notify('Balance snapshot saved', 'success');
      setAmount('');
      onClose();
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  return (
    <Dialog open={!!accountId} onClose={onClose} title="Record balance">
      <div className="grid gap-3">
        <div className="grid gap-1">
          <Label htmlFor="balance-amount">Balance amount</Label>
          <Input
            id="balance-amount"
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="balance-date">As of</Label>
          <Input
            id="balance-date"
            type="date"
            value={asOf}
            onChange={(event) => setAsOf(event.target.value)}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Balance history is append-only. Each account can have one immutable snapshot per date.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={Number(amount) < 0 || amount === '' || save.isPending}
          >
            Save balance
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
