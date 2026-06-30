import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import { clearSession, isSessionExpired, loadSession, saveSession } from '@/lib/session';
import type { AuthTokenResponse, Session, User } from '@/lib/types';

interface AuthContextValue {
  session: Session | null;
  user: User | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string, currency: string) => Promise<void>;
  startDemo: () => Promise<void>;
  logout: (message?: string) => void;
  expiryMessage: string | null;
  clearExpiryMessage: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function buildSession(payload: AuthTokenResponse): Session {
  return {
    mode: 'auth',
    token: payload.access_token,
    expiresAt: Date.now() + payload.expires_in * 1000,
    user: payload.user,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => {
    const stored = loadSession();
    return stored && !isSessionExpired(stored) ? stored : null;
  });
  const [expiryMessage, setExpiryMessage] = useState<string | null>(null);

  const logout = useCallback((message?: string) => {
    clearSession();
    setSession(null);
    if (message) setExpiryMessage(message);
  }, []);

  const commit = useCallback((next: Session) => {
    saveSession(next);
    setSession(next);
    setExpiryMessage(null);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      commit(buildSession(await api.login(email, password)));
    },
    [commit],
  );

  const register = useCallback(
    async (name: string, email: string, password: string, currency: string) => {
      commit(buildSession(await api.register(name, email, password, currency)));
    },
    [commit],
  );

  const startDemo = useCallback(async () => {
    const users = await api.listUsers();
    const demo = users.find((u) => u.email === 'demo@pfis.app') ?? users[0];
    if (!demo) throw new Error('No demo workspace is available.');
    commit({ mode: 'demo', token: null, expiresAt: null, user: demo });
  }, [commit]);

  // Expiry watchdog for authenticated sessions.
  useEffect(() => {
    if (!session || session.mode === 'demo') return;
    const check = () => {
      if (isSessionExpired(session)) logout('Your session expired. Please sign in again.');
    };
    const timer = setInterval(check, 30_000);
    return () => clearInterval(timer);
  }, [session, logout]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      user: session?.user ?? null,
      isAuthenticated: !!session,
      login,
      register,
      startDemo,
      logout,
      expiryMessage,
      clearExpiryMessage: () => setExpiryMessage(null),
    }),
    [session, login, register, startDemo, logout, expiryMessage],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
