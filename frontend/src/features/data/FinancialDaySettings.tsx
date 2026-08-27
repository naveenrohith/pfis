import { useEffect, useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { CalendarClock } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input, Label } from '@/components/ui/Input';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';

const FALLBACK_TIMEZONES = [
  'UTC',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Australia/Sydney',
  'Europe/London',
  'Europe/Paris',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
];

const timezoneProvider = Intl as typeof Intl & {
  supportedValuesOf?: (key: 'timeZone') => string[];
};
const SUPPORTED_TIMEZONES = timezoneProvider.supportedValuesOf?.('timeZone') ?? FALLBACK_TIMEZONES;

function formatBoundary(timezone: string): string | null {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'full',
      timeStyle: 'short',
      timeZone: timezone,
    }).format(new Date());
  } catch {
    return null;
  }
}

export function FinancialDaySettings() {
  const { user, updateProfile } = useAuth();
  const { notify } = useToast();
  const [timezone, setTimezone] = useState(user?.timezone ?? 'Asia/Kolkata');

  useEffect(() => {
    if (user?.timezone) setTimezone(user.timezone);
  }, [user?.timezone]);

  const boundary = useMemo(() => formatBoundary(timezone.trim()), [timezone]);
  const save = useMutation({
    mutationFn: () => updateProfile({ timezone: timezone.trim() }),
    onSuccess: () => notify('Financial day saved', 'success'),
    onError: (error) => notify((error as Error).message, 'error'),
  });
  const unchanged = timezone.trim() === user?.timezone;

  return (
    <Card className="border border-border">
      <CardHeader className="border-b border-border/70">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 rounded-lg bg-intelligence/10 p-2 text-intelligence">
            <CalendarClock aria-hidden="true" className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <CardTitle className="text-pretty">Choose when your financial day changes</CardTitle>
            <CardDescription className="mt-1 max-w-2xl text-pretty">
              PFIS uses this boundary for Today, balance freshness, recurring expectations, and
              forecasts. Source transaction dates remain unchanged.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-5 sm:pt-6">
        <form
          className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.7fr)] lg:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            if (boundary && !unchanged && !save.isPending) save.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="financial-timezone">IANA timezone</Label>
            <Input
              id="financial-timezone"
              name="timezone"
              list="financial-timezones"
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              aria-describedby="financial-timezone-help financial-timezone-error"
            />
            <datalist id="financial-timezones">
              {SUPPORTED_TIMEZONES.map((value) => (
                <option key={value} value={value} />
              ))}
            </datalist>
            <p id="financial-timezone-help" className="text-xs text-muted-foreground">
              Use a city-based timezone so daylight-saving changes remain correct.
            </p>
            {boundary ? null : (
              <p id="financial-timezone-error" role="alert" className="text-xs text-danger">
                Enter a valid timezone such as Asia/Kolkata or America/New_York.
              </p>
            )}
          </div>

          <div className="rounded-lg bg-muted/55 p-4">
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">
              Current boundary
            </p>
            <p className="mt-1 text-sm font-semibold text-foreground">
              {boundary ?? 'Waiting for a valid timezone'}
            </p>
            <Button
              type="submit"
              className="mt-4 w-full sm:w-auto"
              disabled={!user || !boundary || unchanged || save.isPending}
            >
              {save.isPending ? 'Saving…' : 'Save financial day'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
