import { lazy, Suspense } from 'react';
import {
  Calendar,
  ChevronLeft,
  ChevronRight,
  LogOut,
  RefreshCw,
  Search,
  Settings2,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ThemeToggle } from './ThemeToggle';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { useSync } from '@/features/workspace/SyncContext';
import { formatCountdown, initials, monthLabel } from '@/lib/format';
import { useDashboardUi } from './DashboardUiContext';

const GlobalSearch = lazy(() =>
  import('@/features/search/GlobalSearch').then((module) => ({ default: module.GlobalSearch })),
);

export function Header() {
  const { user, session, logout } = useAuth();
  const { month, year, isCurrentMonth, goPrev, goNext, goToday } = useWorkspace();
  const { running, runSync } = useSync();
  const { setCustomizeOpen, setCommandOpen } = useDashboardUi();
  const countdown =
    session?.mode === 'demo' ? 'Demo workspace' : formatCountdown(session?.expiresAt ?? null);

  return (
    <header className="sticky top-0 z-30 border-b border-border/70 bg-background/90 backdrop-blur-xl">
      <div className="flex h-16 items-center justify-between gap-2 px-3 sm:px-6 lg:h-[72px] lg:px-8">
        <div className="flex min-w-0 items-center gap-1">
          <Button variant="ghost" size="icon" onClick={goPrev} aria-label="Previous month">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <button
            type="button"
            onClick={goToday}
            className="focus-ring min-h-11 min-w-0 rounded-lg px-1 text-sm font-extrabold sm:min-w-32 sm:px-3"
            aria-label={`${monthLabel(month, year)}. Go to current month`}
          >
            <span className="hidden sm:inline">{monthLabel(month, year)}</span>
            <span className="sm:hidden">{monthLabel(month, year).replace(' ', ' ’')}</span>
          </button>
          <Button
            variant="ghost"
            size="icon"
            onClick={goNext}
            disabled={isCurrentMonth}
            aria-label="Next month"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
          {!isCurrentMonth ? (
            <Badge variant="outline" className="ml-1 hidden lg:inline-flex">
              <Calendar className="h-3.5 w-3.5" /> Historical
            </Badge>
          ) : null}
        </div>

        <div className="flex items-center gap-1 sm:gap-1.5">
          <Suspense fallback={null}>
            <GlobalSearch triggerClassName="hidden lg:inline-flex" />
          </Suspense>
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setCommandOpen(true)}
            aria-label="Search or act"
          >
            <Search className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={runSync}
            disabled={running}
            aria-label={running ? 'Syncing inbox' : 'Sync inbox'}
            title={running ? 'Syncing inbox' : 'Sync inbox'}
          >
            <RefreshCw className={`h-4 w-4 ${running ? 'animate-spin' : ''}`} />
          </Button>

          <details className="group relative">
            <summary
              className="focus-ring ml-0.5 grid h-11 w-11 cursor-pointer list-none place-items-center rounded-full bg-accent text-xs font-extrabold text-accent-foreground hover:bg-accent/80 [&::-webkit-details-marker]:hidden"
              aria-label="Open account menu"
            >
              {initials(user?.name || user?.email || '?')}
            </summary>
            <div className="shadow-overlay absolute right-0 top-[3.25rem] z-50 w-64 rounded-xl bg-card p-2 ring-1 ring-border">
              <div className="px-3 py-2">
                <p className="truncate text-sm font-extrabold">{user?.name || user?.email}</p>
                {countdown ? (
                  <p className="mt-1 text-xs text-muted-foreground">{countdown}</p>
                ) : null}
              </div>
              <div className="my-1 border-t border-border" />
              <div className="flex items-center justify-between rounded-lg px-3 py-1.5 text-sm font-bold">
                Appearance <ThemeToggle />
              </div>
              <button
                type="button"
                onClick={() => setCustomizeOpen(true)}
                className="focus-ring flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-bold hover:bg-muted"
              >
                <Settings2 className="h-4 w-4" /> Preferences
              </button>
              <button
                type="button"
                onClick={() => logout()}
                className="focus-ring flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-bold text-danger hover:bg-danger/10"
              >
                <LogOut className="h-4 w-4" /> {session?.mode === 'demo' ? 'End demo' : 'Sign out'}
              </button>
            </div>
          </details>
        </div>
      </div>
      {session?.mode === 'demo' ? (
        <div className="bg-info/10 py-1 text-center text-xs font-medium text-foreground">
          <Badge variant="info" className="mr-1 text-foreground">
            Demo
          </Badge>
          Seeded sample data
        </div>
      ) : null}
    </header>
  );
}
