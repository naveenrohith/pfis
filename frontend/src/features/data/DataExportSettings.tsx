import { useMutation } from '@tanstack/react-query';
import { Download, FileCheck2, ShieldCheck } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { api } from '@/lib/api';

const INCLUDED_GROUPS = [
  'Profile, workspace preferences, and financial-day settings',
  'Transactions, source evidence, corrections, and import history',
  'Accounts, plans, budgets, goals, liabilities, and health records',
  'Forecast snapshots and their later measured outcomes',
  'Temporal decisions and planning history used for historical forecasts',
  'Recommendation decisions, relevance feedback, and outcome checks',
  'Your household records, with other members replaced by stable aliases',
];

const EXCLUDED_GROUPS = [
  'Password hashes, login sessions, and CSRF or OAuth state',
  'Gmail access and refresh credentials',
  'Temporary job leases and PFIS-wide merchant reference data',
];

function saveDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function DataExportSettings() {
  const { user } = useAuth();
  const { notify } = useToast();
  const exportData = useMutation({
    mutationFn: async () => {
      if (!user) throw new Error('Sign in to export your data.');
      return api.portableExport(user.id);
    },
    onSuccess: ({ blob, filename }) => {
      saveDownload(blob, filename);
      notify('Portable copy downloaded', 'success');
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });

  return (
    <Card className="border border-border">
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 rounded-lg bg-intelligence/10 p-2 text-intelligence">
              <FileCheck2 aria-hidden="true" className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <CardTitle className="text-pretty">Take a portable copy of your PFIS data</CardTitle>
              <CardDescription className="mt-1 max-w-2xl text-pretty">
                A structured ZIP for safekeeping or migration. Review its manifest before you
                download: the archive includes source evidence and may contain sensitive financial
                details.
              </CardDescription>
            </div>
          </div>
          <span className="w-fit rounded-full border border-border bg-muted/55 px-3 py-1 text-xs font-bold text-muted-foreground">
            Schema version 6
          </span>
        </div>
      </CardHeader>

      <CardContent className="pt-5 sm:pt-6">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(18rem,0.85fr)]">
          <section aria-labelledby="portable-included">
            <h4 id="portable-included" className="text-sm font-extrabold text-foreground">
              Included record groups
            </h4>
            <ul className="mt-3 space-y-2">
              {INCLUDED_GROUPS.map((group) => (
                <li key={group} className="flex gap-2 text-sm text-muted-foreground">
                  <FileCheck2 aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                  <span>{group}</span>
                </li>
              ))}
            </ul>
          </section>

          <section
            aria-labelledby="portable-excluded"
            className="border-t border-border/70 pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0"
          >
            <h4 id="portable-excluded" className="flex items-center gap-2 text-sm font-extrabold">
              <ShieldCheck aria-hidden="true" className="h-4 w-4 text-success" />
              Always excluded
            </h4>
            <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
              {EXCLUDED_GROUPS.map((group) => (
                <li key={group}>{group}</li>
              ))}
            </ul>
            <p className="mt-4 border-l-2 border-intelligence/45 pl-3 text-xs leading-relaxed text-muted-foreground">
              The included manifest lists every exported file, field, row count, and checksum so the
              copy can be inspected and verified without PFIS.
            </p>
          </section>
        </div>

        <div className="mt-6 flex flex-col gap-3 border-t border-border/70 pt-5 sm:flex-row sm:items-center sm:justify-between">
          <p id="portable-export-help" className="max-w-2xl text-xs text-muted-foreground">
            Store the downloaded ZIP securely. Anyone with the file may be able to read your
            financial history and source evidence.
          </p>
          <Button
            onClick={() => exportData.mutate()}
            disabled={!user || exportData.isPending}
            aria-describedby="portable-export-help"
            className="w-full shrink-0 sm:w-auto"
          >
            <Download aria-hidden="true" className="h-4 w-4" />
            {exportData.isPending ? 'Preparing copy…' : 'Download portable copy'}
          </Button>
        </div>

        {exportData.isError ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            The portable copy could not be prepared. {exportData.error.message}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
