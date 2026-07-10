import { ChevronLeft, ChevronRight, RefreshCw, LogOut, Calendar, WalletCards } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ThemeToggle } from './ThemeToggle';
import { GlobalSearch } from '@/features/search/GlobalSearch';
import { useAuth } from '@/features/auth/AuthContext';
import { useWorkspace } from '@/features/workspace/WorkspaceContext';
import { useSync } from '@/features/workspace/SyncContext';
import { formatCountdown, initials, monthLabel } from '@/lib/format';

export function Header() {
  const { user, session, logout } = useAuth();
  const { month, year, isCurrentMonth, goPrev, goNext, goToday } = useWorkspace();
  const { running, runSync } = useSync();

  const countdown =
    session?.mode === 'demo' ? 'demo workspace' : formatCountdown(session?.expiresAt ?? null);

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-card/90 backdrop-blur-xl">
      <div className="flex w-full flex-wrap items-center gap-2 px-3 py-3 sm:gap-3 sm:px-5 lg:px-8 2xl:px-10">
        <div className="flex min-w-[8rem] items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm shadow-primary/25">
            <WalletCards className="h-5 w-5" />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-bold">PFIS</p>
            <p className="hidden text-xs text-muted-foreground sm:block">Finance Intelligence</p>
          </div>
        </div>

        <div className="order-3 flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-muted/45 p-1 sm:order-none sm:w-auto">
          <Button variant="ghost" size="icon" onClick={goPrev} aria-label="Previous month">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="min-w-[8.5rem] text-center text-sm font-semibold sm:min-w-[9rem]">
            {monthLabel(month, year)}
          </span>
          <Button
            variant="ghost"
            size="icon"
            onClick={goNext}
            disabled={isCurrentMonth}
            aria-label="Next month"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
        {!isCurrentMonth && (
          <Button variant="ghost" size="sm" onClick={goToday} className="order-4 sm:order-none">
            <Calendar className="mr-1 h-3.5 w-3.5" /> Today
          </Button>
        )}

        <div className="order-5 w-full md:order-none md:ml-auto md:w-auto">
          <GlobalSearch />
        </div>

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2 md:ml-0">
          <Button onClick={runSync} disabled={running} size="sm">
            <RefreshCw className={`mr-1 h-3.5 w-3.5 ${running ? 'animate-spin' : ''}`} />
            {running ? 'Syncing…' : 'Sync inbox'}
          </Button>
          <ThemeToggle />
          <div className="hidden items-center gap-2 sm:flex">
            <div className="text-right leading-tight">
              <p className="max-w-[12rem] truncate text-sm font-semibold">{user?.name ?? user?.email}</p>
              {countdown && (
                <p className="text-xs text-muted-foreground">
                  {session?.mode === 'demo' ? countdown : `Session: ${countdown}`}
                </p>
              )}
            </div>
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-sm font-bold text-accent-foreground">
              {initials(user?.name || user?.email || '?')}
            </span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => logout()}
            aria-label={session?.mode === 'demo' ? 'End demo' : 'Sign out'}
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </div>
      {session?.mode === 'demo' && (
        <div className="bg-info/10 py-1 text-center text-xs font-medium text-info">
          <Badge variant="info" className="mr-1">
            Demo
          </Badge>
          You are viewing seeded sample data.
        </div>
      )}
    </header>
  );
}
