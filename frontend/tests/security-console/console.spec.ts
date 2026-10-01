import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

async function routeConsoleApi(page: import('@playwright/test').Page) {
  await page.route('**/security-api/session', async (route) => {
    await route.fulfill({ status: 401, json: { detail: 'Pairing required' } });
  });
  await page.route('**/security-api/pair', async (route) => {
    await route.fulfill({ json: { csrf_token: 'test-csrf-token', expires_in: '3600' } });
  });
  await page.route('**/security-api/lab', async (route) => {
    await route.fulfill({ json: {
      generation: '0123456789ab',
      project: 'pfis-security-0123456789ab',
      https_url: 'https://localhost:8443',
      synthetic_data: true,
      docker_context: 'desktop-linux',
      containers: [{ Names: 'pfis-security-0123456789ab-proxy-1', Status: 'Up' }],
      scanner_network_internal: true,
    } });
  });
  await page.route('**/security-api/tools', async (route) => {
    await route.fulfill({ json: { tools: [
      { id: 'nmap', version: '7.97', image: 'pinned', capabilities: ['ports'], digest_pinned: true, ready: true, status: 'ready', detail: '' },
    ] } });
  });
  await page.route('**/security-api/runs', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 202, json: { id: 'a'.repeat(32), profile: 'baseline', state: 'queued' } });
      return;
    }
    await route.fulfill({ json: [] });
  });
  await page.route('**/security-api/findings', async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route('**/security-api/reports', async (route) => {
    await route.fulfill({ json: [] });
  });
}

test('pairs through the local code and exposes the synthetic locked scope', async ({ page }) => {
  await routeConsoleApi(page);
  await page.goto('/');
  await page.getByLabel('Local pairing code').fill('123456');
  await page.getByRole('button', { name: 'Open local console' }).click();
  await expect(page.getByRole('heading', { name: 'Lab', exact: true })).toBeVisible();
  await expect(page.getByText('Scope is fixed to this disposable PFIS lab.')).toBeVisible();
  await expect(page.getByText('0123456789ab')).toBeVisible();
  await expect(page.getByText('scanner integrations ready')).toBeVisible();
});

test('keeps evidence as inert text and meets serious/critical accessibility checks', async ({ page }) => {
  await routeConsoleApi(page);
  await page.route('**/security-api/findings', async (route) => {
    await route.fulfill({ json: [{
      fingerprint: 'b'.repeat(64),
      title: '<img src=x onerror=alert(1)> finding',
      severity: 'high',
      confidence: 'high',
      target_id: 'pfis-web',
      endpoint: 'https://pfis.test/api/health',
      tool: 'zap',
      evidence: [{ tool: 'zap', value: '<script>localStorage.setItem("pwned","1")</script>', observed_at: '2026-09-30T00:00:00Z' }],
      reproduction: '',
      status: 'candidate',
      first_seen: '2026-09-30T00:00:00Z',
      last_seen: '2026-09-30T00:00:00Z',
    }] });
  });
  await page.goto('/');
  await page.getByLabel('Local pairing code').fill('123456');
  await page.getByRole('button', { name: 'Open local console' }).click();
  await page.getByRole('button', { name: /Findings/ }).click();
  await expect(page.getByText('<img src=x onerror=alert(1)> finding')).toBeVisible();
  await page.getByText('Evidence trail').click();
  await expect(page.locator('script:not([type="module"])')).toHaveCount(0);
  await expect(page.locator('img[src="x"][onerror]')).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('pwned'))).toBeNull();
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(results.violations.filter((violation) => ['critical', 'serious'].includes(violation.impact ?? ''))).toEqual([]);
});
