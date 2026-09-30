import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Browser, BrowserContext, Page } from '@playwright/test';

export interface FixtureProfile {
  profile: string;
  user_id: string;
  email: string;
  storage_state: string;
  currency: string;
  session_mode: 'auth' | 'demo';
  financial_day: string;
  financial_period: { month: number; year: number };
  source_raw_email_id?: string;
  source_identity?: string;
  expected?: Record<string, unknown>;
}

interface FixtureManifest {
  run_id: string;
  database: string;
  base_url: string;
  profiles: Record<string, FixtureProfile>;
}

interface FixtureCredentials {
  [profile: string]: { email: string; password: string };
}

const runDirectory = process.env.PFIS_E2E_RUN_DIR;
if (!runDirectory) {
  throw new Error('PFIS_E2E_RUN_DIR must point to the authenticated E2E fixture run');
}

const storageDirectory = join(runDirectory, 'storage');
const manifest = JSON.parse(
  readFileSync(join(storageDirectory, 'manifest.json'), 'utf8'),
) as FixtureManifest;
const credentials = JSON.parse(
  readFileSync(join(storageDirectory, 'credentials.json'), 'utf8'),
) as FixtureCredentials;

export function getFixtureProfile(name: string): FixtureProfile {
  const profile = manifest.profiles[name];
  if (!profile) throw new Error(`Missing E2E fixture profile: ${name}`);
  return profile;
}

export function getFixtureCredentials(name: string): FixtureCredentials[string] {
  const profile = credentials[name];
  if (!profile) throw new Error(`Missing E2E fixture credentials: ${name}`);
  return profile;
}

export async function openFixturePage(
  browser: Browser,
  profileName: string,
): Promise<{ context: BrowserContext; page: Page; profile: FixtureProfile }> {
  const profile = getFixtureProfile(profileName);
  const context = await browser.newContext({
    baseURL: process.env.PFIS_E2E_BASE_URL ?? manifest.base_url,
    storageState: join(storageDirectory, profile.storage_state),
  });
  return { context, page: await context.newPage(), profile };
}

export function fixtureBaseUrl(): string {
  return process.env.PFIS_E2E_BASE_URL ?? manifest.base_url;
}
