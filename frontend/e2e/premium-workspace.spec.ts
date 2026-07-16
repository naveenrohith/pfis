import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

async function openDemoWorkspace(page: import('@playwright/test').Page) {
  await page.goto('/dashboard/');
  const demo = page.getByRole('button', { name: 'Try demo workspace' });
  if (await demo.isVisible()) await demo.click();
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
}

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
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await expect(page).toHaveScreenshot('today-workspace.png', {
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
  await expect(page).toHaveURL(/#analytics$/);
  await page.getByRole('tab', { name: 'Position', exact: true }).click();
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
