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
    <aside
      data-testid="workspace-rail"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] md:sticky md:inset-x-auto md:bottom-auto md:top-0 md:flex md:h-screen md:w-[88px] md:flex-col md:border-r md:border-t-0 md:bg-secondary/55 md:p-3"
    >
      <div className="hidden h-14 place-items-center md:grid">
        <button
          type="button"
          onClick={() => openWorkspace('today')}
          className="focus-ring grid h-11 w-11 place-items-center rounded-lg bg-primary text-sm font-extrabold text-primary-foreground shadow-lift"
          aria-label="PFIS Today"
        >
          P
        </button>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_3.25rem] md:contents">
        <nav
          aria-label="Primary financial destinations"
          className="grid min-w-0 grid-cols-5 md:mt-6 md:flex md:flex-1 md:flex-col md:gap-2"
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
                  'focus-ring group relative flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 rounded-lg px-1 text-[10px] font-bold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:min-h-14 md:text-[9px]',
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
                  <span className="absolute left-0 hidden h-5 w-0.5 rounded-full bg-primary md:block" />
                ) : null}
              </button>
            );
          })}
        </nav>

        <button
          type="button"
          onClick={() => setQuickAddOpen(true)}
          className="focus-ring grid min-h-16 place-items-center rounded-lg bg-primary text-primary-foreground shadow-lift md:hidden"
          aria-label="Quick add activity"
          title="Quick add activity"
        >
          <Plus className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      <button
        type="button"
        onClick={() => setQuickAddOpen(true)}
        className="focus-ring hidden h-14 w-full place-items-center rounded-lg bg-primary text-primary-foreground shadow-lift md:static md:mt-3 md:grid"
        aria-label="Quick add activity"
        title="Quick add activity"
      >
        <Plus className="h-5 w-5" aria-hidden="true" />
      </button>
    </aside>
  );
}
