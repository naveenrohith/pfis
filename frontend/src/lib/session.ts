import type { Session } from './types';

const SESSION_KEY = 'pfis.session.v3';

export function loadSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
}

export function isSessionExpired(session: Session | null): boolean {
  if (!session) return true;
  if (session.mode === 'demo') return false;
  if (!session.expiresAt) return false;
  return Date.now() >= session.expiresAt;
}
