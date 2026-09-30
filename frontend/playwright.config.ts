import { defineConfig, devices } from '@playwright/test';
import { join } from 'node:path';

const e2ePort = process.env.PFIS_E2E_PORT ?? '8000';
if (!/^\d{1,5}$/.test(e2ePort) || Number(e2ePort) > 65_535) {
  throw new Error('PFIS_E2E_PORT must be a valid TCP port');
}
const e2eServerUrl = `http://127.0.0.1:${e2ePort}`;
const reportDirectory = process.env.PFIS_E2E_REPORT_DIR ?? 'playwright-report';
const htmlReportDirectory = join(reportDirectory, 'html');
const outputDirectory = process.env.PFIS_E2E_OUTPUT_DIR ?? 'test-results';
const fullMode = process.env.PFIS_E2E_MODE === 'full';

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  retries: fullMode ? 1 : 0,
  failOnFlakyTests: true,
  timeout: 30_000,
  outputDir: outputDirectory,
  reporter: [
    ['html', { outputFolder: htmlReportDirectory, open: 'never' }],
    ['junit', { outputFile: join(reportDirectory, 'junit.xml') }],
    ['json', { outputFile: join(reportDirectory, 'results.json') }],
  ],
  expect: { timeout: 8_000, toHaveScreenshot: { maxDiffPixelRatio: 0.02 } },
  use: {
    baseURL: process.env.PFIS_E2E_BASE_URL ?? `${e2eServerUrl}/dashboard`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: undefined,
  projects: [
    { name: 'mobile-360', use: { ...devices['Desktop Chrome'], colorScheme: 'light', viewport: { width: 360, height: 800 } } },
    { name: 'tablet-768', use: { ...devices['Desktop Chrome'], colorScheme: 'light', viewport: { width: 768, height: 1024 } } },
    { name: 'desktop', use: { ...devices['Desktop Chrome'], colorScheme: 'light', viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile-360-dark', use: { ...devices['Desktop Chrome'], colorScheme: 'dark', viewport: { width: 360, height: 800 } } },
    { name: 'tablet-768-dark', use: { ...devices['Desktop Chrome'], colorScheme: 'dark', viewport: { width: 768, height: 1024 } } },
    { name: 'desktop-dark', use: { ...devices['Desktop Chrome'], colorScheme: 'dark', viewport: { width: 1440, height: 1000 } } },
  ],
});
