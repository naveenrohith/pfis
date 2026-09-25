import { formatCurrency } from '@/lib/format';
import type { TodayFinancialState } from './todayState';

interface TodayBriefCopyInput {
  transactionCount: number;
  netCashFlow: number;
  name: string;
  currency: string;
  recommendationTitle?: string;
  financialState?: TodayFinancialState | null;
}

export function buildTodayBriefCopy({
  transactionCount,
  netCashFlow,
  name,
  currency,
  recommendationTitle,
  financialState,
}: TodayBriefCopyInput) {
  if (transactionCount === 0) {
    return {
      headline: 'Connect or add activity to begin your brief.',
      summary:
        'PFIS has no transactions for this month yet. Add one or sync Gmail to build an evidence-based brief.',
    };
  }

  if (financialState === 'low-data') {
    return {
      headline: 'Your brief needs more activity before it can draw conclusions.',
      summary: `PFIS has ${transactionCount} ${
        transactionCount === 1 ? 'transaction' : 'transactions'
      } for this month. Connect a source or add activity so trends and projections rest on enough evidence.`,
    };
  }

  return {
    headline: recommendationTitle || fallbackHeadline(netCashFlow, name, financialState),
    summary: `You have ${netCashFlow >= 0 ? 'kept' : 'spent'} ${formatCurrency(Math.abs(netCashFlow), currency)} ${
      netCashFlow >= 0 ? 'after spending' : 'more than you earned'
    } this month.`,
  };
}

function fallbackHeadline(
  netCashFlow: number,
  name: string,
  financialState?: TodayFinancialState | null,
) {
  if (netCashFlow < 0 || financialState === 'deficit') {
    return `Hello, ${name}. This month needs one clear adjustment.`;
  }
  if (financialState === 'attention') {
    return `${name}, you are ahead this month, with one pressure worth watching.`;
  }
  return `Good work, ${name}. You are keeping more than you spend.`;
}
