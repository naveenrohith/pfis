/** Formatting helpers shared across views. */

export function formatCurrency(value: number | null | undefined, currency = 'INR'): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(value ?? 0);
}

export function formatCompact(value: number | null | undefined): string {
  const n = value ?? 0;
  if (Math.abs(n) >= 10_000_000) return `${(n / 10_000_000).toFixed(1)}Cr`;
  if (Math.abs(n) >= 100_000) return `${(n / 100_000).toFixed(1)}L`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

export function formatSignedAmount(
  amount: number,
  type: string,
  currency = 'INR',
): { text: string; tone: 'positive' | 'negative' | 'neutral' } {
  const isCredit = type === 'credit' || type === 'refund';
  const sign = isCredit ? '+' : '-';
  return {
    text: `${sign}${formatCurrency(Math.abs(amount), currency)}`,
    tone: isCredit ? 'positive' : 'negative',
  };
}

export function initials(value: string): string {
  const parts = value.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

export function monthLabel(month: number, year: number): string {
  return `${MONTH_NAMES[month - 1]} ${year}`;
}

export function parseDateValue(value: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(value);
}

export function relativeDateGroup(value: string): 'Today' | 'Yesterday' | 'This week' | 'Earlier' {
  const date = parseDateValue(value);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.floor((startOfToday.getTime() - date.getTime()) / 86_400_000);
  if (diffDays <= 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 7) return 'This week';
  return 'Earlier';
}

export function formatCountdown(expiresAt: number | null): string | null {
  if (!expiresAt) return null;
  const ms = expiresAt - Date.now();
  if (ms <= 0) return 'expired';
  const minutes = Math.floor(ms / 60_000);
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  if (minutes >= 1) return `${minutes}m`;
  return `${Math.floor(ms / 1000)}s`;
}

export function formatTime(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
