import { createContext, useContext } from 'react';
import { useSyncPipeline } from './useSyncPipeline';

type SyncContextValue = ReturnType<typeof useSyncPipeline>;

const SyncContext = createContext<SyncContextValue | null>(null);

export function SyncProvider({ children }: { children: React.ReactNode }) {
  const sync = useSyncPipeline();
  return <SyncContext.Provider value={sync}>{children}</SyncContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSync(): SyncContextValue {
  const ctx = useContext(SyncContext);
  if (!ctx) throw new Error('useSync must be used within SyncProvider');
  return ctx;
}
