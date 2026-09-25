import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { History, RotateCcw, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card';
import { Dialog } from '@/components/ui/Dialog';
import { Input, Label, Select } from '@/components/ui/Input';
import { useAuth } from '@/features/auth/AuthContext';
import { preferencePolicyApi } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/format';
import type {
  PreferencePolicyRecommendationKind,
  UserPreferencePolicy,
  UserPreferencePolicyVersion,
} from '@/lib/types';

const ALERT_MIN = 1;
const ALERT_MAX = 100;
const RESERVE_MIN = 0;
const RESERVE_MAX = 10_000_000;

const policyQueryKeys = {
  current: (userId: string) => ['preferencePolicy', userId] as const,
  history: (userId: string) => ['preferencePolicyHistory', userId] as const,
};

const recommendationKindOptions: Array<{
  value: PreferencePolicyRecommendationKind;
  label: string;
}> = [
  { value: 'anomaly', label: 'Unusual activity' },
  { value: 'budget', label: 'Budget pressure' },
  { value: 'card_payment', label: 'Card payment' },
  { value: 'cash_reserve', label: 'Cash reserve' },
  { value: 'debt_payment', label: 'Debt payment' },
  { value: 'goal_contribution', label: 'Goal contribution' },
  { value: 'keep_reserve', label: 'Keep reserve' },
  { value: 'pay_card_full', label: 'Pay card in full' },
  { value: 'recurring', label: 'Recurring cost' },
  { value: 'reserve', label: 'Reserve' },
  { value: 'review', label: 'Review item' },
  { value: 'savings', label: 'Savings' },
];

const cadenceLabels: Record<UserPreferencePolicy['briefing_cadence'], string> = {
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
};

const defaultPolicy: UserPreferencePolicy = {
  alert_threshold_pct: 20,
  briefing_cadence: 'daily',
  reserve_floor: 0,
  dismissed_recommendation_kinds: [],
  excluded_recommendation_types: [],
  excluded_merchants: [],
  excluded_categories: [],
};

type PolicyDraft = {
  alertThresholdPct: string;
  briefingCadence: UserPreferencePolicy['briefing_cadence'];
  reserveFloor: string;
  dismissedRecommendationKinds: PreferencePolicyRecommendationKind[];
  excludedRecommendationTypes: PreferencePolicyRecommendationKind[];
  excludedMerchants: string;
  excludedCategories: string;
};

type PolicyErrors = Partial<Record<keyof PolicyDraft, string>>;

export function PreferencePolicySettings() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const formRef = useRef<HTMLFormElement>(null);
  const [draft, setDraft] = useState<PolicyDraft>(() => toDraft(defaultPolicy));
  const [errors, setErrors] = useState<PolicyErrors>({});
  const [rollbackTarget, setRollbackTarget] = useState<UserPreferencePolicyVersion | null>(null);

  const current = useQuery({
    queryKey: policyQueryKeys.current(user?.id ?? ''),
    queryFn: () => preferencePolicyApi.current(user!.id),
    enabled: !!user,
  });
  const history = useQuery({
    queryKey: policyQueryKeys.history(user?.id ?? ''),
    queryFn: () => preferencePolicyApi.history(user!.id),
    enabled: !!user,
  });

  useEffect(() => {
    if (current.data?.policy) {
      setDraft(toDraft(current.data.policy));
      setErrors({});
    }
  }, [current.data]);

  const save = useMutation({
    mutationFn: (policy: UserPreferencePolicy) => {
      if (!user) throw new Error('Sign in before saving preference rules');
      return preferencePolicyApi.save(user.id, policy);
    },
    onSuccess: async () => {
      if (!user) return;
      await invalidatePolicyQueries(queryClient, user.id);
    },
  });

  const rollback = useMutation({
    mutationFn: (version: number) => {
      if (!user) throw new Error('Sign in before rolling back preference rules');
      return preferencePolicyApi.rollback(user.id, version);
    },
    onSuccess: async () => {
      if (!user) return;
      setRollbackTarget(null);
      await invalidatePolicyQueries(queryClient, user.id);
    },
  });

  const policyPreview = useMemo(() => fromDraft(draft).policy, [draft]);
  const versionLabel =
    current.data && current.data.version > 0
      ? `Version ${current.data.version}`
      : 'Default policy';

  function updateDraft<K extends keyof PolicyDraft>(key: K, value: PolicyDraft[K]) {
    setDraft((existing) => ({ ...existing, [key]: value }));
    setErrors((existing) => {
      const next = { ...existing };
      delete next[key];
      return next;
    });
  }

  function toggleKind(
    key: 'dismissedRecommendationKinds' | 'excludedRecommendationTypes',
    value: PreferencePolicyRecommendationKind,
  ) {
    const values = new Set(draft[key]);
    if (values.has(value)) values.delete(value);
    else values.add(value);
    updateDraft(key, Array.from(values) as PolicyDraft[typeof key]);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = fromDraft(draft);
    setErrors(parsed.errors);
    if (Object.keys(parsed.errors).length > 0) {
      window.requestAnimationFrame(() => {
        formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      });
      return;
    }
    save.mutate(parsed.policy);
  }

  if (!user) return null;

  return (
    <Card
      className="border border-border/70 shadow-sm"
      aria-labelledby="preference-policy-title"
    >
      <CardHeader>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-intelligence">
              Preference policy
            </p>
            <CardTitle
              id="preference-policy-title"
              className="mt-2 text-xl tracking-[-0.03em]"
            >
              Set explicit rules PFIS must follow.
            </CardTitle>
            <CardDescription className="mt-2 max-w-3xl leading-6">
              These controls are rules you choose, not learned behaviour. Saving appends a new
              version so you can inspect history or roll back without changing old records.
            </CardDescription>
          </div>
          <Badge variant="info">
            <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />
            {versionLabel}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {current.isLoading ? (
          <div role="status" aria-label="Loading preference policy…" className="space-y-3">
            <div className="h-4 w-48 animate-soft-pulse rounded bg-muted" />
            <div className="h-40 animate-soft-pulse rounded-xl bg-muted/70" />
          </div>
        ) : current.isError ? (
          <p role="alert" className="rounded-xl border border-warning/35 bg-warning/5 p-4 text-sm">
            Preference rules could not be loaded. Refresh Data & settings and try again.
          </p>
        ) : (
          <form ref={formRef} className="space-y-6" onSubmit={onSubmit} noValidate>
            <div className="grid gap-4 lg:grid-cols-3">
              <NumberField
                id="policy-alert-threshold"
                label="Alert threshold"
                suffix="%"
                value={draft.alertThresholdPct}
                min={ALERT_MIN}
                max={ALERT_MAX}
                description="PFIS flags changes once they meet this percentage threshold."
                error={errors.alertThresholdPct}
                onChange={(value) => updateDraft('alertThresholdPct', value)}
              />
              <div>
                <Label htmlFor="policy-briefing-cadence">Briefing cadence</Label>
                <Select
                  id="policy-briefing-cadence"
                  name="briefing_cadence"
                  value={draft.briefingCadence}
                  aria-describedby="policy-briefing-cadence-help"
                  onChange={(event) =>
                    updateDraft(
                      'briefingCadence',
                      event.target.value as UserPreferencePolicy['briefing_cadence'],
                    )
                  }
                >
                  {Object.entries(cadenceLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </Select>
                <p id="policy-briefing-cadence-help" className="mt-1 text-xs text-muted-foreground">
                  Sets how often Today prepares a guidance brief.
                </p>
              </div>
              <NumberField
                id="policy-reserve-floor"
                label="Reserve floor"
                prefix={user.currency}
                value={draft.reserveFloor}
                min={RESERVE_MIN}
                max={RESERVE_MAX}
                description={`Keep recommendations aware of a minimum ${formatCurrency(
                  Number(draft.reserveFloor) || 0,
                  user.currency,
                )} reserve.`}
                error={errors.reserveFloor}
                onChange={(value) => updateDraft('reserveFloor', value)}
              />
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <KindPicker
                title="Dismissed recommendation kinds"
                description="Kinds you have already dismissed stay quiet unless you remove them here."
                name="dismissed_recommendation_kinds"
                values={draft.dismissedRecommendationKinds}
                onToggle={(value) => toggleKind('dismissedRecommendationKinds', value)}
              />
              <KindPicker
                title="Excluded recommendation kinds"
                description="PFIS will not rank these kinds while they remain excluded."
                name="excluded_recommendation_types"
                values={draft.excludedRecommendationTypes}
                onToggle={(value) => toggleKind('excludedRecommendationTypes', value)}
              />
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <ListField
                id="policy-excluded-merchants"
                label="Excluded merchants"
                value={draft.excludedMerchants}
                description="Comma-separated merchant names. PFIS normalizes duplicates on save."
                error={errors.excludedMerchants}
                onChange={(value) => updateDraft('excludedMerchants', value)}
              />
              <ListField
                id="policy-excluded-categories"
                label="Excluded categories"
                value={draft.excludedCategories}
                description="Comma-separated categories to leave out of recommendation ranking."
                error={errors.excludedCategories}
                onChange={(value) => updateDraft('excludedCategories', value)}
              />
            </div>

            <div className="rounded-xl border border-border/70 bg-muted/20 p-4">
              <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
                Current policy preview
              </p>
              <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <PolicyFact label="Threshold" value={`${policyPreview.alert_threshold_pct}%`} />
                <PolicyFact
                  label="Cadence"
                  value={cadenceLabels[policyPreview.briefing_cadence]}
                />
                <PolicyFact
                  label="Reserve"
                  value={formatCurrency(policyPreview.reserve_floor, user.currency)}
                />
                <PolicyFact
                  label="Excluded"
                  value={`${
                    policyPreview.excluded_merchants.length +
                    policyPreview.excluded_categories.length +
                    policyPreview.excluded_recommendation_types.length
                  } rules`}
                />
              </dl>
            </div>

            {save.error ? (
              <p role="alert" className="text-sm font-bold text-danger">
                Preference rules were not saved. Check the highlighted fields and try again.
              </p>
            ) : null}
            {save.isSuccess ? (
              <p role="status" aria-live="polite" className="text-sm font-bold text-success">
                Preference rules saved as a new version. Today and recommendations will refresh.
              </p>
            ) : null}

            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-muted-foreground">
                Bounds come from the backend schema: threshold {ALERT_MIN}–{ALERT_MAX}%, reserve{' '}
                {formatCurrency(RESERVE_MIN, user.currency)}–
                {formatCurrency(RESERVE_MAX, user.currency)}.
              </p>
              <Button type="submit" disabled={save.isPending}>
                <SlidersHorizontal aria-hidden="true" className="h-4 w-4" />
                {save.isPending ? 'Saving…' : 'Save rules'}
              </Button>
            </div>
          </form>
        )}

        <section aria-labelledby="preference-history-title" className="space-y-3">
          <div className="flex items-center gap-2">
            <History aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
            <h3 id="preference-history-title" className="font-extrabold">
              Version history
            </h3>
          </div>
          {history.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading history…</p>
          ) : history.isError ? (
            <p role="alert" className="text-sm font-bold text-danger">
              Version history could not be loaded.
            </p>
          ) : history.data?.length ? (
            <ul className="divide-y divide-border/65 rounded-xl border border-border/70">
              {history.data.slice(0, 10).map((version) => (
                <li
                  key={version.id}
                  className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="font-extrabold">Version {version.version}</p>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">
                      {version.created_at ? formatDate(version.created_at) : 'Saved date unknown'}
                      {version.based_on_version
                        ? ` · copied from version ${version.based_on_version}`
                        : ''}
                      {' · '}
                      {version.policy.alert_threshold_pct}% threshold ·{' '}
                      {formatCurrency(version.policy.reserve_floor, user.currency)} reserve
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={rollback.isPending || version.version === current.data?.version}
                    onClick={() => setRollbackTarget(version)}
                  >
                    <RotateCcw aria-hidden="true" className="h-4 w-4" />
                    Roll back
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
              No saved versions yet. Saving rules creates version 1; defaults remain unchanged.
            </p>
          )}
          {rollback.error ? (
            <p role="alert" className="text-sm font-bold text-danger">
              Rollback could not be saved. Refresh version history and try again.
            </p>
          ) : null}
        </section>
      </CardContent>

      <Dialog
        open={Boolean(rollbackTarget)}
        onClose={() => setRollbackTarget(null)}
        title="Roll back preference rules?"
        description={
          rollbackTarget
            ? `PFIS will copy version ${rollbackTarget.version} into a new version. Existing versions stay unchanged.`
            : undefined
        }
      >
        <div className="space-y-4">
          <p className="text-sm leading-6 text-muted-foreground">
            This only changes explicit recommendation rules. It does not erase transactions,
            statement evidence, or earlier policy versions.
          </p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={() => setRollbackTarget(null)}>
              Keep current rules
            </Button>
            <Button
              variant="danger"
              data-dialog-initial-focus
              disabled={rollback.isPending || !rollbackTarget}
              onClick={() => {
                if (rollbackTarget) rollback.mutate(rollbackTarget.version);
              }}
            >
              {rollback.isPending ? 'Rolling back…' : 'Create rollback version'}
            </Button>
          </div>
        </div>
      </Dialog>
    </Card>
  );
}

function NumberField({
  id,
  label,
  value,
  min,
  max,
  description,
  error,
  onChange,
  prefix,
  suffix,
}: {
  id: string;
  label: string;
  value: string;
  min: number;
  max: number;
  description: string;
  error?: string;
  onChange: (value: string) => void;
  prefix?: string;
  suffix?: string;
}) {
  const helpId = `${id}-help`;
  const errorId = `${id}-error`;
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        {prefix ? (
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-xs font-bold text-muted-foreground">
            {prefix}
          </span>
        ) : null}
        <Input
          id={id}
          name={id}
          type="number"
          inputMode="decimal"
          min={min}
          max={max}
          step="0.01"
          value={value}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${helpId} ${errorId}` : helpId}
          autoComplete="off"
          className={prefix ? 'pl-12' : suffix ? 'pr-10' : undefined}
          onChange={(event) => onChange(event.target.value)}
        />
        {suffix ? (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-bold text-muted-foreground">
            {suffix}
          </span>
        ) : null}
      </div>
      <p id={helpId} className="mt-1 text-xs leading-5 text-muted-foreground">
        {description}
      </p>
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-xs font-bold text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function ListField({
  id,
  label,
  value,
  description,
  error,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  description: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  const helpId = `${id}-help`;
  const errorId = `${id}-error`;
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        name={id}
        value={value}
        placeholder="Example: rent, fuel, subscriptions…"
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${helpId} ${errorId}` : helpId}
        autoComplete="off"
        onChange={(event) => onChange(event.target.value)}
      />
      <p id={helpId} className="mt-1 text-xs leading-5 text-muted-foreground">
        {description}
      </p>
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-xs font-bold text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function KindPicker({
  title,
  description,
  name,
  values,
  onToggle,
}: {
  title: string;
  description: string;
  name: string;
  values: PreferencePolicyRecommendationKind[];
  onToggle: (value: PreferencePolicyRecommendationKind) => void;
}) {
  const selected = new Set(values);
  return (
    <fieldset className="rounded-xl border border-border/70 p-4">
      <legend className="px-1 text-sm font-extrabold">{title}</legend>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {recommendationKindOptions.map((option) => (
          <label
            key={option.value}
            className="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-border/60 px-3 py-2 text-sm hover:bg-muted/45"
          >
            <input
              type="checkbox"
              name={name}
              value={option.value}
              checked={selected.has(option.value)}
              className="h-4 w-4 accent-primary"
              onChange={() => onToggle(option.value)}
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function PolicyFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-extrabold tabular-nums">{value}</dd>
    </div>
  );
}

function toDraft(policy: UserPreferencePolicy): PolicyDraft {
  return {
    alertThresholdPct: String(policy.alert_threshold_pct),
    briefingCadence: policy.briefing_cadence,
    reserveFloor: String(policy.reserve_floor),
    dismissedRecommendationKinds: policy.dismissed_recommendation_kinds,
    excludedRecommendationTypes: policy.excluded_recommendation_types,
    excludedMerchants: policy.excluded_merchants.join(', '),
    excludedCategories: policy.excluded_categories.join(', '),
  };
}

function fromDraft(draft: PolicyDraft): { policy: UserPreferencePolicy; errors: PolicyErrors } {
  const errors: PolicyErrors = {};
  const alertThreshold = Number(draft.alertThresholdPct);
  const reserveFloor = Number(draft.reserveFloor);
  const merchants = parseList(draft.excludedMerchants);
  const categories = parseList(draft.excludedCategories);

  if (!Number.isFinite(alertThreshold) || alertThreshold < ALERT_MIN || alertThreshold > ALERT_MAX) {
    errors.alertThresholdPct = `Enter a threshold from ${ALERT_MIN} to ${ALERT_MAX}.`;
  }
  if (!Number.isFinite(reserveFloor) || reserveFloor < RESERVE_MIN || reserveFloor > RESERVE_MAX) {
    errors.reserveFloor = `Enter a reserve from ${RESERVE_MIN} to ${RESERVE_MAX}.`;
  }
  if (merchants.length > 100) errors.excludedMerchants = 'Keep merchant exclusions to 100 or fewer.';
  if (categories.length > 100) errors.excludedCategories = 'Keep category exclusions to 100 or fewer.';

  return {
    errors,
    policy: {
      alert_threshold_pct: Number.isFinite(alertThreshold)
        ? Number(alertThreshold.toFixed(2))
        : defaultPolicy.alert_threshold_pct,
      briefing_cadence: draft.briefingCadence,
      reserve_floor: Number.isFinite(reserveFloor)
        ? Number(reserveFloor.toFixed(2))
        : defaultPolicy.reserve_floor,
      dismissed_recommendation_kinds: draft.dismissedRecommendationKinds,
      excluded_recommendation_types: draft.excludedRecommendationTypes,
      excluded_merchants: merchants,
      excluded_categories: categories,
    },
  };
}

function parseList(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => {
      const key = item.toLocaleLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

async function invalidatePolicyQueries(queryClient: QueryClient, userId: string) {
  const affectedRoots = new Set(['preferencePolicy', 'preferencePolicyHistory']);
  const recommendationRoots = new Set(['workspace', 'guidanceBrief', 'guidance', 'horizon']);
  await queryClient.invalidateQueries({
    predicate: (query) => {
      const root = String(query.queryKey[0]);
      return (
        (affectedRoots.has(root) && query.queryKey.includes(userId)) ||
        (recommendationRoots.has(root) && query.queryKey.includes(userId))
      );
    },
  });
}
