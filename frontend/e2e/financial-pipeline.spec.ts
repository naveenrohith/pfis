import { expect, test } from '@playwright/test';
import { openFixturePage, fixtureBaseUrl } from './e2e-helpers';

interface TransactionRecord {
  id: string;
  amount: number;
  currency: string;
  transaction_type: string;
  merchant_raw: string | null;
  merchant_normalized: string | null;
  transaction_date: string;
  account_last4: string | null;
  reviewed_flag: boolean;
}

interface JobRecord {
  status: string;
  result: {
    sync?: {
      emails_fetched?: number;
      emails_stored?: number;
      emails_skipped_duplicate?: number;
      emails_skipped_otp?: number;
      emails_skipped_promo?: number;
    };
    pipeline?: {
      stored?: number;
      duplicates?: number;
      parsed_failed?: number;
      results?: unknown[];
    };
  };
}

test('authenticated inbox sync persists the pipeline result and reviewed correction @smoke @pipeline', async ({
  browser,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'This pipeline mutation runs once on desktop.');
  test.setTimeout(90_000);
  const { context, page, profile } = await openFixturePage(browser, 'pipeline');
  const baseUrl = fixtureBaseUrl();
  try {
    await page.goto('/dashboard/#review');
    await expect(page.getByRole('button', { name: 'Sync inbox' })).toBeVisible();

    const enqueueResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/api/jobs/demo-sync-pipeline',
    );
    await page.getByRole('button', { name: 'Sync inbox' }).click();
    const queued = await enqueueResponse;
    expect(queued.status()).toBe(202);
    const queuedJob = (await queued.json()) as { id: string };

    let completedJob: JobRecord | undefined;
    await expect
      .poll(
        async () => {
          const response = await page.request.get(`${baseUrl}/api/jobs/${queuedJob.id}`);
          expect(response.ok()).toBe(true);
          completedJob = (await response.json()) as JobRecord;
          return completedJob.status;
        },
        { timeout: 45_000, intervals: [200, 400, 800, 1_000] },
      )
      .toBe('completed');

    expect(completedJob?.result.sync?.emails_fetched).toBe(15);
    expect(completedJob?.result.sync?.emails_stored).toBe(12);
    expect(completedJob?.result.sync?.emails_skipped_duplicate).toBe(1);
    expect(completedJob?.result.sync?.emails_skipped_otp).toBe(1);
    expect(completedJob?.result.sync?.emails_skipped_promo).toBe(1);
    expect(completedJob?.result.pipeline?.stored).toBe(13);
    expect(completedJob?.result.pipeline?.duplicates).toBe(0);
    expect(completedJob?.result.pipeline?.parsed_failed).toBe(0);

    const listUrl = new URL('/api/transactions/', baseUrl);
    listUrl.searchParams.set('user_id', profile.user_id);
    listUrl.searchParams.set('limit', '200');
    const transactionResponse = await page.request.get(listUrl.toString());
    expect(
      transactionResponse.ok(),
      `${transactionResponse.status()}: ${await transactionResponse.text()}`,
    ).toBe(true);
    const transactions = (await transactionResponse.json()) as TransactionRecord[];
    const expected = profile.expected ?? {};
    const sourceTransaction = transactions.find(
      (transaction) =>
        transaction.amount === Number(expected.amount) &&
        transaction.transaction_date === profile.financial_day &&
        transaction.merchant_raw === expected.merchant_raw,
    );
    expect(transactions).toHaveLength(Number(expected.stored_transaction_count));
    expect(
      transactions.reduce((sum, transaction) => sum + Number(transaction.amount), 0).toFixed(2),
    ).toBe(String(expected.gross_ledger_amount));
    expect(sourceTransaction).toMatchObject({
      amount: Number(expected.amount),
      currency: expected.currency,
      transaction_type: expected.transaction_type,
      transaction_date: profile.financial_day,
      account_last4: expected.account_last4,
      reviewed_flag: false,
    });

    await page.goto('/dashboard/#review');
    const reviewButton = page.getByRole('button', { name: /₹450 80%/ });
    await expect(reviewButton).toBeVisible();
    await reviewButton.click();
    await page.getByLabel('Merchant', { exact: true }).fill('PFIS E2E Grocery');
    await page.getByRole('button', { name: 'Save & next' }).click();
    await expect(page.getByText('Transaction saved')).toBeVisible();

    await page.goto('/dashboard/#transactions');
    await expect(page.getByRole('row', { name: /Review transaction PFIS E2E Grocery/ })).toBeVisible();
    await page.reload();
    const savedResponse = await page.request.get(
      `${baseUrl}/api/transactions/${sourceTransaction?.id}`,
    );
    expect(savedResponse.ok()).toBe(true);
    const saved = (await savedResponse.json()) as TransactionRecord;
    expect(saved).toMatchObject({
      amount: Number(expected.amount),
      transaction_type: expected.transaction_type,
      transaction_date: profile.financial_day,
      merchant_normalized: 'PFIS E2E Grocery',
      reviewed_flag: true,
    });
    await expect(page.getByRole('row', { name: /Review transaction PFIS E2E Grocery/ })).toBeVisible();

    await testInfo.attach('financial-pipeline-outcome.json', {
      body: JSON.stringify(
        {
          profile_user_id: profile.user_id,
          expected_source_count: expected.stored_source_count_after_sync,
          expected_sync_new_source_count: expected.sync_new_source_count,
          actual_sync_new_source_count: completedJob?.result.sync?.emails_stored,
          duplicate_source_count: completedJob?.result.sync?.emails_skipped_duplicate,
          expected_transaction_count: expected.stored_transaction_count,
          actual_transaction_count: transactions.length,
          expected_gross_ledger_amount: expected.gross_ledger_amount,
          actual_gross_ledger_amount: transactions
            .reduce((sum, transaction) => sum + Number(transaction.amount), 0)
            .toFixed(2),
          unresolved_pipeline_failures: completedJob?.result.pipeline?.parsed_failed,
          reviewed_transaction_id: saved.id,
        },
        null,
        2,
      ),
      contentType: 'application/json',
    });
  } finally {
    await context.close();
  }
});
