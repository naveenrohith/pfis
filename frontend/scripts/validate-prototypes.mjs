import AxeBuilder from '@axe-core/playwright';
import { chromium } from '@playwright/test';

const baseUrl = process.env.PFIS_PROTOTYPE_URL ?? 'http://127.0.0.1:4174/dashboard/prototype.html';
const screens = ['today', 'activity', 'review', 'plan', 'insights', 'data'];
const viewports = [
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'mobile', width: 390, height: 844 },
];

const browser = await chromium.launch();
const failures = [];

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      reducedMotion: 'reduce',
    });
    const page = await context.newPage();

    for (const screen of screens) {
      await page.goto(`${baseUrl}?audit=${screen}#${screen}`, { waitUntil: 'networkidle' });
      const horizontalOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      if (horizontalOverflow > 1) {
        const overflowTargets = await page.evaluate(() =>
          [...document.querySelectorAll('body *')]
            .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
            .slice(0, 5)
            .map((element) =>
              `${element.tagName.toLowerCase()}.${[...element.classList].slice(0, 3).join('.')}`,
            ),
        );
        failures.push(
          `${screen}/${viewport.name}: ${horizontalOverflow}px horizontal overflow; ${overflowTargets.join(', ')}`,
        );
      }

      const results = await new AxeBuilder({ page }).analyze();
      for (const violation of results.violations) {
        if (violation.impact === 'serious' || violation.impact === 'critical') {
          failures.push(
            `${screen}/${viewport.name}: ${violation.id} (${violation.impact}) - ${violation.help}; ${violation.nodes
              .slice(0, 4)
              .map((node) => node.target.join(' '))
              .join(', ')}`,
          );
        }
      }
    }

    await context.close();
  }
} finally {
  await browser.close();
}

if (failures.length > 0) {
  console.error(failures.join('\n'));
  process.exitCode = 1;
} else {
  console.log('Prototype validation passed for 6 screens at desktop and mobile widths.');
}
