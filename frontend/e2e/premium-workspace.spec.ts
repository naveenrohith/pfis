import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

let demoCookies: Awaited<
  ReturnType<import('@playwright/test').APIRequestContext['storageState']>
>['cookies'] = [];

test.beforeAll(async ({ request }) => {
  const response = await request.post('/api/auth/demo');
  expect(response.ok()).toBe(true);
  demoCookies = (await request.storageState()).cookies;
});

async function openDemoWorkspace(page: import('@playwright/test').Page) {
  await page.clock.setFixedTime(new Date('2026-07-16T09:00:00+05:30'));
  await page.context().addCookies(demoCookies);
  await page.goto('/dashboard/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 20_000 });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
}

async function mockTodayVisualData(page: import('@playwright/test').Page) {
  await page.route(/\/api\/dashboard\/workspace(?:\?.*)?$/, async (route) => {
    const response = await route.fetch();
    const data = (await response.json()) as import('../src/lib/types').WorkspaceResponse;
    await route.fulfill({
      response,
      json: {
        ...data,
        snapshot: {
          ...data.snapshot,
          income: 0,
          spend: 0,
          savings: 0,
          net_cash_flow: 0,
          transaction_count: 0,
          review_count: 0,
          budget_risk_count: 0,
        },
        timeline: [],
        insights: [],
        recommendations: [],
        review_summary: {
          ...data.review_summary,
          pending_count: 0,
          low_confidence_count: 0,
        },
        projection: {
          ...data.projection,
          income: 0,
          spend_to_date: 0,
          net_to_date: 0,
          projected_spend: 0,
          projected_net: 0,
          daily_spend_rate: 0,
          recurring_commitments: 0,
          confirmed_commitments: 0,
          expected_income: 0,
          flexible_spend_projection: 0,
          budgeted_remaining: 0,
          projected_range_low: 0,
          projected_range_high: 0,
        },
        month_comparison: {
          ...data.month_comparison,
          income: 0,
          previous_income: 0,
          spend: 0,
          previous_spend: 0,
          savings: 0,
          previous_savings: 0,
          spend_change_pct: null,
          income_change_pct: null,
          category_deltas: [],
        },
        financial_health: {
          ...data.financial_health,
          data_sufficiency: 'low',
          recurring_burden: 0,
          signals: [],
        },
        recurring_commitments: [],
      },
    });
  });
  await page.route('**/api/cash-plan*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        primary_financial_account_id: 'e2e-cash-plan-account',
        currency: 'INR',
        verified_balance: null,
        balance_as_of: null,
        next_income_date: null,
        confirmed_commitments: [],
        commitment_total: 0,
        approved_reserve_total: 0,
        flexible_money: null,
        daily_allowance: null,
        readiness: 'needs_verified_balance',
        assumptions: ['A recent observed balance is required.'],
      }),
    }),
  );
  await page.route(/\/api\/guidance\/decisions(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
}

async function mockPositionVisualData(
  page: import('@playwright/test').Page,
  includeCard = true,
) {
  const liabilities = includeCard ? 16599 : 0;
  const accountFixtures = [
    {
      id: 'e2e-position-bank',
      user_id: 'e2e-user',
      institution_name: 'Example Bank',
      account_type: 'bank',
      balance_kind: 'asset',
      masked_number: '***1234',
      currency: 'INR',
      is_active: true,
      identity_status: 'confirmed',
      latest_balance: 43362,
      balance_as_of: '2026-07-15',
      created_at: '2026-07-01T00:00:00Z',
    },
    {
      id: 'e2e-position-card',
      user_id: 'e2e-user',
      institution_name: 'Example Card',
      account_type: 'credit_card',
      balance_kind: 'liability',
      masked_number: '***4349',
      currency: 'INR',
      is_active: true,
      identity_status: 'confirmed',
      latest_balance: 16599,
      balance_as_of: '2026-07-15',
      created_at: '2026-07-01T00:00:00Z',
    },
  ].filter((account) => includeCard || account.account_type === 'bank');
  await page.route('**/api/accounts?*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(accountFixtures),
    }),
  );
  await page.route('**/api/net-worth*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        currency: 'INR',
        as_of: '2026-07-15',
        assets: 43362,
        liabilities,
        net_worth: 43362 - liabilities,
        current_position_status: 'observed',
        current_position_as_of: '2026-07-15',
        current_position_confidence: 1,
        current_position_reason_codes: [],
        points: includeCard
          ? [
              { date: '2026-05-15', assets: 40100, liabilities: 18300, net_worth: 21800 },
              { date: '2026-06-15', assets: 41840, liabilities: 17120, net_worth: 24720 },
              { date: '2026-07-15', assets: 43362, liabilities, net_worth: 43362 - liabilities },
            ]
          : [
              { date: '2026-05-15', assets: 40100, liabilities: 0, net_worth: 40100 },
              { date: '2026-06-15', assets: 41840, liabilities: 0, net_worth: 41840 },
              { date: '2026-07-15', assets: 43362, liabilities: 0, net_worth: 43362 },
            ],
      }),
    }),
  );
  await page.route('**/api/balance-provider/status*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        schema_version: 'e2e',
        status: 'not_configured',
        refresh_supported: false,
        consent_required: true,
        account_count: 0,
        mapped_account_count: 0,
        reason_codes: [],
        next_step: 'Provider refresh is not configured.',
        accounts: [],
      }),
    }),
  );
}

async function mockCardVisualData(page: import('@playwright/test').Page) {
  const cardId = 'e2e-card';
  const days = [
    { date: '2026-07-16', balance: 16599, low: 16300, high: 16950 },
    { date: '2026-07-20', balance: 17200, low: 16500, high: 17900 },
    { date: '2026-07-24', balance: 18400, low: 17100, high: 19800 },
    { date: '2026-07-28', balance: 19200, low: 17500, high: 21400 },
    { date: '2026-08-02', balance: 20100, low: 17800, high: 22800 },
    { date: '2026-08-10', balance: 21800, low: 18400, high: 26000 },
  ];
  const projection = {
    status: 'available',
    as_of: '2026-07-16',
    projected_statement_date: '2026-08-10',
    projected_balance: 21800,
    range_low: 18400,
    range_high: 26000,
    projected_utilization_pct: 21.8,
    confidence: 0.78,
    next_state: 'monitor_cycle',
    target_status: 'under_target',
    target_headroom_amount: 8200,
    target_excess_amount: 0,
    target_breach_date: null,
    target_breach_days: null,
    credit_limit_status: 'under_limit',
    credit_limit_headroom_amount: 78200,
    credit_limit_excess_amount: 0,
    credit_limit_breach_date: null,
    credit_limit_breach_days: null,
    calibration: 'historical_blend',
    historical_sample_count: 4,
    seasonal_sample_count: 0,
    seasonal_days_covered: 0,
    known_future_payment_total: 0,
    known_future_charge_total: 0,
    known_future_recurring_charge_total: 0,
    potential_pending_refund_total: 0,
    recurring_charge_candidates: [],
    daily_path: days.map((point, index) => ({
      date: point.date,
      days_from_today: index * 4,
      projected_balance: point.balance,
      range_low: point.low,
      range_high: point.high,
      projected_utilization_pct: point.balance / 1000,
      target_status: 'under_target',
      credit_limit_status: 'under_limit',
      event_amount: 0,
      event_labels: [],
    })),
    reason_codes: [],
    evidence: [
      { label: 'Statement basis', value: 'Issuer statement · 10 Jul 2026', basis: 'observed' },
      { label: 'Current anchor', value: 'Observed 16 Jul 2026', basis: 'observed' },
    ],
    ruleset_version: 'e2e-card-projection-1',
  };

  await page.route('**/api/accounts/e2e-card/balance-forecast*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        financial_account_id: cardId,
        account_type: 'credit_card',
        institution_name: 'HDFC Bank',
        masked_number: '***4349',
        currency: 'INR',
        balance_kind: 'liability',
        status: 'needs_anchor',
        horizon_start: '2026-07-16',
        horizon_end: '2026-08-15',
        horizon_days: 30,
        starting_balance: null,
        starting_balance_as_of: null,
        starting_balance_basis: null,
        expected_ending_balance: null,
        expected_change: null,
        lowest_expected_balance: null,
        lowest_expected_date: null,
        first_shortfall_date: null,
        scheduled_increase_total: 0,
        scheduled_decrease_total: 0,
        baseline_increase_total: 0,
        baseline_decrease_total: 0,
        event_count: 0,
        historical_days: 0,
        historical_activity_count: 0,
        coverage_status: 'unknown',
        position_status: 'needs_observation',
        position_confidence: 0,
        confidence: 0,
        data_sufficiency: 'low',
        position_reason_codes: ['needs_observed_balance'],
        assumptions: [],
        evidence: [],
        points: [],
        ruleset_version: 'e2e-account-balance-forecast-1',
      }),
    }),
  );
  await page.route('**/api/accounts?*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: cardId,
          user_id: 'e2e-user',
          institution_name: 'HDFC Bank',
          account_type: 'credit_card',
          balance_kind: 'liability',
          masked_number: '***4349',
          currency: 'INR',
          is_active: true,
          identity_status: 'confirmed',
          latest_balance: 16599,
          balance_as_of: '2026-07-16',
          created_at: '2026-07-01T00:00:00Z',
        },
      ]),
    }),
  );
  await page.route(`**/api/cards/${cardId}?*`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        financial_account_id: cardId,
        currency: 'INR',
        latest_statement_id: 'e2e-statement',
        statement_date: '2026-07-10',
        period_start: '2026-06-11',
        period_end: '2026-07-10',
        total_due: 16599,
        billed_total_due: 16599,
        billed_total_due_as_of: '2026-07-10',
        paid_since_statement: 0,
        unbilled_activity: 0,
        minimum_due: 7317,
        due_date: '2026-07-25',
        credit_limit: 100000,
        provider_credit_limit: 200000,
        provider_current_outstanding: null,
        estimated_current_balance: 16599,
        estimated_current_as_of: '2026-07-16',
        pending_increase: 0,
        coverage_complete: true,
        coverage_status: 'fresh',
        estimated_utilization_pct: 16.6,
        balance_status: 'estimated',
        balance_confidence: 0.78,
        balance_reason_codes: [],
        statement_utilization_pct: 16.6,
        utilization_target_pct: 30,
        next_statement_projection: projection,
        refund_tracker: {
          status: 'clear',
          as_of: '2026-07-16',
          horizon_days: 30,
          pending_count: 0,
          pending_amount: 0,
          posted_count_90d: 1,
          posted_amount_90d: 499,
          needs_review_count: 0,
          reason_codes: [],
          evidence: [],
          ruleset_version: 'e2e-refund-1',
        },
        reward_rules: [],
        coverage: { matched: 0, newly_imported: 0, ignored_by_rule: 0, needs_review: 0 },
        statement_lines: [],
        statement_history: [
          {
            id: 'e2e-statement',
            statement_date: '2026-07-10',
            period_start: '2026-06-11',
            period_end: '2026-07-10',
            due_date: '2026-07-25',
            total_due: 16599,
            minimum_due: 7317,
            line_count: 6,
            needs_review_count: 0,
          },
        ],
        planned_payments: [],
        calendar: [],
        activity_signals: [],
      }),
    }),
  );
  await page.route(`**/api/cards/${cardId}/utilization-history*`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        financial_account_id: cardId,
        as_of: '2026-07-16',
        utilization_target_pct: 30,
        statement_points: [
          {
            as_of: '2026-05-10',
            basis: 'issuer_statement',
            statement_id: 'e2e-statement-may',
            balance: 22100,
            credit_limit: 100000,
            utilization_pct: 22.1,
            status: 'within_target',
            source_transaction_count: 8,
            confidence: 1,
            reason_codes: [],
          },
          {
            as_of: '2026-06-10',
            basis: 'issuer_statement',
            statement_id: 'e2e-statement-jun',
            balance: 18800,
            credit_limit: 100000,
            utilization_pct: 18.8,
            status: 'within_target',
            source_transaction_count: 7,
            confidence: 1,
            reason_codes: [],
          },
        ],
        daily_points: [
          {
            as_of: '2026-07-10',
            basis: 'ledger_estimate',
            balance: 16599,
            credit_limit: 100000,
            utilization_pct: 16.6,
            status: 'within_target',
            source_transaction_count: 6,
            confidence: 0.78,
            reason_codes: [],
          },
          {
            as_of: '2026-07-16',
            basis: 'ledger_estimate',
            balance: 17600,
            credit_limit: 100000,
            utilization_pct: 17.6,
            status: 'within_target',
            source_transaction_count: 8,
            confidence: 0.78,
            reason_codes: [],
          },
        ],
        trend: 'improving',
        trend_basis: 'issuer_to_current_estimate',
        trend_delta_pct: -4.5,
        peak_statement_utilization_pct: 22.1,
        peak_daily_utilization_pct: 17.6,
        target_breach_count: 0,
        credit_limit_breach_count: 0,
        reason_codes: [],
        assumptions: [],
        ruleset_version: 'e2e-card-history-1',
      }),
    }),
  );
  await page.route(`**/api/cards/${cardId}/due-runway*`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        financial_account_id: cardId,
        currency: 'INR',
        status: 'needs_payment_account',
        statement_date: '2026-07-10',
        due_date: '2026-07-25',
        days_until_due: 9,
        total_due: 16599,
        minimum_due: 7317,
        estimated_current_outstanding: 16599,
        credit_limit: 100000,
        issuer_available_credit_limit: 83401,
        funding_account_id: null,
        funding_account_label: null,
        funding_balance_basis: null,
        funding_balance_as_of: null,
        funding_position_status: null,
        funding_balance_before_due_expected: null,
        funding_balance_before_due_low: null,
        funding_balance_before_due_high: null,
        expected_balance_after_total_due: null,
        expected_cash_gap: null,
        lower_band_cash_gap: null,
        planned_payment_total: 0,
        expected_total_due_covered: null,
        lower_band_total_due_covered: null,
        minimum_due_covered_on_lower_band: null,
        payment_scenarios: [],
        confidence: 0,
        position_reason_codes: [],
        evidence: [],
        assumptions: [],
        ruleset_version: 'e2e-due-runway-1',
      }),
    }),
  );
  await page.route(`**/api/cards/${cardId}/disputes*`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
}

async function mockInsightsVisualData(page: import('@playwright/test').Page) {
  await page.route(/\/api\/dashboard\/workspace(?:\?.*)?$/, async (route) => {
    const response = await route.fetch();
    const data = (await response.json()) as import('../src/lib/types').WorkspaceResponse;
    await route.fulfill({
      response,
      json: {
        ...data,
        month_comparison: {
          ...data.month_comparison,
          spend_change_pct: null,
          income_change_pct: null,
          category_deltas: [],
        },
      },
    });
  });
  await page.route(/\/api\/transactions\/summary\?.*$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_income: 72000,
        total_spend: 14200,
        net: 57800,
        transaction_count: 6,
        category_breakdown: [
          { name: 'Groceries', total: 6100, count: 3 },
          { name: 'Transport', total: 4200, count: 2 },
        ],
        top_merchants: [],
      }),
    }),
  );
  await page.route(/\/api\/insights\/\?.*$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        insights: [],
        daily_trend: [
          { date: '01 Jul', day: 1, total: 1800, count: 1 },
          { date: '04 Jul', day: 4, total: 0, count: 0 },
          { date: '08 Jul', day: 8, total: 4200, count: 2 },
          { date: '12 Jul', day: 12, total: 2700, count: 1 },
          { date: '16 Jul', day: 16, total: 5500, count: 2 },
        ],
        recurring_payments: [],
        anomalies: [],
      }),
    }),
  );
  await page.route(/\/api\/merchants\/\?.*$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          merchant_key: 'corner-market',
          name: 'Corner Market',
          total_spend: 6100,
          transaction_count: 3,
          avg_spend: 2033,
          recurrence_likelihood: 0.08,
          recurrence_status: 'inactive',
          recurrence_confidence: 0.08,
          data_sufficiency: 'medium',
          latest_transaction_date: '2026-07-16',
        },
        {
          merchant_key: 'metro',
          name: 'Metro',
          total_spend: 4200,
          transaction_count: 2,
          avg_spend: 2100,
          recurrence_likelihood: 0,
          recurrence_status: 'inactive',
          recurrence_confidence: 0,
          data_sufficiency: 'low',
          latest_transaction_date: '2026-07-12',
        },
      ]),
    }),
  );
}

async function mockReviewWorkflowData(page: import('@playwright/test').Page) {
  const transactions = [
    {
      id: 'e2e-review-1',
      amount: 1250,
      currency: 'INR',
      transaction_type: 'debit',
      payment_method: 'upi',
      transaction_status: 'completed',
      transaction_date: '2026-07-15',
      merchant_raw: 'Green Market',
      merchant_normalized: 'Green Market',
      confidence_score: 0.48,
      reviewed_flag: false,
      tags: [],
    },
    {
      id: 'e2e-review-2',
      amount: 860,
      currency: 'INR',
      transaction_type: 'debit',
      payment_method: 'debit_card',
      transaction_status: 'completed',
      transaction_date: '2026-07-14',
      merchant_raw: 'North Stationery',
      merchant_normalized: 'North Stationery',
      confidence_score: 0.72,
      reviewed_flag: false,
      tags: [],
    },
  ];

  await page.route(/\/api\/transactions\/(?:\?.*)?$/, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(transactions),
    });
  });
  await page.route(/\/api\/transactions\/e2e-review-\d+$/, async (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    const transactionId = new URL(route.request().url()).pathname.split('/').at(-1);
    const transaction = transactions.find((item) => item.id === transactionId);
    if (!transaction) return route.fulfill({ status: 404, body: 'Transaction not found' });
    Object.assign(transaction, route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(transaction),
    });
  });
  await page.route(/\/api\/transactions\/e2e-review-\d+\/splits(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
  await page.route(/\/api\/transactions\/transfer-match-candidates(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
  await page.route(/\/api\/review\/statement-lines(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
  await page.route(/\/api\/accounts(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
  await page.route(/\/api\/categories\/(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
}

test('sign-in is responsive, consent-clear, and accessible', async ({ page }) => {
  await page.goto('/dashboard/');

  await expect(page.getByRole('link', { name: 'Continue with Google' })).toHaveAttribute(
    'href',
    '/api/auth/google/login',
  );
  await expect(page.locator('body')).toContainText('Identity only');
  await expect(page.locator('body')).toContainText('Read-only Gmail access');
  await expect(page.getByLabel('Email')).toHaveAttribute('autocomplete', 'username');
  await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute(
    'autocomplete',
    'current-password',
  );

  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((violation) =>
    ['serious', 'critical'].includes(violation.impact ?? ''),
  );
  expect(serious).toEqual([]);
  await expectNoHorizontalOverflow(page);
});

async function expectNoHorizontalOverflow(page: import('@playwright/test').Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

test('Today is keyboard reachable, responsive, and free of serious accessibility violations', async ({
  page,
}) => {
  await openDemoWorkspace(page);

  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.locator('main')).not.toContainText('You have kept ₹0');
  const viewport = page.viewportSize();
  if (viewport && viewport.width < 768) {
    const destinationNav = page.getByRole('navigation', { name: 'Primary financial destinations' });
    const quickAdd = page.getByRole('button', { name: 'Quick add activity' });
    const safeToSpendAction = page
      .getByRole('button', { name: /Review Safe to spend/i })
      .first();
    const navBox = await destinationNav.boundingBox();
    const addBox = await quickAdd.boundingBox();
    expect(navBox).not.toBeNull();
    expect(addBox).not.toBeNull();
    expect(addBox!.y).toBeGreaterThanOrEqual(navBox!.y - 1);
    expect(addBox!.y + addBox!.height).toBeLessThanOrEqual(navBox!.y + navBox!.height + 1);
    await expect
      .poll(async () => {
        const actionBox = await safeToSpendAction.boundingBox();
        const currentNavBox = await destinationNav.boundingBox();
        return Boolean(
          actionBox && currentNavBox && actionBox.y + actionBox.height <= currentNavBox.y + 1,
        );
      })
      .toBe(true);

    await safeToSpendAction.focus();
    await expect
      .poll(async () => {
        const actionBox = await safeToSpendAction.boundingBox();
        const navBoxAfterFocus = await destinationNav.boundingBox();
        return Boolean(
          actionBox && navBoxAfterFocus && actionBox.y + actionBox.height <= navBoxAfterFocus.y + 1,
        );
      })
      .toBe(true);
  } else if (viewport && viewport.width < 1024) {
    const rail = page.getByTestId('workspace-rail');
    const quickAdd = page.getByRole('button', { name: 'Quick add activity' });
    const railBox = await rail.boundingBox();
    const addBox = await quickAdd.boundingBox();
    expect(railBox).not.toBeNull();
    expect(addBox).not.toBeNull();
    expect(railBox!.width).toBeLessThanOrEqual(100);
    expect(addBox!.x).toBeGreaterThanOrEqual(railBox!.x);
    expect(addBox!.x + addBox!.width).toBeLessThanOrEqual(railBox!.x + railBox!.width);
  }

  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+K' : 'Control+K');
  await expect(page.getByRole('dialog', { name: 'PFIS command palette' })).toBeVisible();
  await page.keyboard.press('Escape');

  const results = await new AxeBuilder({ page })
    .exclude('[data-recharts-tooltip-wrapper]')
    .analyze();
  const serious = results.violations.filter((violation) =>
    ['serious', 'critical'].includes(violation.impact ?? ''),
  );
  expect(serious).toEqual([]);
  await expectNoHorizontalOverflow(page);
});

test('Today visual baseline @visual', async ({ page }) => {
  await mockTodayVisualData(page);
  await openDemoWorkspace(page);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await expect(page).toHaveScreenshot('today-workspace.png', {
    animations: 'disabled',
    fullPage: true,
  });
});

test('Position visual baseline @visual', async ({ page }) => {
  await mockPositionVisualData(page);
  await openDemoWorkspace(page);
  await page.getByRole('button', { name: 'Plan', exact: true }).click();
  await page.getByRole('link', { name: /(?:Stand|Where do I stand)/ }).click();
  await expect(page.getByTestId('position-summary')).toBeVisible();
  const netWorthCurve = page.locator('[aria-label="Net-worth history"] .recharts-line-curve');
  await expect(netWorthCurve).toHaveCount(1);
  const curvePath = await netWorthCurve.getAttribute('d');
  expect(curvePath?.match(/C/g) ?? []).toHaveLength(2);
  await expectNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot('position-workspace.png', {
    animations: 'disabled',
    fullPage: true,
  });
});

test('Cards visual baselines @visual', async ({ page }) => {
  await mockCardVisualData(page);
  await page.clock.setFixedTime(new Date('2026-07-16T09:00:00+05:30'));
  await page.context().addCookies(demoCookies);
  await page.goto('/dashboard/#cards');
  await expect(page.getByRole('heading', { name: 'Card accounts', exact: true })).toBeVisible({
    timeout: 20_000,
  });

  const nowTab = page.getByRole('tab', { name: 'Now', exact: true });
  await expect(nowTab).toHaveAttribute('aria-selected', 'true');
  await expect(page).toHaveScreenshot('cards-now-workspace.png', {
    animations: 'disabled',
    fullPage: true,
  });

  await page.getByRole('tab', { name: 'Evidence', exact: true }).click();
  await expect(page.getByText('DAILY PATH TO STATEMENT CLOSE')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Where this outstanding could land' })).toBeVisible();
  await expect(page.getByText('Needs observed anchor')).toBeVisible();
  await expect(page.getByText(/Record a dated balance or connect an observation/)).toBeVisible();
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await expect(page).toHaveScreenshot('cards-evidence-workspace.png', {
    animations: 'disabled',
    fullPage: true,
  });
});

test('Insights visual baseline @visual', async ({ page }) => {
  await mockInsightsVisualData(page);
  await openDemoWorkspace(page);
  await page.getByRole('button', { name: 'Insights', exact: true }).click();
  await expect(page.getByText('MONTHLY INVESTIGATION')).toBeVisible({ timeout: 20_000 });
  const spendChart = page
    .locator('figure')
    .filter({ has: page.getByRole('heading', { name: 'Observed spend by day' }) });
  await expect(spendChart.locator('figcaption')).toContainText('1 Jul 2026 to 16 Jul 2026');
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await expect(page).toHaveScreenshot('insights-workspace.png', {
    animations: 'disabled',
    fullPage: true,
  });
});

test('Activity review visual baseline @visual', async ({ page }) => {
  await mockReviewWorkflowData(page);
  await openDemoWorkspace(page);
  await page.getByRole('button', { name: 'Activity', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Review 2 transactions' })).toBeVisible();
  await page.getByRole('tab', { name: /^Review/ }).click();
  await page.getByRole('button', { name: /Green Market/ }).click();
  await expect(page.getByLabel('Merchant')).toHaveValue('Green Market');
  await expectNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot('activity-review-workspace.png', {
    animations: 'disabled',
    fullPage: true,
  });
});

test('Data diagnostics visual baseline @visual', async ({ page }) => {
  await page.route(/\/api\/health\/ops(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'needs_repair',
        status_reasons: ['ledger_currency_needs_repair'],
        data_warnings: [],
      }),
    }),
  );
  await openDemoWorkspace(page);
  await page.getByRole('button', { name: 'Data & settings', exact: true }).click();
  await page.getByRole('tab', { name: 'Diagnostics', exact: true }).click();
  const serviceChecks = page.getByRole('region', { name: 'Service checks' });
  await expect(serviceChecks).toContainText(/operator repair; self-service repair is not available/i);
  await expect(serviceChecks.getByRole('button')).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot('data-diagnostics-workspace.png', {
    animations: 'disabled',
    fullPage: true,
  });
});

test('all five destinations and their primary tabs are deep-linkable', async ({ page }) => {
  await openDemoWorkspace(page);

  await page.getByRole('button', { name: 'Activity', exact: true }).click();
  await expect(page).toHaveURL(/#transactions$/);
  await page.getByRole('tab', { name: /^Review/ }).click();
  await expect(page).toHaveURL(/#review$/);

  await page.getByRole('button', { name: 'Plan', exact: true }).click();
  await expect(page).toHaveURL(/#cash-plan$/);
  await page.getByRole('link', { name: /(?:Stand|Where do I stand)/ }).click();
  await expect(page).toHaveURL(/#networth$/);

  await page.getByRole('button', { name: 'Insights', exact: true }).click();
  await expect(page).toHaveURL(/#insights$/);
  await page.getByRole('tab', { name: 'Categories', exact: true }).click();
  await expect(page).toHaveURL(/#categories$/);

  await page.getByRole('button', { name: 'Data & settings', exact: true }).click();
  await expect(page).toHaveURL(/#inbox$/);
  await page.getByRole('tab', { name: 'Diagnostics', exact: true }).click();
  await expect(page).toHaveURL(/#pipeline$/);
  await expectNoHorizontalOverflow(page);
});

test('Activity review keeps keyboard selection, correction, and next-item progress together', async ({
  page,
}) => {
  await mockReviewWorkflowData(page);
  await openDemoWorkspace(page);

  await page.getByRole('button', { name: 'Activity', exact: true }).click();
  await page.getByRole('tab', { name: /^Review/ }).click();

  const firstTransaction = page.getByRole('button', { name: /Green Market/ });
  await expect(firstTransaction).toBeVisible();
  await firstTransaction.focus();
  await page.keyboard.press('Enter');

  const detailHeading = page.getByRole('heading', { name: 'Transaction detail' });
  await expect(detailHeading).toBeFocused();
  await expect(page.getByLabel('Merchant')).toHaveValue('Green Market');
  await page.getByRole('button', { name: 'Save & next' }).click();
  await expect(page.getByLabel('Merchant')).toHaveValue('North Stationery');
  await expect(detailHeading).toBeFocused();
});

test('Data repair status is honest and disconnected Gmail offers Connect', async ({
  page,
}) => {
  await page.route(/\/api\/gmail\/auto-sync(?:\?.*)?$/, (route) =>
    route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not connected"}' }),
  );
  await page.route(/\/api\/health\/ops(?:\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'needs_repair',
        status_reasons: ['ledger_currency_needs_repair'],
        data_warnings: [],
      }),
    }),
  );
  await openDemoWorkspace(page);

  await page.getByRole('button', { name: 'Data & settings', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Connect Gmail' }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sync now' })).not.toBeVisible();
  await page.getByRole('tab', { name: 'Diagnostics', exact: true }).click();
  const serviceChecks = page.getByRole('region', { name: 'Service checks' });
  await expect(serviceChecks).toContainText(/operator repair; self-service repair is not available/i);
  await expect(serviceChecks.getByRole('button')).toHaveCount(0);
  await expect(page).toHaveURL(/#pipeline$/);
});

test('Safe-to-spend setup stays compact and keeps focused fields above mobile navigation', async ({
  page,
}) => {
  await page.route('**/api/accounts*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'e2e-cash-plan-account',
          user_id: 'e2e-user',
          institution_name: 'Example Bank',
          account_type: 'bank',
          balance_kind: 'asset',
          masked_number: '***1234',
          currency: 'INR',
          is_active: true,
          identity_status: 'confirmed',
          latest_balance: null,
          balance_as_of: null,
          created_at: '2026-07-01T00:00:00Z',
        },
      ]),
    }),
  );
  await page.route('**/api/cash-plan*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        primary_financial_account_id: 'e2e-cash-plan-account',
        currency: 'INR',
        verified_balance: null,
        balance_as_of: null,
        next_income_date: null,
        confirmed_commitments: [],
        commitment_total: 0,
        approved_reserve_total: 0,
        flexible_money: null,
        daily_allowance: null,
        readiness: 'needs_verified_balance',
        assumptions: ['A recent observed balance is required.'],
      }),
    }),
  );
  await openDemoWorkspace(page);
  await page.getByRole('button', { name: 'Plan', exact: true }).click();
  await expect(page).toHaveURL(/#cash-plan$/);

  const account = page.getByLabel('1. Primary bank account');
  const balanceStep = page.getByText('2. Recent observed balance', { exact: true });
  const incomeDate = page.getByLabel('3. Next confirmed income date');
  await expect(account).toBeVisible();
  await expect(balanceStep).toBeVisible();
  await expect(incomeDate).toBeVisible();

  const viewport = page.viewportSize();
  if (viewport && viewport.width >= 768) {
    const observedAmount = page.getByLabel('Observed amount');
    await expect(observedAmount).toBeVisible();
    await expect
      .poll(async () => {
        const balanceBox = await observedAmount.boundingBox();
        const incomeBox = await incomeDate.boundingBox();
        return balanceBox && incomeBox ? incomeBox.x - balanceBox.x : 0;
      })
      .toBeGreaterThan(160);
  }

  await incomeDate.focus();
  if (viewport && viewport.width < 768) {
    const destinationNav = page.getByRole('navigation', {
      name: 'Primary financial destinations',
    });
    await expect
      .poll(async () => {
        const inputBox = await incomeDate.boundingBox();
        const navBox = await destinationNav.boundingBox();
        return Boolean(inputBox && navBox && inputBox.y + inputBox.height <= navBox.y + 1);
      })
      .toBe(true);
  }
  await expectNoHorizontalOverflow(page);
});

test('Cards direct hash settles on a stable target across lazy loading', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-07-16T09:00:00+05:30'));
  await page.context().addCookies(demoCookies);
  const viewport = page.viewportSize();
  if (viewport) await page.setViewportSize({ width: viewport.width, height: 480 });
  await page.goto('/dashboard/#cards');

  await expect(page).toHaveURL(/#cards$/);
  const cardsHeading = page.getByRole('heading', { name: 'Card accounts', exact: true });
  await expect(cardsHeading).toBeVisible({ timeout: 20_000 });
  const anchor = page.locator('#cards');
  await expect(anchor).toBeVisible();

  const headerBottom = await page
    .getByRole('banner')
    .evaluate((element) => element.getBoundingClientRect().bottom);
  const viewportHeight = await page.evaluate(() => window.innerHeight);
  await expect
    .poll(() => anchor.evaluate((element) => element.getBoundingClientRect().top))
    .toBeGreaterThanOrEqual(headerBottom - 1);
  await expect
    .poll(() => cardsHeading.evaluate((element) => element.getBoundingClientRect().top))
    .toBeLessThan(viewportHeight);
});

test('financial roadmap workspaces are responsive, keyboard reachable, and accessible', async ({
  page,
}) => {
  await mockPositionVisualData(page, false);
  await openDemoWorkspace(page);

  await page.getByRole('button', { name: 'Plan', exact: true }).click();
  for (const step of [
    { name: /(?:Spend|Can I spend)/, url: /#cash-plan$/ },
    { name: /(?:Stand|Where do I stand)/, url: /#networth$/ },
    { name: /(?:Coming|What’s coming)/, url: /#obligations$/ },
    { name: /(?:Change|What could change)/, url: /#analytics$/ },
    { name: /(?:Protect|Protect & plan)/, url: /#budgets$/ },
  ]) {
    const tab = page.getByRole('link', { name: step.name });
    await tab.scrollIntoViewIfNeeded();
    await tab.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(step.url);
    await expect(tab).toHaveAttribute('aria-current', 'step');
    if (String(step.name).includes('Stand')) {
      await expect(
        page.getByRole('heading', { name: 'Your financial position', exact: true }),
      ).toBeVisible({ timeout: 20_000 });
      const positionSummary = page.locator('dl[aria-label="Account position summary"]');
      await expect(positionSummary).toBeVisible({ timeout: 20_000 });
      await expect(positionSummary).toContainText('Net worth');
      await expect(positionSummary).toContainText('Assets');
      await expect(positionSummary).toContainText('Liabilities');
    }
    const box = await tab.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    const placement = await tab.evaluate((element) => {
      const tabRect = element.getBoundingClientRect();
      const headerBottom = document.querySelector('header')?.getBoundingClientRect().bottom ?? 0;
      return { tabTop: tabRect.top, headerBottom };
    });
    expect(placement.tabTop).toBeGreaterThanOrEqual(placement.headerBottom - 1);
    await expectNoHorizontalOverflow(page);
  }

  await page.getByRole('link', { name: /(?:Coming|What’s coming)/ }).click();
  await expect(page).toHaveURL(/#obligations$/);
  await page.getByRole('button', { name: 'Card accounts', exact: true }).click();
  await expect(page).toHaveURL(/#cards$/);
  await page.goBack();
  await expect(page).toHaveURL(/#obligations$/);
  await page.getByRole('button', { name: 'Card accounts', exact: true }).click();
  await expect(page).toHaveURL(/#cards$/);
  await page.getByRole('link', { name: /(?:Coming|What’s coming)/ }).click();
  await expect(page).toHaveURL(/#obligations$/);
  await page.getByRole('button', { name: 'All liabilities', exact: true }).click();
  await expect(page).toHaveURL(/#liabilities$/);

  await page.getByRole('link', { name: /(?:Coming|What’s coming)/ }).click();
  await expect(page).toHaveURL(/#obligations$/);

  await page.getByRole('link', { name: /(?:Change|What could change)/ }).click();
  await expect(page).toHaveURL(/#analytics$/);
  await page.getByRole('button', { name: 'Budgets and spending limits' }).click();
  await expect(page).toHaveURL(/#budgets$/);
  await page.goBack();
  await expect(page).toHaveURL(/#analytics$/);
  await expect(page.getByRole('button', { name: 'Budgets and spending limits' })).toBeVisible();

  await page.getByRole('button', { name: 'Data & settings', exact: true }).click();
  const statementsTab = page.getByRole('tab', { name: 'Statements', exact: true });
  await statementsTab.scrollIntoViewIfNeeded();
  await statementsTab.focus();
  await page.keyboard.press('Enter');
  await expect(statementsTab).toHaveAttribute('aria-selected', 'true');
  await expect(page).toHaveURL(/#statements$/);
  await expect(page.locator('main')).toContainText('Extract, then delete');
  const statementsBox = await statementsTab.boundingBox();
  expect(statementsBox?.height ?? 0).toBeGreaterThanOrEqual(44);

  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((violation) =>
    ['serious', 'critical'].includes(violation.impact ?? ''),
  );
  expect(serious).toEqual([]);
  await expectNoHorizontalOverflow(page);
});

test('missing net-worth data stays unavailable instead of displaying zero', async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== 'desktop',
    'One browser project is sufficient to exercise the failed-position state',
  );
  await page.route('**/api/accounts*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'e2e-position-account',
          user_id: 'e2e-user',
          institution_name: 'Example Bank',
          account_type: 'bank',
          balance_kind: 'asset',
          masked_number: '***1234',
          currency: 'INR',
          is_active: true,
          identity_status: 'confirmed',
          latest_balance: 1000,
          balance_as_of: '2026-09-01',
          created_at: '2026-09-01T00:00:00Z',
        },
      ]),
    }),
  );
  let positionFailureServed = false;
  await page.route('**/api/net-worth*', (route) => {
    positionFailureServed = true;
    return route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Temporary position failure' }),
    });
  });
  await openDemoWorkspace(page);

  await page.getByRole('button', { name: 'Plan', exact: true }).click();
  await page.getByRole('link', { name: /(?:Stand|Where do I stand)/ }).click();
  await expect.poll(() => positionFailureServed).toBe(true);
  await expect(page.getByRole('alert')).toContainText('Position data is unavailable', {
    timeout: 20_000,
  });
  await expect(page.getByText('Unavailable', { exact: true })).toHaveCount(3);
  await expect(page.locator('main')).not.toContainText('Add your first balance');
});

test('reduced motion disables non-essential workspace animation', async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== 'desktop',
    'One browser project is sufficient for the CSS media-query contract',
  );
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await openDemoWorkspace(page);

  const motion = await page.locator('#overview').evaluate((element) => {
    const style = getComputedStyle(element);
    const toMilliseconds = (value: string) =>
      value.endsWith('ms') ? Number.parseFloat(value) : Number.parseFloat(value) * 1000;
    return {
      animationMs: toMilliseconds(style.animationDuration),
      scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
    };
  });
  expect(motion.animationMs).toBeLessThanOrEqual(0.01);
  expect(motion.scrollBehavior).toBe('auto');
});

test('scenario preview and briefing rhythm stay user controlled', async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name !== 'desktop',
    'One browser project is sufficient for deterministic persistence coverage',
  );
  await openDemoWorkspace(page);

  await page.getByRole('button', { name: 'Plan', exact: true }).click();
  await page.getByRole('link', { name: /(?:Change|What could change)/ }).click();
  await page.getByLabel('Add expected income', { exact: true }).fill('5000');
  await page.getByRole('button', { name: 'Preview change', exact: true }).click();
  const studio = page.getByRole('region', { name: 'Test one change before you commit to it.' });
  await expect(studio).toContainText('This scenario improves the month-end position by');
  await expect(studio).toContainText('₹5,000');

  await page.getByRole('button', { name: 'Data & settings', exact: true }).click();
  await page.getByRole('button', { name: 'Preferences', exact: true }).click();
  const cadence = page.getByLabel('Financial briefing rhythm');
  await cadence.selectOption('weekly');
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();

  await page.getByRole('button', { name: 'Preferences', exact: true }).click();
  await expect(page.getByLabel('Financial briefing rhythm')).toHaveValue('weekly');
  await page.getByLabel('Financial briefing rhythm').selectOption('daily');
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
});
