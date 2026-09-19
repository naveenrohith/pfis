import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
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
  const wsRetryRef = useRef<number | null>(null);
  const gmailConnectUrl = user ? api.gmailConnectUrl(user.id) : null;

  const append = useCallback((message: string) => {
    const time = new Date().toLocaleTimeString();
    setLog((prev) => [{ time, message }, ...prev].slice(0, MAX_LOG));
  }, []);

  const clearLog = useCallback(() => setLog([]), []);

  const reconnectGmail = useCallback(() => {
    if (!gmailConnectUrl) return;
    window.location.assign(gmailConnectUrl);
  }, [gmailConnectUrl]);

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries();
  }, [queryClient]);

  const formatSyncEvent = useCallback(
    (event: SyncEvent): string | null => {
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
        case 'balance_refresh_completed':
          invalidateAll();
          return `Balance evidence refreshed: ${Number(data.observations_ingested ?? 0)} bank observation(s), ${Number(data.card_observations_ingested ?? 0)} card observation(s)`;
        case 'balance_refresh_failed':
          invalidateAll();
          return `Balance refresh failed: ${String(data.error ?? 'unknown error')}`;
        default:
          return null;
      }
    },
    [invalidateAll],
  );

  useEffect(() => {
    if (!user) return;
    let disposed = false;
    let attempt = 0;
    let heartbeat: number | null = null;
    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const params = new URLSearchParams({ user_id: user.id });
      const wsUrl = `${protocol}//${window.location.host}/api/ws/sync?${params.toString()}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        attempt = 0;
        setLiveConnected(true);
        heartbeat = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping');
        }, 25_000);
      };
      ws.onclose = () => {
        setLiveConnected(false);
        if (heartbeat) window.clearInterval(heartbeat);
        heartbeat = null;
        if (disposed) return;
        attempt += 1;
        wsRetryRef.current = window.setTimeout(
          connect,
          Math.min(30_000, 1_000 * 2 ** Math.min(attempt, 5)),
        );
      };
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
    };
    connect();

    return () => {
      disposed = true;
      if (wsRetryRef.current) window.clearTimeout(wsRetryRef.current);
      if (heartbeat) window.clearInterval(heartbeat);
      wsRef.current?.close();
      wsRef.current = null;
      setLiveConnected(false);
    };
  }, [user, session, append, formatSyncEvent]);

  useEffect(() => {
    const refreshVisibleData = () => {
      if (document.visibilityState === 'visible' && navigator.onLine) {
        invalidateAll();
      }
    };
    window.addEventListener('online', refreshVisibleData);
    document.addEventListener('visibilitychange', refreshVisibleData);
    return () => {
      window.removeEventListener('online', refreshVisibleData);
      document.removeEventListener('visibilitychange', refreshVisibleData);
    };
  }, [invalidateAll]);

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
      if (session?.mode !== 'demo') {
        try {
          const autoSync = await api.autoSyncStatus(user.id);
          if (autoSync.status === 'paused' && autoSync.error) {
            setRunning(false);
            reconnectGmail();
            return;
          }
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) {
            setRunning(false);
            reconnectGmail();
            return;
          }
          throw error;
        }
      }
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
  }, [user, running, session, append, notify, pollJob, reconnectGmail]);

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

  return {
    running,
    status,
    liveConnected,
    log,
    runSync,
    retrySync,
    reconnectGmail,
    gmailConnectUrl,
    clearLog,
  };
}
