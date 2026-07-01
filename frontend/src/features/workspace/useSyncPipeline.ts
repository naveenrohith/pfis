import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuth } from '@/features/auth/AuthContext';
import { useToast } from '@/components/ui/Toast';
import type { Job, JobStatus, SyncEvent } from '@/lib/types';

export interface ActivityEntry {
  time: string;
  message: string;
}

const MAX_LOG = 30;
const JOB_POLL_INTERVAL_MS = 2_000;
const JOB_MAX_ATTEMPTS = 900; // 30 minutes for large Gmail accounts.

export function useSyncPipeline() {
  const { user, session } = useAuth();
  const queryClient = useQueryClient();
  const { notify } = useToast();
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState<JobStatus | 'idle'>('idle');
  const [liveConnected, setLiveConnected] = useState(false);
  const [log, setLog] = useState<ActivityEntry[]>([]);
  const pollRef = useRef<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const append = useCallback((message: string) => {
    const time = new Date().toLocaleTimeString();
    setLog((prev) => [{ time, message }, ...prev].slice(0, MAX_LOG));
  }, []);

  const clearLog = useCallback(() => setLog([]), []);

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries();
  }, [queryClient]);

  const formatSyncEvent = useCallback((event: SyncEvent): string | null => {
    const data = event.data ?? {};
    switch (event.event) {
      case 'ws_connected':
        return 'Live sync connected';
      case 'sync_started':
        setRunning(true);
        setStatus('running');
        return 'Automatic sync started';
      case 'gmail_checked':
        return `Gmail checked: ${Number(data.fetched ?? 0)} new candidate email(s)`;
      case 'emails_stored':
        return `Emails stored: ${Number(data.stored ?? 0)} new, ${Number(data.duplicates ?? 0)} duplicate`;
      case 'pipeline_started':
        return 'Parser pipeline started';
      case 'transactions_updated':
        invalidateAll();
        return `Transactions updated: ${Number(data.stored ?? 0)} stored`;
      case 'sync_completed':
        setRunning(false);
        setStatus('completed');
        invalidateAll();
        return 'Sync completed';
      case 'sync_failed':
        setRunning(false);
        setStatus('failed');
        invalidateAll();
        return `Sync failed: ${String(data.error ?? 'unknown error')}`;
      default:
        return null;
    }
  }, [invalidateAll]);

  useEffect(() => {
    if (!user) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const params = new URLSearchParams({ user_id: user.id });
    if (session?.token) params.set('token', session.token);
    const wsUrl = `${protocol}//${window.location.host}/api/ws/sync?${params.toString()}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setLiveConnected(true);
    ws.onclose = () => setLiveConnected(false);
    ws.onerror = () => setLiveConnected(false);
    ws.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as SyncEvent;
        const line = formatSyncEvent(event);
        if (line) append(line);
      } catch {
        append('Live sync event could not be read');
      }
    };

    return () => {
      ws.close();
      if (wsRef.current === ws) wsRef.current = null;
      setLiveConnected(false);
    };
  }, [user, session, append, formatSyncEvent]);

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
        } catch (err) {
          const message = (err as Error).message || 'Unable to fetch job status';
          append(`⚠️ Job status check delayed: ${message}`);
        }
        if (attempts >= JOB_MAX_ATTEMPTS) {
          append('❌ Sync timed out');
          notify('Sync timed out', 'error');
          setRunning(false);
          return;
        }
        pollRef.current = window.setTimeout(tick, JOB_POLL_INTERVAL_MS);
      };
      if (pollRef.current) window.clearTimeout(pollRef.current);
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

  return { running, status, liveConnected, log, runSync, retrySync, clearLog };
}
