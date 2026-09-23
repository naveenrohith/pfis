import { ArrowRight, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/Button';

export function PageIntro({
  eyebrow,
  title,
  description,
  action,
  className,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn('flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between', className)}
    >
      <div className="max-w-4xl">
        {eyebrow ? (
          <p className="mb-2 text-[10px] font-extrabold uppercase tracking-[0.14em] text-muted-foreground">
            {eyebrow}
          </p>
        ) : null}
        <h1 className="text-balance text-3xl font-extrabold leading-[1.08] tracking-[-0.045em] sm:text-4xl lg:text-[2.8rem]">
          {title}
        </h1>
        {description ? (
          <div className="mt-3 max-w-2xl text-pretty text-sm leading-6 text-muted-foreground sm:text-base">
            {description}
          </div>
        ) : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </header>
  );
}

export function FinancialHero({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn('relative overflow-hidden rounded-2xl bg-jade/10 p-5 sm:p-6 lg:p-7', className)}
    >
      {children}
    </section>
  );
}

export function WorkspaceContextBar({
  label,
  description,
  children,
  className,
}: {
  label: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      aria-label={label}
      data-testid="workspace-context-bar"
      className={cn(
        'workspace-context-strip rounded-xl border border-border/70 bg-background/95 p-2 backdrop-blur-xl lg:sticky lg:top-[5.75rem] lg:z-20',
        className,
      )}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
        <div className="hidden min-w-0 px-3 py-1 lg:block">
          <p className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-muted-foreground">
            {label}
          </p>
          {description ? (
            <p className="mt-0.5 truncate text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </section>
  );
}

export function DecisionStrip({
  items,
  className,
}: {
  items: Array<{
    label: string;
    value: React.ReactNode;
    tone?: 'neutral' | 'positive' | 'attention';
  }>;
  className?: string;
}) {
  return (
    <dl
      className={cn(
        'decision-strip grid gap-px overflow-hidden rounded-xl border border-border/70 bg-border/70 sm:grid-cols-3',
        className,
      )}
    >
      {items.map((item) => (
        <div key={item.label} className="min-w-0 bg-card px-4 py-3.5 sm:px-5">
          <dt className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
            {item.label}
          </dt>
          <dd
            className={cn(
              'mt-1 break-words text-sm font-extrabold tracking-[-0.02em]',
              item.tone === 'positive' && 'text-success',
              item.tone === 'attention' && 'text-warning',
            )}
          >
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export type InsightTone = 'neutral' | 'positive' | 'attention' | 'intelligence';

const insightToneClasses: Record<InsightTone, string> = {
  neutral: 'border-border',
  positive: 'border-success/45',
  attention: 'border-warning/50',
  intelligence: 'border-intelligence/45',
};

export function InsightSurface({
  icon,
  eyebrow,
  title,
  description,
  meta,
  tone = 'neutral',
  className,
}: {
  icon?: React.ReactNode;
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  meta?: React.ReactNode;
  tone?: InsightTone;
  className?: string;
}) {
  return (
    <article
      className={cn('border-l-2 py-2 pl-4 pr-2 sm:pl-5', insightToneClasses[tone], className)}
    >
      <div className="flex items-start gap-3">
        {icon ? (
          <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-muted text-foreground">
            {icon}
          </span>
        ) : null}
        <div className="min-w-0">
          {eyebrow ? <p className="text-xs font-bold text-muted-foreground">{eyebrow}</p> : null}
          <h3 className="mt-0.5 text-base font-extrabold leading-6 tracking-[-0.02em]">{title}</h3>
          {description ? (
            <div className="mt-1 text-sm leading-6 text-muted-foreground">{description}</div>
          ) : null}
          {meta ? <div className="mt-3 text-xs text-muted-foreground">{meta}</div> : null}
        </div>
      </div>
    </article>
  );
}

export function ActionSurface({
  icon,
  eyebrow = 'Recommended next',
  title,
  description,
  actionLabel,
  onAction,
  secondary,
  footer,
  className,
}: {
  icon?: React.ReactNode;
  eyebrow?: string;
  title: React.ReactNode;
  description: React.ReactNode;
  actionLabel: string;
  onAction: () => void;
  secondary?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}) {
  return (
    <aside
      className={cn(
        'flex min-h-0 flex-col rounded-2xl bg-surface-strong p-5 text-background shadow-lift sm:p-6',
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-extrabold tracking-wide text-background/65">{eyebrow}</span>
        {icon ? (
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-background/10 text-intelligence">
            {icon}
          </span>
        ) : null}
      </div>
      <h2 className="mt-6 text-balance text-2xl font-extrabold leading-tight tracking-[-0.035em]">
        {title}
      </h2>
      <div className="text-background/72 mt-3 text-pretty text-sm leading-6">{description}</div>
      <div className="mt-6 pt-1">
        <Button
          variant="secondary"
          className="w-full justify-between bg-background text-foreground hover:bg-background/90"
          onClick={onAction}
        >
          {actionLabel}
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Button>
        {secondary ? <div className="text-background/58 mt-3 text-xs">{secondary}</div> : null}
        {footer ? <div className="mt-4 border-t border-background/15 pt-4">{footer}</div> : null}
      </div>
    </aside>
  );
}

export function LedgerRow({
  leading,
  title,
  subtitle,
  amount,
  meta,
  selected,
  onSelect,
  className,
}: {
  leading?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  amount?: React.ReactNode;
  meta?: React.ReactNode;
  selected?: boolean;
  onSelect?: () => void;
  className?: string;
}) {
  const content = (
    <>
      {leading ? (
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-muted text-sm font-extrabold text-muted-foreground">
          {leading}
        </span>
      ) : null}
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-sm font-extrabold tracking-[-0.015em]">{title}</span>
        {subtitle ? (
          <span className="mt-0.5 block truncate text-xs text-muted-foreground">{subtitle}</span>
        ) : null}
      </span>
      {meta ? <span className="hidden text-xs text-muted-foreground sm:block">{meta}</span> : null}
      {amount ? <span className="money-value shrink-0 text-sm">{amount}</span> : null}
      {onSelect ? (
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      ) : null}
    </>
  );

  const classes = cn(
    'flex min-h-[64px] min-w-0 w-full items-center gap-3 border-b border-border/65 px-2 py-3 last:border-b-0 transition-colors',
    selected ? 'bg-primary/10' : 'hover:bg-muted/40',
    className,
  );

  return onSelect ? (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(classes, 'focus-ring')}
    >
      {content}
    </button>
  ) : (
    <div className={classes}>{content}</div>
  );
}

export function ChartFrame({
  title,
  description,
  summary,
  children,
  dataTable,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  summary: string;
  children: React.ReactNode;
  dataTable?: React.ReactNode;
  className?: string;
}) {
  return (
    <figure className={cn('min-w-0', className)}>
      <figcaption className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-lg font-extrabold tracking-[-0.025em]">{title}</h3>
          {description ? (
            <div className="mt-1 text-sm text-muted-foreground">{description}</div>
          ) : null}
        </div>
      </figcaption>
      <p className="sr-only">{summary}</p>
      <div aria-hidden="true">{children}</div>
      {dataTable ? (
        <details className="mt-4 border-t border-border/65 pt-3 text-sm">
          <summary className="focus-ring cursor-pointer rounded-md py-2 font-bold text-muted-foreground hover:text-foreground">
            View chart data
          </summary>
          <div className="mt-3 overflow-x-auto">{dataTable}</div>
        </details>
      ) : null}
    </figure>
  );
}
