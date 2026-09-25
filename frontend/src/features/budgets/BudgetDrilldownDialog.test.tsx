import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BudgetDrilldownDialog } from './BudgetDrilldownDialog';
import type { BudgetDrilldown, BudgetTracker } from '@/lib/types';

const { useBudgetDrilldown } = vi.hoisted(() => ({
  useBudgetDrilldown: vi.fn(),
}));

vi.mock('@/features/workspace/queries', () => ({
  useBudgetDrilldown,
}));

const budget: BudgetTracker = {
  id: 'budget-food',
  category_id: 'food',
  category: 'Food',
  category_icon: '🍽️',
  limit: 12000,
  actual_spend: 4500,
  remaining: 7500,
  usage_pct: 37.5,
  status: 'under',
};

const drilldown: BudgetDrilldown = {
  budget: {
    id: 'budget-food',
    category_id: 'food',
    category_name: 'Food',
    category_icon: '🍽️',
    monthly_limit: 12000,
    actual_spend: 4300,
    remaining: 7700,
    usage_pct: 35.8,
    status: 'under',
  },
  month: 9,
  year: 2026,
  transaction_count: 3,
  has_more: true,
  transactions: [
    {
      id: 'txn-1',
      transaction_date: '2026-09-14',
      merchant: 'Fresh Basket',
      transaction_type: 'debit',
      amount: 5000,
      spend_effect: 5000,
      currency: 'INR',
    },
    {
      id: 'txn-2',
      transaction_date: '2026-09-15',
      merchant: 'Fresh Basket refund',
      transaction_type: 'refund',
      amount: 700,
      spend_effect: -700,
      currency: 'INR',
    },
  ],
};

function renderDialog() {
  return render(<BudgetDrilldownDialog budget={budget} currency="INR" />);
}

describe('BudgetDrilldownDialog', () => {
  beforeEach(() => {
    useBudgetDrilldown.mockReturnValue({
      data: drilldown,
      isLoading: false,
      isError: false,
    });
    document.body.style.cssText = '';
    document.documentElement.style.cssText = '';
    document.documentElement.removeAttribute('data-base-ui-scroll-locked');
  });

  it('loads the drilldown only while open and restores focus when closed', async () => {
    const user = userEvent.setup();
    renderDialog();

    const trigger = screen.getByRole('button', { name: 'Inspect spend' });
    expect(useBudgetDrilldown).toHaveBeenLastCalledWith('budget-food', false);

    trigger.focus();
    await user.click(trigger);

    expect(useBudgetDrilldown).toHaveBeenLastCalledWith('budget-food', true);
    expect(screen.getByRole('dialog', { name: 'Food spend evidence' })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });
  });

  it('shows remaining amount, truncation, and refunds netting against spend', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('button', { name: 'Inspect spend' }));

    expect(screen.getByText('₹7,700')).toBeInTheDocument();
    expect(
      screen.getByText(/Showing the newest 2 of 3 contributing transactions/i),
    ).toBeInTheDocument();
    expect(screen.getByText('Fresh Basket')).toBeInTheDocument();
    expect(screen.getByText('+₹5,000')).toBeInTheDocument();
    expect(screen.getByText('Fresh Basket refund')).toBeInTheDocument();
    expect(screen.getByText('-₹700')).toBeInTheDocument();
    expect(screen.getByText('Nets against spend')).toBeInTheDocument();
  });

  it('renders loading, empty, and error states', async () => {
    const user = userEvent.setup();
    useBudgetDrilldown.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    });
    const { rerender } = renderDialog();
    await user.click(screen.getByRole('button', { name: 'Inspect spend' }));
    expect(screen.getByLabelText('Loading budget spend evidence')).toBeInTheDocument();

    useBudgetDrilldown.mockReturnValue({
      data: { ...drilldown, has_more: false, transaction_count: 0, transactions: [] },
      isLoading: false,
      isError: false,
    });
    rerender(<BudgetDrilldownDialog budget={budget} currency="INR" />);
    expect(screen.getByText('No contributing transactions')).toBeInTheDocument();

    useBudgetDrilldown.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    });
    rerender(<BudgetDrilldownDialog budget={budget} currency="INR" />);
    expect(screen.getByText(/Budget evidence could not be loaded/i)).toBeInTheDocument();
  });
});
