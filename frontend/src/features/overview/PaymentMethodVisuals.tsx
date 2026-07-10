import { CreditCard, QrCode, WalletCards } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { formatCurrency } from '@/lib/format';
import type { PaymentMethod, Transaction } from '@/lib/types';

const METHODS: Array<{
  id: Exclude<PaymentMethod, 'other'>;
  label: string;
  icon: typeof QrCode;
  tone: string;
}> = [
  { id: 'upi', label: 'UPI', icon: QrCode, tone: 'bg-info' },
  { id: 'debit_card', label: 'Debit card', icon: WalletCards, tone: 'bg-warning' },
  { id: 'credit_card', label: 'Credit card', icon: CreditCard, tone: 'bg-primary' },
];

export function PaymentMethodVisuals({ transactions, currency }: { transactions: Transaction[]; currency: string }) {
  const debitTransactions = transactions.filter((transaction) => transaction.transaction_type === 'debit');
  const total = debitTransactions.reduce((sum, transaction) => sum + transaction.amount, 0);

  return (
    <section className="mt-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-muted-foreground">Payment methods</p>
          <h3 className="text-lg font-bold">How you paid this month</h3>
        </div>
        <p className="text-sm text-muted-foreground">Debit spend only</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {METHODS.map(({ id, label, icon: Icon, tone }) => {
          const matches = debitTransactions.filter((transaction) => transaction.payment_method === id);
          const spent = matches.reduce((sum, transaction) => sum + transaction.amount, 0);
          const share = total > 0 ? Math.round((spent / total) * 100) : 0;
          return (
            <Card key={id}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-muted-foreground">{label}</p>
                    <p className="mt-1 text-xl font-extrabold">{formatCurrency(spent, currency)}</p>
                  </div>
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted text-foreground">
                    <Icon className="h-4 w-4" />
                  </span>
                </div>
                <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted">
                  <div className={`h-full rounded-full ${tone}`} style={{ width: `${share}%` }} />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {matches.length} payment{matches.length === 1 ? '' : 's'} · {share}% of tracked spend
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
