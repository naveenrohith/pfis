// Domain types mirroring the PFIS backend API (docs/api-reference.md).

export type TransactionType = 'debit' | 'credit' | 'refund';
export type PaymentMethod =
  'upi' | 'debit_card' | 'credit_card' | 'emi' | 'pay_later' | 'wallet' | 'bank_transfer' | 'other';
export type PaymentRail = 'upi' | 'debit_card' | 'atm' | 'transfer' | 'wallet' | 'other';
export type CardEvent =
  'none' | 'purchase' | 'payment' | 'refund' | 'cashback' | 'fee' | 'tax' | 'interest' | 'reversal';

export interface User {
  id: string;
  name: string;
  email: string;
  currency: string;
  timezone: string;
  raw_email_retention_days: number | null;
}

export interface AccountDeletionResponse {
  status: 'deleted';
  deleted_at: string;
  provider_revocation: string;
  private_rows_deleted: number;
  households_deleted: number;
  household_ownership_transferred: number;
  household_memberships_closed: number;
}

export type SessionMode = 'auth' | 'demo';

export interface Session {
  mode: SessionMode;
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
  payment_method: PaymentMethod;
  payment_rail?: PaymentRail;
  card_event?: CardEvent;
  transaction_status?: string;
  transaction_timestamp?: string | null;
  transaction_date: string;
  source_received_at?: string | null;
  created_at?: string;
  account_last4?: string | null;
  reference_id?: string | null;
  confidence_score: number;
  reviewed_flag: boolean;
  financial_account_id?: string | null;
  transfer_group_id?: string | null;
  is_transfer?: boolean;
  is_accounting_adjustment?: boolean;
  ledger_subtype?: string | null;
  source_kind?: 'manual' | 'email' | 'statement' | 'connector';
  review_outcome?: 'matched' | 'newly_imported' | 'ignored_by_rule' | 'needs_review';
  note?: string | null;
  tags?: string[];
}

export interface TransactionCreatePayload {
  amount: number;
  currency: string;
  transaction_type: TransactionType;
  payment_method: PaymentMethod;
  payment_rail?: PaymentRail;
  card_event?: CardEvent;
  transaction_date: string;
  merchant_raw?: string | null;
  merchant_normalized?: string | null;
  category_id?: string | null;
  account_last4?: string | null;
  reference_id?: string | null;
  confidence_score?: number;
  financial_account_id?: string | null;
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
  amount_low?: number;
  amount_high?: number;
  monthly_equivalent: number;
  is_consistent?: boolean;
  cadence?: string | null;
  median_interval_days?: number | null;
  cadence_confidence: number;
  amount_confidence: number;
  confidence: number;
  status: 'candidate' | 'early' | 'mature' | 'missed' | 'inactive';
  last_seen: string;
  next_expected_date?: string | null;
  next_expected_date_low?: string | null;
  next_expected_date_high?: string | null;
  data_sufficiency: 'low' | 'medium' | 'high';
  ruleset_version: string;
  evidence: Array<{ label: string; value: string }>;
  signal?: {
    kind: string;
    status: 'observed' | 'calculated' | 'forecast' | 'recommendation';
    value: Record<string, unknown>;
    confidence: number;
    data_sufficiency: 'low' | 'medium' | 'high';
    sample_size: number;
    ruleset: { key: string; version: string };
    evidence: Array<{ label: string; value: string }>;
    assumptions: string[];
    data_through?: string | null;
  };
}

export interface InsightsResponse {
  insights: InsightCard[];
  daily_trend: DailyTrendPoint[];
  recurring_payments: RecurringPayment[];
  anomalies: SpendingAnomaly[];
  meta?: Record<string, unknown>;
}

export interface SpendingAnomaly {
  id: string;
  kind: 'category' | 'merchant';
  predicted_alert?: boolean;
  label: string;
  current_amount: number;
  baseline_amount: number;
  delta_amount: number;
  delta_pct: number;
  robust_score: number;
  history_periods: number;
  transaction_count: number;
  confidence: number;
  data_sufficiency: 'low' | 'medium' | 'high';
  severity: 'info' | 'warning';
  evidence: Array<{ label: string; value: string }>;
  assumptions: string[];
  ruleset_version: string;
  adjudication?: 'expected' | 'material' | 'insufficient_evidence' | null;
  adjudication_note?: string | null;
}

export interface AnomalyAdjudicationResponse {
  schema_version: string;
  id: string;
  anomaly_id: string;
  predicted_alert?: boolean;
  kind: 'category' | 'merchant';
  label: string;
  period_start: string;
  period_end: string;
  decision: 'expected' | 'material' | 'insufficient_evidence';
  note?: string | null;
  current_amount: number;
  baseline_amount: number;
  delta_amount: number;
  confidence: number;
  transaction_count: number;
  ruleset_version: string;
  created_at: string;
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
  connection_status: 'connected' | 'reauthorization_required';
  enabled: boolean;
  interval_seconds: number;
  status: 'idle' | 'running' | 'paused' | 'error';
  error?: string | null;
  last_synced_at?: string | null;
  last_history_id?: string | null;
}

export interface GmailDisconnectResponse {
  status: 'disconnected';
  provider_revocation: 'revoked' | 'provider_rejected' | 'token_unavailable' | 'unconfirmed';
  retained_raw_email_count: number;
  derived_records_retained: true;
}

export type SyncEventName =
  | 'ws_connected'
  | 'sync_started'
  | 'gmail_checked'
  | 'emails_stored'
  | 'pipeline_started'
  | 'transactions_updated'
  | 'sync_completed'
  | 'sync_failed'
  | 'balance_refresh_completed'
  | 'balance_refresh_failed';

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

export interface AuthSessionResponse {
  expires_in: number;
  mode: SessionMode;
  csrf_cookie_name: string;
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
  'income' | 'subscription' | 'bill' | 'shopping' | 'refund' | 'transfer' | 'spending';

export interface TimelineEvent {
  type: TimelineEventType;
  label: string;
  merchant?: string | null;
  category?: string | null;
  amount: number;
  direction: 'in' | 'out';
  date: string;
  payment_method?: PaymentMethod;
  transaction_status?: string;
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

export interface RecommendationConsequence {
  metric: string;
  unit: 'currency' | 'records' | 'percentage_points';
  low: number;
  high: number;
  currency?: string | null;
  basis: string;
}

export interface RecommendationConflict {
  code: string;
  kind: 'data_gap' | 'tradeoff' | 'overlap';
  severity: 'info' | 'warning' | 'blocking';
  title: string;
  description: string;
  related_type?: string | null;
  related_goal_id?: string | null;
}

export interface RecommendationGoalLink {
  goal_id: string;
  label: string;
  relationship: 'supports' | 'conflicts';
  remaining_amount?: number | null;
  currency?: string | null;
}

export interface RecommendationResolution {
  status: 'ready' | 'needs_review' | 'blocked' | 'choose';
  label: string;
  next_step: string;
  rationale: string;
  related_recommendation_ids: string[];
  primary_goal_id?: string | null;
  competing_goal_ids: string[];
}

export interface WorkspaceRecommendation {
  type: RecommendationType;
  severity: 'info' | 'success' | 'warning' | 'danger';
  title: string;
  description: string;
  action_label: string;
  target: string;
  id: string;
  priority: number;
  reason_codes: string[];
  evidence: Array<{ label: string; value: string }>;
  expected_impact?: string | null;
  smallest_action?: string | null;
  consequence?: RecommendationConsequence | null;
  conflicts: RecommendationConflict[];
  goal_links: RecommendationGoalLink[];
  resolution?: RecommendationResolution | null;
  confidence: number;
  freshness_as_of?: string | null;
  urgency: 'now' | 'this_period' | 'monitor';
  reversibility: 'reversible' | 'review_required';
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
  projection: CashFlowProjection;
  month_comparison: MonthComparison;
  financial_health: FinancialHealthScore;
  recurring_commitments: RecurringPayment[];
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
  recurrence_status: 'candidate' | 'early' | 'mature' | 'missed' | 'inactive';
  recurrence_cadence?: string | null;
  recurrence_confidence: number;
  next_expected_date?: string | null;
  data_sufficiency: 'low' | 'medium' | 'high';
  latest_transaction_date?: string | null;
}

export interface MerchantDetail extends MerchantSummary {
  aliases: string[];
  default_category_id?: string | null;
  latest_transactions: TransactionPreview[];
}

export interface LearnedMerchantRule {
  id: string;
  raw_descriptor: string;
  normalized_name: string;
  category_id?: string | null;
  source: string;
  confidence: number;
  source_transaction_id?: string | null;
  created_at: string;
  updated_at: string;
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
  recurring_commitments: number;
  confirmed_commitments: number;
  expected_income: number;
  flexible_spend_projection: number;
  budgeted_remaining: number;
  projected_range_low: number;
  projected_range_high: number;
  interval_calibration?: 'same_cutoff_empirical' | 'robust_history' | 'low_evidence';
  interval_calibration_samples?: number;
  interval_target_coverage_pct?: number;
  category_mix_status?:
    | 'same_month_supported'
    | 'mix_supported'
    | 'supported'
    | 'insufficient_history'
    | 'not_applicable';
  category_mix_sample_months?: number;
  category_mix_adjustment?: number;
  pay_cycle_status?:
    | 'same_month_supported'
    | 'mix_supported'
    | 'supported'
    | 'insufficient_history'
    | 'not_applicable';
  pay_cycle_sample_count?: number;
  temporal_expected_income: number;
  temporal_expected_outflows: number;
  temporal_conflicted_outflows: number;
  temporal_event_count: number;
  temporal_conflict_count: number;
  temporal_ruleset_version?: string | null;
  assumptions: string[];
  evidence: Array<{ label: string; value: string }>;
  confidence: number;
  data_sufficiency: 'low' | 'medium' | 'high';
  historical_months: number;
  data_through?: string | null;
  ruleset_version: string;
}

export interface ScenarioRequest {
  month: number;
  year: number;
  flexible_spend_reduction: number;
  recurring_reduction: number;
  additional_income: number;
}

export interface ScenarioResponse {
  month: number;
  year: number;
  baseline_projected_net: number;
  scenario_projected_net: number;
  scenario_projected_spend: number;
  monthly_impact: number;
  requested_flexible_spend_reduction: number;
  effective_flexible_spend_reduction: number;
  requested_recurring_reduction: number;
  effective_recurring_reduction: number;
  additional_income: number;
  assumptions: string[];
  data_through?: string | null;
  ruleset_version: string;
}

export type TemporalEventState =
  'expected' | 'observed' | 'overdue' | 'missed' | 'cancelled' | 'conflict';

export interface TemporalEventDecision {
  id: string;
  decision: 'confirmed' | 'cancelled' | 'observed' | 'linked' | 'conflict';
  transaction_id?: string | null;
  observed_date?: string | null;
  observed_amount?: number | null;
  note?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemporalFinancialEvent {
  id: string;
  kind: string;
  direction: 'inflow' | 'outflow' | 'reserve' | 'neutral';
  state: TemporalEventState;
  label: string;
  currency: string;
  expected_date: string;
  window_start: string;
  window_end: string;
  amount: { low?: number | null; expected?: number | null; high?: number | null };
  observation?: {
    observed_date: string;
    amount?: number | null;
    transaction_id?: string | null;
    confirmation: 'ledger_match' | 'user_status' | 'issuer_status';
  } | null;
  decision?: TemporalEventDecision | null;
  conflict_reason?: string | null;
  cadence?: string | null;
  confidence: number;
  data_sufficiency: 'low' | 'medium' | 'high';
  evidence: Array<{ source_type: string; source_id: string; role: string }>;
  assumptions: string[];
  ruleset_version: string;
  data_through: string;
}

export interface TemporalEventSummary {
  range_start: string;
  range_end: string;
  as_of: string;
  currency: string;
  ruleset_version: string;
  counts: Record<TemporalEventState, number>;
  events: TemporalFinancialEvent[];
  assumptions: string[];
}

export interface TemporalHistoryBackfillSource {
  source_type: 'transaction' | 'financial_account' | 'statement_line' | 'card_payment_intent';
  candidate_count: number;
  existing_snapshot_count: number;
  missing_snapshot_count: number;
  captured_count: number;
  skipped_count: number;
  truncated: boolean;
}

export interface TemporalHistoryBackfillResponse {
  ruleset_version: string;
  dry_run: boolean;
  captured_at: string;
  baseline_only: boolean;
  sources: TemporalHistoryBackfillSource[];
  limitations: string[];
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
  monthly_stability: number;
  data_confidence: number;
  data_confidence_breakdown: DataConfidenceDimension[];
  data_confidence_ruleset_version: string;
  source_coverage_score?: number;
  source_coverage_ruleset_version?: string;
  source_coverage?: SourceCoverage[];
  data_sufficiency: 'low' | 'medium' | 'high';
  savings_rate: number;
  budget_adherence?: number | null;
  recurring_burden: number;
  review_cleanliness: number;
  spending_volatility: number;
  ruleset_version: string;
  signals: Array<{
    label: string;
    value: number | null;
    severity: 'info' | 'success' | 'warning' | 'danger';
  }>;
}

export interface DataConfidenceDimension {
  key: 'coverage' | 'freshness' | 'parsing' | 'conflicts';
  label: string;
  score: number;
  status: 'strong' | 'watch' | 'limited';
  summary: string;
  evidence: Array<{ label: string; value: string }>;
  remediation_label?: string | null;
  remediation_target?: string | null;
}

export type SourceCoverageStatus =
  'current' | 'stale' | 'partial' | 'unknown' | 'disconnected' | 'error';

export interface SourceCoverage {
  key: string;
  label: string;
  status: SourceCoverageStatus;
  completeness: 'known' | 'partial' | 'unknown';
  score: number;
  observed_count: number;
  coverage_start?: string | null;
  coverage_end?: string | null;
  freshness_at?: string | null;
  freshness_age_days?: number | null;
  evidence: Array<{ label: string; value: string }>;
  limitations: string[];
  remediation_label?: string | null;
  remediation_target?: string | null;
}

export interface SourceCoverageResponse {
  ruleset_version: string;
  as_of: string;
  overall_score: number;
  sources: SourceCoverage[];
  assumptions: string[];
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

export type GuidancePeriod = 'daily' | 'weekly' | 'monthly';

export interface GuidanceAction {
  id: string;
  type: string;
  priority: number;
  title: string;
  description: string;
  action_label: string;
  target: string;
  reason_codes: string[];
  evidence: Array<{ label: string; value: string }>;
  expected_impact?: string | null;
  smallest_action?: string | null;
  consequence?: RecommendationConsequence | null;
  conflicts: RecommendationConflict[];
  goal_links: RecommendationGoalLink[];
  resolution?: RecommendationResolution | null;
  confidence: number;
  freshness_as_of?: string | null;
  urgency: 'now' | 'this_period' | 'monitor';
  reversibility: 'reversible' | 'review_required';
}

export interface GuidanceBrief {
  period: GuidancePeriod;
  as_of: string;
  headline: string;
  summary: string;
  health_score: number;
  status: string;
  changes: string[];
  actions: GuidanceAction[];
  data_through: string;
  ruleset_version: string;
}

export interface GuidanceEvidence {
  source_type: string;
  source_id?: string | null;
  label: string;
  value: string;
  cutoff?: string | null;
}

export interface GuidanceQueryResult {
  supported: boolean;
  intent?: string | null;
  answer: string;
  metrics: Array<{ label: string; value: string }>;
  filters: Record<string, string | number | boolean | null>;
  plan?: string[];
  evidence?: GuidanceEvidence[];
  uncertainty?: string[];
  confidence?: number;
  temporal_scope?: string;
  suggested_actions: string[];
  supported_examples: string[];
  ruleset_version: string;
}

export type RecommendationOutcomeKind = 'helped' | 'no_change' | 'worse' | 'not_completed';
export type RecommendationFeedbackReason =
  'not_relevant' | 'not_feasible' | 'already_done' | 'too_risky' | 'wrong_timing';

export interface RecommendationDecision {
  id: string;
  recommendation_id: string;
  state: 'active' | 'dismissed' | 'snoozed' | 'accepted' | 'not_relevant';
  recommendation_type?: string | null;
  title?: string | null;
  target?: string | null;
  expected_impact?: string | null;
  decision_as_of?: string | null;
  decision_note?: string | null;
  decision_reason?: RecommendationFeedbackReason | null;
  snoozed_until?: string | null;
  baseline_metric_key?: string | null;
  baseline_metric_value?: number | null;
  baseline_metric_unit?: string | null;
  smallest_action?: string | null;
  consequence?: RecommendationConsequence | null;
  conflicts: RecommendationConflict[];
  goal_links: RecommendationGoalLink[];
  resolution?: RecommendationResolution | null;
  confidence: number;
  freshness_as_of?: string | null;
  urgency: 'now' | 'this_period' | 'monitor';
  reversibility: 'reversible' | 'review_required';
  decided_at?: string | null;
  updated_at: string;
}

export interface RecommendationOutcome {
  id: string;
  decision_id: string;
  outcome: RecommendationOutcomeKind;
  note?: string | null;
  actual_impact_value?: number | null;
  actual_impact_unit?: string | null;
  baseline_metric_value?: number | null;
  observed_metric_value?: number | null;
  automatic_impact_value?: number | null;
  metric_key?: string | null;
  metric_unit?: string | null;
  outcome_ruleset_version: string;
  observed_at: string;
}

export interface RecommendationEffectivenessCohort {
  recommendation_type: string;
  guidance_ruleset_version: string;
  outcome_ruleset_version: string;
  metric_key?: string | null;
  metric_unit?: string | null;
  sample_size: number;
  unique_users: number;
  completed_rate?: number | null;
  helped_rate?: number | null;
  measured_evidence_status: 'available' | 'insufficient_sample';
  measured_sample_size: number;
  measured_unique_users: number;
  measured_improvement_rate?: number | null;
  mean_automatic_impact?: number | null;
  user_measurement_agreement_rate?: number | null;
}

export interface RecommendationEffectivenessReport {
  generated_at: string;
  window_started_at: string;
  window_days: number;
  minimum_sample_size: number;
  minimum_unique_users: number;
  evidence_status: 'available' | 'insufficient_sample';
  eligible_outcome_count: number;
  suppressed_cohort_count: number;
  cohorts: RecommendationEffectivenessCohort[];
  effectiveness_ruleset_version: string;
}

export type WidgetSize = 'small' | 'medium' | 'large';
export interface DashboardWidget {
  id: string;
  visible: boolean;
  size: WidgetSize;
}

export interface DashboardPreferences {
  user_id: string;
  layout_version: number;
  widgets: DashboardWidget[];
  theme: 'system' | 'light' | 'dark';
  density: 'comfortable' | 'compact';
  briefing_cadence: GuidancePeriod;
  favorites: string[];
  onboarding_goal?: 'budgeting' | 'saving' | 'recurring_reduction' | 'cleanup' | null;
  updated_at?: string | null;
}

export interface FinancialAccount {
  id: string;
  user_id: string;
  institution_name: string;
  account_type: string;
  balance_kind: 'asset' | 'liability';
  masked_number: string;
  currency: string;
  is_active: boolean;
  identity_status?: 'unresolved' | 'inferred' | 'confirmed';
  identity_confidence?: number;
  identity_evidence?: AccountIdentityEvidence[];
  latest_balance?: number | null;
  balance_as_of?: string | null;
  current_balance?: number | null;
  current_balance_as_of?: string | null;
  current_balance_status?:
    'needs_observation' | 'observed' | 'estimated' | 'stale' | 'incomplete' | 'needs_review';
  current_balance_confidence?: number;
  current_balance_reason_codes?: string[];
  latest_observed_balance?: number | null;
  latest_observed_as_of?: string | null;
  latest_observed_verified?: boolean | null;
  created_at: string;
  updated_at?: string | null;
}

export interface AccountIdentityEvidence {
  source_type: string;
  source_id: string;
  role: string;
  note?: string | null;
  observed_at?: string | null;
}

export interface AccountIdentitySnapshot {
  financial_account_id: string;
  captured_at: string;
  effective_date: string;
  institution_name: string;
  account_type: string;
  balance_kind: 'asset' | 'liability';
  masked_number: string;
  currency: string;
  is_active: boolean;
  identity_status: 'unresolved' | 'inferred' | 'confirmed';
  identity_confidence: number;
  identity_evidence: AccountIdentityEvidence[];
}

export type AccountProductType =
  'bank' | 'credit_card' | 'loan' | 'pay_later' | 'cash' | 'investment' | 'unknown';

export interface AccountLinkRule {
  id: string;
  user_id: string;
  financial_account_id: string;
  evidence_kind: 'masked_suffix';
  evidence_value: string;
  currency: string;
  is_active: boolean;
  repaired_transaction_count: number;
  created_at: string;
}

export interface BalanceSnapshot {
  id: string;
  financial_account_id: string;
  amount: number;
  currency: string;
  as_of: string;
  source: string;
  source_record_id?: string | null;
  verified: boolean;
  observed_at: string;
  effective_at?: string | null;
  created_at: string;
}

export type BalanceProviderReadinessStatus =
  'not_configured' | 'blocked' | 'ready' | 'due' | 'overdue' | 'incomplete';

export interface BalanceProviderAccountStatus {
  financial_account_id: string;
  account_type: 'bank' | 'credit_card' | 'loan' | 'pay_later' | 'cash' | 'investment' | 'unknown';
  masked_number: string;
  status: 'unmapped' | 'not_configured' | 'ready' | 'due' | 'overdue' | 'incomplete';
  source_account_id?: string | null;
  expected_next_at?: string | null;
  last_observed_at?: string | null;
  last_success_at?: string | null;
  coverage_complete?: boolean | null;
  freshness_status: 'fresh' | 'due' | 'overdue' | 'unknown';
  reason_codes: string[];
}

export interface BalanceProviderStatus {
  schema_version: string;
  status: BalanceProviderReadinessStatus;
  refresh_supported: boolean;
  consent_required: boolean;
  provider_name?: string | null;
  supported_provider_types?: string[];
  connections?: BalanceProviderConnection[];
  account_count: number;
  mapped_account_count: number;
  last_success_at?: string | null;
  reason_codes: string[];
  next_step: string;
  accounts: BalanceProviderAccountStatus[];
}

export type BalanceProviderConnectionStatus =
  'pending' | 'active' | 'expired' | 'revoked' | 'error';

export interface BalanceProviderConnection {
  id: string;
  provider_type: string;
  status: BalanceProviderConnectionStatus;
  consent_requested_at?: string | null;
  consent_granted_at?: string | null;
  consent_expires_at?: string | null;
  last_refresh_requested_at?: string | null;
  last_refresh_started_at?: string | null;
  last_refresh_completed_at?: string | null;
  last_error_code?: string | null;
}

export interface BalanceProviderAccountMapping {
  id: string;
  financial_account_id: string;
  provider_type: string;
  provider_account_id: string;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface BalanceProviderAccountCandidate {
  provider_account_id: string;
  display_name?: string | null;
  masked_number?: string | null;
  account_type?: 'bank' | 'credit_card' | 'loan' | 'pay_later' | 'cash' | 'investment' | null;
  currency?: string | null;
  mapped_financial_account_id?: string | null;
}

export interface CardPositionObservation {
  id: string;
  financial_account_id: string;
  currency: string;
  current_outstanding: number;
  billed_due?: number | null;
  pending_amount?: number | null;
  credit_limit?: number | null;
  available_credit?: number | null;
  as_of: string;
  source: string;
  source_record_id: string;
  source_account_id?: string | null;
  observed_at: string;
  effective_at?: string | null;
  expected_cadence_minutes?: number | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  coverage_complete: boolean;
  created_at: string;
}

/** Issuer/connector payload accepted by POST /accounts/{account_id}/card-observations. */
export interface CardPositionObservationCreate {
  current_outstanding: number;
  billed_due?: number | null;
  pending_amount?: number | null;
  credit_limit?: number | null;
  available_credit?: number | null;
  currency: string;
  as_of: string;
  source_record_id: string;
  source_account_id?: string | null;
  observed_at?: string | null;
  effective_at?: string | null;
  expected_cadence_minutes?: number | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  coverage_complete?: boolean;
}

export interface AccountPosition {
  financial_account_id: string;
  currency: string;
  balance_kind: 'asset' | 'liability';
  verified_balance: number | null;
  balance_as_of: string | null;
  balance_source: string | null;
  observed_balance: number | null;
  observed_as_of: string | null;
  observed_verified: boolean | null;
  observed_source?: string | null;
  observed_source_record_id?: string | null;
  observed_at?: string | null;
  observed_effective_at?: string | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  latest_sync_at?: string | null;
  coverage_complete?: boolean | null;
  coverage_status?: 'fresh' | 'due' | 'overdue' | 'unknown';
  reconciliation_delta?: number | null;
  last_reconciled_at?: string | null;
  estimated_balance: number | null;
  estimated_as_of: string | null;
  settled_movement_since_observation: number | null;
  pending_increase: number;
  pending_decrease: number;
  position_status:
    'needs_observation' | 'observed' | 'estimated' | 'stale' | 'incomplete' | 'needs_review';
  position_confidence: number;
  position_reason_codes: string[];
  position_ruleset_version: string;
  opening_balance: number | null;
  opening_as_of: string | null;
  known_movement: number | null;
  inflows: number;
  outflows: number;
  rail_breakdown: Record<string, number>;
  reconciliation_status: 'not_ready' | 'reconciled' | 'needs_review';
  unexplained_amount: number | null;
  review_count: number;
  reconciliation_items: Array<{
    id: string;
    kind:
      'transaction_review' | 'duplicate_candidate' | 'unlinked_transfer' | 'unexplained_movement';
    title: string;
    description: string;
    amount: number | null;
    activity_date: string | null;
    transaction_ids: string[];
    basis: string;
  }>;
}

export interface BalanceReconciliation {
  id: string;
  financial_account_id: string;
  opening_snapshot_id: string;
  closing_snapshot_id: string;
  currency: string;
  balance_kind: 'asset' | 'liability';
  opening_as_of: string;
  closing_as_of: string;
  opening_balance: number;
  known_movement: number;
  expected_closing_balance: number;
  observed_closing_balance: number;
  residual: number;
  absolute_residual: number;
  transaction_count: number;
  eligible_transaction_count: number;
  excluded_transaction_count: number;
  eligible_transaction_ids: string[];
  excluded_transaction_ids: string[];
  reason_codes: string[];
  reconciliation_status: 'reconciled' | 'needs_review';
  ruleset_version: string;
  created_at: string;
}

export interface AccountBalanceForecastPoint {
  date: string;
  expected_balance: number | null;
  low_balance: number | null;
  high_balance: number | null;
  scheduled_increase: number;
  scheduled_decrease: number;
  baseline_increase: number;
  baseline_decrease: number;
  event_count: number;
  evidence_ids: string[];
  risk: 'none' | 'watch' | 'shortfall' | 'limit_pressure';
  risk_reasons: string[];
}

export interface AccountBalanceForecast {
  financial_account_id: string;
  account_type: string;
  institution_name: string;
  masked_number: string;
  currency: string;
  balance_kind: 'asset' | 'liability';
  status: 'ready' | 'needs_anchor' | 'needs_review';
  horizon_start: string;
  horizon_end: string;
  horizon_days: number;
  starting_balance: number | null;
  starting_balance_as_of: string | null;
  starting_balance_basis: 'observed' | 'estimated' | null;
  expected_ending_balance: number | null;
  expected_change: number | null;
  lowest_expected_balance: number | null;
  lowest_expected_date: string | null;
  first_shortfall_date: string | null;
  scheduled_increase_total: number;
  scheduled_decrease_total: number;
  baseline_increase_total: number;
  baseline_decrease_total: number;
  event_count: number;
  historical_days: number;
  historical_activity_count: number;
  coverage_status: 'fresh' | 'due' | 'overdue' | 'unknown';
  position_status: string;
  position_confidence: number;
  confidence: number;
  data_sufficiency: 'low' | 'medium' | 'high';
  position_reason_codes: string[];
  assumptions: string[];
  evidence: Array<{ label: string; value: string }>;
  points: AccountBalanceForecastPoint[];
  ruleset_version: string;
}

export interface AccountBalanceForecastSnapshot {
  id: string;
  financial_account_id: string;
  currency: string;
  balance_kind: 'asset' | 'liability';
  cutoff_date: string;
  horizon_start: string;
  horizon_end: string;
  horizon_days: number;
  forecast_ruleset_version: string;
  status: 'ready' | 'needs_anchor' | 'needs_review';
  starting_balance: number | null;
  starting_balance_as_of: string | null;
  starting_balance_basis: 'observed' | 'estimated' | null;
  expected_ending_balance: number | null;
  expected_change: number | null;
  lowest_expected_balance: number | null;
  lowest_expected_date: string | null;
  first_shortfall_date: string | null;
  event_count: number;
  historical_days: number;
  historical_activity_count: number;
  coverage_status: 'fresh' | 'due' | 'overdue' | 'unknown';
  position_status: string;
  position_confidence: number;
  confidence: number;
  data_sufficiency: 'low' | 'medium' | 'high';
  position_reason_codes: string[];
  evidence: Array<{ label: string; value: string }>;
  assumptions: string[];
  points: AccountBalanceForecastPoint[];
  created_at: string;
}

export interface AccountBalanceForecastOutcome {
  id: string;
  snapshot_id: string;
  financial_account_id: string;
  target_date: string;
  cutoff_date: string;
  actual_observation_id: string;
  actual_source: string;
  actual_balance: number;
  expected_balance: number;
  low_balance: number | null;
  high_balance: number | null;
  signed_error: number;
  absolute_error: number;
  interval_covered: boolean | null;
  predicted_risk: 'none' | 'watch' | 'shortfall' | 'limit_pressure';
  forecast_ruleset_version: string;
  outcome_ruleset_version: string;
  evaluated_at: string;
}

export interface AccountBalanceForecastEvaluation {
  evaluation_version: string;
  evaluated_count: number;
  already_evaluated_count: number;
  pending_count: number;
  interval_coverage_pct: number | null;
  mean_absolute_error: number | null;
  outcomes: AccountBalanceForecastOutcome[];
}

export interface CardDueRunway {
  financial_account_id: string;
  currency: string;
  status:
    | 'covered'
    | 'at_risk'
    | 'needs_statement'
    | 'needs_payment_account'
    | 'needs_funding_anchor'
    | 'needs_review'
    | 'due_passed';
  statement_date: string | null;
  due_date: string | null;
  days_until_due: number | null;
  total_due: number | null;
  minimum_due: number | null;
  estimated_current_outstanding: number | null;
  credit_limit: number | null;
  issuer_available_credit_limit: number | null;
  funding_account_id: string | null;
  funding_account_label: string | null;
  funding_balance_basis: 'observed' | 'estimated' | null;
  funding_balance_as_of: string | null;
  funding_position_status: string | null;
  funding_balance_before_due_expected: number | null;
  funding_balance_before_due_low: number | null;
  funding_balance_before_due_high: number | null;
  expected_balance_after_total_due: number | null;
  expected_cash_gap: number | null;
  lower_band_cash_gap: number | null;
  planned_payment_total: number;
  expected_total_due_covered: boolean | null;
  lower_band_total_due_covered: boolean | null;
  minimum_due_covered_on_lower_band: boolean | null;
  payment_scenarios: CardPaymentScenario[];
  confidence: number;
  position_reason_codes: string[];
  evidence: Array<{ label: string; value: string }>;
  assumptions: string[];
  ruleset_version: string;
}

export interface Commitment {
  id: string;
  user_id: string;
  label: string;
  commitment_type: string;
  amount: number;
  due_date: string;
  cadence?: 'weekly' | 'monthly' | 'quarterly' | 'annual' | null;
  financial_account_id?: string | null;
  liability_id?: string | null;
  source_kind: 'manual' | 'email' | 'statement' | 'connector';
  source_identifier?: string | null;
  confirmed: boolean;
  is_active: boolean;
  created_at: string;
}

export interface ReservePlan {
  id: string;
  user_id: string;
  financial_account_id: string;
  label: string;
  target_amount: number;
  due_date: string;
  monthly_allocation: number;
  approved: boolean;
  is_active: boolean;
  created_at: string;
}

export interface Liability {
  id: string;
  user_id: string;
  label: string;
  liability_type: 'loan' | 'pay_later' | 'card_emi' | 'credit_card';
  financial_account_id?: string | null;
  source_kind: 'manual' | 'email' | 'statement' | 'connector';
  source_identifier?: string | null;
  source_confidence?: number | null;
  issuer_plan_reference?: string | null;
  outstanding_principal?: number | null;
  monthly_due?: number | null;
  next_due_date?: string | null;
  end_date?: string | null;
  interest_rate?: number | null;
  tenure_months?: number | null;
  remaining_installments?: number | null;
  observed_original_amount?: number | null;
  observed_monthly_amount?: number | null;
  observed_principal_component?: number | null;
  observed_interest_component?: number | null;
  observed_tax_component?: number | null;
  observed_fee_component?: number | null;
  last_observed_statement_date?: string | null;
  evidence_line_count: number;
  schedule_status: 'not_provided' | 'observed_partial' | 'confirmed';
  complete_schedule: boolean;
  is_active: boolean;
  created_at: string;
}

export interface LiabilityScheduleItem {
  id: string;
  liability_id: string;
  user_id: string;
  due_date: string;
  installment_amount: number;
  principal_amount?: number | null;
  interest_amount?: number | null;
  tax_amount?: number | null;
  fee_amount?: number | null;
  source_kind: string;
  source_identifier?: string | null;
  confidence?: number | null;
  status: 'upcoming' | 'paid' | 'skipped';
}

export interface LiabilityOverview {
  currency: string;
  liabilities: Liability[];
  known_monthly_debt: number;
  confirmed_monthly_debt: number;
  observed_card_emi_monthly: number;
  next_due_date?: string | null;
  next_due_amount?: number | null;
  complete_schedule_count: number;
  partial_evidence_count: number;
  assumptions: string[];
}

export interface RoadmapBill {
  id: string;
  user_id: string;
  financial_account_id?: string | null;
  label: string;
  bill_type: 'bill' | 'subscription' | 'insurance' | 'utility' | 'rent';
  amount: number;
  due_date: string;
  cadence?: 'weekly' | 'monthly' | 'quarterly' | 'annual' | null;
  status: 'due' | 'due_soon' | 'paid' | 'skipped';
  source_kind: 'manual' | 'email' | 'statement' | 'connector';
  source_identifier?: string | null;
  confirmed: boolean;
  paid_at?: string | null;
  created_at: string;
}

export interface HealthChecklistItem {
  id: string;
  user_id: string;
  item_type:
    'emergency_fund' | 'health_insurance' | 'life_insurance' | 'nominee' | 'will' | 'other';
  label: string;
  status: 'not_started' | 'in_progress' | 'complete' | 'not_applicable';
  note?: string | null;
  reviewed_at: string;
}

export interface CardDispute {
  id: string;
  user_id: string;
  financial_account_id: string;
  statement_line_id?: string | null;
  label: string;
  amount: number;
  complaint_date: string;
  reference_number?: string | null;
  status: 'open' | 'issuer_review' | 'resolved' | 'rejected';
  note?: string | null;
  created_at: string;
}

export interface HouseholdSummary {
  id: string;
  owner_user_id: string;
  name: string;
  member_count: number;
  expense_count: number;
  open_settlement_count: number;
  created_at: string;
}

export interface HouseholdMember {
  id: string;
  household_id: string;
  user_id: string;
  role: 'owner' | 'member' | 'viewer';
  visibility: 'annotations_only';
  joined_at: string;
}

export interface HouseholdExpense {
  id: string;
  household_id: string;
  created_by_user_id: string;
  payer_user_id: string;
  label: string;
  amount: number;
  currency: string;
  expense_date: string;
  splits: Record<string, number>;
  created_at: string;
}

export interface HouseholdSettlement {
  id: string;
  household_id: string;
  created_by_user_id: string;
  from_user_id: string;
  to_user_id: string;
  amount: number;
  currency: string;
  settlement_date: string;
  status: 'planned' | 'recorded' | 'cancelled';
  note?: string | null;
  created_at: string;
}

export interface PayoffComparison {
  readiness: 'ready' | 'needs_complete_liabilities' | 'insufficient_budget';
  monthly_budget: number;
  debts: Array<{
    liability_id: string;
    label: string;
    starting_balance: number;
    annual_interest_rate: number;
    minimum_payment: number;
  }>;
  excluded_liability_ids: string[];
  scenarios: Array<{
    method: 'highest_interest_first' | 'smallest_balance_first';
    payoff_order: string[];
    estimated_months?: number | null;
    estimated_interest?: number | null;
  }>;
  assumptions: string[];
}

export interface CashPlan {
  primary_financial_account_id: string;
  currency: string;
  verified_balance: number | null;
  balance_as_of: string | null;
  estimated_balance?: number | null;
  estimated_balance_as_of?: string | null;
  planning_balance?: number | null;
  planning_balance_as_of?: string | null;
  balance_basis?: 'verified' | 'estimated' | null;
  position_status?:
    'needs_observation' | 'observed' | 'estimated' | 'stale' | 'incomplete' | 'needs_review';
  position_confidence?: number;
  position_reason_codes?: string[];
  observed_source?: string | null;
  observed_at?: string | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  latest_sync_at?: string | null;
  coverage_complete?: boolean | null;
  coverage_status?: 'fresh' | 'due' | 'overdue' | 'unknown';
  settled_movement_since_observation?: number | null;
  pending_increase?: number;
  pending_decrease?: number;
  next_income_date: string | null;
  confirmed_commitments: Commitment[];
  commitment_total: number;
  approved_reserve_total: number;
  flexible_money: number | null;
  daily_allowance: number | null;
  readiness:
    | 'ready'
    | 'needs_verified_balance'
    | 'needs_fresh_balance'
    | 'needs_next_income'
    | 'needs_position_review';
  assumptions: string[];
}

export interface CardPaymentIntent {
  id: string;
  financial_account_id: string;
  paying_account_id?: string | null;
  amount: number;
  planned_for: string;
  note?: string | null;
  status: 'planned' | 'recorded' | 'cancelled';
  transfer_group_id?: string | null;
  created_at: string;
}

export interface CardCalendarEvent {
  id: string;
  financial_account_id: string;
  event_type: 'renewal' | 'annual_fee' | 'fee_reversal' | 'milestone';
  label: string;
  event_date: string;
  source_kind: string;
  created_at: string;
}

export interface CardStatementProjection {
  status:
    | 'available'
    | 'needs_recent_statement'
    | 'needs_current_position'
    | 'needs_credit_limit'
    | 'needs_activity';
  as_of?: string | null;
  projected_statement_date?: string | null;
  projected_balance?: number | null;
  range_low?: number | null;
  range_high?: number | null;
  projected_utilization_pct?: number | null;
  confidence: number;
  next_state:
    'monitor_cycle' | 'reduce_spend_or_pay' | 'prepare_statement_payment' | 'review_evidence';
  target_status: 'under_target' | 'at_risk' | 'over_target' | 'unavailable';
  target_headroom_amount: number | null;
  target_excess_amount: number | null;
  target_breach_date?: string | null;
  target_breach_days?: number | null;
  credit_limit_status: 'under_limit' | 'at_risk' | 'over_limit' | 'unavailable';
  credit_limit_headroom_amount: number | null;
  credit_limit_excess_amount: number | null;
  credit_limit_breach_date?: string | null;
  credit_limit_breach_days?: number | null;
  calibration: 'current_cycle_only' | 'historical_blend';
  historical_sample_count: number;
  seasonal_sample_count: number;
  seasonal_days_covered: number;
  known_future_payment_total: number;
  known_future_charge_total: number;
  known_future_recurring_charge_total: number;
  potential_pending_refund_total: number;
  recurring_charge_candidates: Array<{
    merchant: string;
    expected_date: string;
    expected_date_low: string;
    expected_date_high: string;
    expected_amount: number;
    expected_amount_low: number;
    expected_amount_high: number;
    cadence?: string | null;
    occurrences: number;
    confidence: number;
  }>;
  daily_path: CardStatementProjectionPoint[];
  reason_codes: string[];
  evidence: Array<{ label: string; value: string; basis: string }>;
  ruleset_version: string;
}

export interface CardStatementProjectionPoint {
  date: string;
  days_from_today: number;
  projected_balance: number;
  range_low: number;
  range_high: number;
  projected_utilization_pct: number;
  target_status: 'under_target' | 'at_risk' | 'over_target' | 'unavailable';
  credit_limit_status: 'under_limit' | 'at_risk' | 'over_limit' | 'unavailable';
  event_amount: number;
  event_labels: string[];
}

export interface CardUpcomingEvent {
  id: string;
  event_type:
    | 'payment_due'
    | 'statement_close'
    | 'planned_payment'
    | 'projected_charge'
    | 'utilization_target_breach'
    | 'credit_limit_breach'
    | 'calendar_event'
    | 'pending_refund';
  date: string;
  days_from_today: number;
  label: string;
  amount?: number | null;
  source_kind: 'issuer' | 'user' | 'forecast' | 'ledger';
  status: 'observed' | 'planned' | 'estimated' | 'risk';
  confidence: number;
  reason_codes: string[];
}

export interface CardPortfolioUpcomingCard {
  financial_account_id: string;
  label: string;
  state:
    | 'monitor_cycle'
    | 'payment_due'
    | 'target_pressure'
    | 'limit_pressure'
    | 'review_evidence'
    | 'no_upcoming_evidence';
  next_event?: CardUpcomingEvent | null;
  confidence: number;
  total_due?: number | null;
  due_date?: string | null;
  estimated_current_outstanding?: number | null;
  estimated_current_as_of?: string | null;
  balance_status:
    'needs_observation' | 'observed' | 'estimated' | 'stale' | 'incomplete' | 'needs_review';
  projection_status:
    | 'available'
    | 'needs_recent_statement'
    | 'needs_current_position'
    | 'needs_credit_limit'
    | 'needs_activity';
  projected_statement_date?: string | null;
  target_status: 'under_target' | 'at_risk' | 'over_target' | 'unavailable';
  credit_limit_status: 'under_limit' | 'at_risk' | 'over_limit' | 'unavailable';
  reason_codes: string[];
}

export interface CardPortfolioUpcomingState {
  as_of: string;
  state:
    | 'no_active_cards'
    | 'monitor_cycle'
    | 'payment_due'
    | 'target_pressure'
    | 'limit_pressure'
    | 'review_evidence'
    | 'no_upcoming_evidence';
  card_count: number;
  cards_with_due: number;
  issuer_total_due?: number | null;
  issuer_total_due_cards: number;
  issuer_total_due_complete: boolean;
  earliest_due_date?: string | null;
  estimated_outstanding_total?: number | null;
  estimated_outstanding_cards: number;
  estimated_outstanding_complete: boolean;
  next_event?: CardUpcomingEvent | null;
  events: CardUpcomingEvent[];
  cards_needing_review: number;
  confidence: number;
  reason_codes: string[];
  evidence: Array<{ label: string; value: string; basis: string }>;
  assumptions: string[];
  cards: CardPortfolioUpcomingCard[];
  ruleset_version: string;
}

export interface CardPaymentScenario {
  scenario: 'minimum_due' | 'total_due';
  payment_date: string;
  payment_amount: number;
  planned_payment_applied: number;
  additional_payment_amount: number;
  effective_payment_amount: number;
  remaining_total_due: number;
  expected_funding_balance_after?: number | null;
  lower_band_funding_balance_after?: number | null;
  upper_band_funding_balance_after?: number | null;
  expected_cash_gap?: number | null;
  lower_band_cash_gap?: number | null;
  expected_covered?: boolean | null;
  lower_band_covered?: boolean | null;
  status: 'covered' | 'at_risk' | 'unavailable';
}

export interface CardPortfolioPaymentPlanFundingPath {
  funding_account_id: string;
  funding_account_label: string;
  card_ids: string[];
  cards_covered_on_lower_band: number;
  cards_at_risk: number;
  forecast_status: 'ready' | 'needs_anchor' | 'needs_review';
  status: 'covered' | 'at_risk' | 'needs_review' | 'unavailable';
  starting_balance?: number | null;
  starting_balance_as_of?: string | null;
  starting_balance_basis?: 'observed' | 'estimated' | null;
  lowest_expected_balance_after?: number | null;
  lowest_lower_band_balance_after?: number | null;
  lowest_upper_band_balance_after?: number | null;
  first_lower_band_shortfall_date?: string | null;
  lower_band_cash_gap?: number | null;
  confidence: number;
  reason_codes: string[];
  assumptions: string[];
}

export interface CardPortfolioPaymentPlanStrategy {
  strategy: 'minimum_due' | 'total_due';
  status:
    | 'covered'
    | 'at_risk'
    | 'needs_statement'
    | 'needs_payment_account'
    | 'needs_review'
    | 'unavailable';
  issuer_payment_target_total?: number | null;
  planned_payment_total: number;
  additional_payment_total?: number | null;
  effective_payment_total?: number | null;
  remaining_total_due?: number | null;
  cards_with_target: number;
  cards_with_funding_path: number;
  cards_covered_on_lower_band: number;
  cards_at_risk: number;
  cards_unavailable: number;
  confidence: number;
  reason_codes: string[];
  funding_paths: CardPortfolioPaymentPlanFundingPath[];
}

export interface CardPortfolioPaymentPlanCard {
  financial_account_id: string;
  label: string;
  currency: string;
  runway_status:
    | 'covered'
    | 'at_risk'
    | 'needs_statement'
    | 'needs_payment_account'
    | 'needs_funding_anchor'
    | 'needs_review'
    | 'due_passed';
  statement_date?: string | null;
  due_date?: string | null;
  total_due?: number | null;
  minimum_due?: number | null;
  funding_account_id?: string | null;
  funding_account_label?: string | null;
  minimum_due_scenario?: CardPaymentScenario | null;
  total_due_scenario?: CardPaymentScenario | null;
  confidence: number;
  reason_codes: string[];
  evidence: Array<{ label: string; value: string }>;
  assumptions: string[];
}

export interface CardPortfolioPaymentPlan {
  as_of: string;
  state: 'no_active_cards' | 'ready' | 'partial' | 'needs_review';
  card_count: number;
  cards_with_statement: number;
  cards_needing_review: number;
  minimum_due_plan: CardPortfolioPaymentPlanStrategy;
  total_due_plan: CardPortfolioPaymentPlanStrategy;
  cards: CardPortfolioPaymentPlanCard[];
  confidence: number;
  reason_codes: string[];
  evidence: Array<{ label: string; value: string }>;
  assumptions: string[];
  ruleset_version: string;
}

export type CardSpendRoutingPriority = 'utilization_safety' | 'rewards' | 'balanced';

export interface CardSpendRoutingOption {
  financial_account_id: string;
  label: string;
  currency: string;
  status:
    'recommended' | 'eligible' | 'over_target' | 'over_limit' | 'needs_review' | 'unavailable';
  current_outstanding?: number | null;
  credit_limit?: number | null;
  current_utilization_pct?: number | null;
  projected_statement_balance?: number | null;
  projected_statement_utilization_pct?: number | null;
  utilization_status:
    'within_target' | 'over_target' | 'within_limit' | 'over_limit' | 'unavailable';
  utilization_target_pct?: number | null;
  target_headroom_amount?: number | null;
  hard_headroom_amount?: number | null;
  reward_label?: string | null;
  reward_rate_pct?: number | null;
  estimated_reward?: number | null;
  reward_status: 'explicit' | 'no_rule' | 'category_mismatch' | 'invalid_rule';
  source_kind: 'provider' | 'ledger_estimate' | 'none';
  confidence: number;
  reason_codes: string[];
  assumptions: string[];
}

export interface CardSpendRoutingResponse {
  as_of: string;
  amount: number;
  category?: string | null;
  priority: CardSpendRoutingPriority;
  currency?: string | null;
  state: 'ready' | 'partial' | 'needs_review' | 'no_active_cards';
  recommended_card_id?: string | null;
  options: CardSpendRoutingOption[];
  confidence: number;
  reason_codes: string[];
  assumptions: string[];
  ruleset_version: string;
}

export interface CardUtilizationHistoryPoint {
  as_of: string;
  basis: 'issuer_statement' | 'ledger_estimate';
  statement_id?: string | null;
  balance?: number | null;
  credit_limit?: number | null;
  utilization_pct?: number | null;
  status: 'within_target' | 'within_limit' | 'over_target' | 'over_limit' | 'unavailable';
  source_transaction_count: number;
  confidence: number;
  reason_codes: string[];
}

export interface CardUtilizationHistory {
  financial_account_id: string;
  as_of: string;
  utilization_target_pct?: number | null;
  statement_points: CardUtilizationHistoryPoint[];
  daily_points: CardUtilizationHistoryPoint[];
  trend: 'improving' | 'worsening' | 'stable' | 'insufficient_history' | 'unavailable';
  trend_basis: 'issuer_statements' | 'issuer_to_current_estimate' | 'unavailable';
  trend_delta_pct?: number | null;
  peak_statement_utilization_pct?: number | null;
  peak_daily_utilization_pct?: number | null;
  target_breach_count: number;
  credit_limit_breach_count: number;
  reason_codes: string[];
  assumptions: string[];
  ruleset_version: string;
}

export interface CardRefundTracker {
  status: 'clear' | 'pending' | 'needs_review';
  as_of: string;
  horizon_days: number;
  pending_count: number;
  pending_amount: number;
  oldest_pending_date?: string | null;
  posted_count_90d: number;
  posted_amount_90d: number;
  needs_review_count: number;
  reason_codes: string[];
  evidence: Array<{ label: string; value: string; basis: string }>;
  ruleset_version: string;
}

export interface CardOverview {
  financial_account_id: string;
  currency: string;
  latest_statement_id?: string | null;
  statement_date?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  total_due?: number | null;
  billed_total_due?: number | null;
  billed_total_due_as_of?: string | null;
  paid_since_statement?: number | null;
  unbilled_activity?: number | null;
  unbilled_activity_increase?: number | null;
  unbilled_activity_decrease?: number | null;
  minimum_due?: number | null;
  due_date?: string | null;
  previous_due?: number | null;
  payments_credits?: number | null;
  purchases_debits?: number | null;
  finance_charges?: number | null;
  credit_limit?: number | null;
  available_credit_limit?: number | null;
  available_cash_limit?: number | null;
  observed_balance?: number | null;
  observed_balance_as_of?: string | null;
  observed_source?: string | null;
  observed_source_record_id?: string | null;
  observed_at?: string | null;
  observed_effective_at?: string | null;
  provider_current_outstanding?: number | null;
  provider_current_outstanding_as_of?: string | null;
  provider_billed_due?: number | null;
  provider_pending_amount?: number | null;
  provider_credit_limit?: number | null;
  provider_available_credit?: number | null;
  provider_source?: string | null;
  provider_source_record_id?: string | null;
  provider_observed_at?: string | null;
  provider_effective_at?: string | null;
  provider_coverage_start?: string | null;
  provider_coverage_end?: string | null;
  provider_coverage_complete?: boolean | null;
  estimated_current_balance?: number | null;
  estimated_current_as_of?: string | null;
  settled_movement_since_observation?: number | null;
  pending_increase?: number;
  pending_decrease?: number;
  coverage_start?: string | null;
  coverage_end?: string | null;
  latest_sync_at?: string | null;
  coverage_complete?: boolean | null;
  coverage_status?: 'fresh' | 'due' | 'overdue' | 'unknown';
  reconciliation_delta?: number | null;
  last_reconciled_at?: string | null;
  estimated_utilization_pct?: number | null;
  next_statement_projection: CardStatementProjection;
  refund_tracker: CardRefundTracker;
  balance_status?:
    'needs_observation' | 'observed' | 'estimated' | 'stale' | 'incomplete' | 'needs_review';
  balance_confidence?: number;
  balance_reason_codes?: string[];
  balance_ruleset_version?: string;
  statement_utilization_pct?: number | null;
  utilization_target_pct?: number | null;
  preferred_payment_account_id?: string | null;
  reward_rules: Array<Record<string, string | number>>;
  coverage: Record<'matched' | 'newly_imported' | 'ignored_by_rule' | 'needs_review', number>;
  statement_lines: CardStatementLine[];
  statement_history: CardStatementHistoryItem[];
  planned_payments: CardPaymentIntent[];
  calendar: CardCalendarEvent[];
  activity_signals: CardActivitySignal[];
  emi_plans?: CardEmiPlan[];
}

export interface CardEmiComponent {
  statement_line_id: string;
  statement_date: string;
  transaction_date: string;
  component_kind: string;
  amount: number;
  installment_number?: number | null;
  description: string;
}

export interface CardEmiPlan {
  issuer_plan_reference: string;
  merchant: string;
  original_amount?: number | null;
  conversion_date?: string | null;
  latest_installment_number?: number | null;
  latest_statement_date?: string | null;
  latest_due_date?: string | null;
  latest_principal: number;
  latest_interest: number;
  latest_tax: number;
  latest_fees: number;
  latest_installment_amount: number;
  evidence_line_count: number;
  observed_principal: number;
  observed_interest: number;
  observed_tax: number;
  observed_fees: number;
  status: 'observed' | 'active' | 'preclosed';
  schedule_completeness: 'partial';
  limitation: string;
  missing_fields: string[];
  components: CardEmiComponent[];
}

export interface CardStatementLine {
  id: string;
  transaction_date: string;
  description: string;
  amount: number;
  transaction_type: 'debit' | 'credit' | 'refund';
  card_event:
    'purchase' | 'payment' | 'refund' | 'cashback' | 'fee' | 'tax' | 'interest' | 'reversal';
  component_kind: string;
  issuer_plan_reference?: string | null;
  installment_number?: number | null;
  merchant_normalized?: string | null;
  merchant_confidence?: number | null;
  review_outcome: 'matched' | 'newly_imported' | 'ignored_by_rule' | 'needs_review';
  created_transaction_id?: string | null;
}

export interface ImportedCreditCardStatement {
  id: string;
  financial_account_id: string;
  statement_date: string;
  period_start: string;
  period_end: string;
  due_date?: string | null;
  total_due?: number | null;
  minimum_due?: number | null;
  credit_limit?: number | null;
  available_credit_limit?: number | null;
  available_cash_limit?: number | null;
  previous_due?: number | null;
  payments_credits?: number | null;
  purchases_debits?: number | null;
  finance_charges?: number | null;
  currency: string;
  lines: CardStatementLine[];
}

export interface StatementDetection {
  /** Null means the product family is recognized but the issuer is not mapped. */
  institution?: string | null;
  product_type: 'credit_card' | 'deposit_account' | 'unknown';
  format_id?: string | null;
  support_status: 'supported' | 'recognized_not_supported' | 'ambiguous' | 'unsupported';
  confidence: number;
  reason_codes: string[];
  activity_types: string[];
  detector_version: string;
}

export interface StatementAnalysisLine {
  line_number: number;
  transaction_date?: string | null;
  description: string;
  amount?: number | null;
  direction: 'debit' | 'credit' | 'unknown';
  payment_rail: 'upi' | 'debit_card' | 'atm' | 'transfer' | 'credit_card' | 'other' | 'unknown';
  balance_after?: number | null;
  confidence: number;
  reason_codes: string[];
}

export interface StatementAnalysis {
  status: 'available' | 'partial' | 'signature_only' | 'failed';
  source_kind: 'reviewed_extractor' | 'generic_table' | 'signature_only';
  period_start?: string | null;
  period_end?: string | null;
  opening_balance?: number | null;
  closing_balance?: number | null;
  row_count: number;
  preview_count: number;
  omitted_line_count: number;
  debit_total: number;
  credit_total: number;
  rail_totals: Record<string, number>;
  reconciled?: boolean | null;
  confidence: number;
  reason_codes: string[];
  ruleset_version: string;
  lines: StatementAnalysisLine[];
}

export interface StatementAnalysisReview {
  id: string;
  document_fingerprint: string;
  institution?: string | null;
  product_type: 'credit_card' | 'deposit_account' | 'unknown';
  format_id?: string | null;
  support_status: 'supported' | 'recognized_not_supported' | 'ambiguous' | 'unsupported';
  confidence: number;
  reason_codes: string[];
  activity_types: string[];
  detector_version: string;
  status: 'ready_to_import' | 'pending_review';
  analysis: StatementAnalysis;
  created_at: string;
}

export interface DepositStatementLine {
  id: string;
  line_number: number;
  transaction_date: string;
  value_date: string;
  description: string;
  reference_id?: string | null;
  amount: number;
  transaction_type: 'debit' | 'credit';
  payment_rail: 'upi' | 'debit_card' | 'atm' | 'transfer' | 'other';
  balance_after: number;
  review_outcome: string;
  created_transaction_id?: string | null;
}

export interface ImportedDepositAccountStatement {
  id: string;
  financial_account_id: string;
  period_start: string;
  period_end: string;
  opening_balance: number;
  closing_balance: number;
  currency: string;
  imported_transaction_count: number;
  review_count: number;
  lines: DepositStatementLine[];
}

export interface DepositStatementReviewItem extends DepositStatementLine {
  financial_account_id: string;
  account_label: string;
  masked_number: string;
  period_start: string;
  period_end: string;
  decision_count: number;
}

export interface DepositStatementLineReviewResponse {
  line: DepositStatementLine;
  decision: 'ignore' | 'import';
  previous_outcome: string;
  new_outcome: string;
  payment_rail: DepositStatementLine['payment_rail'];
  created_transaction_id?: string | null;
  decided_at: string;
}

export interface StatementImportResult {
  product_type: 'credit_card' | 'deposit_account';
  detection: StatementDetection;
  credit_card_statement?: ImportedCreditCardStatement | null;
  deposit_account_statement?: ImportedDepositAccountStatement | null;
}

export interface StatementReviewItem extends CardStatementLine {
  financial_account_id: string;
  account_label: string;
  masked_number: string;
  statement_date: string;
  decision_count: number;
  candidate_transactions: Array<{
    id: string;
    label: string;
    amount: number;
    transaction_date: string;
    transaction_type: 'debit' | 'credit' | 'refund';
    source_kind: string;
  }>;
}

export interface StatementLineReviewResponse {
  line: CardStatementLine;
  decision: 'ignore' | 'match' | 'import' | 'record_card_payment';
  previous_outcome: CardStatementLine['review_outcome'];
  new_outcome: CardStatementLine['review_outcome'];
  matched_transaction_id?: string | null;
  paying_account_id?: string | null;
  decided_at: string;
}

export interface CardStatementHistoryItem {
  id: string;
  statement_date: string;
  period_start: string;
  period_end: string;
  due_date?: string | null;
  total_due?: number | null;
  minimum_due?: number | null;
  line_count: number;
  needs_review_count: number;
}

export interface CardActivitySignal {
  id: string;
  signal_type: 'duplicate_candidate' | 'high_value' | 'pending_reversal';
  title: string;
  description: string;
  amount: number;
  activity_date: string;
  basis: string;
}

export interface NetWorthPoint {
  date: string;
  assets: number;
  liabilities: number;
  net_worth: number;
}

export interface NetWorthSeries {
  currency: string;
  as_of?: string | null;
  assets: number;
  liabilities: number;
  net_worth: number;
  points: NetWorthPoint[];
  current_position_status?:
    | 'observed'
    | 'estimated'
    | 'partial'
    | 'needs_review'
    | 'stale'
    | 'not_available'
    | 'historical';
  current_position_confidence?: number;
  current_position_reason_codes?: string[];
  current_position_as_of?: string | null;
}

export interface Transfer {
  transfer_group_id: string;
  debit_transaction_id: string;
  credit_transaction_id: string;
  amount: number;
  currency: string;
  transaction_date: string;
  payment_rail: 'transfer' | 'atm';
}

export interface TransferMatchCandidate {
  candidate_id: string;
  debit_transaction_id: string;
  credit_transaction_id: string;
  debit_account_id: string;
  debit_account_label: string;
  credit_account_id: string;
  credit_account_label: string;
  amount: number;
  currency: string;
  debit_date: string;
  credit_date: string;
  date_difference_days: number;
  kind: 'card_payment' | 'account_transfer';
  confidence: number;
  ambiguous: boolean;
  reason_codes: string[];
}

export interface TransactionSplit {
  id: string;
  transaction_id: string;
  user_id: string;
  label: string;
  amount: number;
  category_id?: string | null;
  created_at: string;
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

export interface ProductCapabilitySource {
  key: string;
  label: string;
  status: 'beta' | 'best_effort' | 'deferred';
  scope: string;
  freshness: string;
  limitations: string[];
}

export interface ProductRecoveryPath {
  code: string;
  label: string;
  target: string;
  description: string;
}

export interface ProductCapabilitiesResponse {
  schema_version: string;
  product_stage: 'beta' | 'product_candidate' | 'production';
  incident_status: 'not_configured' | 'operational';
  incident_message: string;
  sources: ProductCapabilitySource[];
  recovery_paths: ProductRecoveryPath[];
}

export type OperationalHealthStatus = 'healthy' | 'degraded' | 'needs_repair';

export interface OperationalHealth {
  status: OperationalHealthStatus;
  status_reasons: string[];
  data_warnings: string[];
}

export type IntelligenceReadinessStatus = 'ready' | 'collecting' | 'blocked' | 'deferred';

export interface IntelligenceReadinessGate {
  key: string;
  label: string;
  status: IntelligenceReadinessStatus;
  summary: string;
  next_step: string;
  target?: string | null;
  evidence: string[];
}

export interface TemporalHistoryReadiness {
  transaction_rows: number;
  transaction_snapshots: number;
  transaction_coverage_pct: number;
  account_rows: number;
  account_snapshots: number;
  account_coverage_pct: number;
  statement_line_rows: number;
  statement_line_snapshots: number;
  statement_line_coverage_pct: number;
  card_payment_intent_rows: number;
  card_payment_intent_snapshots: number;
  card_payment_intent_coverage_pct: number;
  forward_only: boolean;
}

export interface ForecastReadiness {
  evaluated_months: number;
  eligible_horizons: number;
  interval_coverage_floor_pct: number;
  maximum_mape_pct: number;
  temporal_evidence_evaluated: boolean;
  transaction_history_coverage_pct: number;
  category_mix_supported_periods: number;
  daily_snapshot_count: number;
  daily_outcome_count: number;
  daily_interval_coverage_pct: number | null;
  daily_mean_absolute_error: number | null;
}

export interface ReconciliationReadiness {
  status: IntelligenceReadinessStatus;
  evidence_score: number;
  transaction_review_coverage_pct: number;
  statement_resolution_coverage_pct: number;
  account_reconciliation_coverage_pct: number;
  unresolved_items: number;
  duplicate_candidate_groups: number;
  unexplained_movements: number;
}

export interface ReconciliationQualityResponse {
  schema_version: string;
  as_of: string;
  status: IntelligenceReadinessStatus;
  evidence_score: number;
  transaction_total: number;
  transaction_reviewed: number;
  transaction_needs_review: number;
  transaction_ignored: number;
  transaction_review_coverage_pct: number;
  account_total: number;
  accounts_with_history: number;
  accounts_reconciled: number;
  accounts_needs_review: number;
  accounts_not_ready: number;
  account_reconciliation_coverage_pct: number;
  statement_line_total: number;
  statement_lines_matched: number;
  statement_lines_newly_imported: number;
  statement_lines_ignored: number;
  statement_lines_needs_review: number;
  statement_resolution_coverage_pct: number;
  duplicate_candidate_groups: number;
  unexplained_movements: number;
  unresolved_items: number;
  evidence: string[];
  limitations: string[];
}

export interface IntelligenceReadinessResponse {
  schema_version: string;
  as_of: string;
  product_stage: 'beta' | 'product_candidate' | 'production';
  overall_status: IntelligenceReadinessStatus;
  evidence_readiness_score: number;
  source_coverage_score: number;
  temporal_history: TemporalHistoryReadiness;
  forecast: ForecastReadiness;
  reconciliation: ReconciliationReadiness;
  recommendation_evidence_status: IntelligenceReadinessStatus;
  gates: IntelligenceReadinessGate[];
  assumptions: string[];
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

export interface FinancialIntelligenceRepairResponse {
  dry_run: boolean;
  email_merchants_repaired: number;
  statement_merchants_repaired: number;
  source_provenance_repaired: number;
  transaction_semantics_repaired: number;
  emi_components_classified: number;
  emi_ledger_events_projected: number;
  accounting_adjustments_marked: number;
  non_spend_payments_classified: number;
  duplicates_merged: number;
  fuel_surcharge_duplicates_merged: number;
  amounts_reconciled_to_statement: number;
  liabilities_synced: number;
  false_positive_transactions_removed: number;
  conflicts_held_for_review: number;
}
