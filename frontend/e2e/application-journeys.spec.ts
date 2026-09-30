import { expect, test } from '@playwright/test';
import {
  fixtureBaseUrl,
  getFixtureCredentials,
  openFixturePage,
} from './e2e-helpers';

interface TransactionRecord {
  id: string;
  amount: number;
  currency: string;
  transaction_type: string;
  merchant_normalized: string | null;
  transaction_date: string;
  reviewed_flag: boolean;
}

async function listTransactions(page: import('@playwright/test').Page, userId: string) {
  const url = new URL('/api/transactions/', fixtureBaseUrl());
  url.searchParams.set('user_id', userId);
  url.searchParams.set('limit', '200');
  const response = await page.request.get(url.toString());
  expect(response.ok(), `${response.status()}: ${await response.text()}`).toBe(true);
  return (await response.json()) as TransactionRecord[];
}

test('quick add saves a durable expense on the user financial day @smoke @journey @mobile', async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-360', 'This mutation is selected for mobile smoke.');
  const { context, page, profile } = await openFixturePage(browser, 'quick_add');
  const baseUrl = fixtureBaseUrl();
  try {
    await page.goto('/dashboard/#transactions');
    await expect(page.getByRole('heading', { name: 'Follow every movement of money.' })).toBeVisible();
    await page.getByRole('button', { name: 'Quick add activity' }).click();

    const dialog = page.getByRole('dialog', { name: 'Quick add' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Date')).toHaveValue(profile.financial_day);
    await dialog.getByLabel('Amount').fill('127.35');
    await dialog.getByLabel('Merchant').fill('PFIS E2E Coffee');
    await dialog.getByLabel('Payment method').selectOption('upi');
    await dialog.getByLabel('Account last four').fill('4242');
    await dialog.getByRole('button', { name: 'Add activity' }).click();
    await expect(page.getByText('Activity added')).toBeVisible();

    const query = new URL('/api/transactions/', baseUrl);
    query.searchParams.set('user_id', profile.user_id);
    query.searchParams.set('limit', '200');
    const findRecord = async () => {
      const response = await page.request.get(query.toString());
      expect(response.ok(), `${response.status()}: ${await response.text()}`).toBe(true);
      const transactions = (await response.json()) as TransactionRecord[];
      return transactions.find((transaction) => transaction.merchant_normalized === 'PFIS E2E Coffee');
    };
    let saved = await findRecord();
    await expect.poll(findRecord, { timeout: 15_000 }).toBeTruthy();
    saved = await findRecord();
    expect(saved).toMatchObject({
      amount: 127.35,
      currency: 'INR',
      transaction_type: 'debit',
      merchant_normalized: 'PFIS E2E Coffee',
      transaction_date: profile.financial_day,
      reviewed_flag: false,
    });

    const observer = await openFixturePage(browser, 'quick_add');
    try {
      await observer.page.goto('/dashboard/#transactions');
      await expect(
        observer.page.getByLabel('Search transactions by merchant, account, or reference'),
      ).toBeVisible();
      await observer.page
        .getByLabel('Search transactions by merchant, account, or reference')
        .fill('PFIS E2E Coffee');
      await expect(observer.page.getByRole('button', { name: /PFIS E2E Coffee/ }).first()).toBeVisible();
    } finally {
      await observer.context.close();
    }

    await page.reload();
    await expect(page.getByLabel('Search transactions by merchant, account, or reference')).toBeVisible();
    const persisted = await page.request.get(`${baseUrl}/api/transactions/${saved?.id}`);
    expect(persisted.ok()).toBe(true);
    expect(await persisted.json()).toMatchObject({
      amount: 127.35,
      transaction_date: profile.financial_day,
      merchant_normalized: 'PFIS E2E Coffee',
    });
  } finally {
    await context.close();
  }
});

test('account sessions reject bad passwords, restore registration, and sign out @smoke @journey', async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Auth workflow runs once on desktop.');
  const credentials = getFixtureCredentials('auth_flow');
  await page.goto('/dashboard/#transactions');
  await expect(page.getByRole('heading', { name: 'Open your financial workspace' })).toBeVisible();

  await page.getByLabel('Email').fill(credentials.email);
  await page.getByRole('textbox', { name: 'Password' }).fill(
    getFixtureCredentials('other_user').password,
  );
  await page.getByRole('button', { name: 'Sign in securely' }).click();
  await expect(page.getByRole('alert')).toContainText('Invalid email or password');

  const registeredEmail = `pfis-e2e-${testInfo.workerIndex}-${Date.now()}@example.com`;
  const registeredPassword = credentials.password;
  await page.getByRole('button', { name: 'Create a private workspace' }).click();
  await page.getByLabel('Name').fill('E2E Registration');
  await page.getByLabel('Email').fill(registeredEmail);
  await page.getByRole('textbox', { name: 'Password' }).fill(registeredPassword);
  await page.getByRole('button', { name: 'Create workspace' }).click();
  await expect(page.getByRole('button', { name: 'Quick add activity' })).toBeVisible();
  await expect(page).toHaveURL(/#transactions$/);

  await page.reload();
  await expect(page.getByRole('button', { name: 'Quick add activity' })).toBeVisible();
  await page.getByLabel('Open account menu').click();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Open your financial workspace' })).toBeVisible();

  const sessionResponse = await page.request.get(`${fixtureBaseUrl()}/api/auth/session`);
  expect(sessionResponse.status()).toBe(401);

  await page.getByLabel('Email').fill(registeredEmail);
  await page.getByRole('textbox', { name: 'Password' }).fill(registeredPassword);
  await page.getByRole('button', { name: 'Sign in securely' }).click();
  await expect(page.getByRole('button', { name: 'Quick add activity' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Quick add activity' })).toBeVisible();
});

test('financial APIs enforce ownership for authenticated browser sessions @smoke @journey', async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Ownership check runs once on desktop.');
  const owner = await openFixturePage(browser, 'owner');
  const other = await openFixturePage(browser, 'other_user');
  const baseUrl = fixtureBaseUrl();
  try {
    await owner.page.goto('/dashboard/');
    await other.page.goto('/dashboard/');
    const ownerData = await owner.page.request.get(
      `${baseUrl}/api/transactions/?user_id=${encodeURIComponent(owner.profile.user_id)}&limit=20`,
    );
    expect(ownerData.ok(), `${ownerData.status()}: ${await ownerData.text()}`).toBe(true);
    const crossUserRead = await owner.page.request.get(
      `${baseUrl}/api/transactions/?user_id=${encodeURIComponent(other.profile.user_id)}&limit=20`,
    );
    expect(crossUserRead.status()).toBe(403);
    const otherSessionRead = await other.page.request.get(
      `${baseUrl}/api/transactions/?user_id=${encodeURIComponent(owner.profile.user_id)}&limit=20`,
    );
    expect(otherSessionRead.status()).toBe(403);
  } finally {
    await owner.context.close();
    await other.context.close();
  }
});

test('budget changes persist while scenario previews leave the ledger untouched @smoke @journey @planning', async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Planning mutations run once on desktop.');
  const { context, page, profile } = await openFixturePage(browser, 'planning');
  try {
    await page.goto('/dashboard/#budgets');
    const createBudget = page.getByRole('button', { name: 'Create budget' });
    await expect(createBudget).toBeVisible();
    await createBudget.click();

    const dialog = page.getByRole('dialog', { name: 'Set budget' });
    const category = dialog.getByLabel('Category');
    await category.selectOption({ index: testInfo.retry + 1 });
    const categoryLabel = (await category.locator('option:checked').innerText()).trim();
    await dialog.getByLabel('Monthly limit').fill('2500');
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText('Budget created')).toBeVisible();
    await expect(page.getByText(/₹0 of ₹2,500/)).toBeVisible();

    await page.reload();
    await expect(page.getByRole('button', { name: 'Create budget' })).toBeVisible();
    await expect(page.getByText(categoryLabel, { exact: false }).first()).toBeVisible();
    await expect(page.getByText(/₹0 of ₹2,500/)).toBeVisible();

    await page.goto('/dashboard/#analytics');
    const ledgerBeforePreview = await listTransactions(page, profile.user_id);
    await page.getByLabel('Add expected income', { exact: true }).fill('5000');
    await page.getByRole('button', { name: 'Preview change', exact: true }).click();
    const preview = page.getByRole('region', {
      name: 'Test one change before you commit to it.',
    });
    await expect(preview).toContainText('This scenario improves the month-end position by');
    await expect(preview).toContainText('₹5,000');
    expect(await listTransactions(page, profile.user_id)).toHaveLength(ledgerBeforePreview.length);
  } finally {
    await context.close();
  }
});

test('unsupported statement uploads fail before changing the ledger @journey @statements', async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Statement upload runs once on desktop.');
  const { context, page, profile } = await openFixturePage(browser, 'statement');
  try {
    await page.goto('/dashboard/#statements');
    await expect(page.getByRole('heading', { name: 'Import a statement' })).toBeVisible();
    const before = await listTransactions(page, profile.user_id);

    await page.getByLabel('Digital PDF').setInputFiles({
      name: 'unsupported-statement.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('This file is not a PDF statement.'),
    });
    await expect(page.getByRole('alert')).toContainText('Upload a digital PDF statement');
    await expect(page.getByLabel('Matching financial account')).toBeDisabled();
    expect(await listTransactions(page, profile.user_id)).toHaveLength(before.length);
  } finally {
    await context.close();
  }
});

test('privacy changes require confirmation and deletion keeps its safeguards @journey @privacy', async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Privacy mutations run once on desktop.');
  const { context, page, profile } = await openFixturePage(browser, 'privacy');
  try {
    await page.goto('/dashboard/#settings');
    await expect(
      page.getByRole('heading', { name: 'Tune the workspace and control your data.' }),
    ).toBeVisible();

    const retention = page.getByRole('combobox', { name: 'Keep processed source content' });
    await expect(retention).toHaveText('1 year');
    await retention.click();
    await page.getByRole('option', { name: '90 days' }).click();
    await page.getByRole('button', { name: 'Save retention policy' }).click();
    const confirmation = page.getByRole('dialog', { name: 'Shorten source retention?' });
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole('button', { name: 'Keep current policy' }).click();
    await page.reload();
    await expect(
      page.getByRole('combobox', { name: 'Keep processed source content' }),
    ).toHaveText('1 year');

    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download portable copy' }).click();
    const portableCopy = await download;
    expect(portableCopy.suggestedFilename()).toMatch(/^pfis-portable-export-.*\.zip$/);

    await page.getByRole('button', { name: 'Delete my account' }).click();
    const deletion = page.getByRole('dialog', { name: 'Delete your account permanently?' });
    const deleteButton = deletion.getByRole('button', { name: 'Permanently delete account' });
    await expect(deleteButton).toBeDisabled();
    const entry = deletion.getByLabel(/Type DELETE/);
    await entry.fill(`DELETE ${profile.email.toUpperCase()}`);
    await expect(deleteButton).toBeDisabled();
    await entry.fill(`DELETE ${profile.email}`);
    await expect(deleteButton).toBeEnabled();
    await deletion.getByRole('button', { name: 'Keep my account' }).click();
    await expect(page.getByRole('heading', { name: 'Tune the workspace and control your data.' })).toBeVisible();

    const session = await page.request.get(`${fixtureBaseUrl()}/api/auth/session`);
    expect(session.ok()).toBe(true);
  } finally {
    await context.close();
  }
});
