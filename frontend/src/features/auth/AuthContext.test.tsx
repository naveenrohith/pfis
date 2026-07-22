import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AUTH_SESSION_ENDED_EVENT } from '@/lib/api';
import { AuthProvider, useAuth } from './AuthContext';

const sessionPayload = {
  expires_in: 3600,
  csrf_cookie_name: 'pfis_csrf',
  mode: 'auth',
  user: {
    id: 'user-1',
    name: 'Naveen',
    email: 'naveen@example.com',
    currency: 'INR',
    is_active: true,
    created_at: '2026-07-21T00:00:00Z',
  },
};

function Harness() {
  const { isReady, isAuthenticated, logout, expiryMessage } = useAuth();
  return (
    <div>
      <p>{isReady ? 'ready' : 'loading'}</p>
      <p>{isAuthenticated ? 'authenticated' : 'signed out'}</p>
      {expiryMessage ? <p>{expiryMessage}</p> : null}
      <button type="button" onClick={() => void logout()}>
        Sign out
      </button>
    </div>
  );
}

function renderProvider(queryClient = new QueryClient()) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Harness />
        </AuthProvider>
      </QueryClientProvider>,
    ),
  };
}

describe('AuthProvider', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('keeps the authenticated UI when the server cannot confirm logout', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(sessionPayload))
      .mockRejectedValueOnce(new TypeError('Network unavailable'));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    renderProvider();
    await screen.findByText('authenticated');
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText('authenticated')).toBeInTheDocument();
  });

  it('clears private query data and returns to sign-in after a later 401', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(sessionPayload)));
    const queryClient = new QueryClient();
    queryClient.setQueryData(['private-finances'], { amount: 1250 });
    renderProvider(queryClient);
    await screen.findByText('authenticated');

    fireEvent(window, new Event(AUTH_SESSION_ENDED_EVENT));

    expect(await screen.findByText('signed out')).toBeInTheDocument();
    expect(queryClient.getQueryData(['private-finances'])).toBeUndefined();
    expect(screen.getByText('Your secure session ended. Sign in to continue.')).toBeInTheDocument();
  });
});
