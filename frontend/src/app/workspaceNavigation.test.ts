import { describe, expect, it } from 'vitest';
import {
  firstSectionForWorkspace,
  sectionFromHash,
  workspaceForSection,
} from './workspaceNavigation';

describe('workspace navigation model', () => {
  it('maps every legacy section hash to its owning workspace', () => {
    expect(workspaceForSection('overview')).toBe('today');
    expect(workspaceForSection('analytics')).toBe('plan');
    expect(workspaceForSection('budgets')).toBe('plan');
    expect(workspaceForSection('transactions')).toBe('activity');
    expect(workspaceForSection('pipeline')).toBe('data');
  });

  it('uses a stable entry section for each workspace', () => {
    expect(firstSectionForWorkspace('today')).toBe('overview');
    expect(firstSectionForWorkspace('activity')).toBe('transactions');
    expect(firstSectionForWorkspace('plan')).toBe('analytics');
    expect(firstSectionForWorkspace('insights')).toBe('insights');
    expect(firstSectionForWorkspace('data')).toBe('inbox');
  });

  it('accepts known hashes and rejects unknown targets', () => {
    expect(sectionFromHash('#transactions')).toBe('transactions');
    expect(sectionFromHash('#home')).toBe('overview');
    expect(sectionFromHash('#system')).toBe('inbox');
    expect(sectionFromHash('#not-a-section')).toBeNull();
    expect(sectionFromHash('#%E0%A4%A')).toBeNull();
    expect(sectionFromHash('')).toBeNull();
  });
});
