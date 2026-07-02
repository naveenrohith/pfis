import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex min-h-6 items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold leading-none',
  {
    variants: {
      variant: {
        default: 'bg-secondary text-secondary-foreground',
        primary: 'bg-accent text-accent-foreground',
        success: 'bg-success/15 text-success ring-1 ring-success/20',
        warning: 'bg-warning/15 text-warning ring-1 ring-warning/20',
        danger: 'bg-danger/15 text-danger ring-1 ring-danger/20',
        info: 'bg-info/15 text-info ring-1 ring-info/20',
        outline: 'border border-border text-muted-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
