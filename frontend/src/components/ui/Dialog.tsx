import { Dialog as BaseDialog } from '@base-ui/react/dialog';
import { X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

export function Dialog({ open, onClose, title, description, children, className }: DialogProps) {
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  return (
    <BaseDialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <BaseDialog.Portal>
        <BaseDialog.Backdrop className="bg-foreground/32 fixed inset-0 z-50 backdrop-blur-[2px] transition-opacity" />
        <BaseDialog.Viewport className="fixed inset-0 z-50 grid min-h-full place-items-center overflow-y-auto p-4 sm:p-8">
          <BaseDialog.Popup
            ref={popupRef}
            aria-modal="true"
            initialFocus={() =>
              popupRef.current?.querySelector<HTMLElement>(
                '[data-dialog-initial-focus], input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
              ) ?? true
            }
            className={cn(
              'relative w-full max-w-md animate-fade-in rounded-xl bg-card p-6 text-card-foreground shadow-float outline-none sm:p-7',
              className,
            )}
          >
            <div className="mb-5 pr-12">
              <BaseDialog.Title className="text-xl font-extrabold leading-tight tracking-[-0.03em]">
                {title}
              </BaseDialog.Title>
              {description ? (
                <BaseDialog.Description className="mt-1.5 text-sm leading-6 text-muted-foreground">
                  {description}
                </BaseDialog.Description>
              ) : null}
            </div>
            <BaseDialog.Close
              aria-label="Close dialog"
              className="focus-ring absolute right-4 top-4 grid h-11 w-11 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </BaseDialog.Close>
            {children}
          </BaseDialog.Popup>
        </BaseDialog.Viewport>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  );
}
