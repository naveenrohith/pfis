import { describe, expect, it } from 'vitest';
import { PLAN_STAGES, planStageForView, planViewFromSection } from './PlanModel';

describe('Planning decision trail', () => {
  it('uses a short, ordered path that matches the financial decision', () => {
    expect(PLAN_STAGES.map((stage) => stage.label)).toEqual([
      'Safe to spend',
      'Verified position',
      'Commitments',
      'Outlook & guardrails',
    ]);
    expect(PLAN_STAGES.map((stage) => stage.destination)).toEqual([
      'cash-plan',
      'networth',
      'obligations',
      'analytics',
    ]);
  });

  it('keeps every deep-linked Plan surface inside the right stage', () => {
    expect(planStageForView('cash-plan')).toBe('available');
    expect(planStageForView('networth')).toBe('position');
    expect(planStageForView('cards')).toBe('commitments');
    expect(planStageForView('liabilities')).toBe('commitments');
    expect(planStageForView('obligations')).toBe('commitments');
    expect(planStageForView('household')).toBe('commitments');
    expect(planStageForView('analytics')).toBe('outlook');
    expect(planStageForView('budgets')).toBe('outlook');
  });

  it('falls back to the safe-to-spend entry for non-Plan sections', () => {
    expect(planViewFromSection('overview')).toBe('cash-plan');
    expect(planViewFromSection('cash-plan')).toBe('cash-plan');
    expect(planViewFromSection('budgets')).toBe('budgets');
  });
});
