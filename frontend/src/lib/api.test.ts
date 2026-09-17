import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, AUTH_SESSION_ENDED_EVENT } from './api';

describe('API session handling', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = 'pfis_csrf=; Max-Age=0; Path=/';
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

  it('builds the separate Gmail consent URL for the current user', () => {
    expect(api.gmailConnectUrl('user with spaces')).toBe(
      '/api/auth/gmail/connect?user_id=user+with+spaces',
    );
  });

  it('downloads a portable copy with CSRF protection and the server filename', async () => {
    document.cookie = 'pfis_csrf=portable-csrf; Path=/';
    const fetchMock = vi.fn(
      async () =>
        new Response('archive', {
          status: 200,
          headers: {
            'Content-Type': 'application/zip',
            'Content-Disposition': 'attachment; filename="pfis-portable-export-20260731.zip"',
          },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.portableExport('user with spaces');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/reports/export/portable?user_id=user+with+spaces',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRF-Token': 'portable-csrf' },
      }),
    );
    expect(result.filename).toBe('pfis-portable-export-20260731.zip');
    expect(await result.blob.text()).toBe('archive');
  });

  it('posts connector card observations through the typed issuer route', async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({
        id: 'observation-1',
        financial_account_id: 'card-1',
        current_outstanding: 12000,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const payload = {
      current_outstanding: 12000,
      currency: 'INR',
      as_of: '2026-02-12',
      source_record_id: 'connector-record-1',
      coverage_start: '2026-02-01T00:00:00Z',
      coverage_end: '2026-02-12T00:00:00Z',
    };

    await api.createCardPositionObservation('user-1', 'card-1', payload);

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/accounts/card-1/card-observations?user_id=user-1',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      }),
    );
  });
});
