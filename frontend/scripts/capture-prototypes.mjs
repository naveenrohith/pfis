import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

const baseUrl = process.env.PFIS_PROTOTYPE_URL ?? 'http://127.0.0.1:4174/dashboard/prototype.html';
const outputDirectory = resolve(process.cwd(), '../docs/prototypes/experience');
const screens = ['today', 'activity', 'review', 'plan', 'insights', 'data'];
const viewports = [
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'mobile', width: 390, height: 844 },
];

await mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch();

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      deviceScaleFactor: 1,
      reducedMotion: 'reduce',
    });
    const page = await context.newPage();

    for (const screen of screens) {
      await page.goto(`${baseUrl}?screen=${screen}#${screen}`, { waitUntil: 'networkidle' });
      await page.screenshot({
        path: resolve(outputDirectory, `${screen}-${viewport.name}.png`),
        fullPage: true,
      });
    }

    await context.close();
  }
} finally {
  await browser.close();
}
