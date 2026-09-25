import { describe, expect, it } from 'vitest';
import {
  PLAN_NAV_ITEMS,
  PLAN_STAGES,
  planNavigationForView,
  planSectionForNavigation,
  planStageForView,
  planViewFromSection,
} from './PlanModel';

describe('Planning decision trail', () => {
  it('uses a short, ordered path that matches the financial decision', () => {
    expect(PLAN_STAGES.map((stage) => stage.label)).toEqual([
      'Can I spend?',
      'Where do I stand?',
      'What’s coming?',
      'What could change?',
      'Protect & plan',
    ]);
    expect(PLAN_STAGES.map((stage) => stage.destination)).toEqual([
      'cash-plan',
      'networth',
      'obligations',
      'analytics',
      'budgets',
    ]);
  });

  it('keeps every deep-linked Plan surface inside the right stage', () => {
    expect(planStageForView('cash-plan')).toBe('spend');
    expect(planStageForView('networth')).toBe('stand');
    expect(planStageForView('cards')).toBe('coming');
    expect(planStageForView('liabilities')).toBe('coming');
    expect(planStageForView('obligations')).toBe('coming');
    expect(planStageForView('household')).toBe('protect');
    expect(planStageForView('analytics')).toBe('change');
    expect(planStageForView('budgets')).toBe('protect');
  });

  it('falls back to the safe-to-spend entry for non-Plan sections', () => {
    expect(planViewFromSection('overview')).toBe('cash-plan');
    expect(planViewFromSection('cash-plan')).toBe('cash-plan');
    expect(planViewFromSection('budgets')).toBe('budgets');
  });

  it('keeps the five decision steps visible and maps detail routes into their stage', () => {
    expect(PLAN_NAV_ITEMS.map((item) => item.label)).toEqual([
      'Can I spend?',
      'Where do I stand?',
      'What’s coming?',
      'What could change?',
      'Protect & plan',
    ]);
    expect(planNavigationForView('cards')).toBe('coming');
    expect(planNavigationForView('liabilities')).toBe('coming');
    expect(planNavigationForView('household')).toBe('protect');
    expect(planNavigationForView('budgets')).toBe('protect');
    expect(planSectionForNavigation('coming')).toBe('obligations');
    expect(planSectionForNavigation('change')).toBe('analytics');
    expect(planSectionForNavigation('protect')).toBe('budgets');
  });
});
