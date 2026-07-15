import { Tabs as BaseTabs } from '@base-ui/react/tabs';
import { cn } from '@/lib/utils';

export interface TabOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface TabsProps {
  options: TabOption[];
  value: string;
  onValueChange: (value: string) => void;
  ariaLabel: string;
  className?: string;
}

export function Tabs({ options, value, onValueChange, ariaLabel, className }: TabsProps) {
  return (
    <BaseTabs.Root
      value={value}
      onValueChange={(nextValue) => {
        if (typeof nextValue === 'string') onValueChange(nextValue);
      }}
      className={className}
    >
      <BaseTabs.List
        aria-label={ariaLabel}
        className="scrollbar-none relative flex min-h-11 max-w-full items-center gap-1 overflow-x-auto rounded-lg bg-secondary/75 p-1"
      >
        {options.map((option) => (
          <BaseTabs.Tab
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            className={cn(
              'focus-ring relative z-10 min-h-9 shrink-0 rounded-md px-3 text-sm font-bold text-muted-foreground transition-colors',
              'disabled:cursor-not-allowed disabled:opacity-45 data-[active]:text-foreground',
            )}
          >
            {option.label}
          </BaseTabs.Tab>
        ))}
        <BaseTabs.Indicator className="absolute bottom-1 left-[var(--active-tab-left)] top-1 w-[var(--active-tab-width)] rounded-md bg-card shadow-lift transition-[left,width] duration-200" />
      </BaseTabs.List>
    </BaseTabs.Root>
  );
}
