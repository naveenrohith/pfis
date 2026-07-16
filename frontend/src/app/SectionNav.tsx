import { Activity, Database, House, LineChart, Plus, Target } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useDashboardUi } from './DashboardUiContext';
import { WORKSPACES, type WorkspaceId } from './workspaceNavigation';

const NAV_ICONS = {
  today: House,
  activity: Activity,
  plan: Target,
  insights: LineChart,
  data: Database,
} satisfies Record<WorkspaceId, typeof House>;

export function SectionNav() {
  const { activeWorkspace, openWorkspace, setQuickAddOpen } = useDashboardUi();

  return (
    <aside className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:border-r lg:border-t-0 lg:bg-secondary/55 lg:p-3">
      <div className="hidden h-14 place-items-center lg:grid">
        <button
          type="button"
          onClick={() => openWorkspace('today')}
          className="focus-ring grid h-11 w-11 place-items-center rounded-lg bg-primary text-sm font-extrabold text-primary-foreground shadow-lift"
          aria-label="PFIS Today"
        >
          P
        </button>
      </div>

      <nav
        aria-label="Primary financial destinations"
        className="grid grid-cols-5 lg:mt-6 lg:flex lg:flex-1 lg:flex-col lg:gap-2"
      >
        {WORKSPACES.map((workspace) => {
          const Icon = NAV_ICONS[workspace.id];
          const active = workspace.id === activeWorkspace;
          return (
            <button
              type="button"
              key={workspace.id}
              onClick={() => openWorkspace(workspace.id)}
              className={cn(
                'focus-ring group relative flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 rounded-lg px-1 text-[10px] font-bold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:min-h-14 lg:text-[9px]',
                active && 'bg-primary/10 text-primary',
              )}
              aria-current={active ? 'page' : undefined}
              aria-label={workspace.label}
              title={workspace.label}
            >
              <Icon className="h-5 w-5" aria-hidden="true" />
              <span className="w-full truncate text-center text-foreground">
                {workspace.shortLabel}
              </span>
              {active ? (
                <span className="absolute left-0 hidden h-5 w-0.5 rounded-full bg-primary lg:block" />
              ) : null}
            </button>
          );
        })}
      </nav>

      <button
        type="button"
        onClick={() => setQuickAddOpen(true)}
        className="focus-ring absolute bottom-[5.2rem] right-4 grid h-12 w-12 place-items-center rounded-full bg-primary text-primary-foreground shadow-lift lg:static lg:mt-3 lg:h-14 lg:w-full lg:rounded-lg"
        aria-label="Quick add activity"
        title="Quick add activity"
      >
        <Plus className="h-5 w-5" aria-hidden="true" />
      </button>
    </aside>
  );
}
