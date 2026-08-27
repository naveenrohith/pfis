import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RoadmapExtensionsSection } from './RoadmapExtensionsSection';

const apiMocks = vi.hoisted(() => ({
  householdExpenses: vi.fn(),
  householdMembers: vi.fn(),
  householdSettlements: vi.fn(),
  payoffComparison: vi.fn(),
}));

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'user-1', name: 'Test', email: 'test@example.com', currency: 'INR' },
  }),
}));

vi.mock('@/features/workspace/queries', () => ({
  queryKeys: {
    bills: (userId: string) => ['bills', userId],
    healthChecklist: (userId: string) => ['healthChecklist', userId],
    households: (userId: string) => ['households', userId],
    householdExpenses: (userId: string, householdId: string) => [
      'householdExpenses',
      userId,
      householdId,
    ],
    householdMembers: (userId: string, householdId: string) => [
      'householdMembers',
      userId,
      householdId,
    ],
    householdSettlements: (userId: string, householdId: string) => [
      'householdSettlements',
      userId,
      householdId,
    ],
  },
  useBills: () => ({
    data: [
      {
        id: 'bill-1',
        label: 'Electricity',
        amount: 1800,
        due_date: '2026-07-30',
        status: 'due',
        confirmed: true,
      },
    ],
  }),
  useHealthChecklist: () => ({
    data: [
      {
        id: 'health-1',
        item_type: 'emergency_fund',
        label: 'Emergency fund',
        status: 'complete',
      },
    ],
  }),
  useLiabilities: () => ({ data: [] }),
  useHouseholds: () => ({
    data: [
      {
        id: 'household-1',
        owner_user_id: 'user-1',
        name: 'Home',
        member_count: 2,
        expense_count: 1,
        open_settlement_count: 1,
      },
    ],
  }),
}));

vi.mock('@/lib/api', () => ({
  api: {
    ...apiMocks,
    addHouseholdMember: vi.fn(),
    createBill: vi.fn(),
    createCardDispute: vi.fn(),
    createHousehold: vi.fn(),
    createHouseholdExpense: vi.fn(),
    createHouseholdSettlement: vi.fn(),
    deleteHousehold: vi.fn(),
    removeHouseholdMember: vi.fn(),
    updateBill: vi.fn(),
    updateHealthChecklist: vi.fn(),
    updateHouseholdMember: vi.fn(),
    updateHouseholdSettlement: vi.fn(),
    upsertHealthChecklist: vi.fn(),
  },
}));

function renderSection(view: 'obligations' | 'household') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RoadmapExtensionsSection view={view} />
    </QueryClientProvider>,
  );
}

describe('RoadmapExtensionsSection', () => {
  it('keeps bill status separate from Cash Plan evidence', () => {
    renderSection('obligations');

    expect(screen.getByText(/Confirmed obligations/i)).toBeInTheDocument();
    expect(screen.getByText('Electricity')).toBeInTheDocument();
    expect(
      screen.getByText(/Only confirmed commitments affect the Cash Plan/i),
    ).toBeInTheDocument();
    expect(screen.getByText('Financial safety checklist')).toBeInTheDocument();
    expect(screen.getByLabelText(/Emergency fund: Complete/i)).toHaveClass('h-11');
  });

  it('labels household data as annotation-only and never private evidence', async () => {
    apiMocks.householdMembers.mockResolvedValue([
      {
        id: 'member-1',
        household_id: 'household-1',
        user_id: 'user-1',
        role: 'owner',
        visibility: 'annotations_only',
        joined_at: '2026-07-01T00:00:00Z',
      },
      {
        id: 'member-2',
        household_id: 'household-1',
        user_id: 'user-2',
        role: 'member',
        visibility: 'annotations_only',
        joined_at: '2026-07-02T00:00:00Z',
      },
    ]);
    apiMocks.householdExpenses.mockResolvedValue([
      {
        id: 'expense-1',
        household_id: 'household-1',
        created_by_user_id: 'user-1',
        payer_user_id: 'user-1',
        label: 'Groceries',
        amount: 1200,
        currency: 'INR',
        expense_date: '2026-07-20',
        splits: { 'user-1': 600, 'user-2': 600 },
        created_at: '2026-07-20T00:00:00Z',
      },
    ]);
    apiMocks.householdSettlements.mockResolvedValue([]);

    renderSection('household');

    expect(await screen.findByText(/Shared annotations only/i)).toBeInTheDocument();
    expect(await screen.findByText('Groceries')).toBeInTheDocument();
    expect(screen.getByText(/Private financial evidence is never shared/i)).toBeInTheDocument();
    expect(screen.queryByText(/transaction id/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/statement evidence/i)).not.toBeInTheDocument();
  });
});
