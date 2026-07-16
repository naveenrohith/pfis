import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip';

interface TooltipProps {
  label: string;
  children: React.ReactElement;
  side?: 'top' | 'right' | 'bottom' | 'left';
}

export function Tooltip({ label, children, side = 'top' }: TooltipProps) {
  return (
    <BaseTooltip.Provider delay={450} closeDelay={80}>
      <BaseTooltip.Root>
        <BaseTooltip.Trigger render={children} />
        <BaseTooltip.Portal>
          <BaseTooltip.Positioner side={side} sideOffset={8} className="z-[70]">
            <BaseTooltip.Popup className="max-w-64 animate-fade-in rounded-md bg-surface-strong px-2.5 py-1.5 text-xs font-semibold leading-5 text-background shadow-lift">
              {label}
            </BaseTooltip.Popup>
          </BaseTooltip.Positioner>
        </BaseTooltip.Portal>
      </BaseTooltip.Root>
    </BaseTooltip.Provider>
  );
}
