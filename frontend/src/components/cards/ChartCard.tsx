import { useId } from 'react';
import { Card, CardContent } from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { cn } from '@/lib/utils';

export interface ChartCardProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  loading?: boolean;
  chartSummary?: string;
  context?: string;
  dataTable?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}

/** Card shell for charts and data visualisations with a consistent header. */
export function ChartCard({
  title,
  description,
  action,
  loading,
  chartSummary,
  context,
  dataTable,
  className,
  children,
}: ChartCardProps) {
  const titleId = useId();
  const descriptionId = useId();
  const summaryId = useId();

  return (
    <Card className={cn('overflow-hidden', className)}>
      <CardContent className="p-4 sm:p-5">
        <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h3 id={titleId} className="font-bold">{title}</h3>
            {description && <p id={descriptionId} className="text-xs text-muted-foreground">{description}</p>}
          </div>
          <div className="flex shrink-0 items-start gap-2">
            {context && (
              <details className="relative text-xs">
                <summary className="cursor-pointer rounded-md border border-border px-2 py-1 font-semibold text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  How to read
                </summary>
                <p className="absolute right-0 z-20 mt-2 w-64 rounded-lg border border-border bg-card p-3 leading-relaxed text-card-foreground shadow-xl">
                  {context}
                </p>
              </details>
            )}
            {action}
          </div>
        </div>
        {loading ? (
          <Skeleton className={cn('h-56')} />
        ) : (
          <figure
            aria-labelledby={titleId}
            aria-describedby={
              [description ? descriptionId : null, chartSummary ? summaryId : null]
                .filter(Boolean)
                .join(' ') || undefined
            }
          >
            {chartSummary && <p id={summaryId} className="sr-only">{chartSummary}</p>}
            {children}
            {dataTable && (
              <details className="mt-4 rounded-lg border border-border bg-muted/20">
                <summary className="cursor-pointer px-3 py-2 text-xs font-bold text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  View chart data
                </summary>
                <div className="max-h-64 overflow-auto border-t border-border p-2">{dataTable}</div>
              </details>
            )}
          </figure>
        )}
      </CardContent>
    </Card>
  );
}
