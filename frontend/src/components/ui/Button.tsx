import { forwardRef } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-bold transition-[background-color,color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:translate-y-px disabled:pointer-events-none disabled:opacity-45 disabled:active:translate-y-0',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground shadow-lift hover:bg-primary/90',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-muted',
        ghost: 'text-foreground hover:bg-muted',
        outline: 'border border-border bg-card/45 hover:border-foreground/20 hover:bg-card',
        danger: 'bg-danger text-danger-foreground hover:bg-danger/90',
        link: 'h-auto px-0 text-primary underline-offset-4 hover:underline active:translate-y-0',
      },
      size: {
        sm: 'h-9 px-3 text-xs',
        md: 'h-11 px-4',
        lg: 'h-12 px-6 text-base',
        icon: 'h-11 w-11 p-0',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = 'button', ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);
Button.displayName = 'Button';
