import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from '@/components/theme/ThemeProvider';
import { AuthScreen } from './AuthScreen';

const auth = {
  login: vi.fn(async () => {}),
  register: vi.fn(async () => {}),
  startDemo: vi.fn(async () => {}),
  expiryMessage: null as string | null,
  clearExpiryMessage: vi.fn(),
};

vi.mock('./AuthContext', () => ({
  useAuth: () => auth,
}));

function renderScreen() {
  return render(
    <ThemeProvider>
      <AuthScreen />
    </ThemeProvider>,
  );
}

describe('AuthScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, '', '/dashboard');
  });

  it('separates Google identity sign-in from later Gmail access', () => {
    renderScreen();

    const google = screen.getByRole('link', { name: 'Continue with Google' });
    expect(google).toHaveAttribute('href', '/api/auth/google/login');
    expect(screen.getAllByText(/Identity only/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Read-only Gmail access/i).length).toBeGreaterThan(0);
  });

  it('uses password-manager friendly fields and reveals registration requirements', async () => {
    const user = userEvent.setup();
    renderScreen();

    expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'username');
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password');

    await user.click(screen.getByRole('button', { name: 'Create a private workspace' }));

    expect(screen.getByLabelText('Name')).toHaveAttribute('autocomplete', 'name');
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'new-password');
    expect(screen.getByLabelText('Password')).toHaveAttribute('minlength', '12');
    expect(screen.getByText('12 characters minimum')).toBeInTheDocument();
  });

  it('submits registration without requesting inbox permission', async () => {
    const user = userEvent.setup();
    renderScreen();

    await user.click(screen.getByRole('button', { name: 'Create a private workspace' }));
    await user.type(screen.getByLabelText('Name'), 'Naveen');
    await user.type(screen.getByLabelText('Email'), 'naveen@example.com');
    await user.type(screen.getByLabelText('Password'), 'correct horse battery staple');
    await user.click(screen.getByRole('button', { name: 'Create workspace' }));

    expect(auth.register).toHaveBeenCalledWith(
      'Naveen',
      'naveen@example.com',
      'correct horse battery staple',
      'INR',
    );
  });
});
