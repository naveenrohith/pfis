import { Activity, Database, House, LineChart, Plus, ShieldCheck, Target } from 'lucide-react';
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
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:border-r lg:border-t-0 lg:bg-card/70 lg:px-4 lg:py-5"
    >
      <div className="hidden items-center gap-3 border-b border-border/70 pb-5 lg:flex">
        <button
          type="button"
          onClick={() => openWorkspace('today')}
          className="focus-ring grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-primary text-sm font-extrabold text-primary-foreground shadow-lift"
          aria-label="PFIS Today"
        >
          P
        </button>
        <div className="min-w-0">
          <p className="text-sm font-extrabold tracking-[-0.02em]">PFIS</p>
          <p className="truncate text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
            Financial workspace
          </p>
        </div>
      </div>

      <nav
        aria-label="Primary financial destinations"
        className="grid grid-cols-5 lg:mt-6 lg:flex lg:flex-1 lg:flex-col lg:gap-1.5"
      >
        <p className="sr-only lg:not-sr-only lg:mb-2 lg:px-3 lg:text-[10px] lg:font-extrabold lg:uppercase lg:tracking-[0.14em] lg:text-muted-foreground">
          Workspaces
        </p>
        {WORKSPACES.map((workspace) => {
          const Icon = NAV_ICONS[workspace.id];
          const active = workspace.id === activeWorkspace;
          return (
            <button
              type="button"
              key={workspace.id}
              onClick={() => openWorkspace(workspace.id)}
              className={cn(
                'focus-ring group relative flex min-h-16 min-w-0 flex-col items-center justify-center gap-1 rounded-lg px-1 text-[10px] font-bold text-muted-foreground transition-[background-color,color] duration-150 hover:bg-muted hover:text-foreground lg:min-h-[4.25rem] lg:flex-row lg:items-start lg:gap-3 lg:px-3 lg:py-3 lg:text-left',
                active && 'bg-primary/10 text-primary lg:bg-primary/[0.12]',
              )}
              aria-current={active ? 'page' : undefined}
              aria-label={workspace.label}
              title={workspace.label}
            >
              <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
              <span className="min-w-0 lg:pr-1">
                <span className="block w-full truncate text-center text-foreground lg:text-left">
                  {workspace.shortLabel}
                </span>
                <span className="mt-0.5 hidden text-[11px] font-medium leading-4 text-muted-foreground lg:block">
                  {workspace.description}
                </span>
              </span>
              {active ? (
                <span className="absolute left-0 hidden h-8 w-0.5 rounded-full bg-primary lg:block" />
              ) : null}
            </button>
          );
        })}
      </nav>

      <button
        type="button"
        onClick={() => setQuickAddOpen(true)}
        className="focus-ring absolute bottom-[5.2rem] right-4 grid h-12 w-12 place-items-center rounded-full bg-primary text-primary-foreground shadow-lift lg:static lg:mt-4 lg:flex lg:h-11 lg:w-full lg:items-center lg:justify-center lg:gap-2 lg:rounded-lg"
        aria-label="Quick add activity"
        title="Quick add activity"
      >
        <Plus className="h-5 w-5" aria-hidden="true" />
        <span className="hidden text-sm font-extrabold lg:inline">Add activity</span>
      </button>

      <div className="mt-4 hidden items-center gap-2 border-t border-border/70 px-2 pt-4 text-[10px] font-bold text-muted-foreground lg:flex">
        <ShieldCheck className="h-3.5 w-3.5 text-success" aria-hidden="true" />
        Private by design
      </div>
    </aside>
  );
}
