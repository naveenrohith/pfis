import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuth } from '@/features/auth/AuthContext';
import { useToast } from '@/components/ui/Toast';
import type { Job, JobStatus } from '@/lib/types';

export interface ActivityEntry {
  time: string;
  message: string;
}

const MAX_LOG = 30;

export function useSyncPipeline() {
  const { user, session } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<JobStatus | 'idle'>('idle');
  const [log, setLog] = useState<ActivityEntry[]>([]);
  const pollRef = useRef<number | null>(null);

  const append = useCallback((message: string) => {
    const time = new Date().toLocaleTimeString();
    setLog((prev) => [{ time, message }, ...prev].slice(0, MAX_LOG));
  }, []);

  const clearLog = useCallback(() => setLog([]), []);

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries();
  }, [queryClient]);

  const pollJob = useCallback(
    (jobId: string) => {
      let attempts = 0;
      const tick = async () => {
        attempts += 1;
        try {
          const job: Job = await api.job(jobId);
          setStatus(job.status);
          if (job.status === 'completed') {
            append('✅ Sync completed');
            notify('Sync completed', 'success');
            setRunning(false);
            invalidateAll();
            return;
          }
          if (job.status === 'failed') {
            append(`❌ Sync failed: ${job.error_message ?? 'unknown error'}`);
            notify('Sync failed', 'error');
            setRunning(false);
            invalidateAll();
            return;
          }
        } catch {
          // transient; keep polling until attempt budget exhausts
        }
        if (attempts >= 120) {
          append('❌ Sync timed out');
          notify('Sync timed out', 'error');
          setRunning(false);
          return;
        }
        pollRef.current = window.setTimeout(tick, 500);
      };
      tick();
    },
    [append, notify, invalidateAll],
  );

  const runSync = useCallback(async () => {
    if (!user || running) return;
    setRunning(true);
    setStatus('queued');
    append('⏳ Starting sync…');
    try {
      const job =
        session?.mode === 'demo'
          ? await api.demoSyncPipeline(user.id, 80)
          : await api.gmailSyncPipeline(user.id);
      append('⚙️ Job queued');
      pollJob(job.id);
    } catch (err) {
      append(`❌ ${(err as Error).message}`);
      notify((err as Error).message, 'error');
      setRunning(false);
    }
  }, [user, running, session, append, notify, pollJob]);

  const retrySync = useCallback(async () => {
    if (!user || running) return;
    setRunning(true);
    setStatus('queued');
    append('⏳ Retrying parse failures…');
    try {
      const job = await api.retryParseFailures(user.id, 40);
      pollJob(job.id);
    } catch (err) {
      append(`❌ ${(err as Error).message}`);
      notify((err as Error).message, 'error');
      setRunning(false);
    }
  }, [user, running, append, notify, pollJob]);

  return { running, status, log, runSync, retrySync, clearLog };
}
