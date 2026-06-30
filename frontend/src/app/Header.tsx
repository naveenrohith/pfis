import { ChevronLeft, ChevronRight, RefreshCw, LogOut, Calendar } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ThemeToggle } from './ThemeToggle';
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
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-lg font-bold text-primary-foreground">
            ₹
          </span>
          <div className="leading-tight">
            <p className="text-sm font-bold">PFIS</p>
            <p className="text-xs text-muted-foreground">Finance Intelligence</p>
          </div>
        </div>

        {/* Month nav */}
        <div className="flex items-center gap-1 rounded-full border border-border bg-card p-1">
          <Button variant="ghost" size="icon" onClick={goPrev} aria-label="Previous month">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="min-w-[8.5rem] text-center text-sm font-semibold">
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
          <Button variant="ghost" size="sm" onClick={goToday}>
            <Calendar className="mr-1 h-3.5 w-3.5" /> Today
          </Button>
        )}

        <div className="ml-auto flex items-center gap-2">
          <Button onClick={runSync} disabled={running} size="sm">
            <RefreshCw className={`mr-1 h-3.5 w-3.5 ${running ? 'animate-spin' : ''}`} />
            {running ? 'Syncing…' : 'Sync inbox'}
          </Button>
          <ThemeToggle />
          <div className="hidden items-center gap-2 sm:flex">
            <div className="text-right leading-tight">
              <p className="text-sm font-semibold">{user?.name ?? user?.email}</p>
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
