import { Card, CardContent } from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/utils';

export interface ChartCardProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  loading?: boolean;
  className?: string;
  children: React.ReactNode;
}

/** Card shell for charts and data visualisations with a consistent header. */
export function ChartCard({
  title,
  description,
  action,
  loading,
  className,
  children,
}: ChartCardProps) {
  return (
    <Card className={cn('overflow-hidden', className)}>
      <CardContent className="p-4 sm:p-5">
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h3 className="font-bold">{title}</h3>
            {description && <p className="text-xs text-muted-foreground">{description}</p>}
          </div>
          {action}
        </div>
        {loading ? <Skeleton className={cn('h-56')} /> : children}
      </CardContent>
    </Card>
  );
}
