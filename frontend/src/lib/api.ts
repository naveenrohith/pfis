import { loadSession } from './session';
import type {
  AuthTokenResponse,
  AutoSyncStatus,
  BudgetTracker,
  BulkUpdateResponse,
  Category,
  EmailsResponse,
  InsightsResponse,
  Job,
  SyncStatusResponse,
  Transaction,
  TransactionSummary,
  TransactionType,
  User,
} from './types';

const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  auth?: boolean;
  tolerate401?: boolean;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, auth = true, tolerate401 = false } = opts;

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

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (auth) {
    const session = loadSession();
    if (session?.token) headers.Authorization = `Bearer ${session.token}`;
  }

  const response = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (response.status === 401 && !tolerate401) {
    throw new ApiError('Session expired', 401);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      detail = (errBody as { detail?: string }).detail || detail;
    } catch {
      // keep statusText
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface TransactionUpdatePayload {
  merchant_normalized?: string;
  category_id?: string | null;
  amount?: number;
  transaction_type?: TransactionType;
  reviewed_flag?: boolean;
}

export interface BulkUpdatePayload {
  transaction_ids: string[];
  category_id?: string | null;
  transaction_type?: TransactionType;
  reviewed_flag?: boolean;
}

export const api = {
  // Auth
  login: (email: string, password: string) =>
    request<AuthTokenResponse>('/auth/login', {
      method: 'POST',
      body: { email, password },
      auth: false,
    }),
  register: (name: string, email: string, password: string, currency: string) =>
    request<AuthTokenResponse>('/auth/register', {
      method: 'POST',
      body: { name, email, password, currency },
      auth: false,
    }),
  me: () => request<User>('/auth/me'),
  listUsers: () => request<User[]>('/users/', { auth: false, tolerate401: true }),

  // Reference data
  categories: () => request<Category[]>('/categories/'),

  // Transactions
  summary: (userId: string, month: number, year: number) =>
    request<TransactionSummary>('/transactions/summary', {
      query: { user_id: userId, month, year },
    }),
  transactions: (
    userId: string,
    params: { month?: number; year?: number; categoryId?: string; limit?: number; offset?: number },
  ) =>
    request<Transaction[]>('/transactions/', {
      query: {
        user_id: userId,
        month: params.month,
        year: params.year,
        category_id: params.categoryId,
        limit: params.limit ?? 200,
        offset: params.offset,
      },
    }),
  updateTransaction: (id: string, payload: TransactionUpdatePayload) =>
    request<Transaction>(`/transactions/${id}`, { method: 'PATCH', body: payload }),
  bulkUpdate: (userId: string, payload: BulkUpdatePayload) =>
    request<BulkUpdateResponse>('/transactions/bulk-update', {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),

  // Gmail / inbox
  emails: (userId: string, limit = 12) =>
    request<EmailsResponse>('/gmail/emails', { query: { user_id: userId, limit } }),
  syncStatus: (userId: string) =>
    request<SyncStatusResponse>('/gmail/status', { query: { user_id: userId } }),
  autoSyncStatus: (userId: string) =>
    request<AutoSyncStatus>('/gmail/auto-sync', { query: { user_id: userId } }),
  updateAutoSync: (
    userId: string,
    payload: { enabled?: boolean; interval_seconds?: number },
  ) =>
    request<AutoSyncStatus>('/gmail/auto-sync', {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),

  // Insights
  insights: (userId: string, month: number, year: number) =>
    request<InsightsResponse>('/insights/', { query: { user_id: userId, month, year } }),

  // Budgets
  budgetsTrack: (userId: string, month: number, year: number) =>
    request<BudgetTracker[]>('/budgets/track', { query: { user_id: userId, month, year } }),
  createBudget: (userId: string, categoryId: string, monthlyLimit: number) =>
    request<{ id: string; status: string }>('/budgets/', {
      method: 'POST',
      query: { user_id: userId },
      body: { category_id: categoryId, monthly_limit: monthlyLimit },
    }),
  updateBudget: (budgetId: string, monthlyLimit: number) =>
    request<{ id: string; monthly_limit: number; status: string }>(`/budgets/${budgetId}`, {
      method: 'PATCH',
      body: { monthly_limit: monthlyLimit },
    }),
  deleteBudget: (budgetId: string) =>
    request<void>(`/budgets/${budgetId}`, { method: 'DELETE' }),

  // Jobs
  demoSyncPipeline: (userId: string, limit = 80) =>
    request<Job>('/jobs/demo-sync-pipeline', {
      method: 'POST',
      query: { user_id: userId, limit },
    }),
  gmailSyncPipeline: (userId: string, syncAll = false) =>
    request<Job>('/jobs/gmail-sync-pipeline', {
      method: 'POST',
      query: { user_id: userId, sync_all: syncAll },
    }),
  retryParseFailures: (userId: string, limit = 40) =>
    request<Job>('/jobs/retry-parse-failures', {
      method: 'POST',
      query: { user_id: userId, limit },
    }),
  job: (jobId: string) => request<Job>(`/jobs/${jobId}`),

  // Reports (URLs for direct navigation/download)
  csvUrl: (userId: string, month: number, year: number) =>
    `${API_BASE}/reports/export/csv?user_id=${encodeURIComponent(userId)}&month=${month}&year=${year}`,
  reportUrl: (userId: string, month: number, year: number) =>
    `${API_BASE}/reports/monthly?user_id=${encodeURIComponent(userId)}&month=${month}&year=${year}`,
};
