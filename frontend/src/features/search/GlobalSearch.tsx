import { Command } from 'cmdk';
import {
  CalendarClock,
  Command as CommandIcon,
  Moon,
  Plus,
  RefreshCw,
  Search,
  Sun,
  WalletCards,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { useDashboardUi } from '@/app/DashboardUiContext';
import { WORKSPACES } from '@/app/workspaceNavigation';
import { useTransactions } from '@/features/workspace/queries';
import { useSync } from '@/features/workspace/SyncContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { useTheme } from '@/components/theme/ThemeProvider';

export function GlobalSearch({ triggerClassName }: { triggerClassName?: string }) {
  const transactions = useTransactions();
  const {
    commandOpen,
    setCommandOpen,
    setQuickAddOpen,
    openWorkspace,
    focusReview,
    setCategoryDrill,
    scrollTo,
  } = useDashboardUi();
  const { runSync, running } = useSync();
  const { goPrev, goNext, goToday, isCurrentMonth } = useWorkspace();
  const { theme, toggleTheme } = useTheme();

  function run(action: () => void) {
    setCommandOpen(false);
    action();
  }

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={`w-full justify-between gap-4 text-muted-foreground md:w-64 ${triggerClassName ?? ''}`}
        onClick={() => setCommandOpen(true)}
        aria-label="Open command palette"
      >
        <span className="flex items-center gap-2">
          <Search className="h-4 w-4" /> Search or act
        </span>
        <kbd className="hidden rounded-md border border-border bg-muted px-1.5 py-0.5 text-[10px] font-bold sm:inline">
          ⌘K
        </kbd>
      </Button>

      <Command.Dialog
        open={commandOpen}
        onOpenChange={setCommandOpen}
        label="PFIS command palette"
        overlayClassName="fixed inset-0 z-[70] bg-black/45 backdrop-blur-sm"
        contentClassName="fixed left-1/2 top-[10vh] z-[71] w-[calc(100%-1.5rem)] max-w-2xl -translate-x-1/2 outline-none"
      >
        <div className="overflow-hidden rounded-2xl border border-border bg-card shadow-2xl">
          <div className="flex items-center gap-3 border-b border-border px-4">
            <CommandIcon className="h-4 w-4 text-primary" />
            <Command.Input
              autoFocus
              placeholder="Search transactions, workspaces, or actions…"
              className="h-14 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-[60vh] overflow-y-auto p-2">
            <Command.Empty className="px-4 py-10 text-center text-sm text-muted-foreground">
              No matching transaction or action.
            </Command.Empty>
            <Command.Group heading="Quick actions" className="command-group">
              <PaletteItem icon={<Plus />} onSelect={() => run(() => setQuickAddOpen(true))}>
                Quick add activity
              </PaletteItem>
              <PaletteItem icon={<RefreshCw />} disabled={running} onSelect={() => run(runSync)}>
                Sync inbox
              </PaletteItem>
              <PaletteItem icon={<CalendarClock />} onSelect={() => run(goToday)}>
                Go to current month
              </PaletteItem>
              <PaletteItem
                icon={theme === 'dark' ? <Sun /> : <Moon />}
                onSelect={() => run(toggleTheme)}
              >
                Switch to {theme === 'dark' ? 'light' : 'dark'} theme
              </PaletteItem>
              <PaletteItem icon={<CalendarClock />} onSelect={() => run(goPrev)}>
                Previous month
              </PaletteItem>
              <PaletteItem
                icon={<CalendarClock />}
                disabled={isCurrentMonth}
                onSelect={() => run(goNext)}
              >
                Next month
              </PaletteItem>
            </Command.Group>

            <Command.Group heading="Workspaces" className="command-group">
              {WORKSPACES.map((workspace) => (
                <PaletteItem
                  key={workspace.id}
                  value={`${workspace.label} ${workspace.description}`}
                  icon={<WalletCards />}
                  onSelect={() => run(() => openWorkspace(workspace.id))}
                >
                  <span className="flex-1">{workspace.label}</span>
                  <span className="text-xs text-muted-foreground">{workspace.description}</span>
                </PaletteItem>
              ))}
            </Command.Group>

            <Command.Group heading="Transactions" className="command-group">
              {(transactions.data ?? []).slice(0, 80).map((transaction) => {
                const merchant =
                  transaction.merchant_normalized || transaction.merchant_raw || 'Unknown';
                return (
                  <PaletteItem
                    key={transaction.id}
                    value={`${merchant} ${transaction.category_name ?? ''} ${transaction.reference_id ?? ''}`}
                    icon={<Search />}
                    onSelect={() =>
                      run(() => {
                        if (!transaction.reviewed_flag) focusReview(transaction.id);
                        else if (transaction.category_name) {
                          setCategoryDrill({
                            categoryId: transaction.category_id ?? transaction.category_name,
                            label: transaction.category_name,
                          });
                          scrollTo('transactions');
                        } else scrollTo('transactions');
                      })
                    }
                  >
                    <span className="min-w-0 flex-1 truncate">{merchant}</span>
                    {!transaction.reviewed_flag && <Badge variant="warning">Review</Badge>}
                  </PaletteItem>
                );
              })}
            </Command.Group>
          </Command.List>
          <div className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
            Use ↑↓ to move, Enter to select, and Esc to close.
          </div>
        </div>
      </Command.Dialog>
    </>
  );
}

function PaletteItem({
  icon,
  children,
  className,
  ...props
}: React.ComponentProps<typeof Command.Item> & { icon: React.ReactNode }) {
  return (
    <Command.Item
      className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm outline-none data-[selected=true]:bg-muted data-[selected=true]:text-foreground data-[disabled=true]:opacity-40 ${className ?? ''}`}
      {...props}
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground [&_svg]:h-4 [&_svg]:w-4">
        {icon}
      </span>
      {children}
    </Command.Item>
  );
}
