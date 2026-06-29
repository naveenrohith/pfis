// Typed-ish API client for the PFIS backend.
// Endpoints and contracts mirror docs/api-reference.md. Centralizing fetch here
// keeps auth, error handling, and user scoping consistent across views.
import { loadSession } from './session.js';

const API_BASE = '/api';

function authHeaders() {
  const session = loadSession();
  const headers = { 'Content-Type': 'application/json' };
  if (session?.access_token) {
    headers.Authorization = `Bearer ${session.access_token}`;
  }
  return headers;
}

async function apiFetch(path, { method = 'GET', body, query } = {}) {
  let url = `${API_BASE}${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        params.set(key, String(value));
      }
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  const response = await fetch(url, {
    method,
    headers: authHeaders(),
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      detail = errBody.detail || detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new Error(`API ${method} ${path} failed (${response.status}): ${detail}`);
  }

  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  health: () => apiFetch('/health'),
  categories: () => apiFetch('/categories/'),

  insights: (userId, month, year) =>
    apiFetch('/insights/', { query: { user_id: userId, month, year } }),

  transactionSummary: (userId, month, year) =>
    apiFetch('/transactions/summary', { query: { user_id: userId, month, year } }),

  transactions: (userId, { month, year, categoryId, limit = 50, offset = 0 } = {}) =>
    apiFetch('/transactions/', {
      query: { user_id: userId, month, year, category_id: categoryId, limit, offset },
    }),

  budgetsTrack: (userId, month, year) =>
    apiFetch('/budgets/track', { query: { user_id: userId, month, year } }),
};
