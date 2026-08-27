export type PlanView =
  | 'analytics'
  | 'networth'
  | 'budgets'
  | 'cash-plan'
  | 'liabilities'
  | 'cards'
  | 'obligations'
  | 'household';

export type PlanStageId = 'available' | 'position' | 'commitments' | 'outlook';

export const PLAN_STAGES = [
  {
    id: 'available',
    label: 'Safe to spend',
    destination: 'cash-plan',
    description: 'What is safe before the next income',
  },
  {
    id: 'position',
    label: 'Verified position',
    destination: 'networth',
    description: 'What is actually yours today',
  },
  {
    id: 'commitments',
    label: 'Commitments',
    destination: 'obligations',
    description: 'What must be paid or reviewed',
  },
  {
    id: 'outlook',
    label: 'Outlook & guardrails',
    destination: 'analytics',
    description: 'What one change could improve',
  },
] as const satisfies ReadonlyArray<{
  id: PlanStageId;
  label: string;
  destination: PlanView;
  description: string;
}>;

const PLAN_VIEWS: readonly PlanView[] = [
  'analytics',
  'networth',
  'budgets',
  'cash-plan',
  'liabilities',
  'cards',
  'obligations',
  'household',
];

export function planViewFromSection(section: string): PlanView {
  return PLAN_VIEWS.includes(section as PlanView) ? (section as PlanView) : 'cash-plan';
}

export function planStageForView(view: PlanView): PlanStageId {
  if (view === 'cash-plan') return 'available';
  if (view === 'networth') return 'position';
  if (view === 'analytics' || view === 'budgets') return 'outlook';
  return 'commitments';
}

export function stageForId(stage: PlanStageId) {
  return PLAN_STAGES.find((definition) => definition.id === stage) ?? PLAN_STAGES[0];
}
