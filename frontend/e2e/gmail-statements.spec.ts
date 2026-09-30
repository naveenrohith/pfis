import { expect, test } from '@playwright/test';

test('Gmail statement picker searches and keeps PDF upload available', async ({ page }) => {
  await page.route('**/api/statements/gmail/candidates**', async (route) => {
    await route.fulfill({
      json: {
        candidates: [
          {
            source_ref: 'e2e-ref',
            sender: 'alerts@example.com',
            subject: 'Statement',
            filename: 'statement.pdf',
            size_bytes: 1024,
            received_at: '2026-09-01T00:00:00Z',
          },
        ],
        next_cursor: null,
        coverage_complete: true,
        message_failures: 0,
        truncated: false,
      },
    });
  });
  await page.route('**/api/statements/gmail/detect', async (route) => {
    await route.fulfill({
      json: {
        status: 'detected',
        detection: {
          institution: 'hdfc',
          product_type: 'credit_card',
          support_status: 'supported',
        },
        document_fingerprint: 'e2e-fingerprint',
      },
    });
  });
  await page.goto('/dashboard/#statements');
  await expect(page.getByRole('button', { name: 'From Gmail' })).toBeVisible();
  await page.getByRole('button', { name: 'From Gmail' }).click();
  await expect(page.getByRole('heading', { name: 'Find a statement in Gmail' })).toBeVisible();
  await page.getByRole('button', { name: 'Upload PDF' }).click();
  await expect(page.getByLabel('Digital PDF')).toBeVisible();
});
