import { useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/api';
import type { ExplainPayload, ExplainResponse } from '@/lib/types';

interface ExplainActionProps {
  payload: ExplainPayload;
  userId?: string;
}

export function ExplainAction({ payload, userId }: ExplainActionProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [explanation, setExplanation] = useState<ExplainResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setOpen(true);
    if (explanation || busy) return;
    setBusy(true);
    setError(null);
    try {
      setExplanation(await api.explain(payload, userId));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="ghost" size="sm" onClick={load}>
        <Sparkles className="h-3.5 w-3.5" /> Explain
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="PFIS explanation">
        {busy ? (
          <Skeleton className="h-32" />
        ) : error ? (
          <p className="text-sm text-danger">{error}</p>
        ) : explanation ? (
          <div className="grid gap-4 text-sm">
            <p className="font-semibold">{explanation.summary}</p>
            {explanation.evidence_status ? (
              <p className="text-xs text-muted-foreground">
                Evidence: {explanation.evidence_status.replace('_', ' ')}
                {explanation.as_of ? ` · as of ${new Date(explanation.as_of).toLocaleString()}` : ''}
              </p>
            ) : null}
            {explanation.drivers.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-wide text-muted-foreground">
                  Drivers
                </p>
                <ul className="grid gap-1 text-muted-foreground">
                  {explanation.drivers.map((driver) => (
                    <li key={driver}>- {driver}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <p className="mb-1 text-xs font-bold uppercase tracking-wide text-muted-foreground">
                Next actions
              </p>
              <ul className="grid gap-1 text-muted-foreground">
                {explanation.next_actions.map((action) => (
                  <li key={action}>- {action}</li>
                ))}
              </ul>
            </div>
            {explanation.missing_evidence && explanation.missing_evidence.length > 0 ? (
              <div>
                <p className="mb-1 text-xs font-bold uppercase tracking-wide text-muted-foreground">
                  Missing evidence
                </p>
                <ul className="grid gap-1 text-muted-foreground">
                  {explanation.missing_evidence.map((item) => (
                    <li key={item}>- {item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className="rounded-lg border border-border bg-muted/35 p-3 text-xs text-muted-foreground">
              {explanation.safety_note}
            </p>
          </div>
        ) : null}
      </Dialog>
    </>
  );
}
