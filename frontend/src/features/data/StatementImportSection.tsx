import { FormEvent, type ReactNode, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  FileSearch,
  FileUp,
  Landmark,
  Link2,
  LockKeyhole,
  ShieldCheck,
  Unlink,
} from 'lucide-react';
import { FinancialHero } from '@/components/system';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Label, Select } from '@/components/ui/Input';
import { EmptyState } from '@/components/ui/Skeleton';
import { useAuth } from '@/features/auth/AuthContext';
import { queryKeys, useAccountLinkRules, useAccounts } from '@/features/workspace/queries';
import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/format';
import { DepositStatementReviewPanel } from './DepositStatementReviewPanel';
import { StatementAnalysisReviewPanel } from './StatementAnalysisReviewPanel';

const MAX_STATEMENT_BYTES = 10 * 1024 * 1024;

export function StatementImportSection() {
  const { user } = useAuth();
  const accounts = useAccounts();
  const queryClient = useQueryClient();
  const statementAccounts = useMemo(
    () =>
      (accounts.data ?? []).filter(
        (account) =>
          account.is_active &&
          (account.account_type === 'credit_card' || account.account_type === 'bank'),
      ),
    [accounts.data],
  );
  const [accountId, setAccountId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState('');
  const detectStatement = useMutation({
    mutationFn: (candidate: File) => {
      if (!user) throw new Error('Sign in before checking a statement');
      if (candidate.size > MAX_STATEMENT_BYTES) {
        throw new Error('Statements must be 10 MB or smaller');
      }
      return api.detectStatement(user.id, candidate);
    },
  });
  const detectedInstitution = detectStatement.data?.institution?.toUpperCase();
  const compatibleAccounts = useMemo(() => {
    if (detectStatement.data?.product_type === 'credit_card') {
      return statementAccounts.filter((account) => account.account_type === 'credit_card');
    }
    if (detectStatement.data?.product_type === 'deposit_account') {
      return statementAccounts.filter(
        (account) =>
          account.account_type === 'bank' &&
          account.identity_status === 'confirmed' &&
          (!detectedInstitution ||
            account.institution_name.toUpperCase().includes(detectedInstitution)),
      );
    }
    return statementAccounts;
  }, [detectStatement.data?.product_type, detectedInstitution, statementAccounts]);
  const selectionEnabled = detectStatement.data?.support_status === 'supported';
  const selectedAccountId = selectionEnabled
    ? compatibleAccounts.some((account) => account.id === accountId)
      ? accountId
      : compatibleAccounts[0]?.id || ''
    : '';
  const importStatement = useMutation({
    mutationFn: ({
      targetAccountId,
      statementFile,
    }: {
      targetAccountId: string;
      statementFile: File;
    }) => {
      if (!user || !targetAccountId) {
        throw new Error('Choose a compatible account and PDF statement');
      }
      if (detectStatement.data?.support_status !== 'supported') {
        throw new Error('PFIS must recognize a supported statement before import');
      }
      return api.importStatement(user.id, targetAccountId, statementFile);
    },
    onSuccess: async (imported, variables) => {
      if (user) {
        const targetAccountId = variables.targetAccountId;
        const invalidations = [
          queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) }),
          queryClient.invalidateQueries({ queryKey: ['transactions', user.id] }),
          queryClient.invalidateQueries({ queryKey: queryKeys.statementReview(user.id) }),
          queryClient.invalidateQueries({
            queryKey: ['balanceForecast', user.id, targetAccountId],
          }),
        ];
        if (imported.product_type === 'credit_card') {
          invalidations.push(
            queryClient.invalidateQueries({
              queryKey: ['cardOverview', user.id, targetAccountId],
            }),
            queryClient.invalidateQueries({
              queryKey: ['cardDueRunway', user.id, targetAccountId],
            }),
          );
        }
        await Promise.all(invalidations);
      }
    },
  });
  const result = importStatement.data;
  const cardStatement = result?.credit_card_statement ?? null;
  const depositStatement = result?.deposit_account_statement ?? null;
  const resultLines = cardStatement?.lines ?? depositStatement?.lines ?? [];
  const outcomes = resultLines.reduce<Record<string, number>>((counts, line) => {
    counts[line.review_outcome] = (counts[line.review_outcome] ?? 0) + 1;
    return counts;
  }, {});
  const detection = detectStatement.data;
  const institutionLabel = detection?.institution
    ? detection.institution.toUpperCase()
    : 'Unidentified issuer';
  const productLabel =
    detection?.product_type === 'credit_card'
      ? `${institutionLabel} credit card`
      : detection?.product_type === 'deposit_account'
        ? `${institutionLabel} bank account`
        : 'Statement type pending';
  const detectionBlocked = Boolean(detection && detection.support_status !== 'supported');

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !selectedAccountId) return;
    importStatement.mutate({ targetAccountId: selectedAccountId, statementFile: file });
  }

  function chooseFile(candidate: File | null) {
    setFile(candidate);
    setAccountId('');
    setFileError('');
    importStatement.reset();
    detectStatement.reset();
    if (!candidate) return;
    if (candidate.size > MAX_STATEMENT_BYTES) {
      setFileError('Statements must be 10 MB or smaller');
      return;
    }
    detectStatement.mutate(candidate);
  }

  return (
    <div className="space-y-6">
      <FinancialHero className="bg-intelligence/10">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(17rem,0.8fr)] lg:items-end">
          <div>
            <div className="flex items-center gap-2 text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              <ShieldCheck className="h-4 w-4 text-intelligence" aria-hidden="true" />
              STATEMENT EVIDENCE INTAKE
            </div>
            <h2 className="mt-2 text-3xl font-extrabold tracking-[-0.05em]">
              Let the document identify itself.
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              PFIS reads a digital statement in memory, identifies whether it belongs to a card or
              bank account, then asks for the matching owned account before adding ledger evidence.
            </p>
          </div>
          <div className="rounded-lg bg-card/70 p-4">
            <div className="flex items-start gap-3">
              <LockKeyhole className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
              <div>
                <p className="text-sm font-extrabold">Extract, then delete</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  PDF bytes, passwords, full account numbers, addresses, and contact details are not
                  retained.
                </p>
              </div>
            </div>
          </div>
        </div>
      </FinancialHero>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="statement-upload-title">
          <h2 id="statement-upload-title" className="text-lg font-extrabold tracking-[-0.025em]">
            Import a statement
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            Choose the file first. PFIS checks its institution, product, layout, and observed rails
            before enabling account selection and import.
          </p>
          <form className="mt-5 space-y-4" onSubmit={submit}>
            <div className="space-y-1.5">
              <Label htmlFor="statement-account">Matching financial account</Label>
              <Select
                id="statement-account"
                value={selectedAccountId}
                onChange={(event) => setAccountId(event.target.value)}
                disabled={!detection || detectionBlocked || !compatibleAccounts.length}
                required
              >
                {!selectionEnabled ? (
                  <option value="">Choose a file to match an account</option>
                ) : null}
                {!compatibleAccounts.length && selectionEnabled ? (
                  <option value="">Add a compatible account first</option>
                ) : null}
                {compatibleAccounts.map((card) => (
                  <option key={card.id} value={card.id}>
                    {card.institution_name} · {card.masked_number}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="statement-file">Digital PDF</Label>
              <input
                id="statement-file"
                type="file"
                accept="application/pdf,.pdf"
                name="statement_pdf"
                autoComplete="off"
                className="focus-ring min-h-11 w-full rounded-lg border border-input bg-card/80 px-3.5 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1.5 file:text-xs file:font-bold"
                onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
                required
              />
              <p className="text-xs text-muted-foreground">Maximum 10 MB. No password entry.</p>
            </div>
            <Button
              type="submit"
              disabled={
                !file ||
                !selectedAccountId ||
                detection?.support_status !== 'supported' ||
                detectStatement.isPending ||
                importStatement.isPending
              }
            >
              <FileUp className="h-4 w-4" aria-hidden="true" />
              {importStatement.isPending ? 'Importing…' : 'Import verified statement'}
            </Button>
            {fileError || detectStatement.error || importStatement.error ? (
              <p role="alert" className="text-sm font-bold text-danger">
                {fileError || detectStatement.error?.message || importStatement.error?.message}
              </p>
            ) : null}
            {detectionBlocked ? (
              <p role="status" className="text-sm font-bold text-warning">
                This statement family is recognized, but its exact layout is not write-enabled. No
                ledger data changed; use a reviewed digital layout supported by PFIS.
              </p>
            ) : null}
          </form>
          <div
            className="mt-5 grid gap-2 rounded-lg bg-muted/55 p-3 sm:grid-cols-[1fr_auto_1fr_auto_1fr] sm:items-center"
            role="status"
            aria-live="polite"
          >
            <EvidenceStep
              icon={<FileSearch className="h-4 w-4" aria-hidden="true" />}
              label="Source"
              value={detectStatement.isPending ? 'Reading PDF…' : file?.name || 'Choose a PDF'}
            />
            <ArrowRight
              className="hidden h-4 w-4 text-muted-foreground sm:block"
              aria-hidden="true"
            />
            <EvidenceStep
              icon={<ShieldCheck className="h-4 w-4" aria-hidden="true" />}
              label="Recognized as"
              value={
                detectionBlocked
                  ? `${productLabel} · review required`
                  : detection
                    ? productLabel
                    : 'Waiting for source'
              }
            />
            <ArrowRight
              className="hidden h-4 w-4 text-muted-foreground sm:block"
              aria-hidden="true"
            />
            <EvidenceStep
              icon={<Landmark className="h-4 w-4" aria-hidden="true" />}
              label="Ledger destination"
              value={
                selectedAccountId
                  ? compatibleAccounts.find((account) => account.id === selectedAccountId)
                      ?.masked_number || 'Owned account selected'
                  : 'Needs a matching account'
              }
            />
          </div>
        </section>

        <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="statement-result-title">
          <div className="flex items-start gap-3">
            <span className="bg-success/12 grid h-10 w-10 shrink-0 place-items-center rounded-lg text-success">
              {result ? (
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              ) : (
                <FileCheck2 className="h-4 w-4" aria-hidden="true" />
              )}
            </span>
            <div>
              <h2
                id="statement-result-title"
                className="text-lg font-extrabold tracking-[-0.025em]"
              >
                {result ? 'Import reconciled' : 'Waiting for a supported statement'}
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {result
                  ? 'Every source line has an outcome; uncertain rows remain outside the ledger for review.'
                  : 'The receipt will distinguish observed statement facts, imported activity, and review evidence.'}
              </p>
            </div>
          </div>
          {result ? (
            <>
              <dl className="mt-5 grid grid-cols-2 gap-4 rounded-lg bg-muted/55 p-4 sm:grid-cols-3">
                <div>
                  <dt className="text-xs font-bold text-muted-foreground">
                    {cardStatement ? 'Statement date' : 'Period end'}
                  </dt>
                  <dd className="mt-1 text-sm font-extrabold">
                    {formatDate(cardStatement?.statement_date ?? depositStatement!.period_end)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-bold text-muted-foreground">
                    {cardStatement ? 'Total due' : 'Closing balance'}
                  </dt>
                  <dd className="money-value mt-1 text-sm font-extrabold">
                    {cardStatement
                      ? cardStatement.total_due == null
                        ? '—'
                        : formatCurrency(cardStatement.total_due, cardStatement.currency)
                      : formatCurrency(
                          depositStatement!.closing_balance,
                          depositStatement!.currency,
                        )}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-bold text-muted-foreground">
                    {cardStatement ? 'Due date' : 'Opening balance'}
                  </dt>
                  <dd className="mt-1 text-sm font-extrabold">
                    {cardStatement
                      ? cardStatement.due_date
                        ? formatDate(cardStatement.due_date)
                        : '—'
                      : formatCurrency(
                          depositStatement!.opening_balance,
                          depositStatement!.currency,
                        )}
                  </dd>
                </div>
              </dl>
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  ['Matched', outcomes.matched ?? 0],
                  ['Imported', outcomes.newly_imported ?? 0],
                  ['Review', outcomes.needs_review ?? 0],
                  ['Held', outcomes.ignored_by_rule ?? 0],
                ].map(([label, count]) => (
                  <div key={label} className="rounded-lg border border-border/65 p-3">
                    <p className="money-value text-lg font-extrabold">{count}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{label}</p>
                  </div>
                ))}
              </div>
              <div className="mt-4">
                <Badge variant={(outcomes.needs_review ?? 0) ? 'warning' : 'success'}>
                  {(outcomes.needs_review ?? 0)
                    ? `${outcomes.needs_review} lines need evidence review`
                    : 'All lines settled'}
                </Badge>
              </div>
            </>
          ) : (
            <div className="mt-5 rounded-lg border border-dashed border-border p-6 text-sm leading-6 text-muted-foreground">
              Recognition does not write money. Import stays locked until the document profile and
              selected account identity both pass their evidence checks.
            </div>
          )}
        </section>
      </div>
      <StatementAnalysisReviewPanel file={file} detection={detection} />
      <DepositStatementReviewPanel />
      {!statementAccounts.length && !accounts.isLoading ? (
        <EmptyState
          icon={<Landmark className="h-5 w-5" aria-hidden="true" />}
          title="Add a bank or credit-card account"
          description="PFIS needs a confirmed masked account identity before a recognized statement can enter the ledger."
        />
      ) : null}
      <AccountLinkRulesSection />
    </div>
  );
}

function EvidenceStep({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-start gap-2">
      <span className="mt-0.5 shrink-0 text-intelligence">{icon}</span>
      <div className="min-w-0">
        <p className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-muted-foreground">
          {label}
        </p>
        <p className="truncate text-xs font-bold" title={value}>
          {value}
        </p>
      </div>
    </div>
  );
}

function AccountLinkRulesSection() {
  const { user } = useAuth();
  const accounts = useAccounts();
  const rules = useAccountLinkRules();
  const queryClient = useQueryClient();
  const eligibleAccounts = (accounts.data ?? []).filter(
    (account) => account.is_active && account.account_type !== 'unknown',
  );
  const [accountId, setAccountId] = useState('');
  const selected =
    eligibleAccounts.find((account) => account.id === accountId) ?? eligibleAccounts[0] ?? null;
  const suffix = selected?.masked_number.replace(/\D/g, '').slice(-4) ?? '';
  const createRule = useMutation({
    mutationFn: () => {
      if (!user || !selected || suffix.length !== 4) {
        throw new Error('Choose an account with a four-digit masked suffix');
      }
      return api.createAccountLinkRule(user.id, {
        financial_account_id: selected.id,
        evidence_kind: 'masked_suffix',
        evidence_value: suffix,
        currency: selected.currency,
      });
    },
    onSuccess: async () => {
      if (!user) return;
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.accountLinkRules(user.id),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts(user.id) }),
      ]);
    },
  });
  const deactivateRule = useMutation({
    mutationFn: (ruleId: string) => api.deactivateAccountLinkRule(user!.id, ruleId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.accountLinkRules(user!.id),
      });
    },
  });

  return (
    <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="account-link-title">
      <div className="flex items-start gap-3">
        <span className="bg-intelligence/12 grid h-10 w-10 shrink-0 place-items-center rounded-lg text-intelligence">
          <Link2 className="h-4 w-4" aria-hidden="true" />
        </span>
        <div>
          <h2 id="account-link-title" className="text-lg font-extrabold tracking-[-0.025em]">
            Approved account linking
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            Approve a masked suffix only when it uniquely identifies this product. The rule repairs
            unambiguous historical imports and guides future email activity without overwriting an
            earlier manual correction.
          </p>
        </div>
      </div>

      {eligibleAccounts.length ? (
        <form
          className="mt-5 grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            createRule.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="account-link-product">Financial product</Label>
            <Select
              id="account-link-product"
              value={selected?.id ?? ''}
              onChange={(event) => setAccountId(event.target.value)}
            >
              {eligibleAccounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.institution_name} · {account.account_type.replace('_', ' ')} ·{' '}
                  {account.masked_number}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" disabled={createRule.isPending || suffix.length !== 4}>
            Approve suffix {suffix ? `••••${suffix}` : ''}
          </Button>
        </form>
      ) : (
        <p className="mt-5 text-sm text-muted-foreground">
          Add a validated bank, card, loan, pay-later, cash, or investment account first.
        </p>
      )}

      {createRule.data ? (
        <p role="status" className="mt-3 text-sm font-bold text-success">
          Rule approved. {createRule.data.repaired_transaction_count} historical transaction
          {createRule.data.repaired_transaction_count === 1 ? '' : 's'} repaired.
        </p>
      ) : null}
      {createRule.error ? (
        <p role="alert" className="mt-3 text-sm font-bold text-danger">
          {createRule.error.message}
        </p>
      ) : null}

      {(rules.data ?? []).length ? (
        <ul className="mt-5 divide-y divide-border/70 border-y border-border/70">
          {(rules.data ?? []).map((rule) => {
            const account = eligibleAccounts.find(
              (candidate) => candidate.id === rule.financial_account_id,
            );
            return (
              <li
                key={rule.id}
                className="flex min-w-0 flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-extrabold">
                    {account?.institution_name ?? 'Inactive product'} · ••••
                    {rule.evidence_value}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {rule.is_active ? 'Approved for future imports' : 'Inactive'} · {rule.currency}
                  </p>
                </div>
                {rule.is_active ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => deactivateRule.mutate(rule.id)}
                    disabled={deactivateRule.isPending}
                  >
                    <Unlink className="h-4 w-4" aria-hidden="true" />
                    Deactivate
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
