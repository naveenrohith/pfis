/**
 * PFIS Dashboard — Application Logic
 * Handles API calls, chart rendering, month navigation,
 * user corrections, and UI updates.
 */

const API = 'http://localhost:8000/api';
let USER_ID = null;
let SUMMARY = null;
let CATEGORIES = [];

// Current month/year for navigation
let currentMonth = new Date().getMonth() + 1;
let currentYear = new Date().getFullYear();

// ═══════════════════════════════════════════
// Init
// ═══════════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
  updateMonthLabel();
  try {
    await loadUser();
    await loadCategories();
    await refreshDashboard();
  } catch (e) {
    showToast('Failed to connect to API', 'error');
    console.error(e);
  }
});

async function loadUser() {
  const users = await apiGet('/users/');
  if (users.length === 0) throw new Error('No users found');
  USER_ID = users[0].id;
  document.getElementById('user-name').textContent = users[0].name;
  document.getElementById('user-email').textContent = users[0].email;
}

async function loadCategories() {
  try {
    CATEGORIES = await apiGet('/categories/');
  } catch (e) {
    console.warn('Failed to load categories:', e);
    CATEGORIES = [];
  }
}

async function refreshDashboard() {
  showLoading(true);

  try {
    // Fetch all data in parallel (Phases 4-6)
    const [summary, txns, emailsResp, insightsResp, budgetTrack] = await Promise.all([
      apiGet(`/transactions/summary?user_id=${USER_ID}&month=${currentMonth}&year=${currentYear}`),
      apiGet(`/transactions/?user_id=${USER_ID}&month=${currentMonth}&year=${currentYear}`),
      apiGet(`/gmail/emails?user_id=${USER_ID}`),
      apiGet(`/insights/?user_id=${USER_ID}&month=${currentMonth}&year=${currentYear}`),
      apiGet(`/budgets/track?user_id=${USER_ID}&month=${currentMonth}&year=${currentYear}`).catch(() => []),
    ]);

    SUMMARY = summary;

    updateStatCards(summary);
    renderCategoryChart(summary.category_breakdown);
    renderCategoryList(summary.category_breakdown, summary.total_spend);
    renderTopMerchants(summary.top_merchants);
    renderTransactionTable(txns);
    updateEmailCount(emailsResp.total);

    // Phase 5: Insights
    renderInsightCards(insightsResp.insights);
    renderTrendChart(insightsResp.daily_trend);
    renderRecurringPayments(insightsResp.recurring_payments);

    // Phase 6: Budgets
    renderBudgetTracker(budgetTrack);

    document.getElementById('last-updated').textContent =
      `Updated: ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    console.error('Dashboard refresh failed:', e);
  } finally {
    showLoading(false);
  }
}

// ═══════════════════════════════════════════
// Month Navigation
// ═══════════════════════════════════════════

function changeMonth(delta) {
  currentMonth += delta;
  if (currentMonth > 12) { currentMonth = 1; currentYear++; }
  if (currentMonth < 1) { currentMonth = 12; currentYear--; }
  updateMonthLabel();
  refreshDashboard();
}

function updateMonthLabel() {
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const label = document.getElementById('month-label');
  if (label) {
    label.textContent = `${monthNames[currentMonth - 1]} ${currentYear}`;
  }

  // Disable next if we're at the current month
  const now = new Date();
  const btnNext = document.getElementById('btn-next-month');
  if (btnNext) {
    btnNext.disabled = (currentMonth === now.getMonth() + 1 && currentYear === now.getFullYear());
  }
}

// ═══════════════════════════════════════════
// Stat Cards
// ═══════════════════════════════════════════

function updateStatCards(s) {
  animateValue('stat-spend', s.total_spend);
  animateValue('stat-income', s.total_income);
  animateValue('stat-net', s.net);
  document.getElementById('stat-count').textContent = s.transaction_count;

  document.getElementById('stat-net-card').classList.toggle('positive', s.net >= 0);
}

function animateValue(id, target) {
  const el = document.getElementById(id);
  const start = parseFloat(el.dataset.value || 0);
  el.dataset.value = target;
  const duration = 800;
  const startTime = performance.now();

  function update(now) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const ease = 1 - Math.pow(1 - progress, 3); // easeOutCubic
    const current = start + (target - start) * ease;
    el.textContent = formatCurrency(current);
    if (progress < 1) requestAnimationFrame(update);
  }

  requestAnimationFrame(update);
}

// ═══════════════════════════════════════════
// Charts
// ═══════════════════════════════════════════

let categoryChart = null;

const CHART_COLORS = [
  '#ef4444', '#3b82f6', '#22c55e', '#f59e0b',
  '#a855f7', '#06b6d4', '#ec4899', '#84cc16',
  '#f97316', '#6366f1', '#14b8a6', '#e11d48',
];

function renderCategoryChart(categories) {
  const ctx = document.getElementById('category-chart');
  if (!ctx) return;

  if (categoryChart) categoryChart.destroy();

  if (!categories || categories.length === 0) {
    ctx.parentElement.innerHTML = '<div class="empty-state"><div class="empty-icon">📊</div><h3>No spending data</h3></div>';
    return;
  }

  categoryChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: categories.map(c => c.name),
      datasets: [{
        data: categories.map(c => c.total),
        backgroundColor: CHART_COLORS.slice(0, categories.length),
        borderWidth: 0,
        hoverBorderWidth: 2,
        hoverBorderColor: '#fff',
        borderRadius: 4,
        spacing: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '68%',
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a2035',
          titleColor: '#f1f5f9',
          bodyColor: '#94a3b8',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          cornerRadius: 10,
          padding: 12,
          displayColors: true,
          callbacks: {
            label: (ctx) => ` ${ctx.label}: ₹${ctx.raw.toLocaleString('en-IN')}`,
          },
        },
      },
      animation: { animateRotate: true, duration: 1000 },
    },
  });
}

function renderCategoryList(categories, totalSpend) {
  const list = document.getElementById('category-list');
  if (!list) return;

  if (!categories || categories.length === 0) {
    list.innerHTML = '<li class="empty-state"><p>No categories yet</p></li>';
    return;
  }

  list.innerHTML = categories.map((c, i) => {
    const pct = totalSpend > 0 ? ((c.total / totalSpend) * 100).toFixed(0) : 0;
    return `
      <li class="category-item">
        <span class="cat-color" style="background:${CHART_COLORS[i % CHART_COLORS.length]}"></span>
        <span class="cat-name">${c.name}</span>
        <span class="cat-amount">₹${c.total.toLocaleString('en-IN')}</span>
        <span class="cat-pct">${pct}%</span>
      </li>
    `;
  }).join('');
}

// ═══════════════════════════════════════════
// Top Merchants
// ═══════════════════════════════════════════

function renderTopMerchants(merchants) {
  const list = document.getElementById('merchant-list');
  if (!list) return;

  if (!merchants || merchants.length === 0) {
    list.innerHTML = '<li class="empty-state"><p>No merchants yet</p></li>';
    return;
  }

  list.innerHTML = merchants.map((m, i) => `
    <li class="merchant-rank-item">
      <span class="rank-number">${i + 1}</span>
      <span class="rank-name">${m.name}</span>
      <span class="rank-amount">₹${m.total.toLocaleString('en-IN')}</span>
      <span class="rank-count">${m.count} txn${m.count > 1 ? 's' : ''}</span>
    </li>
  `).join('');
}

// ═══════════════════════════════════════════
// Tab Switching (Categories / Merchants)
// ═══════════════════════════════════════════

function switchTab(tab) {
  const catList = document.getElementById('category-list');
  const merchList = document.getElementById('merchant-list');
  const tabCat = document.getElementById('tab-categories');
  const tabMerch = document.getElementById('tab-merchants');

  if (tab === 'categories') {
    catList.style.display = '';
    merchList.style.display = 'none';
    tabCat.classList.add('active');
    tabMerch.classList.remove('active');
    tabCat.style.background = 'var(--bg-card-hover)';
    tabCat.style.color = 'var(--text-primary)';
    tabMerch.style.background = 'transparent';
    tabMerch.style.color = 'var(--text-muted)';
  } else {
    catList.style.display = 'none';
    merchList.style.display = '';
    tabMerch.classList.add('active');
    tabCat.classList.remove('active');
    tabMerch.style.background = 'var(--bg-card-hover)';
    tabMerch.style.color = 'var(--text-primary)';
    tabCat.style.background = 'transparent';
    tabCat.style.color = 'var(--text-muted)';
  }
}

// ═══════════════════════════════════════════
// Transaction Table
// ═══════════════════════════════════════════

function renderTransactionTable(txns) {
  const tbody = document.getElementById('txn-tbody');
  if (!tbody) return;

  if (!txns || txns.length === 0) {
    tbody.innerHTML = `
      <tr><td colspan="7" class="empty-state">
        <div class="empty-icon">📋</div>
        <h3>No transactions yet</h3>
        <p>Click "Sync & Process" to import demo bank emails</p>
      </td></tr>
    `;
    return;
  }

  tbody.innerHTML = txns.map(t => {
    const type = (t.transaction_type || 'debit').toLowerCase();
    const amountClass = type === 'credit' ? 'amount-credit' : type === 'refund' ? 'amount-refund' : 'amount-debit';
    const sign = type === 'debit' ? '-' : '+';
    const conf = t.confidence_score || 0;
    const confClass = conf >= 0.9 ? 'conf-high' : conf >= 0.7 ? 'conf-med' : 'conf-low';
    const confPct = (conf * 100).toFixed(0);
    const dateStr = t.transaction_date ? new Date(t.transaction_date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—';
    const initial = (t.merchant_normalized || '?')[0].toUpperCase();
    const avatarBg = CHART_COLORS[initial.charCodeAt(0) % CHART_COLORS.length] + '22';
    const avatarColor = CHART_COLORS[initial.charCodeAt(0) % CHART_COLORS.length];

    // Confidence badge for low confidence items
    const confBadge = conf < 0.7
      ? '<span style="font-size:0.7rem; color:var(--accent-amber); margin-left:4px;" title="Needs review">⚠️</span>'
      : '';

    return `
      <tr>
        <td>
          <div class="merchant-cell">
            <div class="merchant-avatar" style="background:${avatarBg};color:${avatarColor}">${initial}</div>
            <div class="merchant-info">
              <div class="merchant-name">${t.merchant_normalized || 'Unknown'}${confBadge}</div>
              <div class="merchant-category">${t.merchant_raw || ''}</div>
            </div>
          </div>
        </td>
        <td class="${amountClass}">${sign}₹${t.amount.toLocaleString('en-IN')}</td>
        <td><span class="status-badge ${type}" style="background:${amountClass === 'amount-credit' ? 'var(--accent-green-bg)' : amountClass === 'amount-refund' ? 'var(--accent-amber-bg)' : 'var(--accent-red-bg)'}; color:${amountClass === 'amount-credit' ? 'var(--accent-green)' : amountClass === 'amount-refund' ? 'var(--accent-amber)' : 'var(--accent-red)'};">${type}</span></td>
        <td style="color:var(--text-secondary)">${dateStr}</td>
        <td>
          <div style="display:flex;align-items:center;gap:6px;">
            <div class="confidence-bar"><div class="confidence-fill ${confClass}" style="width:${confPct}%"></div></div>
            <span style="font-size:0.75rem;color:var(--text-muted)">${confPct}%</span>
          </div>
        </td>
        <td style="color:var(--text-muted);font-size:0.78rem">${t.account_last4 ? '••' + t.account_last4 : '—'}</td>
        <td>
          <button class="btn-edit" onclick="openEditModal('${t.id}', '${(t.merchant_normalized || '').replace(/'/g, "\\'")}', '${t.category_id || ''}')">✏️ Edit</button>
        </td>
      </tr>
    `;
  }).join('');
}

// ═══════════════════════════════════════════
// Edit Modal & User Corrections
// ═══════════════════════════════════════════

function openEditModal(txnId, merchantName, categoryId) {
  document.getElementById('edit-txn-id').value = txnId;
  document.getElementById('edit-merchant').value = merchantName;

  // Populate category dropdown
  const select = document.getElementById('edit-category');
  select.innerHTML = '<option value="">— Select —</option>';
  CATEGORIES.forEach(c => {
    const selected = c.id === categoryId ? 'selected' : '';
    select.innerHTML += `<option value="${c.id}" ${selected}>${c.icon || ''} ${c.name}</option>`;
  });

  document.getElementById('edit-modal').style.display = '';
}

function closeModal() {
  document.getElementById('edit-modal').style.display = 'none';
}

async function saveCorrection() {
  const txnId = document.getElementById('edit-txn-id').value;
  const merchant = document.getElementById('edit-merchant').value.trim();
  const categoryId = document.getElementById('edit-category').value;

  if (!merchant && !categoryId) {
    showToast('Please enter a correction', 'error');
    return;
  }

  const body = {};
  if (merchant) body.merchant_normalized = merchant;
  if (categoryId) body.category_id = categoryId;

  try {
    await apiPatch(`/transactions/${txnId}`, body);
    showToast('Transaction corrected', 'success');
    closeModal();
    await refreshDashboard();
  } catch (e) {
    showToast('Failed to save: ' + e.message, 'error');
  }
}

// Close modal on backdrop click
document.addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-overlay')) {
    closeModal();
  }
});

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
});

// ═══════════════════════════════════════════
// Sync & Process
// ═══════════════════════════════════════════

async function syncAndProcess() {
  const btn = document.getElementById('btn-sync');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Syncing...';

  const log = document.getElementById('sync-log');
  log.classList.add('open');
  const pre = log.querySelector('pre');
  pre.textContent = '';

  try {
    // Step 1: Demo sync
    appendLog(pre, '⏳ Fetching emails from Gmail (demo mode)...\n');
    const syncResult = await apiPost(`/gmail/demo-sync?user_id=${USER_ID}`);
    const ss = syncResult.stats;
    appendLog(pre, `✅ Fetched ${ss.emails_fetched} emails\n`);
    appendLog(pre, `   📧 Stored: ${ss.emails_stored}\n`);
    appendLog(pre, `   🚫 OTP skipped: ${ss.emails_skipped_otp}\n`);
    appendLog(pre, `   🚫 Promo skipped: ${ss.emails_skipped_promo}\n`);
    appendLog(pre, `   ♻️ Duplicates: ${ss.emails_skipped_duplicate}\n\n`);

    // Step 2: Process pipeline
    btn.innerHTML = '<span class="spinner"></span> Processing...';
    appendLog(pre, '⏳ Running parsing pipeline...\n');
    const pipeResult = await apiPost(`/pipeline/process?user_id=${USER_ID}`);
    const ps = pipeResult.stats;
    appendLog(pre, `✅ Pipeline complete\n`);
    appendLog(pre, `   📊 Parsed: ${ps.parsed_success}/${ps.total_unprocessed}\n`);
    appendLog(pre, `   💾 Stored: ${ps.stored}\n`);
    appendLog(pre, `   ♻️ Duplicates: ${ps.duplicates}\n`);
    appendLog(pre, `   ❌ Failed: ${ps.parsed_failed}\n\n`);

    // Show parsed details
    if (ps.results && ps.results.length > 0) {
      appendLog(pre, '─── Transaction Details ───\n');
      ps.results.forEach(r => {
        const icon = r.status === 'stored' ? '✅' : r.status === 'duplicate' ? '♻️' : '❌';
        const amt = r.amount ? `₹${r.amount.toLocaleString('en-IN')}` : '—';
        const merch = r.merchant_normalized || r.merchant_raw || 'Unknown';
        appendLog(pre, `${icon} ${merch.padEnd(18)} ${amt.padStart(10)}  [${(r.type || '?').padEnd(7)}] ${r.bank || ''}\n`);
      });
    }

    appendLog(pre, '\n🎉 Sync & process complete!');
    showToast(`${ps.stored} transactions imported`, 'success');

    // Refresh dashboard
    await refreshDashboard();

  } catch (e) {
    appendLog(pre, `\n❌ Error: ${e.message}`);
    showToast('Sync failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔄 Sync & Process';
  }
}

function appendLog(el, text) {
  el.textContent += text;
  el.scrollTop = el.scrollHeight;
}

// ═══════════════════════════════════════════
// API Helpers
// ═══════════════════════════════════════════

async function apiGet(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function apiPost(path, body = null) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : '{}',
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json();
}

async function apiPatch(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${path} failed: ${res.status}`);
  return res.json();
}

async function apiDelete(path) {
  const res = await fetch(`${API}${path}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`DELETE ${path} failed: ${res.status}`);
  return res.json();
}

// ═══════════════════════════════════════════
// Phase 5: Insights Rendering
// ═══════════════════════════════════════════

function renderInsightCards(insights) {
  const grid = document.getElementById('insights-grid');
  if (!grid) return;

  if (!insights || insights.length === 0) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1/-1;">
        <div class="empty-icon">💡</div>
        <h3>No insights yet</h3>
        <p>Sync some transactions to generate financial insights</p>
      </div>
    `;
    return;
  }

  grid.innerHTML = insights.map(i => `
    <div class="insight-card severity-${i.severity}">
      <div class="insight-icon">${i.icon}</div>
      <div class="insight-content">
        <div class="insight-title">${i.title}</div>
        <div class="insight-desc">${i.description}</div>
      </div>
    </div>
  `).join('');
}

// ═══════════════════════════════════════════
// Phase 5: Daily Spending Trend Chart
// ═══════════════════════════════════════════

let trendChart = null;

function renderTrendChart(dailyTrend) {
  const ctx = document.getElementById('trend-chart');
  if (!ctx) return;

  if (trendChart) trendChart.destroy();

  if (!dailyTrend || dailyTrend.length === 0) {
    ctx.parentElement.innerHTML = '<div class="empty-state"><div class="empty-icon">📈</div><h3>No trend data</h3></div>';
    return;
  }

  const labels = dailyTrend.map(d => d.date);
  const amounts = dailyTrend.map(d => d.total);

  // Compute cumulative spending for area fill
  let cumulative = [];
  let running = 0;
  amounts.forEach(a => {
    running += a;
    cumulative.push(running);
  });

  trendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Daily Spend',
          data: amounts,
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239, 68, 68, 0.08)',
          borderWidth: 2.5,
          pointRadius: 3,
          pointBackgroundColor: '#ef4444',
          pointBorderColor: '#1a2035',
          pointBorderWidth: 2,
          pointHoverRadius: 6,
          tension: 0.35,
          fill: true,
        },
        {
          label: 'Cumulative',
          data: cumulative,
          borderColor: '#a855f7',
          borderWidth: 1.5,
          borderDash: [5, 5],
          pointRadius: 0,
          tension: 0.35,
          fill: false,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          align: 'end',
          labels: {
            color: '#94a3b8',
            font: { size: 11, family: 'Inter' },
            boxWidth: 12,
            boxHeight: 2,
            padding: 16,
          },
        },
        tooltip: {
          backgroundColor: '#1a2035',
          titleColor: '#f1f5f9',
          bodyColor: '#94a3b8',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          cornerRadius: 10,
          padding: 12,
          callbacks: {
            label: (ctx) => ` ${ctx.dataset.label}: ₹${ctx.raw.toLocaleString('en-IN')}`,
          },
        },
      },
      scales: {
        x: {
          ticks: {
            color: '#64748b',
            font: { size: 10 },
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 10,
          },
          grid: { display: false },
        },
        y: {
          position: 'left',
          ticks: {
            color: '#64748b',
            font: { size: 10 },
            callback: (v) => '₹' + (v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v),
          },
          grid: { color: 'rgba(255,255,255,0.04)' },
        },
        y1: {
          position: 'right',
          ticks: {
            color: '#a855f780',
            font: { size: 10 },
            callback: (v) => '₹' + (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v),
          },
          grid: { display: false },
        },
      },
    },
  });
}

// ═══════════════════════════════════════════
// Phase 5: Recurring Payments
// ═══════════════════════════════════════════

function renderRecurringPayments(recurring) {
  const list = document.getElementById('recurring-list');
  if (!list) return;

  if (!recurring || recurring.length === 0) {
    list.innerHTML = '<li class="empty-state"><p>No recurring payments detected yet</p></li>';
    return;
  }

  list.innerHTML = recurring.map(r => {
    const initial = (r.merchant || '?')[0].toUpperCase();
    return `
      <li class="recurring-item">
        <div class="recurring-icon">${initial}</div>
        <div class="recurring-info">
          <div class="recurring-name">${r.merchant}</div>
          <div class="recurring-detail">${r.occurrences} occurrences • consistent amount</div>
        </div>
        <div class="recurring-amount">~₹${r.avg_amount.toLocaleString('en-IN')}/mo</div>
      </li>
    `;
  }).join('');
}

// ═══════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════

function formatCurrency(num) {
  if (Math.abs(num) >= 100000) {
    return '₹' + (num / 100000).toFixed(1) + 'L';
  }
  return '₹' + Math.round(num).toLocaleString('en-IN');
}

function updateEmailCount(count) {
  const el = document.getElementById('email-count');
  if (el) el.textContent = count;
}

// ═══════════════════════════════════════════
// Phase 6: CSV Export & Monthly Report
// ═══════════════════════════════════════════

function exportCSV() {
  const url = `${API}/reports/export/csv?user_id=${USER_ID}&month=${currentMonth}&year=${currentYear}`;
  // Trigger browser download
  const a = document.createElement('a');
  a.href = url;
  a.download = `pfis_${currentYear}-${String(currentMonth).padStart(2, '0')}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  showToast('CSV download started', 'success');
}

function openReport() {
  const url = `${API}/reports/monthly?user_id=${USER_ID}&month=${currentMonth}&year=${currentYear}`;
  window.open(url, '_blank');
  showToast('Report opened in new tab', 'info');
}

// ═══════════════════════════════════════════
// Phase 6: Budget Tracker
// ═══════════════════════════════════════════

function renderBudgetTracker(budgets) {
  const grid = document.getElementById('budget-grid');
  if (!grid) return;

  if (!budgets || budgets.length === 0) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1/-1;">
        <div class="empty-icon">💰</div>
        <h3>No budgets set</h3>
        <p>Click "Set Budget" to create monthly spending limits per category</p>
      </div>
    `;
    return;
  }

  grid.innerHTML = budgets.map(b => {
    const fillWidth = Math.min(b.usage_pct, 100);
    const statusLabel = b.status === 'over' ? 'Over Budget' : b.status === 'warning' ? 'Warning' : 'On Track';
    const remainText = b.remaining >= 0
      ? `₹${b.remaining.toLocaleString('en-IN')} left`
      : `₹${Math.abs(b.remaining).toLocaleString('en-IN')} over`;

    return `
      <div class="budget-item">
        <div class="budget-item-header">
          <span class="budget-cat-name">${b.category_icon || '📦'} ${b.category_name}</span>
          <button class="budget-delete" onclick="deleteBudget('${b.id}')" title="Remove budget">✕</button>
        </div>
        <div class="budget-amounts">
          <span class="actual">₹${b.actual_spend.toLocaleString('en-IN')} spent</span>
          <span>of ₹${b.monthly_limit.toLocaleString('en-IN')}</span>
        </div>
        <div class="budget-bar">
          <div class="budget-fill status-${b.status}" style="width:${fillWidth}%"></div>
        </div>
        <div class="budget-footer">
          <span style="color:var(--text-muted)">${remainText}</span>
          <span class="budget-status ${b.status}">${statusLabel}</span>
        </div>
      </div>
    `;
  }).join('');
}

function openBudgetModal() {
  const select = document.getElementById('budget-category');
  select.innerHTML = '<option value="">— Select —</option>';
  CATEGORIES.forEach(c => {
    select.innerHTML += `<option value="${c.id}">${c.icon || ''} ${c.name}</option>`;
  });
  document.getElementById('budget-limit').value = '';
  document.getElementById('budget-modal').style.display = '';
}

function closeBudgetModal() {
  document.getElementById('budget-modal').style.display = 'none';
}

async function saveBudget() {
  const categoryId = document.getElementById('budget-category').value;
  const limit = parseFloat(document.getElementById('budget-limit').value);

  if (!categoryId || !limit || limit <= 0) {
    showToast('Please select a category and enter a valid limit', 'error');
    return;
  }

  try {
    await apiPost(`/budgets/?user_id=${USER_ID}`, {
      category_id: categoryId,
      monthly_limit: limit,
    });
    showToast('Budget created!', 'success');
    closeBudgetModal();
    await refreshDashboard();
  } catch (e) {
    if (e.message.includes('409')) {
      showToast('Budget already exists for this category', 'error');
    } else {
      showToast('Failed to create budget: ' + e.message, 'error');
    }
  }
}

async function deleteBudget(budgetId) {
  if (!confirm('Remove this budget?')) return;
  try {
    await apiDelete(`/budgets/${budgetId}`);
    showToast('Budget removed', 'success');
    await refreshDashboard();
  } catch (e) {
    showToast('Failed to remove: ' + e.message, 'error');
  }
}

// Close budget modal on backdrop click and escape
document.addEventListener('click', (e) => {
  if (e.target.id === 'budget-modal') closeBudgetModal();
});

function showLoading(show) {
  // Future: add skeleton loading
}

// ═══════════════════════════════════════════
// Toast Notifications
// ═══════════════════════════════════════════

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️'}</span>
    <span>${message}</span>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
