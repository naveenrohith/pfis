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
    timezone: 'Asia/Kolkata',
    is_active: true,
    created_at: '2026-07-21T00:00:00Z',
  },
};

function Harness() {
  const { isReady, isAuthenticated, user, logout, updateProfile, deleteAccount, expiryMessage } =
    useAuth();
  return (
    <div>
      <p>{isReady ? 'ready' : 'loading'}</p>
      <p>{isAuthenticated ? 'authenticated' : 'signed out'}</p>
      <p>{user?.timezone ?? 'no timezone'}</p>
      {expiryMessage ? <p>{expiryMessage}</p> : null}
      <button type="button" onClick={() => void logout()}>
        Sign out
      </button>
      <button type="button" onClick={() => void updateProfile({ timezone: 'America/New_York' })}>
        Change timezone
      </button>
      <button type="button" onClick={() => void deleteAccount('DELETE naveen@example.com')}>
        Delete account
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
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(sessionPayload)),
    );
    const queryClient = new QueryClient();
    queryClient.setQueryData(['private-finances'], { amount: 1250 });
    renderProvider(queryClient);
    await screen.findByText('authenticated');

    fireEvent(window, new Event(AUTH_SESSION_ENDED_EVENT));

    expect(await screen.findByText('signed out')).toBeInTheDocument();
    expect(queryClient.getQueryData(['private-finances'])).toBeUndefined();
    expect(screen.getByText('Your secure session ended. Sign in to continue.')).toBeInTheDocument();
  });

  it('updates the active session after saving profile settings', async () => {
    const updatedUser = {
      ...sessionPayload.user,
      timezone: 'America/New_York',
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(sessionPayload))
      .mockResolvedValueOnce(Response.json(updatedUser));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    renderProvider();
    await screen.findByText('Asia/Kolkata');
    await user.click(screen.getByRole('button', { name: 'Change timezone' }));

    expect(await screen.findByText('America/New_York')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/users/user-1',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ timezone: 'America/New_York' }),
      }),
    );
  });

  it('clears the session and private query data after account deletion', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(sessionPayload))
      .mockResolvedValueOnce(
        Response.json({ status: 'deleted', deleted_at: '2026-07-31T00:00:00Z' }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const queryClient = new QueryClient();
    queryClient.setQueryData(['private-finances'], { amount: 1250 });
    const user = userEvent.setup();
    renderProvider(queryClient);
    await screen.findByText('authenticated');

    await user.click(screen.getByRole('button', { name: 'Delete account' }));

    expect(await screen.findByText('signed out')).toBeInTheDocument();
    expect(queryClient.getQueryData(['private-finances'])).toBeUndefined();
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/users/user-1',
      expect.objectContaining({
        method: 'DELETE',
        body: JSON.stringify({ confirmation: 'DELETE naveen@example.com' }),
      }),
    );
  });
});
