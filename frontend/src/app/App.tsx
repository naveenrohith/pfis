import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThemeProvider } from '@/components/theme/ThemeProvider';
import { ToastProvider } from '@/components/ui/Toast';
import { AuthProvider, useAuth } from '@/features/auth/AuthContext';
import { WorkspaceProvider } from '@/features/workspace/WorkspaceContext';
import { SyncProvider } from '@/features/workspace/SyncContext';
import { AuthScreen } from '@/features/auth/AuthScreen';
import { DashboardLayout } from './DashboardLayout';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        const status = (error as { status?: number }).status;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 3;
      },
      refetchOnWindowFocus: false,
      refetchOnReconnect: 'always',
      staleTime: 30_000,
    },
  },
});

function Root() {
  const { isAuthenticated, isReady } = useAuth();
  if (!isReady) {
    return (
      <main className="grid min-h-screen place-items-center bg-background" aria-busy="true">
        <p className="text-sm font-semibold text-muted-foreground">
          Opening your private workspace…
        </p>
      </main>
    );
  }
  if (!isAuthenticated) return <AuthScreen />;
  return (
    <WorkspaceProvider>
      <SyncProvider>
        <DashboardLayout />
      </SyncProvider>
    </WorkspaceProvider>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>
            <Root />
          </AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
