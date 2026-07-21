import { useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  Check,
  Eye,
  EyeOff,
  Inbox,
  LoaderCircle,
  LockKeyhole,
  ShieldCheck,
  WalletCards,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input, Label } from '@/components/ui/Input';
import { ThemeToggle } from '@/app/ThemeToggle';
import { useAuth } from './AuthContext';

type View = 'login' | 'register';

const AUTH_ERROR_MESSAGES: Record<string, string> = {
  google_not_configured: 'Google sign-in is not available in this environment yet.',
  google_start_failed: 'Google sign-in could not start. Try again or use email and password.',
  google_signin_failed: 'Google could not complete sign-in. Try again or use email and password.',
  google_identity_invalid:
    'Google could not verify this sign-in. Start again and choose your PFIS account.',
  google_account_not_allowed:
    'This Google account is not approved for PFIS. Choose the configured account instead.',
  account_link_required: 'This email already has a PFIS account. Sign in with your password first.',
};

function GoogleMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" focusable="false">
      <path
        fill="#4285F4"
        d="M21.6 12.23c0-.71-.06-1.4-.18-2.07H12v3.92h5.38a4.6 4.6 0 0 1-2 3.02v2.54h3.24c1.9-1.75 2.98-4.33 2.98-7.41Z"
      />
      <path
        fill="#34A853"
        d="M12 22c2.7 0 4.98-.9 6.63-2.36l-3.24-2.54c-.9.6-2.05.96-3.39.96-2.61 0-4.82-1.76-5.61-4.13H3.04v2.62A10 10 0 0 0 12 22Z"
      />
      <path
        fill="#FBBC05"
        d="M6.39 13.93A6.02 6.02 0 0 1 6.08 12c0-.67.11-1.32.31-1.93V7.45H3.04A10 10 0 0 0 2 12c0 1.63.39 3.17 1.04 4.55l3.35-2.62Z"
      />
      <path
        fill="#EA4335"
        d="M12 5.94c1.47 0 2.79.5 3.83 1.5l2.87-2.87A9.63 9.63 0 0 0 12 2a10 10 0 0 0-8.96 5.45l3.35 2.62C7.18 7.7 9.39 5.94 12 5.94Z"
      />
    </svg>
  );
}

export function AuthScreen() {
  const { login, register, startDemo, expiryMessage, clearExpiryMessage } = useAuth();
  const [view, setView] = useState<View>('login');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('auth_error');
    if (code) {
      setError(AUTH_ERROR_MESSAGES[code] ?? 'Sign-in could not be completed. Try again.');
      params.delete('auth_error');
      const query = params.toString();
      window.history.replaceState({}, '', `${window.location.pathname}${query ? `?${query}` : ''}`);
    }
  }, []);

  function changeView(next: View) {
    setView(next);
    setError(null);
    clearExpiryMessage();
    setPassword('');
    setShowPassword(false);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    clearExpiryMessage();
    try {
      await action();
    } catch (caught) {
      setError((caught as Error).message || 'PFIS could not complete that request. Try again.');
      window.requestAnimationFrame(() => errorRef.current?.focus());
    } finally {
      setBusy(false);
    }
  }

  const message = error ?? expiryMessage;

  return (
    <main className="min-h-screen overflow-x-hidden bg-background px-4 py-4 sm:px-6 sm:py-6 lg:grid lg:grid-cols-[minmax(0,1.08fr)_minmax(420px,0.92fr)] lg:gap-6 lg:p-6">
      <section className="relative hidden min-h-[calc(100vh-3rem)] overflow-hidden rounded-[var(--radius-lg)] bg-primary text-primary-foreground lg:flex lg:flex-col lg:justify-between lg:p-10 xl:p-14">
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <span className="bg-white/12 grid h-11 w-11 place-items-center rounded-xl ring-1 ring-white/15">
              <WalletCards aria-hidden="true" className="h-5 w-5" />
            </span>
            <div>
              <p className="text-sm font-extrabold tracking-[-0.01em]">PFIS</p>
              <p className="text-xs text-primary-foreground">Private financial workspace</p>
            </div>
          </div>

          <p className="mt-16 max-w-xl text-sm font-bold uppercase tracking-[0.18em] text-primary-foreground">
            Your money, reconciled
          </p>
          <h1 className="mt-5 max-w-2xl text-balance text-5xl font-extrabold leading-[1.04] tracking-[-0.055em] xl:text-6xl">
            Begin with clarity, not another consent screen.
          </h1>
          <p className="mt-6 max-w-xl text-pretty text-base leading-7 text-primary-foreground xl:text-lg">
            Sign in to your private workspace first. Connect a financial inbox only when you choose
            to bring transaction evidence into PFIS.
          </p>
        </div>

        <div className="relative z-10 max-w-xl rounded-2xl bg-white/[0.07] p-5 ring-1 ring-white/15 backdrop-blur-sm">
          <div className="border-white/12 flex items-center justify-between border-b pb-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-primary-foreground">
                Permission receipt
              </p>
              <p className="mt-1 text-sm font-bold">You decide what PFIS can access</p>
            </div>
            <ShieldCheck aria-hidden="true" className="h-5 w-5 text-primary-foreground" />
          </div>
          <div className="grid gap-4 pt-4">
            <div className="grid grid-cols-[24px_1fr_auto] items-start gap-3">
              <span className="bg-white/12 grid h-6 w-6 place-items-center rounded-full">
                <Check aria-hidden="true" className="h-3.5 w-3.5" />
              </span>
              <div>
                <p className="text-sm font-bold">Sign in</p>
                <p className="mt-0.5 text-xs leading-5 text-primary-foreground">
                  Identity only: your name and verified email.
                </p>
              </div>
              <span className="rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-bold">
                Now
              </span>
            </div>
            <div className="grid grid-cols-[24px_1fr_auto] items-start gap-3">
              <span className="grid h-6 w-6 place-items-center rounded-full bg-white/[0.06]">
                <Inbox aria-hidden="true" className="h-3.5 w-3.5" />
              </span>
              <div>
                <p className="text-sm font-bold">Connect inbox</p>
                <p className="mt-0.5 text-xs leading-5 text-primary-foreground">
                  Read-only Gmail access, requested separately inside your workspace.
                </p>
              </div>
              <span className="rounded-full px-2.5 py-1 text-[11px] font-bold text-primary-foreground">
                Later
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="flex min-h-[calc(100vh-2rem)] items-center justify-center py-8 lg:min-h-[calc(100vh-3rem)] lg:py-0">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center justify-between lg:justify-end">
            <div className="flex items-center gap-2 lg:hidden">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-primary text-primary-foreground">
                <WalletCards aria-hidden="true" className="h-5 w-5" />
              </span>
              <div>
                <p className="text-sm font-extrabold">PFIS</p>
                <p className="text-xs text-muted-foreground">Private financial workspace</p>
              </div>
            </div>
            <ThemeToggle />
          </div>

          {view === 'register' ? (
            <button
              type="button"
              onClick={() => changeView('login')}
              className="focus-ring mb-5 inline-flex min-h-11 items-center gap-2 rounded-lg px-1 text-sm font-bold text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft aria-hidden="true" className="h-4 w-4" /> Back to sign in
            </button>
          ) : null}

          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-primary">
              Secure entry
            </p>
            <h2 className="mt-3 text-balance text-3xl font-extrabold tracking-[-0.04em] sm:text-4xl">
              {view === 'login' ? 'Open your financial workspace' : 'Create your private workspace'}
            </h2>
            <p className="mt-3 text-pretty text-sm leading-6 text-muted-foreground">
              {view === 'login'
                ? 'Your session stays in a protected browser cookie and can be revoked from the server.'
                : 'Start with your identity. Inbox access remains a separate decision after sign-up.'}
            </p>
          </div>

          {message ? (
            <div
              ref={errorRef}
              tabIndex={-1}
              role="alert"
              aria-live="assertive"
              className="focus-ring mt-5 flex items-start gap-3 rounded-xl bg-danger/10 p-3.5 text-sm leading-5 text-danger ring-1 ring-danger/25"
            >
              <AlertCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{message}</span>
            </div>
          ) : null}

          <div className="mt-7 grid gap-3">
            <a
              href="/api/auth/google/login"
              className="focus-ring inline-flex h-12 w-full items-center justify-center gap-3 rounded-lg border border-[#747775] bg-white px-4 font-sans text-sm font-semibold text-[#1f1f1f] transition-[background-color,box-shadow] hover:bg-[#f8fafd] active:bg-[#f1f3f4]"
            >
              <GoogleMark /> Continue with Google
            </a>
            <div className="flex items-center gap-3 text-xs font-semibold text-muted-foreground">
              <span className="h-px flex-1 bg-border" />
              <span>or use email</span>
              <span className="h-px flex-1 bg-border" />
            </div>
          </div>

          <form
            className="mt-3 grid gap-4"
            aria-busy={busy}
            onSubmit={(event) => {
              event.preventDefault();
              if (view === 'login') void run(() => login(email, password));
              else void run(() => register(name, email, password, 'INR'));
            }}
          >
            {view === 'register' ? (
              <div className="grid gap-1.5">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  name="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                  maxLength={255}
                  autoComplete="name"
                />
              </div>
            ) : null}

            <div className="grid gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoComplete="username"
                inputMode="email"
                spellCheck={false}
              />
            </div>

            <div className="grid gap-1.5">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="password">Password</Label>
                {view === 'register' ? (
                  <span id="password-hint" className="text-xs text-muted-foreground">
                    12 characters minimum
                  </span>
                ) : null}
              </div>
              <div className="relative">
                <Input
                  id="password"
                  name="password"
                  className="pr-12"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  minLength={view === 'register' ? 12 : 8}
                  autoComplete={view === 'login' ? 'current-password' : 'new-password'}
                  aria-describedby={view === 'register' ? 'password-hint' : undefined}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((current) => !current)}
                  className="focus-ring absolute right-1 top-1 grid h-9 w-9 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                >
                  {showPassword ? (
                    <EyeOff aria-hidden="true" className="h-4 w-4" />
                  ) : (
                    <Eye aria-hidden="true" className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            <Button type="submit" disabled={busy} className="mt-1 w-full" size="lg">
              {busy ? (
                <LoaderCircle
                  aria-hidden="true"
                  className="h-4 w-4 animate-spin motion-reduce:animate-none"
                />
              ) : (
                <LockKeyhole aria-hidden="true" className="h-4 w-4" />
              )}
              {busy
                ? view === 'login'
                  ? 'Signing in…'
                  : 'Creating workspace…'
                : view === 'login'
                  ? 'Sign in securely'
                  : 'Create workspace'}
            </Button>
          </form>

          <div className="mt-6 border-t border-border pt-5 text-center">
            {view === 'login' ? (
              <p className="text-sm text-muted-foreground">
                New to PFIS?{' '}
                <button
                  type="button"
                  onClick={() => changeView('register')}
                  className="focus-ring min-h-11 rounded-md px-1 font-bold text-foreground hover:text-primary"
                >
                  Create a private workspace
                </button>
              </p>
            ) : (
              <p className="text-xs leading-5 text-muted-foreground">
                Creating an account does not connect Gmail or grant inbox access.
              </p>
            )}

            {view === 'login' ? (
              <Button
                variant="ghost"
                className="mt-2 w-full text-muted-foreground"
                type="button"
                disabled={busy}
                onClick={() => void run(startDemo)}
              >
                Preview with synthetic data
              </Button>
            ) : null}
          </div>

          <div className="mt-6 rounded-xl bg-muted/50 p-4 ring-1 ring-border/70 lg:hidden">
            <div className="flex items-start gap-3">
              <ShieldCheck aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
              <div>
                <p className="text-sm font-bold">Identity now. Inbox access later.</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  Google sign-in shares your verified identity only. Read-only Gmail access is a
                  separate choice inside PFIS.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
