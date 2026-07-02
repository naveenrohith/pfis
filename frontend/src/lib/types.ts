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

export interface AutoSyncStatus {
  gmail_account_id: string;
  enabled: boolean;
  interval_seconds: number;
  status: 'idle' | 'running' | 'paused' | 'error';
  error?: string | null;
  last_synced_at?: string | null;
  last_history_id?: string | null;
}

export type SyncEventName =
  | 'ws_connected'
  | 'sync_started'
  | 'gmail_checked'
  | 'emails_stored'
  | 'pipeline_started'
  | 'transactions_updated'
  | 'sync_completed'
  | 'sync_failed';

export interface SyncEvent {
  event: SyncEventName;
  user_id: string;
  timestamp: string;
  data?: Record<string, unknown>;
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

// --- Financial Decision Workspace (GET /api/dashboard/workspace) ---

export interface WorkspaceSnapshot {
  income: number;
  spend: number;
  savings: number;
  net_cash_flow: number;
  transaction_count: number;
  review_count: number;
  budget_risk_count: number;
  sync_status: string;
}

export type TimelineEventType =
  | 'income'
  | 'subscription'
  | 'bill'
  | 'shopping'
  | 'refund'
  | 'spending';

export interface TimelineEvent {
  type: TimelineEventType;
  label: string;
  merchant?: string | null;
  category?: string | null;
  amount: number;
  direction: 'in' | 'out';
  date: string;
  confidence: number;
}

export interface WorkspaceInsight {
  type?: string | null;
  icon?: string | null;
  title: string;
  description: string;
  severity: 'info' | 'success' | 'warning' | 'danger';
}

export type RecommendationType = 'savings' | 'recurring' | 'budget' | 'anomaly' | 'review';

export interface WorkspaceRecommendation {
  type: RecommendationType;
  severity: 'info' | 'success' | 'warning' | 'danger';
  title: string;
  description: string;
  action_label: string;
  target: string;
}

export interface ReviewSummary {
  pending_count: number;
  low_confidence_count: number;
  avg_confidence?: number | null;
}

export interface SyncSummary {
  latest_status?: string | null;
  last_synced_at?: string | null;
  processed_total: number;
  unprocessed_total: number;
}

export interface WorkspaceResponse {
  month: number;
  year: number;
  snapshot: WorkspaceSnapshot;
  timeline: TimelineEvent[];
  insights: WorkspaceInsight[];
  recommendations: WorkspaceRecommendation[];
  review_summary: ReviewSummary;
  sync_summary: SyncSummary;
}

export interface TransactionPreview {
  id: string;
  merchant: string;
  category?: string | null;
  amount: number;
  transaction_type: TransactionType;
  transaction_date: string;
  confidence_score: number;
  reviewed_flag: boolean;
}

export interface MerchantSummary {
  merchant_key: string;
  name: string;
  total_spend: number;
  transaction_count: number;
  avg_spend: number;
  month_change_pct?: number | null;
  category?: string | null;
  category_id?: string | null;
  recurrence_likelihood: number;
  latest_transaction_date?: string | null;
}

export interface MerchantDetail extends MerchantSummary {
  aliases: string[];
  default_category_id?: string | null;
  latest_transactions: TransactionPreview[];
}

export interface CategoryTopMerchant {
  name: string;
  total: number;
  count: number;
}

export interface CategoryIntelligenceItem {
  category_id?: string | null;
  name: string;
  parent_category_id?: string | null;
  parent_name?: string | null;
  icon?: string | null;
  total_spend: number;
  transaction_count: number;
  month_change_pct?: number | null;
  budget_limit?: number | null;
  budget_usage_pct?: number | null;
  top_merchants: CategoryTopMerchant[];
}

export interface CategoryIntelligenceResponse {
  month: number;
  year: number;
  categories: CategoryIntelligenceItem[];
}

export interface CashFlowProjection {
  month: number;
  year: number;
  income: number;
  spend_to_date: number;
  net_to_date: number;
  projected_spend: number;
  projected_net: number;
  daily_spend_rate: number;
  days_elapsed: number;
  days_in_month: number;
}

export interface MonthComparison {
  month: number;
  year: number;
  previous_month: number;
  previous_year: number;
  income: number;
  previous_income: number;
  spend: number;
  previous_spend: number;
  savings: number;
  previous_savings: number;
  spend_change_pct?: number | null;
  income_change_pct?: number | null;
  category_deltas: Array<{
    category: string;
    current: number;
    previous: number;
    change_pct?: number | null;
  }>;
}

export interface FinancialHealthScore {
  score: number;
  savings_rate: number;
  budget_adherence: number;
  recurring_burden: number;
  review_cleanliness: number;
  signals: Array<{ label: string; value: number; severity: 'info' | 'success' | 'warning' | 'danger' }>;
}

export type GoalType = 'savings' | 'category_reduction' | 'recurring_reduction';

export interface Goal {
  id: string;
  user_id: string;
  goal_type: GoalType;
  label: string;
  target_amount: number;
  target_key?: string | null;
  target_month?: number | null;
  target_year?: number | null;
  is_active: boolean;
  current_amount: number;
  progress_pct: number;
  status: string;
  created_at: string;
}

export interface GoalCreatePayload {
  goal_type: GoalType;
  label: string;
  target_amount: number;
  target_key?: string | null;
  target_month?: number | null;
  target_year?: number | null;
}

export interface ExplainPayload {
  surface: string;
  title: string;
  description?: string | null;
  metrics?: Record<string, string | number | boolean | null | undefined>;
}

export interface ExplainResponse {
  surface: string;
  summary: string;
  drivers: string[];
  next_actions: string[];
  safety_note: string;
}

export interface PipelineMetrics {
  user_id: string;
  month?: number | null;
  year?: number | null;
  parse_attempts: number;
  parsed_count: number;
  transaction_created_count: number;
  parse_success_rate: number;
  average_confidence: number;
  fallback_rate: number;
  unknown_merchant_rate: number;
  duplicate_rate: number;
  retry_count: number;
  dlq_size: number;
  average_parse_time_ms: number;
}

export interface PipelineFailure {
  id: string;
  email_id: string;
  subject?: string | null;
  sender?: string | null;
  received_at?: string | null;
  transaction_id?: string | null;
  error_message?: string | null;
  failure_stage?: string | null;
  failure_code?: string | null;
  parser_name?: string | null;
  parser_version: number;
  pattern_version?: number | null;
  confidence_version?: number | null;
  normalization_version?: number | null;
  diagnostic?: Record<string, unknown>;
  retry_count: number;
  last_retry_at?: string | null;
  resolved: boolean;
}

export interface PipelineFailuresResponse {
  total: number;
  failures: PipelineFailure[];
}

export interface PipelineRetryResponse {
  status: string;
  stats: Record<string, unknown>;
}

export interface PipelineReprocessRequest {
  email_ids?: string[];
  from_date?: string;
  to_date?: string;
  dry_run?: boolean;
  limit?: number;
}

export interface PipelineReprocessResponse {
  dry_run: boolean;
  email_count: number;
  comparisons?: Array<Record<string, unknown>>;
  stats?: Record<string, unknown>;
}
