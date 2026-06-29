// Session persistence for the PFIS dashboard.
// Mirrors the versioned key used by the legacy static dashboard so an existing
// signed-in session is reused after the migration.
const SESSION_KEY = 'pfis.session.v3';

export function loadSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession(session) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}
