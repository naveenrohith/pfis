import { ArrowRight } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import type { Severity } from './InsightCard';

const SEVERITY_VARIANT: Record<Severity, 'info' | 'success' | 'warning' | 'danger'> = {
  info: 'info',
  success: 'success',
  warning: 'warning',
  danger: 'danger',
};

const SEVERITY_ACCENT: Record<Severity, string> = {
  info: 'border-l-info',
  success: 'border-l-success',
  warning: 'border-l-warning',
  danger: 'border-l-danger',
};

export interface RecommendationCardProps {
  title: string;
  description: string;
  severity?: Severity;
  actionLabel: string;
  onAction?: () => void;
  className?: string;
}

/** A recommendation with a clear call to action (budget risk, cleanup, etc.). */
export function RecommendationCard({
  title,
  description,
  severity = 'info',
  actionLabel,
  onAction,
  className,
}: RecommendationCardProps) {
  return (
    <Card className={`border-l-4 ${SEVERITY_ACCENT[severity]} ${className ?? ''}`}>
      <CardContent className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <p className="min-w-0 text-sm font-bold leading-snug">{title}</p>
          <Badge variant={SEVERITY_VARIANT[severity]} className="shrink-0 capitalize">
            {severity}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">{description}</p>
        <Button size="sm" variant="ghost" className="mt-auto w-fit gap-1 px-2" onClick={onAction}>
          {actionLabel} <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </CardContent>
    </Card>
  );
}
