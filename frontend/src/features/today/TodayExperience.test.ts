import { describe, expect, it } from 'vitest';
import { buildTodayBriefCopy } from './todayCopy';

describe('buildTodayBriefCopy', () => {
  it('does not describe an empty month as positive financial performance', () => {
    const copy = buildTodayBriefCopy({
      transactionCount: 0,
      netCashFlow: 0,
      name: 'Demo',
      currency: 'INR',
      recommendationTitle: 'A recommendation that requires transaction evidence',
    });

    expect(copy).toEqual({
      headline: 'Connect or add activity to begin your brief.',
      summary:
        'PFIS has no transactions for this month yet. Add one or sync Gmail to build an evidence-based brief.',
    });
    expect(copy.summary).not.toContain('kept');
  });

  it('keeps evidence-backed recommendations for months with activity', () => {
    const copy = buildTodayBriefCopy({
      transactionCount: 4,
      netCashFlow: 1250,
      name: 'Naveen',
      currency: 'INR',
      recommendationTitle: 'Your spending remains within this month’s income.',
    });

    expect(copy.headline).toBe('Your spending remains within this month’s income.');
    expect(copy.summary).toContain('₹1,250');
  });
});
