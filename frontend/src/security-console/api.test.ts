import { afterEach, describe, expect, it, vi } from 'vitest';
import { requestJson } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('local security API client', () => {
  it('refuses non-security API paths before issuing a request', async () => {
    const fetchStub = vi.fn();
    vi.stubGlobal('fetch', fetchStub);
    await expect(requestJson('/api/transactions')).rejects.toThrow('Invalid local API path');
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it('requires an in-memory CSRF token for every mutation', async () => {
    const fetchStub = vi.fn();
    vi.stubGlobal('fetch', fetchStub);
    await expect(requestJson('/security-api/runs', { method: 'POST', body: '{}' })).rejects.toThrow(
      'paired again',
    );
    expect(fetchStub).not.toHaveBeenCalled();
  });
});
