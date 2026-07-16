import type { LucideIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { cn } from '@/lib/utils';

export type CardTone = 'default' | 'success' | 'warning' | 'danger' | 'info';

const TONE_TEXT: Record<CardTone, string> = {
  default: 'text-foreground',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
};

export interface StatCardProps {
  label: string;
  value: string | number;
  icon?: LucideIcon;
  tone?: CardTone;
  hint?: string;
  onClick?: () => void;
  className?: string;
}

/** Compact headline metric used across the command center and overview. */
export function StatCard({
  label,
  value,
  icon: Icon,
  tone = 'default',
  hint,
  onClick,
  className,
}: StatCardProps) {
  const interactive = typeof onClick === 'function';
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!interactive) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onClick?.();
    }
  };

  return (
    <Card
      className={cn(
        'overflow-hidden',
        interactive &&
          'cursor-pointer transition-colors hover:border-primary/50 hover:bg-muted/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30',
        className,
      )}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      {...(interactive ? { role: 'button', tabIndex: 0 } : {})}
    >
      <CardContent className="flex min-h-28 flex-col justify-between gap-3 p-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-muted-foreground">{label}</span>
          {Icon && (
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
              <Icon className={cn('h-4 w-4', TONE_TEXT[tone])} />
            </span>
          )}
        </div>
        <span className="metric-value">{value}</span>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      </CardContent>
    </Card>
  );
}
