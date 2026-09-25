export type PlanView =
  | 'analytics'
  | 'networth'
  | 'budgets'
  | 'cash-plan'
  | 'liabilities'
  | 'cards'
  | 'obligations'
  | 'household';

export type PlanStageId = 'spend' | 'stand' | 'coming' | 'change' | 'protect';

export type PlanNavigationId = PlanStageId;

export const PLAN_STAGES = [
  {
    id: 'spend',
    label: 'Can I spend?',
    shortLabel: 'Spend',
    destination: 'cash-plan',
    description: 'Safe-to-spend readiness before the next income',
  },
  {
    id: 'stand',
    label: 'Where do I stand?',
    shortLabel: 'Stand',
    destination: 'networth',
    description: 'Verified and provisional position',
  },
  {
    id: 'coming',
    label: 'What’s coming?',
    shortLabel: 'Coming',
    destination: 'obligations',
    description: 'Commitments, card dues, and liabilities already in motion',
  },
  {
    id: 'change',
    label: 'What could change?',
    shortLabel: 'Change',
    destination: 'analytics',
    description: 'Forecast, outlook, and drift signals',
  },
  {
    id: 'protect',
    label: 'Protect & plan',
    shortLabel: 'Protect',
    destination: 'budgets',
    description: 'Reserves, goals, scenarios, payoff, and household plans',
  },
] as const satisfies ReadonlyArray<{
  id: PlanStageId;
  label: string;
  shortLabel: string;
  destination: PlanView;
  description: string;
}>;

export const PLAN_NAV_ITEMS = PLAN_STAGES.map(({ id, label, shortLabel }) => ({
  id,
  label,
  shortLabel,
})) satisfies ReadonlyArray<{ id: PlanNavigationId; label: string; shortLabel: string }>;

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

export function planNavigationForView(view: PlanView): PlanNavigationId {
  return planStageForView(view);
}

export function planSectionForNavigation(navigation: PlanNavigationId): PlanView {
  return stageForId(navigation).destination;
}

export function planStageForView(view: PlanView): PlanStageId {
  if (view === 'cash-plan') return 'spend';
  if (view === 'networth') return 'stand';
  if (view === 'analytics') return 'change';
  if (view === 'budgets' || view === 'household') return 'protect';
  return 'coming';
}

export function stageForId(stage: PlanStageId) {
  return PLAN_STAGES.find((definition) => definition.id === stage) ?? PLAN_STAGES[0];
}
