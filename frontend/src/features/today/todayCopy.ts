import { formatCurrency } from '@/lib/format';

interface TodayBriefCopyInput {
  transactionCount: number;
  netCashFlow: number;
  name: string;
  currency: string;
  recommendationTitle?: string;
}

export function buildTodayBriefCopy({
  transactionCount,
  netCashFlow,
  name,
  currency,
  recommendationTitle,
}: TodayBriefCopyInput) {
  if (transactionCount === 0) {
    return {
      headline: 'Connect or add activity to begin your brief.',
      summary:
        'PFIS has no transactions for this month yet. Add one or sync Gmail to build an evidence-based brief.',
    };
  }

  return {
    headline: recommendationTitle || fallbackHeadline(netCashFlow, name),
    summary: `You have ${netCashFlow >= 0 ? 'kept' : 'spent'} ${formatCurrency(Math.abs(netCashFlow), currency)} ${
      netCashFlow >= 0 ? 'after spending' : 'more than you earned'
    } this month.`,
  };
}

function fallbackHeadline(netCashFlow: number, name: string) {
  return netCashFlow >= 0
    ? `Good work, ${name}. You are keeping more than you spend.`
    : `Hello, ${name}. This month needs one clear adjustment.`;
}
