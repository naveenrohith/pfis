import {
  Banknote,
  Repeat,
  ReceiptText,
  ShoppingBag,
  Undo2,
  CreditCard,
  type LucideIcon,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { formatCurrency } from '@/lib/format';
import type { TimelineEvent, TimelineEventType } from '@/lib/types';
import { cn } from '@/lib/utils';

const EVENT_META: Record<TimelineEventType, { icon: LucideIcon; label: string; tone: string }> = {
  income: { icon: Banknote, label: 'Income', tone: 'text-success' },
  subscription: { icon: Repeat, label: 'Subscription', tone: 'text-info' },
  bill: { icon: ReceiptText, label: 'Bill', tone: 'text-warning' },
  shopping: { icon: ShoppingBag, label: 'Shopping', tone: 'text-foreground' },
  refund: { icon: Undo2, label: 'Refund', tone: 'text-success' },
  spending: { icon: CreditCard, label: 'Spending', tone: 'text-foreground' },
};

export interface TimelineCardProps {
  event: TimelineEvent;
  currency?: string;
  className?: string;
}

/** A single financial movement rendered on the timeline. */
export function TimelineCard({ event, currency = 'INR', className }: TimelineCardProps) {
  const meta = EVENT_META[event.type] ?? EVENT_META.spending;
  const Icon = meta.icon;
  const isIn = event.direction === 'in';
  const amount = `${isIn ? '+' : '-'}${formatCurrency(Math.abs(event.amount), currency)}`;
  const methodLabel = paymentMethodLabel(event.payment_method);

  return (
    <div
      className={cn(
        'dashboard-row flex items-center gap-3',
        className,
      )}
    >
      <span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted', meta.tone)}>
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold">{event.label}</p>
        <p className="truncate text-xs text-muted-foreground">
          {meta.label}
          {event.category ? ` / ${event.category}` : ''} / {event.date}
        </p>
        {methodLabel && <Badge variant="outline" className="mt-1">{methodLabel}</Badge>}
        {event.transaction_status && event.transaction_status !== 'completed' && (
          <Badge variant="warning" className="mt-1 ml-1">{event.transaction_status.replace('_', ' ')}</Badge>
        )}
      </div>
      <div className="flex flex-col items-end gap-0.5">
        <span className={cn('text-sm font-bold', isIn ? 'text-success' : 'text-foreground')}>
          {amount}
        </span>
        {event.confidence > 0 && event.confidence < 0.85 && (
          <Badge variant="warning">{Math.round(event.confidence * 100)}%</Badge>
        )}
      </div>
    </div>
  );
}

function paymentMethodLabel(method?: TimelineEvent['payment_method']): string | null {
  if (method === 'upi') return 'UPI';
  if (method === 'debit_card') return 'Debit card';
  if (method === 'credit_card') return 'Credit card';
  return null;
}
