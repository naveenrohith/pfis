import { describe, expect, it } from 'vitest';
import {
  calendarDayDifference,
  dateInputValueInTimezone,
  formatChartCurrency,
  formatCurrency,
  formatCompact,
  formatSignedAmount,
  initials,
  relativeDateGroup,
} from '@/lib/format';

describe('format helpers', () => {
  it('formats currency without fraction digits', () => {
    expect(formatCurrency(1234, 'INR')).toContain('1,234');
  });

  it('compacts large numbers', () => {
    expect(formatCompact(1500)).toBe('1.5k');
    expect(formatCompact(250000)).toBe('2.5L');
  });

  it('formats chart values without trusting third-party payload types', () => {
    expect(formatChartCurrency(1234, 'INR')).toContain('1,234');
    expect(formatChartCurrency('1234', 'INR')).toContain('1,234');
    expect(formatChartCurrency(undefined, 'INR')).toContain('0');
  });

  it('signs amounts by type', () => {
    expect(formatSignedAmount(100, 'debit').tone).toBe('negative');
    expect(formatSignedAmount(100, 'credit').tone).toBe('positive');
    expect(formatSignedAmount(100, 'refund').text.startsWith('+')).toBe(true);
  });

  it('derives initials', () => {
    expect(initials('Naveen Rohith')).toBe('NR');
    expect(initials('demo@pfis.app')).toBe('DE');
  });

  it('groups a far-past date as Earlier', () => {
    expect(relativeDateGroup('2000-01-01')).toBe('Earlier');
  });

  it('groups today', () => {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
      now.getDate(),
    ).padStart(2, '0')}`;
    expect(relativeDateGroup(today)).toBe('Today');
  });

  it('derives date input values from the financial timezone', () => {
    const instant = new Date('2026-07-30T20:00:00Z');
    expect(dateInputValueInTimezone('Asia/Kolkata', instant)).toBe('2026-07-31');
    expect(dateInputValueInTimezone('America/Los_Angeles', instant)).toBe('2026-07-30');
  });

  it('compares calendar dates without daylight-saving drift', () => {
    expect(calendarDayDifference('2026-03-10', '2026-03-01')).toBe(9);
  });
});
