import { Menu as BaseMenu } from '@base-ui/react/menu';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface MenuItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  disabled?: boolean;
  destructive?: boolean;
  onSelect: () => void;
}

interface MenuProps {
  label: React.ReactNode;
  accessibleLabel: string;
  items: MenuItem[];
  className?: string;
  align?: 'start' | 'center' | 'end';
}

export function Menu({ label, accessibleLabel, items, className, align = 'end' }: MenuProps) {
  return (
    <BaseMenu.Root>
      <BaseMenu.Trigger
        aria-label={accessibleLabel}
        className={cn(
          'focus-ring inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm font-bold text-foreground transition-colors hover:bg-muted',
          className,
        )}
      >
        {label}
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
      </BaseMenu.Trigger>
      <BaseMenu.Portal>
        <BaseMenu.Positioner align={align} sideOffset={7} className="z-[70]">
          <BaseMenu.Popup className="min-w-52 animate-fade-in rounded-lg bg-card p-1.5 text-card-foreground shadow-float outline-none">
            {items.map((item) => (
              <BaseMenu.Item
                key={item.id}
                disabled={item.disabled}
                onClick={item.onSelect}
                className={cn(
                  'flex min-h-10 cursor-default items-center gap-2 rounded-md px-3 text-sm font-semibold outline-none transition-colors data-[highlighted]:bg-muted',
                  item.destructive && 'text-danger data-[highlighted]:bg-danger/10',
                  item.disabled && 'opacity-45',
                )}
              >
                {item.icon}
                {item.label}
              </BaseMenu.Item>
            ))}
          </BaseMenu.Popup>
        </BaseMenu.Positioner>
      </BaseMenu.Portal>
    </BaseMenu.Root>
  );
}
