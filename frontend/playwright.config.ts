import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000, toHaveScreenshot: { maxDiffPixelRatio: 0.02 } },
  use: {
    baseURL: process.env.PFIS_E2E_BASE_URL ?? 'http://127.0.0.1:8000/dashboard',
    trace: 'retain-on-failure',
  },
  webServer: process.env.CI
    ? {
        command:
          'python -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8000',
        url: 'http://127.0.0.1:8000/api/health',
        reuseExistingServer: false,
        timeout: 120_000,
      }
    : undefined,
  projects: [
    { name: 'mobile-360', use: { ...devices['Desktop Chrome'], colorScheme: 'light', viewport: { width: 360, height: 800 } } },
    { name: 'tablet-768', use: { ...devices['Desktop Chrome'], colorScheme: 'light', viewport: { width: 768, height: 1024 } } },
    { name: 'desktop', use: { ...devices['Desktop Chrome'], colorScheme: 'light', viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile-360-dark', use: { ...devices['Desktop Chrome'], colorScheme: 'dark', viewport: { width: 360, height: 800 } } },
    { name: 'tablet-768-dark', use: { ...devices['Desktop Chrome'], colorScheme: 'dark', viewport: { width: 768, height: 1024 } } },
    { name: 'desktop-dark', use: { ...devices['Desktop Chrome'], colorScheme: 'dark', viewport: { width: 1440, height: 1000 } } },
  ],
});
