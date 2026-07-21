import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, ApiError, AUTH_SESSION_ENDED_EVENT } from '@/lib/api';
import type { AuthSessionResponse, Session, User } from '@/lib/types';

interface AuthContextValue {
  session: Session | null;
  user: User | null;
  isAuthenticated: boolean;
  isReady: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string, currency: string) => Promise<void>;
  startDemo: () => Promise<void>;
  logout: (message?: string) => Promise<boolean>;
  expiryMessage: string | null;
  clearExpiryMessage: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function buildSession(payload: AuthSessionResponse): Session {
  return {
    mode: payload.mode,
    expiresAt: Date.now() + payload.expires_in * 1000,
    user: payload.user,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<Session | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [expiryMessage, setExpiryMessage] = useState<string | null>(null);

  const commit = useCallback((payload: AuthSessionResponse) => {
    setSession(buildSession(payload));
    setExpiryMessage(null);
  }, []);

  const endSession = useCallback(
    (message?: string) => {
      queryClient.clear();
      setSession(null);
      if (message) setExpiryMessage(message);
    },
    [queryClient],
  );

  useEffect(() => {
    const handleUnauthorized = () => {
      endSession('Your secure session ended. Sign in to continue.');
    };
    window.addEventListener(AUTH_SESSION_ENDED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(AUTH_SESSION_ENDED_EVENT, handleUnauthorized);
  }, [endSession]);

  useEffect(() => {
    let active = true;
    api
      .session()
      .then((payload) => {
        if (active) commit(payload);
      })
      .catch((error: unknown) => {
        if (active && (!(error instanceof ApiError) || error.status !== 401)) {
          setExpiryMessage('PFIS could not verify your session. Refresh and try again.');
        }
      })
      .finally(() => {
        if (active) setIsReady(true);
      });
    return () => {
      active = false;
    };
  }, [commit]);

  const logout = useCallback(
    async (message?: string) => {
      try {
        await api.logout();
        endSession(message);
        return true;
      } catch (error: unknown) {
        if ((error instanceof ApiError && error.status === 401) || message) {
          endSession(message);
          return true;
        }
        return false;
      }
    },
    [endSession],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      commit(await api.login(email, password));
    },
    [commit],
  );

  const register = useCallback(
    async (name: string, email: string, password: string, currency: string) => {
      commit(await api.register(name, email, password, currency));
    },
    [commit],
  );

  const startDemo = useCallback(async () => {
    commit(await api.startDemo());
  }, [commit]);

  useEffect(() => {
    if (!session?.expiresAt) return;
    const remaining = session.expiresAt - Date.now();
    if (remaining <= 0) {
      void logout('Your secure session ended. Sign in to continue.');
      return;
    }
    const timer = window.setTimeout(
      () => {
        void logout('Your secure session ended. Sign in to continue.');
      },
      Math.min(remaining, 2_147_000_000),
    );
    return () => window.clearTimeout(timer);
  }, [session, logout]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      user: session?.user ?? null,
      isAuthenticated: !!session,
      isReady,
      login,
      register,
      startDemo,
      logout,
      expiryMessage,
      clearExpiryMessage: () => setExpiryMessage(null),
    }),
    [session, isReady, login, register, startDemo, logout, expiryMessage],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
