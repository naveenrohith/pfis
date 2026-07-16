import type { LucideIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';

export interface ActionCardProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  actionLabel: string;
  onAction?: () => void;
  disabled?: boolean;
  className?: string;
}

/** A prominent call-to-action tile used for primary workspace actions. */
export function ActionCard({
  title,
  description,
  icon: Icon,
  actionLabel,
  onAction,
  disabled,
  className,
}: ActionCardProps) {
  return (
    <Card className={className}>
      <CardContent className="flex h-full flex-col gap-2 p-4">
        <div className="flex items-center gap-2">
          {Icon && (
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-accent-foreground">
              <Icon className="h-4 w-4" />
            </span>
          )}
          <p className="font-bold">{title}</p>
        </div>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
        <Button
          size="sm"
          className={cn('mt-auto w-fit')}
          onClick={onAction}
          disabled={disabled}
        >
          {actionLabel}
        </Button>
      </CardContent>
    </Card>
  );
}
