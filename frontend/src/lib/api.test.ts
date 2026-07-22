import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, AUTH_SESSION_ENDED_EVENT } from './api';

describe('API session handling', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('notifies the application when an authenticated request loses its session', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 401, statusText: 'Unauthorized' })),
    );
    const listener = vi.fn();
    window.addEventListener(AUTH_SESSION_ENDED_EVENT, listener);

    await expect(api.me()).rejects.toMatchObject({ status: 401 } satisfies Partial<ApiError>);
    expect(listener).toHaveBeenCalledOnce();

    window.removeEventListener(AUTH_SESSION_ENDED_EVENT, listener);
  });

  it('does not report a normal signed-out bootstrap as an expired session', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json(
          { error: { code: 'authentication_required', message: 'Authentication required' } },
          { status: 401 },
        ),
      ),
    );
    const listener = vi.fn();
    window.addEventListener(AUTH_SESSION_ENDED_EVENT, listener);

    await expect(api.session()).rejects.toMatchObject({ status: 401 } satisfies Partial<ApiError>);
    expect(listener).not.toHaveBeenCalled();

    window.removeEventListener(AUTH_SESSION_ENDED_EVENT, listener);
  });
});
