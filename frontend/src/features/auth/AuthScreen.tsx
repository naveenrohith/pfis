import { useState } from 'react';
import { ShieldCheck, Sparkles, Zap, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input, Label } from '@/components/ui/Input';
import { Segmented } from '@/components/ui/Segmented';
import { ThemeToggle } from '@/app/ThemeToggle';
import { useAuth } from './AuthContext';

type Tab = 'login' | 'register';

const FEATURES = [
  { icon: ShieldCheck, title: 'Secure session', text: 'Encrypted tokens, ownership-scoped data.' },
  { icon: Zap, title: 'One-tap review', text: 'Confirm parsed transactions in seconds.' },
  { icon: Sparkles, title: 'Smart insights', text: 'Trends, recurring charges, and budgets.' },
];

export function AuthScreen() {
  const { login, register, startDemo, expiryMessage } = useAuth();
  const [tab, setTab] = useState<Tab>('login');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [currency, setCurrency] = useState('INR');

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Spotlight */}
      <div className="relative hidden flex-col justify-between overflow-hidden bg-primary p-12 text-primary-foreground lg:flex">
        <div className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-white/10 blur-3xl" />
        <div className="absolute -bottom-24 -left-24 h-96 w-96 rounded-full bg-black/10 blur-3xl" />
        <div className="relative">
          <p className="text-sm font-bold uppercase tracking-widest opacity-80">
            PFIS · Personal Finance
          </p>
          <h1 className="mt-6 max-w-md text-5xl font-extrabold leading-tight">
            Understand your money instantly.
          </h1>
          <p className="mt-4 max-w-md text-lg opacity-90">
            PFIS reads your transaction emails, organizes them automatically, and turns them into
            clear, actionable insight.
          </p>
        </div>
        <div className="relative grid gap-4">
          {FEATURES.map((f) => (
            <div key={f.title} className="flex items-start gap-3 rounded-xl bg-white/10 p-4">
              <f.icon className="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <p className="font-semibold">{f.title}</p>
                <p className="text-sm opacity-80">{f.text}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Panel */}
      <div className="flex items-center justify-center bg-background p-6">
        <div className="w-full max-w-sm">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
                Welcome
              </p>
              <h2 className="text-2xl font-bold">Open PFIS</h2>
            </div>
            <ThemeToggle />
          </div>

          {(error || expiryMessage) && (
            <div className="mb-4 flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error ?? expiryMessage}</span>
            </div>
          )}

          <Segmented
            className="mb-5 w-full"
            aria-label="Authentication tabs"
            value={tab}
            onChange={setTab}
            options={[
              { value: 'login', label: 'Sign in' },
              { value: 'register', label: 'Create account' },
            ]}
          />

          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (tab === 'login') run(() => login(email, password));
              else run(() => register(name, email, password, currency));
            }}
          >
            {tab === 'register' && (
              <div className="grid gap-1.5">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  autoComplete="name"
                />
              </div>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
              />
            </div>
            {tab === 'register' && (
              <div className="grid gap-1.5">
                <Label htmlFor="currency">Currency</Label>
                <Input
                  id="currency"
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                  maxLength={3}
                />
              </div>
            )}
            <Button type="submit" disabled={busy} className="mt-1 w-full">
              {busy ? 'Working…' : tab === 'login' ? 'Sign in' : 'Create workspace'}
            </Button>
          </form>

          <div className="my-5 flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            OR
            <span className="h-px flex-1 bg-border" />
          </div>

          <div className="grid gap-2">
            <a href="/api/auth/google/login" className="w-full">
              <Button variant="outline" className="w-full" type="button">
                Continue with Google
              </Button>
            </a>
            <Button
              variant="ghost"
              className="w-full"
              type="button"
              disabled={busy}
              onClick={() => run(startDemo)}
            >
              Try demo workspace
            </Button>
          </div>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            Demo mode uses seeded sample data — no real account required.
          </p>
        </div>
      </div>
    </div>
  );
}
