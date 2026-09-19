import { CircleAlert, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Card, CardContent } from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { useProductCapabilities } from '@/features/workspace/queries';
import type { ProductCapabilitySource } from '@/lib/types';

const statusLabels: Record<ProductCapabilitySource['status'], string> = {
  beta: 'Beta scope',
  best_effort: 'Best effort',
  deferred: 'Deferred',
};

const statusVariants: Record<ProductCapabilitySource['status'], 'success' | 'warning' | 'outline'> =
  {
    beta: 'warning',
    best_effort: 'outline',
    deferred: 'outline',
  };

export function ProductBoundaryCard() {
  const capabilities = useProductCapabilities();

  if (capabilities.isLoading) return <Skeleton className="h-56" />;
  if (!capabilities.data) return null;

  const { data } = capabilities;
  return (
    <Card className="border border-intelligence/20 bg-intelligence/[0.035]">
      <CardContent className="grid gap-4 p-4 sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 rounded-lg bg-intelligence/10 p-2 text-intelligence">
              <ShieldCheck aria-hidden="true" className="h-4 w-4" />
            </span>
            <div>
              <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-intelligence">
                Product boundary
              </p>
              <h2 className="mt-1 text-lg font-extrabold tracking-[-0.025em]">Source register</h2>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                Narrow source support is labelled so a best-effort parse never looks like a verified
                institution guarantee.
              </p>
            </div>
          </div>
          <Badge variant="warning">
            {data.product_stage === 'beta' ? 'Beta' : data.product_stage}
          </Badge>
        </div>

        <div className="divide-y divide-border/70 border-y border-border/70">
          {data.sources.map((source) => (
            <article
              key={source.key}
              className="grid gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[minmax(10rem,.8fr)_auto_minmax(0,1.5fr)_minmax(0,1.3fr)] sm:items-start sm:gap-4"
            >
              <h3 className="text-sm font-bold">{source.label}</h3>
              <div>
                <Badge variant={statusVariants[source.status]}>{statusLabels[source.status]}</Badge>
              </div>
              <p className="text-xs leading-5 text-muted-foreground">{source.scope}</p>
              <div className="text-xs leading-5 text-muted-foreground">
                <p>{source.freshness}</p>
                {source.limitations.length ? (
                  <p className="mt-1 border-l-2 border-warning/40 pl-2">{source.limitations[0]}</p>
                ) : null}
              </div>
            </article>
          ))}
        </div>

        <div className="flex items-start gap-2 border-t border-border/70 pt-4 text-xs leading-5 text-muted-foreground">
          <CircleAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <p>{data.incident_message}</p>
        </div>
      </CardContent>
    </Card>
  );
}
