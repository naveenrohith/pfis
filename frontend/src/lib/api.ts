import type {
  AuthSessionResponse,
  AutoSyncStatus,
  FinancialChangePage,
  AccountLinkRule,
  BudgetDrilldown,
  BudgetTracker,
  BulkUpdateResponse,
  CashFlowProjection,
  ScenarioRequest,
  ScenarioResponse,
  Category,
  CategoryIntelligenceResponse,
  EmailsResponse,
  FinancialAccount,
  AccountIdentitySnapshot,
  FinancialHorizonResponse,
  ExplainPayload,
  ExplainResponse,
  FinancialHealthScore,
  SourceCoverageResponse,
  FinancialIntelligenceRepairResponse,
  GmailDisconnectResponse,
  GuidanceBrief,
  GuidancePeriod,
  GuidanceQueryResult,
  IntelligenceReadinessResponse,
  ReconciliationQualityResponse,
  RecommendationDecision,
  RecommendationEffectivenessReport,
  RecommendationOutcome,
  RecommendationOutcomeKind,
  Goal,
  GoalCreatePayload,
  InsightsResponse,
  SpendingAnomaly,
  AnomalyAdjudicationResponse,
  Job,
  LearnedMerchantRule,
  MerchantDetail,
  MerchantSummary,
  MonthComparison,
  PipelineFailuresResponse,
  PipelineMetrics,
  PipelineReprocessRequest,
  PipelineReprocessResponse,
  PipelineRetryResponse,
  ProductCapabilitiesResponse,
  OperationalHealth,
  SyncStatusResponse,
  Transaction,
  TransactionCreatePayload,
  TransactionSummary,
  TransactionSplit,
  TransactionType,
  TemporalEventSummary,
  TemporalFinancialEvent,
  TemporalHistoryBackfillResponse,
  PaymentMethod,
  User,
  DashboardPreferences,
  BalanceSnapshot,
  BalanceProviderConnection,
  BalanceProviderAccountMapping,
  BalanceProviderAccountCandidate,
  BalanceProviderStatus,
  CardPositionObservation,
  CardPositionObservationCreate,
  AccountPosition,
  AccountBalanceForecast,
  AccountBalanceForecastEvaluation,
  AccountBalanceForecastOutcome,
  AccountBalanceForecastSnapshot,
  BalanceReconciliation,
  CardDueRunway,
  AccountDeletionResponse,
  CardCalendarEvent,
  CardOverview,
  CardPortfolioUpcomingState,
  CardPortfolioPaymentPlan,
  CardSpendRoutingResponse,
  CardUtilizationHistory,
  CardPaymentIntent,
  CardDispute,
  CashPlan,
  Commitment,
  HealthChecklistItem,
  HouseholdExpense,
  HouseholdMember,
  HouseholdSettlement,
  HouseholdSummary,
  ImportedCreditCardStatement,
  Liability,
  LiabilityOverview,
  LiabilityScheduleItem,
  NetWorthSeries,
  PayoffComparison,
  ReservePlan,
  RoadmapBill,
  StatementLineReviewResponse,
  DepositStatementLineReviewResponse,
  DepositStatementReviewItem,
  StatementDetection,
  StatementAnalysisReview,
  StatementImportResult,
  StatementReviewItem,
  Transfer,
  TransferMatchCandidate,
  WorkspaceResponse,
} from './types';

const API_BASE = '/api';
export const AUTH_SESSION_ENDED_EVENT = 'pfis:auth-session-ended';
let csrfCookieName = 'pfis_csrf';

function csrfHeaders(): Record<string, string> {
  if (typeof document === 'undefined') return {};
  const csrf = document.cookie
    .split('; ')
    .find((entry) => entry.startsWith(`${csrfCookieName}=`))
    ?.split('=')[1];
  return csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf) } : {};
}

function rememberSessionConfiguration(payload: AuthSessionResponse): AuthSessionResponse {
  csrfCookieName = payload.csrf_cookie_name;
  return payload;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  requestId?: string;
  details?: unknown;
  constructor(
    message: string,
    status: number,
    code?: string,
    requestId?: string,
    details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  auth?: boolean;
  tolerate401?: boolean;
  headers?: Record<string, string>;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const {
    method = 'GET',
    body,
    query,
    auth = true,
    tolerate401 = false,
    headers: extraHeaders,
  } = opts;

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
  Object.assign(headers, extraHeaders);
  if (auth && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase())) {
    Object.assign(headers, csrfHeaders());
  }

  const response = await fetch(url, {
    method,
    headers,
    credentials: 'same-origin',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (response.status === 401 && !tolerate401) {
    if (auth && typeof window !== 'undefined') {
      window.dispatchEvent(new Event(AUTH_SESSION_ENDED_EVENT));
    }
    throw new ApiError('Session expired', 401);
  }

  if (!response.ok) {
    let detail = response.statusText;
    let code: string | undefined;
    let requestId: string | undefined;
    let details: unknown;
    try {
      const errBody = await response.json();
      const error = (
        errBody as {
          detail?: string;
          error?: { code?: string; message?: string; request_id?: string; details?: unknown };
        }
      ).error;
      detail = error?.message || (errBody as { detail?: string }).detail || detail;
      code = error?.code;
      requestId = error?.request_id;
      details = error?.details;
    } catch {
      // keep statusText
    }
    throw new ApiError(detail, response.status, code, requestId, details);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function uploadStatementPdf<T>(
  path: string,
  userId: string,
  file: File,
  accountId?: string,
): Promise<T> {
  const params = new URLSearchParams({ user_id: userId });
  if (accountId) params.set('financial_account_id', accountId);
  const response = await fetch(`${API_BASE}${path}?${params}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/pdf',
      ...csrfHeaders(),
    },
    credentials: 'same-origin',
    body: file,
  });
  if (response.status === 401) {
    window.dispatchEvent(new Event(AUTH_SESSION_ENDED_EVENT));
    throw new ApiError('Session expired', 401);
  }
  if (!response.ok) {
    let detail = response.statusText;
    let code: string | undefined;
    let requestId: string | undefined;
    let details: unknown;
    try {
      const body = (await response.json()) as {
        detail?: string;
        error?: {
          code?: string;
          message?: string;
          request_id?: string;
          details?: unknown;
        };
      };
      detail = body.error?.message || body.detail || detail;
      code = body.error?.code;
      requestId = body.error?.request_id;
      details = body.error?.details;
    } catch {
      // Keep the HTTP status text for non-JSON failures.
    }
    throw new ApiError(detail, response.status, code, requestId, details);
  }
  return (await response.json()) as T;
}

export interface TransactionUpdatePayload {
  merchant_normalized?: string;
  category_id?: string | null;
  amount?: number;
  transaction_type?: TransactionType;
  payment_method?: PaymentMethod;
  reviewed_flag?: boolean;
  note?: string | null;
  tags?: string[];
}

export interface BulkUpdatePayload {
  transaction_ids: string[];
  category_id?: string | null;
  transaction_type?: TransactionType;
  payment_method?: PaymentMethod;
  reviewed_flag?: boolean;
}

export interface PortableExportDownload {
  blob: Blob;
  filename: string;
}

export const api = {
  // Auth
  login: async (email: string, password: string) =>
    rememberSessionConfiguration(
      await request<AuthSessionResponse>('/auth/login', {
        method: 'POST',
        body: { email, password },
        auth: false,
      }),
    ),
  register: async (name: string, email: string, password: string, currency: string) =>
    rememberSessionConfiguration(
      await request<AuthSessionResponse>('/auth/register', {
        method: 'POST',
        body: { name, email, password, currency },
        auth: false,
      }),
    ),
  session: async () =>
    rememberSessionConfiguration(
      await request<AuthSessionResponse>('/auth/session', { tolerate401: true }),
    ),
  financialChanges: (userId: string, afterSequence: number, limit = 250) =>
    request<FinancialChangePage>('/sync/changes', {
      query: { user_id: userId, after_sequence: afterSequence, limit },
    }),
  horizon: (userId: string, days = 30) =>
    request<FinancialHorizonResponse>('/horizon', {
      query: { user_id: userId, days },
    }),
  logout: () => request<{ status: string }>('/auth/logout', { method: 'POST' }),
  startDemo: async () =>
    rememberSessionConfiguration(
      await request<AuthSessionResponse>('/auth/demo', { method: 'POST', auth: false }),
    ),
  gmailConnectUrl: (userId: string) =>
    `${API_BASE}/auth/gmail/connect?${new URLSearchParams({ user_id: userId }).toString()}`,
  me: () => request<User>('/auth/me'),
  listUsers: () => request<User[]>('/users/', { auth: false, tolerate401: true }),
  updateUser: (
    userId: string,
    data: { name?: string; timezone?: string; raw_email_retention_days?: number | null },
  ) => request<User>(`/users/${userId}`, { method: 'PATCH', body: data }),
  deleteAccount: (userId: string, confirmation: string) =>
    request<AccountDeletionResponse>(`/users/${userId}`, {
      method: 'DELETE',
      body: { confirmation },
    }),

  // Reference data
  categories: () => request<Category[]>('/categories/'),

  // Transactions
  summary: (userId: string, month: number, year: number) =>
    request<TransactionSummary>('/transactions/summary', {
      query: { user_id: userId, month, year },
    }),
  transactions: (
    userId: string,
    params: {
      month?: number;
      year?: number;
      categoryId?: string;
      limit?: number;
      offset?: number;
      q?: string;
      transactionType?: TransactionType;
      paymentMethod?: PaymentMethod;
      reviewed?: boolean;
      sort?: 'transaction_date' | 'amount' | 'merchant' | 'created_at';
      direction?: 'asc' | 'desc';
    },
  ) =>
    request<Transaction[]>('/transactions/', {
      query: {
        user_id: userId,
        month: params.month,
        year: params.year,
        category_id: params.categoryId,
        limit: params.limit ?? 200,
        offset: params.offset,
        q: params.q,
        transaction_type: params.transactionType,
        payment_method: params.paymentMethod,
        reviewed: params.reviewed,
        sort: params.sort,
        direction: params.direction,
      },
    }),
  createTransaction: (userId: string, payload: TransactionCreatePayload) =>
    request<Transaction>('/transactions/', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateTransaction: (id: string, payload: TransactionUpdatePayload) =>
    request<Transaction>(`/transactions/${id}`, { method: 'PATCH', body: payload }),
  transactionSplits: (userId: string, id: string) =>
    request<TransactionSplit[]>(`/transactions/${id}/splits`, {
      query: { user_id: userId },
    }),
  replaceTransactionSplits: (
    userId: string,
    id: string,
    splits: Array<{ label: string; amount: number; category_id?: string | null }>,
  ) =>
    request<TransactionSplit[]>(`/transactions/${id}/splits`, {
      method: 'PUT',
      query: { user_id: userId },
      body: { splits },
    }),
  bulkUpdate: (userId: string, payload: BulkUpdatePayload) =>
    request<BulkUpdateResponse>('/transactions/bulk-update', {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  transferMatchCandidates: (userId: string, accountId?: string) =>
    request<TransferMatchCandidate[]>('/transactions/transfer-match-candidates', {
      query: { user_id: userId, account_id: accountId, limit: 100 },
    }),
  linkTransferMatch: (
    userId: string,
    transactionId: string,
    payload: { counterparty_transaction_id: string; kind: TransferMatchCandidate['kind'] },
  ) =>
    request<Transfer>(`/transactions/${transactionId}/transfer-link`, {
      method: 'POST',
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
  updateAutoSync: (userId: string, payload: { enabled?: boolean; interval_seconds?: number }) =>
    request<AutoSyncStatus>('/gmail/auto-sync', {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  disconnectGmail: (userId: string) =>
    request<GmailDisconnectResponse>('/gmail/connection', {
      method: 'DELETE',
      query: { user_id: userId },
    }),

  // Public product boundary
  productCapabilities: () =>
    request<ProductCapabilitiesResponse>('/health/capabilities', {
      auth: false,
      tolerate401: true,
    }),
  operationalHealth: () =>
    request<OperationalHealth>('/health/ops', {
      auth: false,
      tolerate401: true,
    }),

  // Insights
  insights: (userId: string, month: number, year: number) =>
    request<InsightsResponse>('/insights/', { query: { user_id: userId, month, year } }),
  adjudicateAnomaly: (
    userId: string,
    anomalyId: string,
    month: number,
    year: number,
    decision: 'expected' | 'material' | 'insufficient_evidence',
    note?: string,
  ) =>
    request<AnomalyAdjudicationResponse>(
      `/insights/anomalies/${encodeURIComponent(anomalyId)}/adjudication`,
      {
        method: 'POST',
        query: { user_id: userId, month, year },
        body: { decision, note },
      },
    ),
  anomalyAdjudications: (userId: string, limit = 100) =>
    request<AnomalyAdjudicationResponse[]>('/insights/anomaly-adjudications', {
      query: { user_id: userId, limit },
    }),
  anomalySamples: (userId: string, month: number, year: number, limit = 4) =>
    request<SpendingAnomaly[]>('/insights/anomaly-samples', {
      query: { user_id: userId, month, year, limit },
    }),
  adjudicateAnomalySample: (
    userId: string,
    sampleId: string,
    month: number,
    year: number,
    decision: 'expected' | 'material' | 'insufficient_evidence',
    note?: string,
  ) =>
    request<AnomalyAdjudicationResponse>(
      `/insights/anomaly-samples/${encodeURIComponent(sampleId)}/adjudication`,
      {
        method: 'POST',
        query: { user_id: userId, month, year },
        body: { decision, note },
      },
    ),

  // Financial Decision Workspace (aggregate)
  workspace: (userId: string, month: number, year: number) =>
    request<WorkspaceResponse>('/dashboard/workspace', {
      query: { user_id: userId, month, year },
    }),

  // Merchant and category intelligence
  merchants: (userId: string, month: number, year: number) =>
    request<MerchantSummary[]>('/merchants/', { query: { user_id: userId, month, year } }),
  learnedMerchantRules: (userId: string) =>
    request<LearnedMerchantRule[]>('/merchants/learned-rules', { query: { user_id: userId } }),
  deleteLearnedMerchantRule: (userId: string, ruleId: string) =>
    request<void>(`/merchants/learned-rules/${ruleId}`, {
      method: 'DELETE',
      query: { user_id: userId },
    }),
  merchant: (userId: string, merchantKey: string, month: number, year: number) =>
    request<MerchantDetail>(`/merchants/${encodeURIComponent(merchantKey)}`, {
      query: { user_id: userId, month, year },
    }),
  categoryIntelligence: (userId: string, month: number, year: number) =>
    request<CategoryIntelligenceResponse>('/categories/intelligence', {
      query: { user_id: userId, month, year },
    }),

  // Advanced analytics and goals
  cashFlow: (userId: string, month: number, year: number) =>
    request<CashFlowProjection>('/analytics/cash-flow', {
      query: { user_id: userId, month, year },
    }),
  previewScenario: (userId: string, payload: ScenarioRequest) =>
    request<ScenarioResponse>('/analytics/scenario', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  monthComparison: (userId: string, month: number, year: number) =>
    request<MonthComparison>('/analytics/month-comparison', {
      query: { user_id: userId, month, year },
    }),
  financialHealth: (userId: string, month: number, year: number) =>
    request<FinancialHealthScore>('/analytics/financial-health', {
      query: { user_id: userId, month, year },
    }),
  sourceCoverage: (userId: string) =>
    request<SourceCoverageResponse>('/analytics/source-coverage', {
      query: { user_id: userId },
    }),
  intelligenceReadiness: (userId: string) =>
    request<IntelligenceReadinessResponse>('/analytics/intelligence-readiness', {
      query: { user_id: userId },
    }),
  reconciliationQuality: (userId: string) =>
    request<ReconciliationQualityResponse>('/analytics/reconciliation-quality', {
      query: { user_id: userId },
    }),
  goals: (userId: string, month: number, year: number) =>
    request<Goal[]>('/goals/', { query: { user_id: userId, month, year } }),
  createGoal: (userId: string, payload: GoalCreatePayload) =>
    request<Goal>('/goals/', { method: 'POST', query: { user_id: userId }, body: payload }),
  explain: (payload: ExplainPayload, userId?: string) =>
    request<ExplainResponse>('/ai/explain', {
      method: 'POST',
      query: userId ? { user_id: userId } : undefined,
      body: payload,
    }),
  guidanceBrief: (userId: string, period: GuidancePeriod, asOf: string) =>
    request<GuidanceBrief>('/guidance/brief', {
      query: { user_id: userId, period, as_of: asOf },
    }),
  guidanceQuery: (userId: string, query: string, month: number, year: number) =>
    request<GuidanceQueryResult>('/guidance/query', {
      method: 'POST',
      query: { user_id: userId },
      body: { query, month, year },
    }),
  setGuidanceState: (
    userId: string,
    recommendationId: string,
    state: 'active' | 'dismissed' | 'snoozed' | 'accepted' | 'not_relevant',
    snoozedUntil?: string,
    asOf?: string,
    note?: string,
    reason?: 'not_relevant' | 'not_feasible' | 'already_done' | 'too_risky' | 'wrong_timing',
  ) =>
    request(`/guidance/${encodeURIComponent(recommendationId)}/state`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: { state, snoozed_until: snoozedUntil, as_of: asOf, note, reason },
    }),
  guidanceDecisions: (userId: string) =>
    request<RecommendationDecision[]>('/guidance/decisions', {
      query: { user_id: userId },
    }),
  guidanceOutcomes: (userId: string) =>
    request<RecommendationOutcome[]>('/guidance/outcomes', {
      query: { user_id: userId },
    }),
  guidanceEffectiveness: (userId: string) =>
    request<RecommendationEffectivenessReport>('/guidance/effectiveness', {
      query: { user_id: userId },
    }),
  temporalEvents: (userId: string, rangeStart?: string, rangeEnd?: string, asOf?: string) =>
    request<TemporalEventSummary>('/knowledge/events', {
      query: { user_id: userId, range_start: rangeStart, range_end: rangeEnd, as_of: asOf },
    }),
  updateTemporalEventDecision: (
    userId: string,
    eventId: string,
    payload: {
      decision: 'confirmed' | 'cancelled' | 'observed' | 'linked' | 'conflict';
      observed_date?: string;
      observed_amount?: number;
      transaction_id?: string;
      note?: string;
    },
  ) =>
    request<TemporalFinancialEvent>(`/knowledge/events/${encodeURIComponent(eventId)}/decision`, {
      method: 'PUT',
      query: { user_id: userId },
      body: payload,
    }),
  backfillTemporalHistory: (
    userId: string,
    dryRun = true,
    sourceTypes: Array<
      'transaction' | 'financial_account' | 'statement_line' | 'card_payment_intent'
    > = ['transaction', 'financial_account', 'statement_line', 'card_payment_intent'],
  ) =>
    request<TemporalHistoryBackfillResponse>('/knowledge/history/backfill', {
      method: 'POST',
      query: { user_id: userId },
      body: { dry_run: dryRun, source_types: sourceTypes },
    }),
  recordGuidanceOutcome: (userId: string, decisionId: string, outcome: RecommendationOutcomeKind) =>
    request<RecommendationOutcome>(
      `/guidance/decisions/${encodeURIComponent(decisionId)}/outcome`,
      {
        method: 'POST',
        query: { user_id: userId },
        body: { outcome },
      },
    ),

  // Personalization
  dashboardPreferences: (userId: string) =>
    request<DashboardPreferences>('/preferences/dashboard', { query: { user_id: userId } }),
  updateDashboardPreferences: (userId: string, payload: Partial<DashboardPreferences>) =>
    request<DashboardPreferences>('/preferences/dashboard', {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  resetDashboardPreferences: (userId: string) =>
    request<DashboardPreferences>('/preferences/dashboard', {
      method: 'DELETE',
      query: { user_id: userId },
    }),

  // Accounts, balances, net worth, and transfers
  accounts: (userId: string) =>
    request<FinancialAccount[]>('/accounts', { query: { user_id: userId } }),
  accountIdentityHistory: (userId: string, accountId: string) =>
    request<AccountIdentitySnapshot[]>(`/accounts/${accountId}/identity-history`, {
      query: { user_id: userId },
    }),
  accountLinkRules: (userId: string) =>
    request<AccountLinkRule[]>('/account-link-rules', {
      query: { user_id: userId },
    }),
  createAccountLinkRule: (
    userId: string,
    payload: {
      financial_account_id: string;
      evidence_kind: 'masked_suffix';
      evidence_value: string;
      currency: string;
    },
  ) =>
    request<AccountLinkRule>('/account-link-rules', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  deactivateAccountLinkRule: (userId: string, ruleId: string) =>
    request<void>(`/account-link-rules/${ruleId}`, {
      method: 'DELETE',
      query: { user_id: userId },
    }),
  createAccount: (
    userId: string,
    payload: Pick<
      FinancialAccount,
      'institution_name' | 'account_type' | 'balance_kind' | 'masked_number' | 'currency'
    >,
  ) =>
    request<FinancialAccount>('/accounts', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateAccount: (
    userId: string,
    accountId: string,
    payload: Partial<
      Pick<
        FinancialAccount,
        | 'institution_name'
        | 'account_type'
        | 'balance_kind'
        | 'masked_number'
        | 'currency'
        | 'is_active'
      >
    >,
  ) =>
    request<FinancialAccount>(`/accounts/${accountId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  addBalance: (userId: string, accountId: string, amount: number, asOf: string) =>
    request<BalanceSnapshot>(`/accounts/${accountId}/balances`, {
      method: 'POST',
      query: { user_id: userId },
      body: { amount, as_of: asOf },
    }),
  netWorth: (userId: string) =>
    request<NetWorthSeries>('/net-worth', { query: { user_id: userId } }),
  balanceProviderStatus: (userId: string) =>
    request<BalanceProviderStatus>('/balance-provider/status', { query: { user_id: userId } }),
  balanceProviderConnections: (userId: string) =>
    request<BalanceProviderConnection[]>('/balance-provider/connections', {
      query: { user_id: userId },
    }),
  requestBalanceProviderConsent: (userId: string, providerType: string) =>
    request<BalanceProviderConnection>('/balance-provider/connections', {
      method: 'POST',
      query: { user_id: userId },
      body: { provider_type: providerType },
    }),
  revokeBalanceProviderConsent: (userId: string, providerType: string) =>
    request<BalanceProviderConnection>(`/balance-provider/connections/${providerType}`, {
      method: 'DELETE',
      query: { user_id: userId },
    }),
  balanceProviderMappings: (userId: string, providerType?: string) =>
    request<BalanceProviderAccountMapping[]>('/balance-provider/mappings', {
      query: { user_id: userId, ...(providerType ? { provider_type: providerType } : {}) },
    }),
  balanceProviderDiscoveredAccounts: (userId: string, providerType: string) =>
    request<BalanceProviderAccountCandidate[]>('/balance-provider/discovered-accounts', {
      query: { user_id: userId, provider_type: providerType },
    }),
  mapBalanceProviderAccount: (
    userId: string,
    accountId: string,
    payload: { provider_type: string; provider_account_id: string },
  ) =>
    request<BalanceProviderAccountMapping>(`/accounts/${accountId}/balance-provider-mapping`, {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  unmapBalanceProviderAccount: (userId: string, accountId: string, providerType: string) =>
    request<void>(`/accounts/${accountId}/balance-provider-mapping/${providerType}`, {
      method: 'DELETE',
      query: { user_id: userId },
    }),
  enqueueBalanceRefresh: (
    userId: string,
    providerType: string,
    accountIds: string[] = [],
    idempotencyKey?: string,
  ) =>
    request<Job>('/jobs/balance-refresh', {
      method: 'POST',
      query: { user_id: userId },
      body: { provider_type: providerType, account_ids: accountIds },
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    }),
  cardPositionObservations: (userId: string, accountId: string, limit = 20) =>
    request<CardPositionObservation[]>(`/accounts/${accountId}/card-observations`, {
      query: { user_id: userId, limit },
    }),
  /** Connector-only issuer facts; user-entered positions use addBalance instead. */
  createCardPositionObservation: (
    userId: string,
    accountId: string,
    payload: CardPositionObservationCreate,
  ) =>
    request<CardPositionObservation>(`/accounts/${accountId}/card-observations`, {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  createTransfer: (
    userId: string,
    payload: {
      from_account_id: string;
      to_account_id: string;
      amount: number;
      currency: string;
      transaction_date: string;
      description?: string;
      payment_rail?: 'transfer' | 'atm';
    },
  ) =>
    request<Transfer>('/transfers', { method: 'POST', query: { user_id: userId }, body: payload }),
  linkAtmWithdrawalToCash: (userId: string, transactionId: string, cashAccountId: string) =>
    request<Transfer>(`/transactions/${transactionId}/atm-cash-link`, {
      method: 'POST',
      query: { user_id: userId },
      body: { cash_account_id: cashAccountId },
    }),
  cardOverview: (userId: string, accountId: string) =>
    request<CardOverview>(`/cards/${accountId}`, { query: { user_id: userId } }),
  cardDueRunway: (userId: string, accountId: string) =>
    request<CardDueRunway>(`/cards/${accountId}/due-runway`, { query: { user_id: userId } }),
  cardUtilizationHistory: (
    userId: string,
    accountId: string,
    statementLimit = 12,
    dailyLimit = 60,
  ) =>
    request<CardUtilizationHistory>(`/cards/${accountId}/utilization-history`, {
      query: {
        user_id: userId,
        statement_limit: statementLimit,
        daily_limit: dailyLimit,
      },
    }),
  cardPortfolioUpcomingState: (userId: string) =>
    request<CardPortfolioUpcomingState>('/cards/portfolio/upcoming-state', {
      query: { user_id: userId },
    }),
  cardPortfolioPaymentPlan: (userId: string) =>
    request<CardPortfolioPaymentPlan>('/cards/portfolio/payment-plan', {
      query: { user_id: userId },
    }),
  cardSpendRouting: (
    userId: string,
    payload: {
      amount: number;
      category?: string | null;
      priority: 'utilization_safety' | 'rewards' | 'balanced';
    },
  ) =>
    request<CardSpendRoutingResponse>('/cards/portfolio/spend-routing', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  repairFinancialIntelligence: (userId: string, dryRun = true) =>
    request<FinancialIntelligenceRepairResponse>('/financial-intelligence/repair', {
      method: 'POST',
      query: { user_id: userId },
      body: { dry_run: dryRun },
    }),
  saveCardPreferences: (
    userId: string,
    accountId: string,
    payload: {
      preferred_payment_account_id?: string | null;
      utilization_target_pct?: number | null;
      reward_rules?: Array<Record<string, string | number>>;
    },
  ) =>
    request<{
      financial_account_id: string;
      preferred_payment_account_id?: string | null;
      utilization_target_pct?: number | null;
      reward_rules: Array<Record<string, string | number>>;
    }>(`/cards/${accountId}/preferences`, {
      method: 'PUT',
      query: { user_id: userId },
      body: payload,
    }),
  createCardPaymentIntent: (
    userId: string,
    accountId: string,
    payload: {
      paying_account_id?: string | null;
      amount: number;
      planned_for: string;
      note?: string | null;
    },
  ) =>
    request<CardPaymentIntent>(`/cards/${accountId}/payment-intents`, {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateCardPaymentIntent: (
    userId: string,
    accountId: string,
    intentId: string,
    status: 'recorded' | 'cancelled',
    payingAccountId?: string | null,
  ) =>
    request<CardPaymentIntent>(`/cards/${accountId}/payment-intents/${intentId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: { status, paying_account_id: payingAccountId },
    }),
  createCardCalendarEvent: (
    userId: string,
    accountId: string,
    payload: {
      event_type: CardCalendarEvent['event_type'];
      label: string;
      event_date: string;
      source_label?: string;
      annual_fee_amount?: number | null;
      fee_reversal_condition?: string | null;
      fee_reversal_status?: CardCalendarEvent['fee_reversal_status'];
      milestone_spend_target?: number | null;
      milestone_period_start?: string | null;
      milestone_period_end?: string | null;
    },
  ) =>
    request<CardCalendarEvent>(`/cards/${accountId}/calendar`, {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateCardCalendarEvent: (
    userId: string,
    accountId: string,
    eventId: string,
    payload: Partial<
      Pick<
        CardCalendarEvent,
        | 'event_type'
        | 'label'
        | 'event_date'
        | 'source_label'
        | 'annual_fee_amount'
        | 'fee_reversal_condition'
        | 'fee_reversal_status'
        | 'milestone_spend_target'
        | 'milestone_period_start'
        | 'milestone_period_end'
      >
    >,
  ) =>
    request<CardCalendarEvent>(`/cards/${accountId}/calendar/${eventId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  deleteCardCalendarEvent: (userId: string, accountId: string, eventId: string) =>
    request<void>(`/cards/${accountId}/calendar/${eventId}`, {
      method: 'DELETE',
      query: { user_id: userId },
    }),
  accountPosition: (userId: string, accountId: string) =>
    request<AccountPosition>(`/accounts/${accountId}/position`, { query: { user_id: userId } }),
  accountBalanceReconciliations: (userId: string, accountId: string) =>
    request<BalanceReconciliation[]>(`/accounts/${accountId}/balance-reconciliations`, {
      query: { user_id: userId },
    }),
  accountBalanceForecast: (userId: string, accountId: string, horizonDays = 30) =>
    request<AccountBalanceForecast>(`/accounts/${accountId}/balance-forecast`, {
      query: { user_id: userId, horizon_days: horizonDays },
    }),
  createAccountBalanceForecastSnapshot: (
    userId: string,
    accountId: string,
    horizonDays = 30,
    cutoffDate?: string,
  ) =>
    request<AccountBalanceForecastSnapshot>(`/accounts/${accountId}/balance-forecast/snapshots`, {
      method: 'POST',
      query: { user_id: userId },
      body: { horizon_days: horizonDays, cutoff_date: cutoffDate },
    }),
  accountBalanceForecastSnapshots: (userId: string, accountId: string) =>
    request<AccountBalanceForecastSnapshot[]>(`/accounts/${accountId}/balance-forecast/snapshots`, {
      query: { user_id: userId },
    }),
  evaluateAccountBalanceForecast: (userId: string, accountId: string) =>
    request<AccountBalanceForecastEvaluation>(
      `/accounts/${accountId}/balance-forecast/outcomes/evaluate`,
      { method: 'POST', query: { user_id: userId } },
    ),
  accountBalanceForecastOutcomes: (userId: string, accountId: string) =>
    request<AccountBalanceForecastOutcome[]>(`/accounts/${accountId}/balance-forecast/outcomes`, {
      query: { user_id: userId },
    }),
  commitments: (userId: string) =>
    request<Commitment[]>('/commitments', { query: { user_id: userId } }),
  createCommitment: (
    userId: string,
    payload: Omit<Commitment, 'id' | 'user_id' | 'is_active' | 'created_at'>,
  ) =>
    request<Commitment>('/commitments', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateCommitment: (
    userId: string,
    commitmentId: string,
    payload: Partial<
      Pick<Commitment, 'label' | 'amount' | 'due_date' | 'cadence' | 'confirmed' | 'is_active'>
    >,
  ) =>
    request<Commitment>(`/commitments/${commitmentId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  cashPlan: (userId: string) => request<CashPlan>('/cash-plan', { query: { user_id: userId } }),
  updateCashPlan: (
    userId: string,
    payload: {
      primary_financial_account_id: string;
      next_income_date?: string | null;
      next_income_amount?: number | null;
      show_daily_allowance?: boolean;
    },
  ) =>
    request<CashPlan>('/cash-plan', { method: 'PUT', query: { user_id: userId }, body: payload }),
  reserves: (userId: string) => request<ReservePlan[]>('/reserves', { query: { user_id: userId } }),
  createReserve: (
    userId: string,
    payload: Omit<ReservePlan, 'id' | 'user_id' | 'is_active' | 'created_at'>,
  ) =>
    request<ReservePlan>('/reserves', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateReserve: (
    userId: string,
    reserveId: string,
    payload: Partial<
      Pick<
        ReservePlan,
        'label' | 'target_amount' | 'due_date' | 'monthly_allocation' | 'approved' | 'is_active'
      >
    >,
  ) =>
    request<ReservePlan>(`/reserves/${reserveId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  liabilities: (userId: string) =>
    request<Liability[]>('/liabilities', { query: { user_id: userId } }),
  liabilityOverview: (userId: string) =>
    request<LiabilityOverview>('/liabilities/overview', {
      query: { user_id: userId },
    }),
  createLiability: (
    userId: string,
    payload: {
      label: string;
      liability_type: Liability['liability_type'];
      financial_account_id?: string | null;
      source_kind: Liability['source_kind'];
      source_identifier?: string | null;
      source_confidence?: number | null;
      outstanding_principal?: number | null;
      monthly_due?: number | null;
      next_due_date?: string | null;
      end_date?: string | null;
      interest_rate?: number | null;
      tenure_months?: number | null;
      remaining_installments?: number | null;
      complete_schedule: boolean;
    },
  ) =>
    request<Liability>('/liabilities', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  liabilitySchedule: (userId: string, liabilityId: string) =>
    request<LiabilityScheduleItem[]>(`/liabilities/${liabilityId}/schedule`, {
      query: { user_id: userId },
    }),
  confirmLiabilitySchedule: (
    userId: string,
    liabilityId: string,
    payload: {
      source_kind: 'manual' | 'statement';
      items: Array<{
        due_date: string;
        installment_amount: number;
        principal_amount?: number | null;
        interest_amount?: number | null;
        tax_amount?: number | null;
        fee_amount?: number | null;
      }>;
    },
  ) =>
    request<LiabilityScheduleItem[]>(`/liabilities/${liabilityId}/schedule/confirm`, {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateLiabilityScheduleItem: (
    userId: string,
    liabilityId: string,
    itemId: string,
    status: LiabilityScheduleItem['status'],
  ) =>
    request<LiabilityScheduleItem>(`/liabilities/${liabilityId}/schedule/${itemId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: { status },
    }),
  bills: (userId: string) => request<RoadmapBill[]>('/bills', { query: { user_id: userId } }),
  createBill: (
    userId: string,
    payload: {
      financial_account_id?: string | null;
      label: string;
      bill_type: RoadmapBill['bill_type'];
      amount: number;
      due_date: string;
      cadence?: RoadmapBill['cadence'];
      source_kind?: RoadmapBill['source_kind'];
      confirmed?: boolean;
    },
  ) =>
    request<RoadmapBill>('/bills', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateBill: (
    userId: string,
    billId: string,
    payload: Partial<Pick<RoadmapBill, 'status' | 'due_date' | 'amount' | 'confirmed'>>,
  ) =>
    request<RoadmapBill>(`/bills/${billId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  healthChecklist: (userId: string) =>
    request<HealthChecklistItem[]>('/health-checklist', { query: { user_id: userId } }),
  upsertHealthChecklist: (
    userId: string,
    item: Pick<HealthChecklistItem, 'item_type' | 'label' | 'status' | 'note'>,
  ) =>
    request<HealthChecklistItem>(`/health-checklist/${item.item_type}`, {
      method: 'PUT',
      query: { user_id: userId },
      body: item,
    }),
  cardDisputes: (userId: string, accountId: string) =>
    request<CardDispute[]>(`/cards/${accountId}/disputes`, { query: { user_id: userId } }),
  createCardDispute: (
    userId: string,
    accountId: string,
    payload: {
      statement_line_id?: string | null;
      label: string;
      amount: number;
      complaint_date: string;
      reference_number?: string | null;
      note?: string | null;
    },
  ) =>
    request<CardDispute>(`/cards/${accountId}/disputes`, {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateCardDispute: (
    userId: string,
    disputeId: string,
    payload: Pick<CardDispute, 'status'> & Partial<Pick<CardDispute, 'reference_number' | 'note'>>,
  ) =>
    request<CardDispute>(`/card-disputes/${disputeId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  households: (userId: string) =>
    request<HouseholdSummary[]>('/households', { query: { user_id: userId } }),
  createHousehold: (userId: string, name: string) =>
    request<HouseholdSummary>('/households', {
      method: 'POST',
      query: { user_id: userId },
      body: { name },
    }),
  deleteHousehold: (userId: string, householdId: string) =>
    request<void>(`/households/${householdId}`, {
      method: 'DELETE',
      query: { user_id: userId },
    }),
  householdMembers: (userId: string, householdId: string) =>
    request<HouseholdMember[]>(`/households/${householdId}/members`, {
      query: { user_id: userId },
    }),
  addHouseholdMember: (
    userId: string,
    householdId: string,
    memberUserId: string,
    role: 'member' | 'viewer' = 'member',
  ) =>
    request<HouseholdSummary>(`/households/${householdId}/members`, {
      method: 'POST',
      query: { user_id: userId },
      body: { user_id: memberUserId, role, visibility: 'annotations_only' },
    }),
  updateHouseholdMember: (
    userId: string,
    householdId: string,
    memberUserId: string,
    role: 'member' | 'viewer',
  ) =>
    request<HouseholdMember>(`/households/${householdId}/members/${memberUserId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: { role, visibility: 'annotations_only' },
    }),
  removeHouseholdMember: (userId: string, householdId: string, memberUserId: string) =>
    request<void>(`/households/${householdId}/members/${memberUserId}`, {
      method: 'DELETE',
      query: { user_id: userId },
    }),
  householdExpenses: (userId: string, householdId: string) =>
    request<HouseholdExpense[]>(`/households/${householdId}/expenses`, {
      query: { user_id: userId },
    }),
  createHouseholdExpense: (
    userId: string,
    householdId: string,
    payload: {
      payer_user_id: string;
      label: string;
      amount: number;
      currency: string;
      expense_date: string;
      splits: Record<string, number>;
    },
  ) =>
    request<HouseholdExpense>(`/households/${householdId}/expenses`, {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  householdSettlements: (userId: string, householdId: string) =>
    request<HouseholdSettlement[]>(`/households/${householdId}/settlements`, {
      query: { user_id: userId },
    }),
  createHouseholdSettlement: (
    userId: string,
    householdId: string,
    payload: {
      from_user_id: string;
      to_user_id: string;
      amount: number;
      currency: string;
      settlement_date: string;
      status?: HouseholdSettlement['status'];
      note?: string | null;
    },
  ) =>
    request<HouseholdSettlement>(`/households/${householdId}/settlements`, {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  updateHouseholdSettlement: (
    userId: string,
    householdId: string,
    settlementId: string,
    payload: Pick<HouseholdSettlement, 'status'> & Partial<Pick<HouseholdSettlement, 'note'>>,
  ) =>
    request<HouseholdSettlement>(`/households/${householdId}/settlements/${settlementId}`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  payoffComparison: (userId: string, monthlyBudget: number) =>
    request<PayoffComparison>('/liabilities/payoff-comparison', {
      query: { user_id: userId, monthly_budget: monthlyBudget },
    }),
  importHdfcStatement: async (
    userId: string,
    accountId: string,
    file: File,
  ): Promise<ImportedCreditCardStatement> => {
    return uploadStatementPdf<ImportedCreditCardStatement>(
      '/statements/hdfc/upload',
      userId,
      file,
      accountId,
    );
  },
  detectStatement: (userId: string, file: File) =>
    uploadStatementPdf<StatementDetection>('/statements/detect/upload', userId, file),
  statementAnalysisReviews: (userId: string, status?: 'ready_to_import' | 'pending_review') =>
    request<StatementAnalysisReview[]>('/statements/review', {
      query: { user_id: userId, status },
    }),
  reviewStatementText: (
    userId: string,
    payload: { statement_text: string; document_fingerprint?: string | null },
  ) =>
    request<StatementAnalysisReview>('/statements/review/text', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),
  reviewStatementPdf: (userId: string, file: File) =>
    uploadStatementPdf<StatementAnalysisReview>('/statements/review/upload', userId, file),
  importStatement: (userId: string, accountId: string, file: File) =>
    uploadStatementPdf<StatementImportResult>('/statements/import/upload', userId, file, accountId),
  statementReviewItems: (userId: string) =>
    request<StatementReviewItem[]>('/review/statement-lines', {
      query: { user_id: userId },
    }),
  depositStatementReviewItems: (userId: string) =>
    request<DepositStatementReviewItem[]>('/review/deposit-statement-lines', {
      query: { user_id: userId },
    }),
  reviewDepositStatementLine: (
    userId: string,
    lineId: string,
    payload: {
      decision: 'ignore' | 'import';
      payment_rail?: 'upi' | 'debit_card' | 'atm' | 'transfer' | null;
      note?: string | null;
    },
  ) =>
    request<DepositStatementLineReviewResponse>(`/deposit-statement-lines/${lineId}/review`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),
  reviewStatementLine: (
    userId: string,
    lineId: string,
    payload: {
      decision: StatementLineReviewResponse['decision'];
      matched_transaction_id?: string | null;
      paying_account_id?: string | null;
      note?: string | null;
    },
  ) =>
    request<StatementLineReviewResponse>(`/statement-lines/${lineId}/review`, {
      method: 'PATCH',
      query: { user_id: userId },
      body: payload,
    }),

  // Parser pipeline operations
  pipelineMetrics: (userId: string, month: number, year: number) =>
    request<PipelineMetrics>('/pipeline/metrics', {
      query: { user_id: userId, month, year },
    }),
  pipelineFailures: (userId: string, resolved = false, limit = 20, offset = 0) =>
    request<PipelineFailuresResponse>('/pipeline/failures', {
      query: { user_id: userId, resolved, limit, offset },
    }),
  retryPipelineFailure: (userId: string, failureId: string) =>
    request<PipelineRetryResponse>(`/pipeline/failures/${failureId}/retry`, {
      method: 'POST',
      query: { user_id: userId },
    }),
  reprocessPipeline: (userId: string, payload: PipelineReprocessRequest) =>
    request<PipelineReprocessResponse>('/pipeline/reprocess', {
      method: 'POST',
      query: { user_id: userId },
      body: payload,
    }),

  // Budgets
  budgetsTrack: (userId: string, month: number, year: number) =>
    request<BudgetTracker[]>('/budgets/track', { query: { user_id: userId, month, year } }),
  budgetDrilldown: (budgetId: string, userId: string, month: number, year: number, limit = 100) =>
    request<BudgetDrilldown>(`/budgets/${budgetId}/drilldown`, {
      query: { user_id: userId, month, year, limit },
    }),
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
  deleteBudget: (budgetId: string) => request<void>(`/budgets/${budgetId}`, { method: 'DELETE' }),

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
  portableExport: async (userId: string): Promise<PortableExportDownload> => {
    const params = new URLSearchParams({ user_id: userId });
    const response = await fetch(`${API_BASE}/reports/export/portable?${params}`, {
      method: 'POST',
      headers: csrfHeaders(),
      credentials: 'same-origin',
    });
    if (response.status === 401) {
      window.dispatchEvent(new Event(AUTH_SESSION_ENDED_EVENT));
      throw new ApiError('Session expired', 401);
    }
    if (!response.ok) {
      let detail = response.statusText;
      let code: string | undefined;
      let requestId: string | undefined;
      let details: unknown;
      try {
        const body = (await response.json()) as {
          detail?: string;
          error?: { code?: string; message?: string; request_id?: string; details?: unknown };
        };
        detail = body.error?.message || body.detail || detail;
        code = body.error?.code;
        requestId = body.error?.request_id;
        details = body.error?.details;
      } catch {
        // Keep the HTTP status text for non-JSON failures.
      }
      throw new ApiError(detail, response.status, code, requestId, details);
    }
    const disposition = response.headers.get('Content-Disposition') ?? '';
    const filename = disposition.match(/filename="([^"]+)"/i)?.[1] ?? 'pfis-portable-export.zip';
    return { blob: await response.blob(), filename };
  },
  csvUrl: (userId: string, month: number, year: number) =>
    `${API_BASE}/reports/export/csv?user_id=${encodeURIComponent(userId)}&month=${month}&year=${year}`,
  reportUrl: (userId: string, month: number, year: number) =>
    `${API_BASE}/reports/monthly?user_id=${encodeURIComponent(userId)}&month=${month}&year=${year}`,
};

export const subscriptionReviewApi = {
  recurringReview: (userId: string, asOf?: string) =>
    request<import('./types').SubscriptionReviewListResponse>('/subscriptions/recurring-review', {
      query: { user_id: userId, as_of: asOf },
    }),
  recordRecurringReviewAction: (
    userId: string,
    streamKey: string,
    action: import('./types').SubscriptionReviewAction,
    note?: string,
    asOf?: string,
  ) =>
    request<import('./types').SubscriptionReviewActionResponse>(
      `/subscriptions/recurring-review/${encodeURIComponent(streamKey)}/actions`,
      {
        method: 'POST',
        query: { user_id: userId, as_of: asOf },
        body: { action, note },
      },
    ),
};
