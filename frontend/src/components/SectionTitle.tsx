import { cn } from '@/lib/utils';

export function SectionTitle({
  eyebrow,
  title,
  description,
  action,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('mb-4 flex flex-wrap items-end justify-between gap-3', className)}>
      <div>
        {eyebrow && (
          <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
            {eyebrow}
          </p>
        )}
        <h2 className="text-xl font-bold">{title}</h2>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}
