import { lazy, type ComponentType, type LazyExoticComponent } from 'react';

/**
 * Recover once when a deployment replaces a code-split asset that an open tab
 * still references. A single reload fetches the no-store SPA shell; the session
 * marker prevents reload loops when the failure is unrelated to deployment.
 */
// Component props are captured by T; React's ComponentType itself uses `any`
// as the constraint required by lazy(), without erasing T at call sites.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyWithRetry<T extends ComponentType<any>>(
  importer: () => Promise<{ default: T }>,
  chunkKey: string,
): LazyExoticComponent<T> {
  return lazy(async (): Promise<{ default: T }> => {
    const reloadKey = `pfis:chunk-reload:${chunkKey}`;
    try {
      const module = await importer();
      sessionStorage.removeItem(reloadKey);
      return module;
    } catch (error) {
      if (!sessionStorage.getItem(reloadKey)) {
        sessionStorage.setItem(reloadKey, '1');
        window.location.reload();
        return new Promise<{ default: T }>(() => undefined);
      }
      throw error;
    }
  });
}
