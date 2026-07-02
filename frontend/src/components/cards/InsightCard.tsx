import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';

export type Severity = 'info' | 'success' | 'warning' | 'danger';

const SEVERITY_VARIANT: Record<Severity, 'info' | 'success' | 'warning' | 'danger'> = {
  info: 'info',
  success: 'success',
  warning: 'warning',
  danger: 'danger',
};

export interface InsightCardProps {
  title: string;
  description: string;
  icon?: string | null;
  severity?: Severity;
  className?: string;
}

/** Action-oriented insight card ("Food spending increased", etc.). */
export function InsightCard({
  title,
  description,
  icon,
  severity = 'info',
  className,
}: InsightCardProps) {
  return (
    <div className={cn('rounded-lg border border-border bg-card p-3 shadow-sm shadow-slate-900/5', className)}>
      <div className="flex items-start gap-2">
        {icon && (
          <span aria-hidden className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted">
            {icon}
          </span>
        )}
        <p className="min-w-0 text-sm font-semibold leading-snug">{title}</p>
        <Badge variant={SEVERITY_VARIANT[severity]} className="ml-auto capitalize">
          {severity}
        </Badge>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{description}</p>
    </div>
  );
}
