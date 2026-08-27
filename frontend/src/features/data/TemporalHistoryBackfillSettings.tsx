import { useMutation } from '@tanstack/react-query';
import { History, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';
import { api } from '@/lib/api';
import type { TemporalHistoryBackfillResponse } from '@/lib/types';

const SOURCE_LABELS = {
  transaction: 'Transactions',
  financial_account: 'Account identity',
  statement_line: 'Issuer statement lines',
  card_payment_intent: 'Planned card payments',
} as const;

export function TemporalHistoryBackfillSettings() {
  const { user } = useAuth();
  const { notify } = useToast();
  const preview = useMutation({
    mutationFn: async () => {
      if (!user) throw new Error('Sign in to inspect historical evidence.');
      return api.backfillTemporalHistory(user.id, true);
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  const capture = useMutation({
    mutationFn: async () => {
      if (!user) throw new Error('Sign in to capture historical evidence.');
      return api.backfillTemporalHistory(user.id, false);
    },
    onSuccess: (result) =>
      notify(
        result.sources.some((source) => source.captured_count > 0)
          ? 'Historical evidence baseline captured'
          : 'Historical evidence is already up to date',
        'success',
      ),
    onError: (error) => notify((error as Error).message, 'error'),
  });

  const result: TemporalHistoryBackfillResponse | undefined = capture.data ?? preview.data;
  const isPending = preview.isPending || capture.isPending;

  return (
    <Card className="border border-border">
      <CardHeader className="border-b border-border/70">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 rounded-lg bg-intelligence/10 p-2 text-intelligence">
            <History aria-hidden="true" className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <CardTitle className="text-pretty">Prepare historical evidence</CardTitle>
            <CardDescription className="mt-1 max-w-2xl text-pretty">
              Capture a forward-only baseline for older transactions, account identities, issuer
              statement lines, and planned card payments that predate PFIS&apos;s immutable history
              hooks.
            </CardDescription>
          </div>
          <Badge variant="outline" className="ml-auto shrink-0">
            Evidence only
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="pt-5 sm:pt-6">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div>
            <p className="text-sm leading-6 text-muted-foreground">
              This does not rewrite transactions, balances, or decisions. It records what PFIS can
              see now so future forecasts can measure their cutoff coverage honestly.
            </p>
            <p className="mt-2 flex items-start gap-2 text-xs leading-5 text-muted-foreground">
              <ShieldCheck aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-success" />
              A baseline capture never claims to reconstruct what was known on an earlier date.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row lg:flex-col">
            <Button
              variant="outline"
              onClick={() => preview.mutate()}
              disabled={!user || isPending}
            >
              {preview.isPending ? 'Checking…' : 'Preview missing evidence'}
            </Button>
            <Button onClick={() => capture.mutate()} disabled={!user || isPending}>
              {capture.isPending ? 'Capturing…' : 'Capture baseline'}
            </Button>
          </div>
        </div>

        {result ? (
          <div className="mt-5 border-t border-border/70 pt-4" aria-live="polite">
            <div className="grid gap-2 sm:grid-cols-2">
              {result.sources.map((source) => (
                <div key={source.source_type} className="rounded-lg bg-muted/45 p-3">
                  <p className="text-xs font-bold text-muted-foreground">
                    {SOURCE_LABELS[source.source_type]}
                  </p>
                  <p className="mt-1 text-sm font-extrabold">
                    {source.missing_snapshot_count} missing · {source.captured_count} captured
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {source.candidate_count} observed · {source.skipped_count} already recorded
                    {source.truncated ? ' · preview limit reached' : ''}
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs leading-5 text-muted-foreground">{result.limitations[0]}</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
