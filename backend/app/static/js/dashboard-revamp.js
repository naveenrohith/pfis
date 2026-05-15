const API = '/api';
const SESSION_KEY = 'pfis.session.v3';
const REVIEW_CONFIDENCE_THRESHOLD = 0.85;
const CHART_COLORS = ['#6366f1', '#22c55e', '#38bdf8', '#f59e0b', '#ef4444', '#14b8a6', '#8b5cf6', '#06b6d4', '#84cc16', '#f97316'];

const state = {
  session: {
    mode: null,
    token: null,
    expiresAt: null,
    user: null,
  },
  currentMonth: new Date().getMonth() + 1,
  currentYear: new Date().getFullYear(),
  categories: [],
  summary: null,
  transactions: [],
  emails: null,
  insights: null,
  budgets: [],
  syncStatus: null,
  activeJob: null,
  lastJob: null,
  categoryDrilldown: null,
  explorerType: 'all',
  explorerSearch: '',
  reviewFilter: 'pending',
  reviewSearch: '',
  selectedReviewIds: new Set(),
  focusedReviewId: null,
  budgetDraft: { mode: 'create', budgetId: null },
  charts: { category: null, trend: null },
  activityLog: ['No background activity yet.'],
  sessionTimer: null,
  observer: null,
};

const el = {};

document.addEventListener('DOMContentLoaded', init);

async function init() {
  cacheElements();
  bindStaticEvents();
  observeSections();
  syncMonthControls();
  renderActivityLog();
  await hydrateSession();
}

function cacheElements() {
  const ids = [
    'auth-shell', 'app-shell', 'auth-error', 'login-form', 'register-form', 'login-email', 'login-password',
    'register-name', 'register-email', 'register-password', 'register-currency', 'btn-login', 'btn-register', 'btn-google-login', 'btn-demo-session',
    'session-chip', 'user-avatar', 'header-user-name', 'header-user-meta', 'btn-logout', 'global-banner', 'btn-prev-month', 'btn-next-month',
    'btn-current-month', 'month-label', 'month-pill', 'filter-pill', 'session-expiry-pill', 'sync-pill', 'btn-sync', 'btn-retry', 'btn-refresh',
    'btn-export', 'btn-report', 'btn-budget-modal', 'hero-title', 'hero-summary-text', 'hero-focus-pills', 'hero-metrics', 'command-status',
    'command-summary', 'processed-emails-value', 'unprocessed-emails-value', 'pending-review-value', 'active-mode-value', 'btn-clear-log', 'sync-log',
    'metrics-grid', 'category-chart', 'category-chart-empty', 'category-legend', 'btn-clear-category-drilldown', 'insight-feed', 'merchant-stack',
    'recurring-stack', 'budget-board', 'btn-new-budget', 'trend-chart', 'trend-chart-empty', 'review-queue-count', 'review-search', 'bulk-selection-count',
    'btn-select-pending', 'btn-clear-selection', 'bulk-category-select', 'bulk-type-select', 'btn-apply-bulk', 'btn-mark-selected-reviewed', 'review-list',
    'btn-focus-next-review', 'review-empty-state', 'review-form', 'review-confidence', 'review-date', 'review-account', 'review-reference', 'review-guidance',
    'review-merchant', 'review-category', 'review-amount', 'review-type', 'review-category-shortcuts', 'btn-save-review', 'btn-save-next', 'btn-mark-reviewed',
    'explorer-count', 'btn-clear-explorer-filters', 'explorer-search', 'active-filter-chips', 'explorer-tbody', 'budget-modal', 'budget-modal-title',
    'btn-close-budget-modal', 'budget-form', 'budget-category', 'budget-limit', 'btn-cancel-budget', 'btn-save-budget', 'toast-stack', 'live-region',
  ];

  ids.forEach((id) => {
    el[id] = document.getElementById(id);
  });

  el.authTabs = [...document.querySelectorAll('[data-auth-tab]')];
  el.sectionLinks = [...document.querySelectorAll('[data-scroll-target]')];
  el.reviewSegments = [...document.querySelectorAll('[data-review-filter]')];
  el.explorerSegments = [...document.querySelectorAll('[data-explorer-filter]')];
}

function bindStaticEvents() {
  el.authTabs.forEach((tab) => tab.addEventListener('click', () => switchAuthTab(tab.dataset.authTab)));
  el['login-form'].addEventListener('submit', handleLogin);
  el['register-form'].addEventListener('submit', handleRegister);
  el['btn-google-login'].addEventListener('click', handleGoogleLogin);
  el['btn-demo-session'].addEventListener('click', handleDemoSession);
  el['btn-logout'].addEventListener('click', () => signOut(true));

  el.sectionLinks.forEach((button) => {
    button.addEventListener('click', () => scrollToSection(button.dataset.scrollTarget));
  });

  el['btn-prev-month'].addEventListener('click', () => changeMonth(-1));
  el['btn-next-month'].addEventListener('click', () => changeMonth(1));
  el['btn-current-month'].addEventListener('click', () => resetToCurrentMonth());
  el['btn-sync'].addEventListener('click', startDemoSyncPipeline);
  el['btn-retry'].addEventListener('click', retryParseFailures);
  el['btn-refresh'].addEventListener('click', () => refreshDashboardData({ announceLabel: 'Dashboard refreshed' }));
  el['btn-export'].addEventListener('click', exportCsv);
  el['btn-report'].addEventListener('click', openMonthlyReport);
  el['btn-budget-modal'].addEventListener('click', () => openBudgetModal('create'));
  el['btn-new-budget'].addEventListener('click', () => openBudgetModal('create'));
  el['btn-clear-log'].addEventListener('click', clearActivityLog);
  el['btn-clear-category-drilldown'].addEventListener('click', clearCategoryDrilldown);
  el.reviewSegments.forEach((button) => button.addEventListener('click', () => setReviewFilter(button.dataset.reviewFilter)));
  el.explorerSegments.forEach((button) => button.addEventListener('click', () => setExplorerType(button.dataset.explorerFilter)));
  el['review-search'].addEventListener('input', (event) => {
    state.reviewSearch = event.target.value.trim().toLowerCase();
    renderReviewQueue();
  });
  el['explorer-search'].addEventListener('input', (event) => {
    state.explorerSearch = event.target.value.trim().toLowerCase();
    renderExplorer();
  });
  el['btn-clear-selection'].addEventListener('click', clearSelectedReviewIds);
  el['btn-select-pending'].addEventListener('click', selectVisibleReviewItems);
  el['btn-apply-bulk'].addEventListener('click', applyBulkReviewUpdates);
  el['btn-mark-selected-reviewed'].addEventListener('click', () => applyBulkReviewUpdates(true));
  el['btn-save-review'].addEventListener('click', () => saveFocusedReview(false));
  el['btn-save-next'].addEventListener('click', () => saveFocusedReview(true));
  el['btn-mark-reviewed'].addEventListener('click', markFocusedReviewed);
  el['btn-focus-next-review'].addEventListener('click', focusNextPendingReview);
  el['btn-clear-explorer-filters'].addEventListener('click', clearExplorerFilters);

  el['review-list'].addEventListener('click', handleReviewListClick);
  el['review-list'].addEventListener('change', handleReviewCheckboxChange);
  el['category-legend'].addEventListener('click', handleCategoryLegendClick);
  el['merchant-stack'].addEventListener('click', handleMerchantClick);
  el['review-category-shortcuts'].addEventListener('click', handleCategoryShortcutClick);
  el['budget-board'].addEventListener('click', handleBudgetBoardClick);
  el['explorer-tbody'].addEventListener('click', handleExplorerTableClick);
  el['active-filter-chips'].addEventListener('click', handleFilterChipClick);

  el['budget-form'].addEventListener('submit', saveBudget);
  el['btn-close-budget-modal'].addEventListener('click', closeBudgetModal);
  el['btn-cancel-budget'].addEventListener('click', closeBudgetModal);
  el['budget-modal'].addEventListener('click', (event) => {
    if (event.target === el['budget-modal']) closeBudgetModal();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeBudgetModal();
      if (!el['auth-shell'].hidden) return;
      if (el['review-form'].hidden) return;
      focusNextPendingReview();
    }
  });
}

function observeSections() {
  const targets = document.querySelectorAll('main section[id]');
  if (!('IntersectionObserver' in window)) return;

  state.observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    setActiveSectionLink(visible.target.id);
  }, { rootMargin: '-25% 0px -60% 0px', threshold: [0.2, 0.45, 0.7] });

  targets.forEach((target) => state.observer.observe(target));
}

async function hydrateSession() {
  setLoading(true);
  consumeOAuthStatus();
  const storedSession = readStoredSession();
  if (!storedSession) {
    showAuthShell();
    setLoading(false);
    return;
  }

  state.session = storedSession;
  try {
    if (storedSession.mode === 'auth') {
      if (isSessionExpired()) {
        clearStoredSession();
        state.session = emptySession();
        showAuthShell('Your secure session expired. Please sign in again.');
        setLoading(false);
        return;
      }
      const user = await apiRequest('/auth/me');
      state.session.user = user;
      persistSession();
    } else if (storedSession.mode === 'demo') {
      const demoUser = await resolveDemoUser(storedSession.user?.id);
      if (!demoUser) {
        throw new Error('Demo workspace is not available. Please sign in instead.');
      }
      state.session.user = demoUser;
      persistSession();
    }

    await bootstrapApp();
  } catch (error) {
    console.error(error);
    clearStoredSession();
    state.session = emptySession();
    showAuthShell(error.message || 'Please sign in to continue.');
  } finally {
    setLoading(false);
  }
}

function consumeOAuthStatus() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('google_auth') === 'success') {
    window.history.replaceState({}, document.title, window.location.pathname);
    showToast('Signed in with Google', 'success');
  }
}

async function bootstrapApp() {
  hideAuthShell();
  updateSessionChrome();
  startSessionTimer();
  if (!state.categories.length) {
    state.categories = await apiRequest('/categories/');
  }
  await refreshDashboardData({ announceLabel: 'Workspace ready' });
}

function emptySession() {
  return { mode: null, token: null, expiresAt: null, user: null };
}

function readStoredSession() {
  try {
    const payload = localStorage.getItem(SESSION_KEY);
    if (!payload) return null;
    return JSON.parse(payload);
  } catch {
    return null;
  }
}

function persistSession() {
  localStorage.setItem(SESSION_KEY, JSON.stringify(state.session));
}

function clearStoredSession() {
  localStorage.removeItem(SESSION_KEY);
}

function isSessionExpired() {
  return state.session.mode === 'auth' && Boolean(state.session.expiresAt) && Date.now() >= state.session.expiresAt;
}

function startSessionTimer() {
  if (state.sessionTimer) window.clearInterval(state.sessionTimer);
  state.sessionTimer = window.setInterval(() => {
    updateSessionChrome();
    if (isSessionExpired()) {
      signOut(true, 'Your session expired.');
    }
  }, 30_000);
}

async function handleLogin(event) {
  event.preventDefault();
  setAuthError('');
  setButtonLoading(el['btn-login'], true, 'Signing in…');
  try {
    const payload = await apiRequest('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: el['login-email'].value.trim(),
        password: el['login-password'].value,
      }),
      auth: false,
    });
    await completeAuthSession(payload, 'auth');
    showToast('Signed in successfully', 'success');
  } catch (error) {
    setAuthError(error.message || 'Unable to sign in.');
  } finally {
    setButtonLoading(el['btn-login'], false, 'Sign in securely');
  }
}

async function handleRegister(event) {
  event.preventDefault();
  setAuthError('');
  setButtonLoading(el['btn-register'], true, 'Creating workspace…');
  try {
    const payload = await apiRequest('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: el['register-name'].value.trim(),
        email: el['register-email'].value.trim(),
        password: el['register-password'].value,
        currency: el['register-currency'].value.trim().toUpperCase(),
      }),
      auth: false,
    });
    await completeAuthSession(payload, 'auth');
    showToast('Workspace created and signed in', 'success');
  } catch (error) {
    setAuthError(error.message || 'Unable to create workspace.');
  } finally {
    setButtonLoading(el['btn-register'], false, 'Create secure workspace');
  }
}

async function handleDemoSession() {
  setAuthError('');
  setButtonLoading(el['btn-demo-session'], true, 'Opening demo…');
  try {
    const demoUser = await resolveDemoUser();
    if (!demoUser) {
      throw new Error('No demo workspace is available. Create an account instead.');
    }
    state.session = {
      mode: 'demo',
      token: null,
      expiresAt: null,
      user: demoUser,
    };
    persistSession();
    await bootstrapApp();
    showToast('Demo workspace loaded', 'success');
  } catch (error) {
    setAuthError(error.message || 'Demo mode is not available.');
  } finally {
    setButtonLoading(el['btn-demo-session'], false, 'Try demo workspace');
  }
}

function handleGoogleLogin(event) {
  event.preventDefault();
  setAuthError('');
  setButtonLoading(el['btn-google-login'], true, 'Opening Google...');
  window.location.href = `${API}/auth/google/login`;
}

async function completeAuthSession(payload) {
  state.session = {
    mode: 'auth',
    token: payload.access_token,
    expiresAt: Date.now() + (payload.expires_in * 1000),
    user: payload.user,
  };
  persistSession();
  await bootstrapApp();
}

async function resolveDemoUser(preferredId = null) {
  const users = await apiRequest('/users/', { auth: false, tolerate401: true });
  if (!Array.isArray(users) || users.length === 0) return null;
  return users.find((user) => user.id === preferredId)
    || users.find((user) => user.email?.toLowerCase() === 'demo@pfis.app')
    || users[0];
}

function switchAuthTab(tabName) {
  el.authTabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.authTab === tabName));
  el['login-form'].hidden = tabName !== 'login';
  el['register-form'].hidden = tabName !== 'register';
  setAuthError('');
}

function setAuthError(message) {
  el['auth-error'].hidden = !message;
  el['auth-error'].textContent = message;
}

function showAuthShell(message = '') {
  switchAuthTab('login');
  resetAuthForms();
  setAuthError(message);
  el['auth-shell'].hidden = false;
  el['app-shell'].hidden = true;
  announce(message || 'Authentication required.');
}

function hideAuthShell() {
  el['auth-shell'].hidden = true;
  el['app-shell'].hidden = false;
}

function resetAuthForms() {
  el['login-form'].reset();
  el['register-form'].reset();
  el['register-currency'].value = 'INR';
}

function updateSessionChrome() {
  const user = state.session.user;
  if (!user) return;

  const initials = (user.name || user.email || 'PF')
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || '')
    .join('') || 'PF';

  el['user-avatar'].textContent = initials;
  el['header-user-name'].textContent = user.name || user.email;
  el['header-user-meta'].textContent = state.session.mode === 'auth'
    ? `${user.email} • ${formatSessionCountdown()}`
    : `${user.email} • demo workspace`;
  el['session-chip'].textContent = state.session.mode === 'auth' ? 'Secure session' : 'Demo workspace';
  el['session-chip'].className = `session-chip ${state.session.mode === 'auth' ? 'authenticated' : 'demo'}`;
  el['active-mode-value'].textContent = state.session.mode === 'auth' ? 'Secure' : 'Demo';
  el['session-expiry-pill'].textContent = state.session.mode === 'auth'
    ? formatSessionCountdown()
    : 'Demo mode • no token expiry';
  el['btn-logout'].textContent = state.session.mode === 'auth' ? 'Sign out' : 'End demo';
}

function formatSessionCountdown() {
  if (state.session.mode !== 'auth' || !state.session.expiresAt) return 'No expiry';
  const msRemaining = Math.max(state.session.expiresAt - Date.now(), 0);
  const minutes = Math.ceil(msRemaining / 60_000);
  return minutes > 60
    ? `Session expires in ${Math.ceil(minutes / 60)}h`
    : `Session expires in ${minutes}m`;
}

async function signOut(notify = true, message = 'Signed out.') {
  clearStoredSession();
  state.session = emptySession();
  state.summary = null;
  state.transactions = [];
  state.emails = null;
  state.insights = null;
  state.budgets = [];
  state.syncStatus = null;
  state.selectedReviewIds = new Set();
  state.focusedReviewId = null;
  destroyCharts();
  showAuthShell(message);
  if (notify) showToast(message, 'info');
}

function destroyCharts() {
  if (state.charts.category) {
    state.charts.category.destroy();
    state.charts.category = null;
  }
  if (state.charts.trend) {
    state.charts.trend.destroy();
    state.charts.trend = null;
  }
}

async function refreshDashboardData(options = {}) {
  if (!state.session.user?.id) return;

  const { announceLabel = '' } = options;
  setLoading(true);
  setGlobalBanner('');
  syncMonthControls();

  try {
    const userId = state.session.user.id;
    const monthQuery = `user_id=${encodeURIComponent(userId)}&month=${state.currentMonth}&year=${state.currentYear}`;
    const countQuery = `user_id=${encodeURIComponent(userId)}`;

    if (!state.categories.length) {
      state.categories = await apiRequest('/categories/');
    }

    const [summary, transactions, emails, insights, budgets, syncStatus] = await Promise.all([
      apiRequest(`/transactions/summary?${monthQuery}`),
      apiRequest(`/transactions/?${monthQuery}&limit=200`),
      apiRequest(`/gmail/emails?${countQuery}&limit=10`),
      apiRequest(`/insights/?${monthQuery}`),
      apiRequest(`/budgets/track?${monthQuery}`).catch(() => []),
      apiRequest(`/gmail/status?${countQuery}`).catch(() => ({ latest_status: 'idle', runs: [] })),
    ]);

    state.summary = summary;
    state.transactions = Array.isArray(transactions) ? transactions : [];
    state.emails = emails;
    state.insights = insights;
    state.budgets = Array.isArray(budgets) ? budgets : [];
    state.syncStatus = syncStatus;

    reconcileReviewFocus();
    syncMonthControls();
    renderAll();
    if (announceLabel) announce(announceLabel);
  } catch (error) {
    console.error(error);
    setGlobalBanner(error.message || 'Unable to load the dashboard.');
    showToast(error.message || 'Unable to load the dashboard.', 'error');
  } finally {
    setLoading(false);
  }
}

function reconcileReviewFocus() {
  const validIds = new Set(state.transactions.map((txn) => txn.id));
  state.selectedReviewIds = new Set([...state.selectedReviewIds].filter((id) => validIds.has(id)));

  if (state.focusedReviewId && validIds.has(state.focusedReviewId)) return;

  const firstPending = getPendingReviewTransactions()[0] || getReviewCandidateTransactions()[0] || null;
  state.focusedReviewId = firstPending?.id || null;
}

function renderAll() {
  updateSessionChrome();
  renderActionBarMeta();
  renderHero();
  renderMetrics();
  renderCommandCenter();
  renderCategoryAnalytics();
  renderInsights();
  renderMerchantStack();
  renderRecurringStack();
  renderBudgetBoard();
  renderTrendChart();
  populateCategorySelects();
  renderReviewQueue();
  renderReviewDetail();
  renderExplorer();
}

function renderActionBarMeta() {
  const monthName = formatMonthLabel();
  el['month-label'].textContent = monthName;
  el['month-pill'].textContent = `Month: ${monthName}`;
  el['sync-pill'].textContent = buildSyncPillText();
  el['filter-pill'].textContent = buildFilterPillText();
  el['btn-clear-category-drilldown'].hidden = !state.categoryDrilldown;
}

function renderHero() {
  const summary = state.summary;
  const pending = getPendingReviewTransactions().length;
  const processedEmails = state.emails?.processed_total ?? 0;
  const unprocessedEmails = state.emails?.unprocessed_total ?? 0;
  const savingsRate = summary?.total_income > 0
    ? Math.round(((summary.total_income - summary.total_spend) / summary.total_income) * 100)
    : 0;
  const savingsHealth = getSavingsHealth(savingsRate);

  if (!summary) {
    el['hero-title'].textContent = 'Your money, made easy to understand.';
    el['hero-summary-text'].textContent = 'Connect a session and sync your inbox to see savings, spending, budgets, and review items in one calm view.';
    el['hero-focus-pills'].innerHTML = '';
    el['hero-metrics'].innerHTML = '';
    return;
  }

  el['hero-title'].textContent = summary.transaction_count > 0
    ? summary.net >= 0
      ? `You saved ${formatCurrency(summary.net)} this month`
      : `You overspent by ${formatCurrency(Math.abs(summary.net))} this month`
    : `No posted activity yet for ${formatMonthLabel()}`;

  el['hero-summary-text'].textContent = summary.transaction_count > 0
    ? `${savingsHealth.label}: ${savingsHealth.detail} ${pending ? `${pending} transaction${pending === 1 ? '' : 's'} need a quick check.` : 'Your review queue is clear.'}`
    : 'Start with a demo sync or secure sign-in workflow, then PFIS will organize transactions and insights automatically.';

  const focusItems = [
    {
      title: pending > 0 ? `${pending} needs confirmation` : 'Everything reviewed',
      detail: pending > 0 ? 'Low-confidence transactions are ready for one-click correction.' : 'All current transactions look clean.',
    },
    {
      title: `${unprocessedEmails} email${unprocessedEmails === 1 ? '' : 's'} waiting`,
      detail: processedEmails > 0 ? `${processedEmails} financial email${processedEmails === 1 ? '' : 's'} already understood.` : 'Sync your inbox to refresh the month.',
    },
    {
      title: savingsHealth.label,
      detail: state.budgets.length > 0 ? `${state.budgets.length} budget${state.budgets.length === 1 ? '' : 's'} watched for overspending.` : 'Add budgets to get early warnings.',
    },
  ];

  el['hero-focus-pills'].innerHTML = focusItems.map((item) => `
    <article class="hero-focus-pill">
      <strong>${item.title}</strong>
      <span>${item.detail}</span>
    </article>
  `).join('');

  const heroMetrics = [
    { label: 'Income', value: formatCurrency(summary.total_income), tone: 'neutral' },
    { label: 'Expenses', value: formatCurrency(summary.total_spend), tone: summary.total_spend > summary.total_income ? 'warning' : 'neutral' },
    { label: 'Savings', value: formatCurrency(summary.net), tone: summary.net >= 0 ? 'success' : 'danger' },
    { label: 'Pending reviews', value: pending, tone: pending > 0 ? 'warning' : 'success' },
  ];

  el['hero-metrics'].innerHTML = heroMetrics.map((item) => `
    <article class="hero-stat-card ${item.tone}">
      <span>${item.label}</span>
      <strong>${item.value}</strong>
    </article>
  `).join('');
}

function renderMetrics() {
  const summary = state.summary;
  if (!summary) {
    el['metrics-grid'].innerHTML = buildMetricsPlaceholder();
    return;
  }

  const pending = getPendingReviewTransactions().length;
  const recurringCount = state.insights?.recurring_payments?.length ?? 0;
  const flaggedBudgets = state.budgets.filter((budget) => budget.status !== 'under').length;
  const totalEmails = state.emails?.all_total ?? 0;

  const cards = [
    { label: 'Spent', value: formatCurrency(summary.total_spend), detail: 'Money that left your accounts this month.' },
    { label: 'Income', value: formatCurrency(summary.total_income), detail: 'Credits PFIS recognized for the selected month.' },
    { label: 'Saved', value: formatCurrency(summary.net), detail: 'What remains after monthly spending.' },
    { label: 'Transactions', value: summary.transaction_count, detail: `${totalEmails} financial email${totalEmails === 1 ? '' : 's'} scanned for activity.` },
    { label: 'Needs review', value: pending, detail: pending > 0 ? 'Quick confirmations keep insights accurate.' : 'No transaction needs attention right now.' },
    { label: 'Subscriptions', value: recurringCount, detail: flaggedBudgets > 0 ? `${flaggedBudgets} budget area${flaggedBudgets === 1 ? '' : 's'} may need attention.` : 'No budget pressure detected.' },
  ];

  el['metrics-grid'].innerHTML = cards.map((card) => `
    <article class="metric-card">
      <span>${card.label}</span>
      <div class="metric-value">${card.value}</div>
      <div class="metric-detail">${card.detail}</div>
    </article>
  `).join('');
}

function buildMetricsPlaceholder() {
  return Array.from({ length: 6 }, () => `
    <article class="metric-card">
      <span>Metric</span>
      <div class="metric-value">—</div>
      <div class="metric-detail">Loading workspace state…</div>
    </article>
  `).join('');
}

function renderCommandCenter() {
  const pending = getPendingReviewTransactions().length;
  const processed = state.emails?.processed_total ?? 0;
  const unprocessed = state.emails?.unprocessed_total ?? 0;
  el['processed-emails-value'].textContent = processed;
  el['unprocessed-emails-value'].textContent = unprocessed;
  el['pending-review-value'].textContent = pending;

  if (state.activeJob) {
    const label = state.activeJob.status === 'running' ? 'Running' : state.activeJob.status === 'queued' ? 'Queued' : 'Ready';
    el['command-status'].className = `status-badge ${state.activeJob.status === 'failed' ? 'error' : state.activeJob.status === 'completed' ? 'success' : state.activeJob.status === 'running' ? 'progress' : 'warning'}`;
    el['command-status'].textContent = label;
    el['command-summary'].textContent = summarizeJob(state.activeJob);
    return;
  }

  const latestSync = state.syncStatus?.runs?.[0];
  if (!latestSync) {
    el['command-status'].className = 'status-badge neutral';
    el['command-status'].textContent = 'Ready';
    el['command-summary'].textContent = 'No sync run recorded yet in this session. Trigger the pipeline to populate the workspace.';
    return;
  }

  const status = latestSync.status || state.syncStatus.latest_status || 'completed';
  el['command-status'].className = `status-badge ${status === 'completed' ? 'success' : status === 'failed' ? 'error' : status === 'running' ? 'progress' : 'warning'}`;
  el['command-status'].textContent = status[0].toUpperCase() + status.slice(1);
  el['command-summary'].textContent = `${latestSync.emails_processed || 0} emails processed in the latest sync. ${pending ? `${pending} transaction${pending === 1 ? '' : 's'} need confirmation.` : 'No transaction needs confirmation.'}`;
}

function renderCategoryAnalytics() {
  const categories = state.summary?.category_breakdown || [];
  if (!categories.length) {
    el['category-chart'].hidden = true;
    el['category-chart-empty'].hidden = false;
    el['category-legend'].innerHTML = '';
    if (state.charts.category) {
      state.charts.category.destroy();
      state.charts.category = null;
    }
    return;
  }

  el['category-chart'].hidden = false;
  el['category-chart-empty'].hidden = true;

  if (state.charts.category) state.charts.category.destroy();
  state.charts.category = new Chart(el['category-chart'], {
    type: 'doughnut',
    data: {
      labels: categories.map((item) => item.name),
      datasets: [{
        data: categories.map((item) => item.total),
        backgroundColor: categories.map((_, index) => CHART_COLORS[index % CHART_COLORS.length]),
        borderWidth: 0,
        spacing: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '68%',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#e5eefc',
          bodyColor: '#cbd5e1',
          borderColor: 'rgba(148,163,184,0.16)',
          borderWidth: 1,
          callbacks: {
            label: (ctx) => ` ${ctx.label}: ${formatCurrency(ctx.raw)}`,
          },
        },
      },
      onClick: (_, elements) => {
        if (!elements.length) return;
        const index = elements[0].index;
        setCategoryDrilldown(categories[index]);
      },
    },
  });

  const totalSpend = state.summary.total_spend || 0;
  el['category-legend'].innerHTML = categories.map((item, index) => {
    const normalizedCategoryId = categoryToken(item.category_id);
    const isActive = state.categoryDrilldown && normalizedCategoryId === state.categoryDrilldown.categoryId;
    const pct = totalSpend > 0 ? Math.round((item.total / totalSpend) * 100) : 0;
    return `
      <button type="button" class="legend-item ${isActive ? 'active' : ''}" data-category-id="${normalizedCategoryId}" data-category-name="${escapeHtml(item.name)}">
        <span class="legend-swatch" style="background:${CHART_COLORS[index % CHART_COLORS.length]}"></span>
        <span class="legend-meta">
          <strong>${item.icon || '📦'} ${item.name}</strong>
          <span>${formatCurrency(item.total)} • ${pct}% of spend</span>
        </span>
      </button>
    `;
  }).join('');
}

function renderInsights() {
  const insights = state.insights?.insights || [];
  if (!insights.length) {
    el['insight-feed'].innerHTML = buildEmptyBlock('No insights yet', 'Once transactions land in the selected month, smart insights will appear here.', '💡');
    return;
  }

  el['insight-feed'].innerHTML = insights.map((item) => `
    <article class="insight-item ${item.severity || 'info'}">
      <div class="icon">${item.icon || '💡'}</div>
      <div>
        <strong>${item.title}</strong>
        <p>${item.description}</p>
      </div>
    </article>
  `).join('');
}

function renderMerchantStack() {
  const merchants = state.summary?.top_merchants || [];
  if (!merchants.length) {
    el['merchant-stack'].innerHTML = buildEmptyBlock('No merchant ranking yet', 'Top merchant behaviour appears once debit transactions are present.', '🏪');
    return;
  }

  el['merchant-stack'].innerHTML = merchants.map((merchant, index) => `
    <button type="button" class="stack-item" data-merchant-name="${escapeHtml(merchant.name)}">
      <div class="stack-main">
        <strong>#${index + 1} ${merchant.name}</strong>
        <span>${merchant.count} transaction${merchant.count === 1 ? '' : 's'}</span>
      </div>
      <strong>${formatCurrency(merchant.total)}</strong>
    </button>
  `).join('');
}

function renderRecurringStack() {
  const recurring = state.insights?.recurring_payments || [];
  if (!recurring.length) {
    el['recurring-stack'].innerHTML = buildEmptyBlock('No recurring charges detected', 'As repeat merchants emerge, they will be surfaced here automatically.', '🔁');
    return;
  }

  el['recurring-stack'].innerHTML = recurring.map((item) => `
    <article class="stack-item">
      <div class="stack-main">
        <strong>${item.merchant}</strong>
        <span>${item.occurrences} consistent charge${item.occurrences === 1 ? '' : 's'}</span>
      </div>
      <strong>${formatCurrency(item.avg_amount)}</strong>
    </article>
  `).join('');
}

function renderBudgetBoard() {
  if (!state.budgets.length) {
    el['budget-board'].innerHTML = buildEmptyBlock('No budgets configured', 'Set monthly category limits to unlock richer budget posture tracking.', '🎯');
    return;
  }

  el['budget-board'].innerHTML = state.budgets.map((budget) => {
    const usage = Math.min(Math.round(budget.usage_pct || 0), 100);
    const ringColor = budget.status === 'over' ? '#ef4444' : budget.status === 'warning' ? '#f59e0b' : '#22c55e';
    const remainingLabel = budget.remaining >= 0
      ? `${formatCurrency(budget.remaining)} left`
      : `${formatCurrency(Math.abs(budget.remaining))} over`;
    const forecast = getBudgetForecast(budget);
    return `
      <article class="budget-card">
        <div class="budget-head">
          <div class="budget-title">
            <strong>${budget.category_icon || '📦'} ${budget.category_name}</strong>
            <span>${budget.status === 'over' ? 'Over budget' : budget.status === 'warning' ? 'Approaching limit' : 'On track'}</span>
          </div>
          <div class="budget-actions">
            <button type="button" class="text-link" data-budget-action="edit" data-budget-id="${budget.id}">Edit</button>
            <button type="button" class="text-link" data-budget-action="delete" data-budget-id="${budget.id}">Delete</button>
          </div>
        </div>
        <div class="budget-visual">
          <div class="budget-ring" style="--fill:${usage * 3.6}deg; --ring-color:${ringColor}">
            <strong>${usage}%</strong>
          </div>
          <div class="budget-stat-list">
            <div class="budget-stat"><span>Actual spend</span><strong>${formatCurrency(budget.actual_spend)}</strong></div>
            <div class="budget-stat"><span>Monthly limit</span><strong>${formatCurrency(budget.monthly_limit)}</strong></div>
            <div class="budget-stat"><span>Runway</span><strong>${remainingLabel}</strong></div>
          </div>
        </div>
        <div class="budget-footer">
          <span class="status-badge ${budget.status === 'over' ? 'error' : budget.status === 'warning' ? 'warning' : 'success'}">${budget.status}</span>
          <button type="button" class="text-link" data-budget-category-drill="${budget.category_id}">Focus category</button>
        </div>
        <p class="budget-forecast ${forecast.tone}">${forecast.text}</p>
      </article>
    `;
  }).join('');
}

function renderTrendChart() {
  const trend = state.insights?.daily_trend || [];
  if (!trend.length) {
    el['trend-chart'].hidden = true;
    el['trend-chart-empty'].hidden = false;
    if (state.charts.trend) {
      state.charts.trend.destroy();
      state.charts.trend = null;
    }
    return;
  }

  el['trend-chart'].hidden = false;
  el['trend-chart-empty'].hidden = true;

  const labels = trend.map((item) => item.date);
  const totals = trend.map((item) => item.total);
  const cumulative = [];
  totals.reduce((acc, value, index) => {
    cumulative[index] = acc + value;
    return cumulative[index];
  }, 0);

  if (state.charts.trend) state.charts.trend.destroy();
  state.charts.trend = new Chart(el['trend-chart'], {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Daily spend',
          data: totals,
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.16)',
          pointRadius: 2.5,
          pointHoverRadius: 5,
          fill: true,
          tension: 0.32,
          borderWidth: 2.4,
        },
        {
          label: 'Cumulative',
          data: cumulative,
          borderColor: '#7c3aed',
          borderDash: [6, 6],
          borderWidth: 1.8,
          pointRadius: 0,
          fill: false,
          tension: 0.26,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: '#cbd5e1', boxWidth: 12, boxHeight: 3 },
        },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#e5eefc',
          bodyColor: '#cbd5e1',
          borderColor: 'rgba(148,163,184,0.18)',
          borderWidth: 1,
          callbacks: {
            label: (ctx) => ` ${ctx.dataset.label}: ${formatCurrency(ctx.raw)}`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#64748b', maxTicksLimit: 9 },
          grid: { display: false },
        },
        y: {
          ticks: { color: '#64748b', callback: (value) => compactCurrency(value) },
          grid: { color: 'rgba(148,163,184,0.08)' },
        },
        y1: {
          position: 'right',
          ticks: { color: '#8b5cf6', callback: (value) => compactCurrency(value) },
          grid: { display: false },
        },
      },
    },
  });
}

function renderReviewQueue() {
  const items = getVisibleReviewTransactions();
  el['review-queue-count'].className = `status-badge ${items.length ? 'warning' : 'success'}`;
  el['review-queue-count'].textContent = items.length ? `${items.length} pending` : 'Queue clear';
  el['bulk-selection-count'].textContent = `${state.selectedReviewIds.size} selected`;
  toggleSegments(el.reviewSegments, state.reviewFilter, 'reviewFilter');

  if (!items.length) {
    el['review-list'].innerHTML = buildEmptyBlock('Review queue is clear', 'Any low-confidence or unreviewed transactions will appear here automatically.', '✅');
    return;
  }

  el['review-list'].innerHTML = items.map((txn) => {
    const checked = state.selectedReviewIds.has(txn.id) ? 'checked' : '';
    const confidence = Math.round((txn.confidence_score || 0) * 100);
    return `
      <article class="review-item ${txn.id === state.focusedReviewId ? 'active' : ''}" data-review-id="${txn.id}">
        <input type="checkbox" data-review-checkbox="${txn.id}" ${checked} aria-label="Select transaction ${escapeHtml(txn.merchant_normalized || txn.merchant_raw || txn.id)}" />
        <div class="review-item-main">
          <strong>${escapeHtml(txn.merchant_normalized || txn.merchant_raw || 'Unknown merchant')}</strong>
          <div class="review-item-meta">
            <span>${txn.category_name || 'Uncategorized'}</span>
            <span>•</span>
            <span>${formatDate(txn.transaction_date)}</span>
            <span>•</span>
            <span>${txn.account_last4 ? `••${txn.account_last4}` : 'Account n/a'}</span>
          </div>
          <div class="review-item-detail">
            <span>${formatSignedAmount(txn)}</span>
            <span>•</span>
            <span>${escapeHtml(txn.reference_id || 'No reference')}</span>
          </div>
        </div>
        <div class="review-score">
          <strong>${confidence}%</strong>
          <span>${txn.reviewed_flag ? 'Reviewed' : 'Pending'}</span>
        </div>
      </article>
    `;
  }).join('');
}

function renderReviewDetail() {
  const transaction = state.transactions.find((txn) => txn.id === state.focusedReviewId);
  if (!transaction) {
    el['review-form'].hidden = true;
    el['review-empty-state'].hidden = false;
    return;
  }

  el['review-empty-state'].hidden = true;
  el['review-form'].hidden = false;

  el['review-confidence'].textContent = `${Math.round((transaction.confidence_score || 0) * 100)}%`;
  el['review-date'].textContent = formatDate(transaction.transaction_date);
  el['review-account'].textContent = transaction.account_last4 ? `••${transaction.account_last4}` : '—';
  el['review-reference'].textContent = transaction.reference_id || '—';
  el['review-guidance'].textContent = transaction.reviewed_flag
    ? 'This transaction has already been marked reviewed. Saving a change will keep it reviewed and update the learning history.'
    : 'Correct the fields below or mark the item reviewed once you are satisfied.';

  el['review-merchant'].value = transaction.merchant_normalized || transaction.merchant_raw || '';
  el['review-category'].value = transaction.category_id || '';
  el['review-amount'].value = transaction.amount;
  el['review-type'].value = transaction.transaction_type || 'debit';

  renderCategoryShortcuts(transaction.category_id || '');
}

function renderCategoryShortcuts(activeCategoryId) {
  el['review-category-shortcuts'].innerHTML = state.categories.slice(0, 10).map((category) => `
    <button type="button" class="shortcut-chip ${category.id === activeCategoryId ? 'active' : ''}" data-shortcut-category="${category.id}">
      <span>${category.icon || '📦'}</span>${escapeHtml(category.name)}
    </button>
  `).join('');
}

function renderActiveFilterChips() {
  const chips = [];
  if (state.categoryDrilldown) {
    chips.push(`<button type="button" class="active-filter-chip" data-filter-chip="category">Category: ${escapeHtml(state.categoryDrilldown.label)} ✕</button>`);
  }
  if (state.explorerType !== 'all') {
    chips.push(`<button type="button" class="active-filter-chip" data-filter-chip="type">Type: ${escapeHtml(labelize(state.explorerType))} ✕</button>`);
  }
  if (state.explorerSearch) {
    chips.push(`<button type="button" class="active-filter-chip" data-filter-chip="search">Search: “${escapeHtml(state.explorerSearch)}” ✕</button>`);
  }
  el['active-filter-chips'].innerHTML = chips.join('');
}

function renderExplorer() {
  toggleSegments(el.explorerSegments, state.explorerType, 'explorerFilter');

  const transactions = getFilteredExplorerTransactions();
  el['explorer-count'].className = `status-badge ${transactions.length ? 'neutral' : 'warning'}`;
  el['explorer-count'].textContent = `${transactions.length} shown`;
  el['btn-clear-explorer-filters'].hidden = !hasActiveExplorerFilters();
  renderActiveFilterChips();

  if (!transactions.length) {
    el['explorer-tbody'].innerHTML = buildEmptyBlock('No transactions match these filters', 'Clear the current search or drill-down to see the full month again.', 'Search');
    return;
  }

  const grouped = groupTransactionsByTime(transactions);
  el['explorer-tbody'].innerHTML = grouped.map((group) => `
    <section class="transaction-group">
      <h4>${group.label}</h4>
      <div class="transaction-group-list">
        ${group.items.map((txn) => {
          const merchant = txn.merchant_normalized || txn.merchant_raw || 'Unknown merchant';
          const tone = txn.transaction_type === 'credit' ? 'positive' : txn.transaction_type === 'refund' ? 'neutral' : 'negative';
          const confidence = Math.round((txn.confidence_score || 0) * 100);
          return `
            <article class="transaction-row" data-open-review="${txn.id}">
              <div class="merchant-avatar">${escapeHtml(getMerchantInitials(merchant))}</div>
              <div class="transaction-main">
                <strong>${escapeHtml(merchant)}</strong>
                <span>${escapeHtml(txn.category_name || lookupCategoryName(txn.category_id))} - ${formatDate(txn.transaction_date)}</span>
              </div>
              <div class="transaction-meta">
                <strong class="amount ${tone}">${formatSignedAmount(txn)}</strong>
                <span class="confidence-pill ${confidence >= 85 ? 'high' : confidence >= 65 ? 'medium' : 'low'}"><i></i>${confidence}%</span>
              </div>
              <button type="button" class="review-nudge ${txn.reviewed_flag ? 'reviewed' : 'needs-review'}" data-open-review="${txn.id}">
                ${txn.reviewed_flag ? 'Reviewed' : 'Needs confirmation'}
              </button>
            </article>
          `;
        }).join('')}
      </div>
    </section>
  `).join('');
}

function populateCategorySelects() {
  const options = ['<option value="">Uncategorized</option>']
    .concat(state.categories.map((category) => `<option value="${category.id}">${category.icon || '📦'} ${escapeHtml(category.name)}</option>`))
    .join('');

  el['review-category'].innerHTML = options;
  el['budget-category'].innerHTML = ['<option value="">Select category…</option>']
    .concat(state.categories.map((category) => `<option value="${category.id}">${category.icon || '📦'} ${escapeHtml(category.name)}</option>`))
    .join('');
  el['bulk-category-select'].innerHTML = ['<option value="">Apply category…</option>']
    .concat(state.categories.map((category) => `<option value="${category.id}">${category.icon || '📦'} ${escapeHtml(category.name)}</option>`))
    .join('');
}

function getPendingReviewTransactions() {
  return state.transactions
    .filter((txn) => !txn.reviewed_flag)
    .sort((a, b) => (a.confidence_score || 0) - (b.confidence_score || 0) || compareDates(b.transaction_date, a.transaction_date));
}

function getReviewCandidateTransactions() {
  return state.transactions
    .filter((txn) => !txn.reviewed_flag || (txn.confidence_score || 0) < REVIEW_CONFIDENCE_THRESHOLD)
    .sort((a, b) => Number(a.reviewed_flag) - Number(b.reviewed_flag) || (a.confidence_score || 0) - (b.confidence_score || 0));
}

function getVisibleReviewTransactions() {
  const base = state.reviewFilter === 'pending' ? getPendingReviewTransactions() : getReviewCandidateTransactions();
  if (!state.reviewSearch) return base;
  return base.filter((txn) => buildTransactionSearchHaystack(txn).includes(state.reviewSearch));
}

function getFilteredExplorerTransactions() {
  return state.transactions.filter((txn) => {
    if (state.categoryDrilldown && categoryToken(txn.category_id) !== state.categoryDrilldown.categoryId) return false;
    if (state.explorerType === 'review' && txn.reviewed_flag) return false;
    if (['debit', 'credit', 'refund'].includes(state.explorerType) && txn.transaction_type !== state.explorerType) return false;
    if (state.explorerSearch && !buildTransactionSearchHaystack(txn).includes(state.explorerSearch)) return false;
    return true;
  });
}

function groupTransactionsByTime(transactions) {
  const buckets = [
    { key: 'today', label: 'Today', items: [] },
    { key: 'yesterday', label: 'Yesterday', items: [] },
    { key: 'week', label: 'This week', items: [] },
    { key: 'earlier', label: 'Earlier', items: [] },
  ];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const weekStart = new Date(today);
  weekStart.setDate(today.getDate() - 6);

  transactions
    .slice()
    .sort((a, b) => compareDates(b.transaction_date, a.transaction_date))
    .forEach((txn) => {
      const date = parseDateValue(txn.transaction_date);
      date.setHours(0, 0, 0, 0);
      if (date.getTime() === today.getTime()) buckets[0].items.push(txn);
      else if (date.getTime() === yesterday.getTime()) buckets[1].items.push(txn);
      else if (date >= weekStart) buckets[2].items.push(txn);
      else buckets[3].items.push(txn);
    });

  return buckets.filter((bucket) => bucket.items.length);
}

function getMerchantInitials(value) {
  return String(value || 'PF')
    .replace(/[^a-zA-Z0-9 ]/g, ' ')
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || '')
    .join('') || 'PF';
}

function buildTransactionSearchHaystack(txn) {
  return [txn.merchant_normalized, txn.merchant_raw, txn.reference_id, txn.account_last4, txn.category_name, txn.transaction_type]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function handleReviewListClick(event) {
  const checkbox = event.target.closest('[data-review-checkbox]');
  if (checkbox) return;
  const item = event.target.closest('[data-review-id]');
  if (!item) return;
  state.focusedReviewId = item.dataset.reviewId;
  renderReviewQueue();
  renderReviewDetail();
}

function handleReviewCheckboxChange(event) {
  const checkbox = event.target.closest('[data-review-checkbox]');
  if (!checkbox) return;
  const reviewId = checkbox.dataset.reviewCheckbox;
  if (checkbox.checked) {
    state.selectedReviewIds.add(reviewId);
  } else {
    state.selectedReviewIds.delete(reviewId);
  }
  renderReviewQueue();
}

function handleCategoryLegendClick(event) {
  const button = event.target.closest('[data-category-id]');
  if (!button) return;
  const category = state.summary?.category_breakdown?.find((item) => categoryToken(item.category_id) === button.dataset.categoryId);
  if (category) setCategoryDrilldown(category, true);
}

function handleMerchantClick(event) {
  const button = event.target.closest('[data-merchant-name]');
  if (!button) return;
  state.explorerSearch = button.dataset.merchantName.toLowerCase();
  el['explorer-search'].value = button.dataset.merchantName;
  renderExplorer();
  renderActionBarMeta();
  scrollToSection('transactions');
}

function handleCategoryShortcutClick(event) {
  const button = event.target.closest('[data-shortcut-category]');
  if (!button) return;
  el['review-category'].value = button.dataset.shortcutCategory;
  renderCategoryShortcuts(button.dataset.shortcutCategory);
}

async function handleBudgetBoardClick(event) {
  const action = event.target.closest('[data-budget-action]');
  if (action) {
    const budget = state.budgets.find((item) => item.id === action.dataset.budgetId);
    if (!budget) return;
    if (action.dataset.budgetAction === 'edit') {
      openBudgetModal('edit', budget);
      return;
    }
    if (action.dataset.budgetAction === 'delete') {
      await deleteBudget(budget.id);
      return;
    }
  }

  const drill = event.target.closest('[data-budget-category-drill]');
  if (drill) {
    const category = state.summary?.category_breakdown?.find((item) => categoryToken(item.category_id) === categoryToken(drill.dataset.budgetCategoryDrill))
      || state.categories.find((item) => item.id === drill.dataset.budgetCategoryDrill);
    if (category) {
      setCategoryDrilldown({ category_id: category.category_id || category.id, name: category.name }, true);
    }
  }
}

function handleExplorerTableClick(event) {
  const button = event.target.closest('[data-open-review]');
  if (!button) return;
  state.focusedReviewId = button.dataset.openReview;
  renderReviewQueue();
  renderReviewDetail();
  scrollToSection('review');
}

function handleFilterChipClick(event) {
  const chip = event.target.closest('[data-filter-chip]');
  if (!chip) return;
  if (chip.dataset.filterChip === 'category') clearCategoryDrilldown();
  if (chip.dataset.filterChip === 'type') setExplorerType('all');
  if (chip.dataset.filterChip === 'search') {
    state.explorerSearch = '';
    el['explorer-search'].value = '';
    renderExplorer();
    renderActionBarMeta();
  }
}

function setReviewFilter(filter) {
  state.reviewFilter = filter;
  renderReviewQueue();
}

function setExplorerType(filter) {
  state.explorerType = filter;
  renderExplorer();
  renderActionBarMeta();
}

function clearExplorerFilters() {
  state.explorerType = 'all';
  state.explorerSearch = '';
  state.categoryDrilldown = null;
  el['explorer-search'].value = '';
  renderCategoryAnalytics();
  renderExplorer();
  renderActionBarMeta();
}

function hasActiveExplorerFilters() {
  return state.explorerType !== 'all' || Boolean(state.explorerSearch) || Boolean(state.categoryDrilldown);
}

function setCategoryDrilldown(category, shouldScroll = false) {
  state.categoryDrilldown = {
    categoryId: categoryToken(category.category_id || category.id),
    label: category.name,
  };
  renderCategoryAnalytics();
  renderExplorer();
  renderActionBarMeta();
  if (shouldScroll) scrollToSection('transactions');
}

function clearCategoryDrilldown() {
  state.categoryDrilldown = null;
  renderCategoryAnalytics();
  renderExplorer();
  renderActionBarMeta();
}

function selectVisibleReviewItems() {
  getVisibleReviewTransactions().forEach((txn) => state.selectedReviewIds.add(txn.id));
  renderReviewQueue();
}

function clearSelectedReviewIds() {
  state.selectedReviewIds.clear();
  renderReviewQueue();
}

async function saveFocusedReview(moveNext) {
  const transaction = state.transactions.find((txn) => txn.id === state.focusedReviewId);
  if (!transaction) return;

  const merchant = el['review-merchant'].value.trim();
  const categoryId = el['review-category'].value || null;
  const amount = Number.parseFloat(el['review-amount'].value);
  const type = el['review-type'].value;

  if (!merchant) {
    showToast('Merchant name is required for a saved review.', 'error');
    return;
  }
  if (!Number.isFinite(amount) || amount <= 0) {
    showToast('Please enter a valid amount.', 'error');
    return;
  }

  const payload = {};
  if (merchant !== (transaction.merchant_normalized || transaction.merchant_raw || '')) payload.merchant_normalized = merchant;
  if ((categoryId || null) !== (transaction.category_id || null)) payload.category_id = categoryId;
  if (amount !== transaction.amount) payload.amount = amount;
  if (type !== transaction.transaction_type) payload.transaction_type = type;
  payload.reviewed_flag = true;

  if (Object.keys(payload).length === 1 && payload.reviewed_flag === true && transaction.reviewed_flag) {
    showToast('Nothing changed on this review.', 'info');
    return;
  }

  await patchTransaction(transaction.id, payload, moveNext);
}

async function markFocusedReviewed() {
  const transaction = state.transactions.find((txn) => txn.id === state.focusedReviewId);
  if (!transaction) return;
  if (transaction.reviewed_flag) {
    showToast('This transaction is already marked reviewed.', 'info');
    return;
  }
  await patchTransaction(transaction.id, { reviewed_flag: true }, true);
}

async function patchTransaction(transactionId, payload, moveNext) {
  const nextId = moveNext ? findNextPendingReviewId(transactionId) : transactionId;
  try {
    await apiRequest(`/transactions/${transactionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    showToast('Review saved', 'success');
    await refreshDashboardData({ announceLabel: 'Review saved' });
    if (nextId) {
      state.focusedReviewId = nextId;
      renderReviewQueue();
      renderReviewDetail();
    }
  } catch (error) {
    showToast(error.message || 'Unable to save the review.', 'error');
  }
}

function findNextPendingReviewId(currentId) {
  const pending = getPendingReviewTransactions();
  if (!pending.length) return null;
  const index = pending.findIndex((txn) => txn.id === currentId);
  if (index === -1) return pending[0].id;
  return pending[index + 1]?.id || pending[index]?.id || pending[0]?.id || null;
}

function focusNextPendingReview() {
  const next = findNextPendingReviewId(state.focusedReviewId);
  if (!next) {
    showToast('No pending review items remain.', 'success');
    return;
  }
  state.focusedReviewId = next;
  renderReviewQueue();
  renderReviewDetail();
}

async function applyBulkReviewUpdates(markReviewedOnly = false) {
  const selectedIds = [...state.selectedReviewIds];
  if (!selectedIds.length) {
    showToast('Select one or more queue items first.', 'error');
    return;
  }

  const payload = {
    transaction_ids: selectedIds,
  };

  if (markReviewedOnly) {
    payload.reviewed_flag = true;
  } else {
    if (el['bulk-category-select'].value) payload.category_id = el['bulk-category-select'].value;
    if (el['bulk-type-select'].value) payload.transaction_type = el['bulk-type-select'].value;
    payload.reviewed_flag = true;
  }

  if (Object.keys(payload).length <= 1) {
    showToast('Choose a category, type, or review action for the selected items.', 'error');
    return;
  }

  try {
    const result = await apiRequest(`/transactions/bulk-update?user_id=${encodeURIComponent(state.session.user.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (result.failed?.length) {
      showToast(`Updated ${result.updated_count}, ${result.failed.length} failed.`, 'info');
    } else {
      showToast(`Updated ${result.updated_count} review item${result.updated_count === 1 ? '' : 's'}.`, 'success');
    }
    clearSelectedReviewIds();
    el['bulk-category-select'].value = '';
    el['bulk-type-select'].value = '';
    await refreshDashboardData({ announceLabel: 'Bulk review update applied' });
  } catch (error) {
    showToast(error.message || 'Unable to apply bulk review update.', 'error');
  }
}

function openBudgetModal(mode, budget = null) {
  state.budgetDraft = { mode, budgetId: budget?.id || null };
  el['budget-modal-title'].textContent = mode === 'edit' ? 'Update budget' : 'Set budget';
  populateCategorySelects();
  el['budget-category'].disabled = mode === 'edit';
  el['budget-category'].value = budget?.category_id || '';
  el['budget-limit'].value = budget?.monthly_limit || '';
  el['budget-modal'].hidden = false;
}

function closeBudgetModal() {
  el['budget-modal'].hidden = true;
  el['budget-form'].reset();
  state.budgetDraft = { mode: 'create', budgetId: null };
}

async function saveBudget(event) {
  event.preventDefault();
  const categoryId = el['budget-category'].value;
  const monthlyLimit = Number.parseFloat(el['budget-limit'].value);
  if (!categoryId || !Number.isFinite(monthlyLimit) || monthlyLimit <= 0) {
    showToast('Select a category and enter a valid monthly limit.', 'error');
    return;
  }

  try {
    if (state.budgetDraft.mode === 'edit' && state.budgetDraft.budgetId) {
      await apiRequest(`/budgets/${state.budgetDraft.budgetId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ monthly_limit: monthlyLimit }),
      });
      showToast('Budget updated', 'success');
    } else {
      await apiRequest(`/budgets/?user_id=${encodeURIComponent(state.session.user.id)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_id: categoryId, monthly_limit: monthlyLimit }),
      });
      showToast('Budget created', 'success');
    }
    closeBudgetModal();
    await refreshDashboardData({ announceLabel: 'Budget saved' });
  } catch (error) {
    showToast(error.message || 'Unable to save the budget.', 'error');
  }
}

async function deleteBudget(budgetId) {
  if (!window.confirm('Remove this budget card from the board?')) return;
  try {
    await apiRequest(`/budgets/${budgetId}`, { method: 'DELETE' });
    showToast('Budget removed', 'success');
    await refreshDashboardData({ announceLabel: 'Budget removed' });
  } catch (error) {
    showToast(error.message || 'Unable to remove the budget.', 'error');
  }
}

async function startDemoSyncPipeline() {
  await runBackgroundJob(`/jobs/demo-sync-pipeline?user_id=${encodeURIComponent(state.session.user.id)}&limit=80`, 'Inbox sync', 'Sync inbox', el['btn-sync']);
}

async function retryParseFailures() {
  await runBackgroundJob(`/jobs/retry-parse-failures?user_id=${encodeURIComponent(state.session.user.id)}&limit=40`, 'Retry sync', 'Retry sync', el['btn-retry']);
}

async function runBackgroundJob(path, label, idleText, button) {
  setButtonLoading(button, true, 'Working…');
  setSyncPill(`${label} queued`, 'warning');
  writeActivity(`⏳ ${label} queued.`);
  try {
    const job = await apiRequest(path, { method: 'POST' });
    state.activeJob = job;
    renderCommandCenter();
    await monitorJob(job.id, label);
  } catch (error) {
    state.activeJob = null;
    renderCommandCenter();
    setSyncPill(error.message || 'Job failed to start', 'error');
    writeActivity(`❌ ${label} failed to start: ${error.message}`);
    showToast(error.message || 'Unable to start the background job.', 'error');
  } finally {
    setButtonLoading(button, false, idleText);
  }
}

async function monitorJob(jobId, label) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    const snapshot = await apiRequest(`/jobs/${jobId}`);
    state.activeJob = snapshot;
    state.lastJob = snapshot;
    renderCommandCenter();
    setSyncPill(`${label} ${snapshot.status}`, snapshot.status === 'failed' ? 'error' : snapshot.status === 'completed' ? 'accent' : snapshot.status === 'running' ? 'accent' : 'warning');

    if (snapshot.status === 'running' && attempt === 0) {
      writeActivity(`⚙️ ${label} is running in the background.`);
    }

    if (snapshot.status === 'completed') {
      writeActivity(`✅ ${label} completed. ${summarizeJob(snapshot)}`);
      state.activeJob = null;
      renderCommandCenter();
      await refreshDashboardData({ announceLabel: `${label} completed` });
      showToast(`${label} completed`, 'success');
      return;
    }

    if (snapshot.status === 'failed') {
      writeActivity(`❌ ${label} failed: ${snapshot.error_message || 'Unknown error'}`);
      state.activeJob = null;
      renderCommandCenter();
      showToast(snapshot.error_message || `${label} failed`, 'error');
      return;
    }

    await delay(500);
  }

  state.activeJob = null;
  renderCommandCenter();
  showToast(`${label} timed out while polling status.`, 'error');
}

async function exportCsv() {
  try {
    const response = await apiFetch(`/reports/export/csv?user_id=${encodeURIComponent(state.session.user.id)}&month=${state.currentMonth}&year=${state.currentYear}`);
    const blob = await response.blob();
    triggerDownload(blob, `pfis-${state.currentYear}-${String(state.currentMonth).padStart(2, '0')}.csv`);
    showToast('CSV export downloaded', 'success');
  } catch (error) {
    showToast(error.message || 'Unable to export CSV.', 'error');
  }
}

async function openMonthlyReport() {
  try {
    const response = await apiFetch(`/reports/monthly?user_id=${encodeURIComponent(state.session.user.id)}&month=${state.currentMonth}&year=${state.currentYear}`);
    const html = await response.text();
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank', 'noopener');
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    showToast('Monthly report opened in a new tab', 'success');
  } catch (error) {
    showToast(error.message || 'Unable to open the monthly report.', 'error');
  }
}

async function apiFetch(path, options = {}) {
  const { auth = true, tolerate401 = false, headers = {}, ...rest } = options;
  if (auth && isSessionExpired()) {
    await signOut(true, 'Your session expired.');
    throw new Error('Session expired');
  }

  const finalHeaders = new Headers(headers);
  if (auth && state.session.mode === 'auth' && state.session.token) {
    finalHeaders.set('Authorization', `Bearer ${state.session.token}`);
  }

  const response = await fetch(`${API}${path}`, {
    ...rest,
    headers: finalHeaders,
  });

  if (response.status === 401 && auth && !tolerate401) {
    await signOut(true, 'Your session expired.');
    throw new Error('Authentication required');
  }

  if (!response.ok) {
    let message = `${response.status} request failed`;
    try {
      const payload = await response.json();
      message = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail);
    } catch {
      try {
        const text = await response.text();
        if (text) message = text;
      } catch {
        /* ignore */
      }
    }
    throw new Error(message);
  }

  return response;
}

async function apiRequest(path, options = {}) {
  const response = await apiFetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) return null;
  return response.json();
}

function syncMonthControls() {
  const now = new Date();
  const atCurrentMonth = state.currentMonth === (now.getMonth() + 1) && state.currentYear === now.getFullYear();
  el['btn-next-month'].disabled = atCurrentMonth;
}

function changeMonth(delta) {
  state.currentMonth += delta;
  if (state.currentMonth > 12) {
    state.currentMonth = 1;
    state.currentYear += 1;
  }
  if (state.currentMonth < 1) {
    state.currentMonth = 12;
    state.currentYear -= 1;
  }
  refreshDashboardData({ announceLabel: `Loaded ${formatMonthLabel()}` });
}

function resetToCurrentMonth() {
  const now = new Date();
  state.currentMonth = now.getMonth() + 1;
  state.currentYear = now.getFullYear();
  refreshDashboardData({ announceLabel: `Loaded ${formatMonthLabel()}` });
}

function formatMonthLabel() {
  return new Date(state.currentYear, state.currentMonth - 1, 1).toLocaleDateString('en-IN', {
    month: 'long',
    year: 'numeric',
  });
}

function setSyncPill(text, variant = 'accent') {
  el['sync-pill'].textContent = text;
  el['sync-pill'].className = `meta-pill ${variant}`;
}

function buildSyncPillText() {
  if (state.activeJob) {
    return `${labelize(state.activeJob.job_type || 'job')} • ${state.activeJob.status}`;
  }
  const latestSync = state.syncStatus?.runs?.[0];
  if (!latestSync) return 'Pipeline idle';
  return `Latest sync • ${latestSync.status}`;
}

function buildFilterPillText() {
  const filters = [];
  if (state.categoryDrilldown) filters.push(`Category: ${state.categoryDrilldown.label}`);
  if (state.explorerType !== 'all') filters.push(labelize(state.explorerType));
  if (state.explorerSearch) filters.push(`Search: ${state.explorerSearch}`);
  return filters.length ? filters.join(' • ') : 'All transactions';
}

function setLoading(show) {
  document.body.classList.toggle('dashboard-loading', show);
}

function setGlobalBanner(message) {
  el['global-banner'].hidden = !message;
  el['global-banner'].textContent = message;
}

function clearActivityLog() {
  state.activityLog = ['Activity log cleared.'];
  renderActivityLog();
}

function writeActivity(message) {
  const timestamp = new Date().toLocaleTimeString();
  state.activityLog = [`[${timestamp}] ${message}`, ...state.activityLog].slice(0, 30);
  renderActivityLog();
}

function renderActivityLog() {
  el['sync-log'].textContent = state.activityLog.join('\n');
}

function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️'}</span>
    <div>${escapeHtml(message)}</div>
  `;
  el['toast-stack'].appendChild(toast);
  announce(message);
  window.setTimeout(() => {
    toast.remove();
  }, 4200);
}

function announce(message) {
  el['live-region'].textContent = message || '';
}

function buildEmptyBlock(title, description, icon) {
  return `
    <div class="empty-panel">
      <span class="empty-icon">${icon}</span>
      <h4>${title}</h4>
      <p>${description}</p>
    </div>
  `;
}

function setButtonLoading(button, loading, label) {
  if (!button) return;
  if ('disabled' in button) button.disabled = loading;
  button.innerHTML = loading ? `<span class="spinner"></span> ${label}` : label;
}

function setActiveSectionLink(sectionId) {
  el.sectionLinks.forEach((button) => button.classList.toggle('active', button.dataset.scrollTarget === sectionId));
}

function scrollToSection(sectionId) {
  const target = document.getElementById(sectionId);
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  setActiveSectionLink(sectionId);
}

function toggleSegments(segments, activeValue, datasetKey) {
  segments.forEach((button) => {
    button.classList.toggle('active', button.dataset[datasetKey] === activeValue);
  });
}

function summarizeJob(job) {
  if (!job) return 'No background activity yet.';
  const result = job.result || {};
  if (job.job_type === 'retry_parse_failures') {
    return `${result.retried_failures || 0} failures retried, ${result.stored || 0} transaction${(result.stored || 0) === 1 ? '' : 's'} recovered.`;
  }
  const sync = result.sync || {};
  const pipeline = result.pipeline || {};
  return `${sync.emails_stored || 0} emails stored, ${pipeline.stored || 0} transaction${(pipeline.stored || 0) === 1 ? '' : 's'} posted, ${pipeline.low_confidence || 0} still need review.`;
}

function lookupCategoryName(categoryId) {
  return state.categories.find((category) => category.id === categoryId)?.name || 'Uncategorized';
}

function getSavingsHealth(rate) {
  if (rate >= 50) {
    return {
      label: `Excellent savings health (${rate}%)`,
      detail: 'You are keeping a strong share of income.',
      tone: 'success',
    };
  }
  if (rate >= 20) {
    return {
      label: `Good savings health (${rate}%)`,
      detail: 'Your month is stable, with room to grow savings.',
      tone: 'success',
    };
  }
  if (rate >= 0) {
    return {
      label: `Thin savings margin (${rate}%)`,
      detail: 'Spending is close to income, so budgets matter this month.',
      tone: 'warning',
    };
  }
  return {
    label: `Overspending alert (${rate}%)`,
    detail: 'Expenses are higher than income for this month.',
    tone: 'danger',
  };
}

function getBudgetForecast(budget) {
  const spend = Number(budget.actual_spend || 0);
  const limit = Number(budget.monthly_limit || 0);
  if (!limit) return { text: 'Add a monthly limit to unlock forecast guidance.', tone: 'neutral' };
  if (spend <= 0) return { text: 'No spending in this category yet this month.', tone: 'success' };
  if (spend > limit) {
    return { text: `Already ${formatCurrency(spend - limit)} over. Reduce or reset this budget.`, tone: 'danger' };
  }

  const today = new Date();
  const isCurrentMonth = today.getFullYear() === state.currentYear && today.getMonth() + 1 === state.currentMonth;
  const dayOfMonth = isCurrentMonth ? today.getDate() : new Date(state.currentYear, state.currentMonth, 0).getDate();
  const daysInMonth = new Date(state.currentYear, state.currentMonth, 0).getDate();
  const dailyPace = spend / Math.max(dayOfMonth, 1);
  const projectedSpend = dailyPace * daysInMonth;

  if (projectedSpend <= limit) {
    return { text: `Forecast: on track to end near ${formatCurrency(projectedSpend)}.`, tone: 'success' };
  }

  const daysUntilLimit = Math.max(1, Math.ceil((limit - spend) / dailyPace));
  const forecastDate = new Date(state.currentYear, state.currentMonth - 1, Math.min(dayOfMonth + daysUntilLimit, daysInMonth));
  return {
    text: `Forecast: may exceed limit around ${formatDate(forecastDate)} at this pace.`,
    tone: budget.status === 'warning' ? 'warning' : 'danger',
  };
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(amount);
}

function compactCurrency(value) {
  const amount = Number(value || 0);
  if (Math.abs(amount) >= 100000) return `${(amount / 100000).toFixed(1)}L`;
  if (Math.abs(amount) >= 1000) return `${(amount / 1000).toFixed(0)}k`;
  return `${Math.round(amount)}`;
}

function formatDate(value) {
  if (!value) return '—';
  return parseDateValue(value).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function formatSignedAmount(txn) {
  const sign = txn.transaction_type === 'credit' ? '+' : txn.transaction_type === 'refund' ? '+' : '-';
  return `${sign}${formatCurrency(txn.amount)}`;
}

function renderConfidencePill(score) {
  const value = Math.round((score || 0) * 100);
  const tone = value >= 85 ? 'high' : value >= 65 ? 'medium' : 'low';
  return `<span class="confidence-pill ${tone}"><i></i>${value}%</span>`;
}

function compareDates(left, right) {
  return parseDateValue(left).getTime() - parseDateValue(right).getTime();
}

function parseDateValue(value) {
  if (value instanceof Date) return value;
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split('-').map(Number);
    return new Date(year, month - 1, day);
  }
  return new Date(value);
}

function categoryToken(value) {
  return value || '__uncategorized__';
}

function labelize(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 5_000);
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}
