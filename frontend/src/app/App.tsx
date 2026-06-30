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
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

function Root() {
  const { isAuthenticated } = useAuth();
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
