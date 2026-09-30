import { expect, test } from '@playwright/test';

test('Gmail statement picker searches and keeps PDF upload available', async ({ page }) => {
  const session = await page.request.post('/api/auth/demo');
  expect(session.ok()).toBe(true);
  await page.route(/\/api\/gmail\/auto-sync(?:\?.*)?$/, (route) =>
    route.fulfill({ json: { connection_status: 'connected' } }),
  );
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
  await page.route('**/api/statements/gmail/detect?**', async (route) => {
    await route.fulfill({
      json: {
        status:
          route.request().postDataJSON().password === 'test-password'
            ? 'detected'
            : 'password_required',
        detection:
          route.request().postDataJSON().password === 'test-password'
            ? {
                institution: 'hdfc',
                product_type: 'credit_card',
                support_status: 'recognized_not_supported',
              }
            : null,
        document_fingerprint: null,
      },
    });
  });
  await page.goto('/dashboard/#statements');
  await expect(page.getByRole('button', { name: 'From Gmail' })).toBeVisible();
  await page.getByRole('button', { name: 'From Gmail' }).click();
  await expect(page.getByRole('heading', { name: 'Find a statement in Gmail' })).toBeVisible();
  await page.getByRole('button', { name: 'Search Gmail' }).click();
  await page.getByRole('button', { name: /statement\.pdf/ }).click();
  await page.getByLabel('PDF password').fill('test-password');
  await page.getByRole('button', { name: 'Unlock and detect' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'read-only' })).toBeVisible();
  await page.getByRole('button', { name: 'Upload PDF' }).click();
  await expect(page.getByLabel('Digital PDF')).toBeVisible();
});
