import { Select as BaseSelect } from '@base-ui/react/select';
import { Check, ChevronsUpDown } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectFieldProps {
  label: string;
  value: string | null;
  options: SelectOption[];
  onValueChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

export function SelectField({
  label,
  value,
  options,
  onValueChange,
  placeholder = 'Select an option',
  className,
}: SelectFieldProps) {
  return (
    <BaseSelect.Root
      value={value}
      items={options}
      onValueChange={(nextValue) => {
        if (typeof nextValue === 'string') onValueChange(nextValue);
      }}
    >
      <BaseSelect.Label className="mb-1.5 block text-sm font-bold text-foreground">
        {label}
      </BaseSelect.Label>
      <BaseSelect.Trigger
        className={cn(
          'focus-ring flex h-11 w-full items-center justify-between gap-3 rounded-lg border border-input bg-card/80 px-3.5 text-left text-sm transition-colors hover:bg-card',
          className,
        )}
      >
        <BaseSelect.Value placeholder={placeholder} />
        <BaseSelect.Icon>
          <ChevronsUpDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        </BaseSelect.Icon>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner sideOffset={6} className="z-[70]">
          <BaseSelect.Popup className="min-w-[var(--anchor-width)] animate-fade-in rounded-lg bg-card p-1.5 text-card-foreground shadow-float outline-none">
            <BaseSelect.List>
              {options.map((option) => (
                <BaseSelect.Item
                  key={option.value}
                  value={option.value}
                  disabled={option.disabled}
                  className="flex min-h-10 cursor-default items-center gap-2 rounded-md px-3 text-sm font-semibold outline-none transition-colors data-[highlighted]:bg-muted data-[disabled]:opacity-45"
                >
                  <BaseSelect.ItemIndicator className="text-primary">
                    <Check className="h-4 w-4" aria-hidden="true" />
                  </BaseSelect.ItemIndicator>
                  <BaseSelect.ItemText>{option.label}</BaseSelect.ItemText>
                </BaseSelect.Item>
              ))}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  );
}
