import { useEffect, useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { History, ShieldCheck } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { SelectField } from '@/components/ui/SelectField';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/features/auth/AuthContext';

const OPTIONS = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '180', label: '180 days' },
  { value: '365', label: '1 year' },
  { value: 'forever', label: 'Keep until I delete it' },
];

function policyValue(value: string): number | null {
  return value === 'forever' ? null : Number(value);
}

function policyLabel(days: number | null): string {
  return days === null ? 'until you delete it' : `for ${days === 365 ? '1 year' : `${days} days`}`;
}

export function RawEmailRetentionSettings() {
  const { user, updateProfile } = useAuth();
  const { notify } = useToast();
  const currentDays = user?.raw_email_retention_days ?? 365;
  const [selection, setSelection] = useState(String(currentDays));
  const [confirmOpen, setConfirmOpen] = useState(false);
  const selectedDays = useMemo(() => policyValue(selection), [selection]);

  useEffect(() => {
    setSelection(user?.raw_email_retention_days === null ? 'forever' : String(currentDays));
  }, [currentDays, user?.raw_email_retention_days]);

  const save = useMutation({
    mutationFn: () => updateProfile({ raw_email_retention_days: selectedDays }),
    onSuccess: () => {
      setConfirmOpen(false);
      notify('Source retention policy saved', 'success');
    },
    onError: (error) => notify((error as Error).message, 'error'),
  });
  const unchanged = selectedDays === user?.raw_email_retention_days;
  const becomesShorter =
    selectedDays !== null &&
    (user?.raw_email_retention_days === null || selectedDays < currentDays);

  function requestSave() {
    if (unchanged || save.isPending) return;
    if (becomesShorter) setConfirmOpen(true);
    else save.mutate();
  }

  return (
    <>
      <Card className="border border-border">
        <CardHeader className="border-b border-border/70">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 rounded-lg bg-intelligence/10 p-2 text-intelligence">
              <History aria-hidden="true" className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <CardTitle className="text-pretty">Control source-email retention</CardTitle>
              <CardDescription className="mt-1 max-w-2xl text-pretty">
                Choose how long PFIS keeps sender, subject, and body content after an email has been
                processed. Shorter retention reduces the sensitive source data stored in your
                workspace.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-5 sm:pt-6">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)] lg:items-end">
            <div>
              <SelectField
                label="Keep processed source content"
                value={selection}
                options={OPTIONS}
                onValueChange={setSelection}
              />
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                Unresolved parser failures keep their source content until they are resolved, so a
                retention sweep cannot silently remove evidence needed for repair.
              </p>
            </div>
            <div className="rounded-lg bg-muted/55 p-4">
              <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground">
                <ShieldCheck aria-hidden="true" className="h-4 w-4 text-success" />
                Lineage retained
              </p>
              <p className="mt-2 text-sm leading-6 text-foreground">
                Message ID, dates, parser evidence, transaction links, and a non-secret redaction
                audit event remain after content is cleared.
              </p>
              <Button
                className="mt-4 w-full sm:w-auto"
                onClick={requestSave}
                disabled={!user || unchanged || save.isPending}
              >
                {save.isPending ? 'Saving policy…' : 'Save retention policy'}
              </Button>
            </div>
          </div>
          {save.isError ? (
            <p role="alert" className="mt-3 text-sm text-danger">
              The policy could not be saved. {save.error.message}
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Dialog
        open={confirmOpen}
        onClose={() => {
          if (!save.isPending) setConfirmOpen(false);
        }}
        title="Shorten source retention?"
        description={`PFIS will keep processed source content ${policyLabel(selectedDays)}.`}
      >
        <p className="text-sm leading-6 text-muted-foreground">
          On the next retention sweep, eligible sender, subject, and body content older than this
          limit is permanently cleared. Ledger records and evidence lineage remain, but the cleared
          text cannot be recovered.
        </p>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button
            data-dialog-initial-focus
            variant="ghost"
            onClick={() => setConfirmOpen(false)}
            disabled={save.isPending}
          >
            Keep current policy
          </Button>
          <Button variant="danger" onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending ? 'Applying policy…' : 'Apply shorter policy'}
          </Button>
        </div>
      </Dialog>
    </>
  );
}
