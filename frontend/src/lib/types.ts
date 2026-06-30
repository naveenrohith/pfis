// Domain types mirroring the PFIS backend API (docs/api-reference.md).

export type TransactionType = 'debit' | 'credit' | 'refund';

export interface User {
  id: string;
  name: string;
  email: string;
  currency: string;
}

export type SessionMode = 'auth' | 'demo';

export interface Session {
  mode: SessionMode;
  token: string | null;
  expiresAt: number | null; // epoch ms
  user: User;
}

export interface Category {
  id: string;
  name: string;
  icon?: string | null;
}

export interface Transaction {
  id: string;
  merchant_raw?: string | null;
  merchant_normalized?: string | null;
  category_id?: string | null;
  category_name?: string | null;
  amount: number;
  currency?: string;
  transaction_type: TransactionType;
  transaction_date: string;
  account_last4?: string | null;
  reference_id?: string | null;
  confidence_score: number;
  reviewed_flag: boolean;
}

export interface CategoryBreakdown {
  name: string;
  icon?: string | null;
  total: number;
  count: number;
}

export interface MerchantTotal {
  name: string;
  total: number;
  count: number;
}

export interface TransactionSummary {
  total_income: number;
  total_spend: number;
  net?: number;
  transaction_count: number;
  category_breakdown?: CategoryBreakdown[];
  top_merchants?: MerchantTotal[];
}

export interface InsightCard {
  type?: string;
  icon?: string;
  title: string;
  description: string;
  severity?: 'info' | 'success' | 'warning' | 'danger';
}

export interface DailyTrendPoint {
  date: string;
  day?: number;
  total: number;
  count?: number;
}

export interface RecurringPayment {
  merchant: string;
  occurrences: number;
  avg_amount: number;
  is_consistent?: boolean;
}

export interface InsightsResponse {
  insights: InsightCard[];
  daily_trend: DailyTrendPoint[];
  recurring_payments: RecurringPayment[];
  meta?: Record<string, unknown>;
}

export interface EmailItem {
  id?: string;
  subject?: string;
  sender?: string;
  body_preview?: string;
  received_at?: string;
  processed?: boolean;
}

export interface EmailsResponse {
  total?: number;
  all_total: number;
  processed_total: number;
  unprocessed_total: number;
  applied_filter?: string | null;
  emails: EmailItem[];
}

export interface SyncRun {
  id?: string;
  status?: string;
  start_time?: string;
  end_time?: string;
  emails_fetched?: number;
  emails_processed?: number;
  emails_failed?: number;
}

export interface SyncStatusResponse {
  latest_status?: string | null;
  runs: SyncRun[];
}

export type BudgetStatus = 'under' | 'warning' | 'over';

export interface BudgetTracker {
  id: string;
  category_id?: string;
  category: string;
  category_icon?: string | null;
  limit: number;
  actual_spend: number;
  remaining: number;
  usage_pct: number;
  status: BudgetStatus;
}

export type JobStatus = 'queued' | 'running' | 'completed' | 'failed';

export interface Job {
  id: string;
  status: JobStatus;
  job_type?: string;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  expires_in: number;
  user: User;
}

export interface BulkUpdateResponse {
  updated_count: number;
  failed?: string[];
}
