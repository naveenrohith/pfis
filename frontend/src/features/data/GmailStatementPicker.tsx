import { useEffect, useMemo, useRef, useState } from 'react';
import { FileSearch, Link2, Mail, RefreshCw, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { Label, Select } from '@/components/ui/Input';
import { useAutoSyncStatus } from '@/features/workspace/queries';
import { api, ApiError } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/format';
import type {
  FinancialAccount,
  GmailStatementCandidate,
  GmailStatementDetectionResponse,
  StatementImportResult,
} from '@/lib/types';

type Props = {
  userId: string;
  accounts: FinancialAccount[];
  onImported: (result: StatementImportResult, accountId: string) => void;
};

function dateValue(date: Date) {
  return date.toISOString().slice(0, 10);
}

function defaultDates() {
  const end = new Date();
  end.setUTCDate(end.getUTCDate() + 1);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 365);
  return { start: dateValue(start), end: dateValue(end) };
}

export function GmailStatementPicker({ userId, accounts, onImported }: Props) {
  const autoSync = useAutoSyncStatus();
  const [dates, setDates] = useState(defaultDates);
  const [candidates, setCandidates] = useState<GmailStatementCandidate[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [coverageComplete, setCoverageComplete] = useState(true);
  const [messageFailures, setMessageFailures] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [selected, setSelected] = useState<GmailStatementCandidate | null>(null);
  const [detection, setDetection] = useState<GmailStatementDetectionResponse | null>(null);
  const [accountId, setAccountId] = useState('');
  const [password, setPassword] = useState('');
  const passwordRef = useRef('');
  const requestVersion = useRef(0);
  const searchVersion = useRef(0);
  const importPending = useRef(false);
  const [isSearching, setIsSearching] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState('');

  const statementAccounts = useMemo(
    () =>
      accounts.filter(
        (account) =>
          account.is_active &&
          (account.account_type === 'credit_card' || account.account_type === 'bank'),
      ),
    [accounts],
  );
  const compatibleAccounts = useMemo(() => {
    const type = detection?.detection?.product_type;
    const institution = detection?.detection?.institution?.toUpperCase();
    if (type === 'credit_card')
      return statementAccounts.filter(
        (account) =>
          account.account_type === 'credit_card' &&
          (institution !== 'HDFC' || account.institution_name.toUpperCase().includes('HDFC')),
      );
    if (type === 'deposit_account')
      return statementAccounts.filter(
        (account) =>
          account.account_type === 'bank' &&
          account.identity_status === 'confirmed' &&
          (!institution || account.institution_name.toUpperCase().includes(institution)),
      );
    return [];
  }, [detection, statementAccounts]);

  useEffect(() => {
    setAccountId((current) =>
      compatibleAccounts.some((account) => account.id === current)
        ? current
        : (compatibleAccounts[0]?.id ?? ''),
    );
  }, [compatibleAccounts]);

  const disconnected = autoSync.isSuccess && autoSync.data === null;
  const needsReconnect = autoSync.data?.connection_status === 'reauthorization_required';
  const connected = autoSync.isSuccess && !disconnected && !needsReconnect;

  useEffect(() => {
    if (!connected) {
      requestVersion.current += 1;
      searchVersion.current += 1;
      passwordRef.current = '';
      setPassword('');
      setSelected(null);
      setDetection(null);
      setAccountId('');
      setCandidates([]);
      setCursor(null);
      setCoverageComplete(true);
      setMessageFailures(0);
      setTruncated(false);
      setError('');
      setIsSearching(false);
      setIsDetecting(false);
      setIsImporting(false);
    }
  }, [connected]);

  useEffect(
    () => () => {
      requestVersion.current += 1;
      searchVersion.current += 1;
      passwordRef.current = '';
    },
    [userId],
  );

  function clearSecret() {
    passwordRef.current = '';
    setPassword('');
  }

  function clearSelection() {
    requestVersion.current += 1;
    setSelected(null);
    setDetection(null);
    setAccountId('');
    setError('');
    setIsDetecting(false);
    clearSecret();
  }

  async function search(nextCursor?: string | null) {
    const version = ++searchVersion.current;
    if (!nextCursor) clearSelection();
    setIsSearching(true);
    setError('');
    try {
      const result = await api.gmailStatementCandidates(userId, {
        startDate: dates.start,
        endDate: dates.end,
        cursor: nextCursor,
      });
      if (version !== searchVersion.current) return;
      setCandidates((current) =>
        nextCursor ? [...current, ...result.candidates] : result.candidates,
      );
      setCursor(result.next_cursor);
      setMessageFailures((current) =>
        nextCursor ? current + result.message_failures : result.message_failures,
      );
      setTruncated((current) => (nextCursor ? current || result.truncated : result.truncated));
      setCoverageComplete(result.coverage_complete);
    } catch (cause) {
      if (version !== searchVersion.current) return;
      setError(cause instanceof ApiError ? cause.message : 'Gmail statements could not be loaded.');
    } finally {
      if (version === searchVersion.current) setIsSearching(false);
    }
  }

  async function selectCandidate(candidate: GmailStatementCandidate) {
    const version = ++requestVersion.current;
    clearSecret();
    setSelected(candidate);
    setDetection(null);
    setAccountId('');
    setError('');
    setIsDetecting(true);
    try {
      const result = await api.detectGmailStatement(userId, candidate.source_ref);
      if (version !== requestVersion.current) return;
      setDetection(result);
    } catch (cause) {
      if (version === requestVersion.current)
        setError(cause instanceof ApiError ? cause.message : 'This attachment could not be read.');
    } finally {
      if (version === requestVersion.current) setIsDetecting(false);
    }
  }

  async function retryDetection() {
    if (!selected) return;
    const version = requestVersion.current;
    setIsDetecting(true);
    setError('');
    try {
      const result = await api.detectGmailStatement(
        userId,
        selected.source_ref,
        passwordRef.current || undefined,
      );
      if (version !== requestVersion.current) return;
      setDetection(result);
      // Keep the password only in the component ref until the explicit import.
      // The backend downloads and decrypts again; it never retains the PDF.
      if (result.status === 'detected') setPassword('');
    } catch (cause) {
      if (version === requestVersion.current)
        setError(
          cause instanceof ApiError ? cause.message : 'The attachment could not be detected.',
        );
    } finally {
      if (version === requestVersion.current) setIsDetecting(false);
    }
  }

  async function importSelected() {
    if (
      !selected ||
      importPending.current ||
      !accountId ||
      !detection?.document_fingerprint ||
      detection.status !== 'detected'
    )
      return;
    setIsImporting(true);
    importPending.current = true;
    setError('');
    const version = requestVersion.current;
    try {
      const result = await api.importGmailStatement(userId, {
        source_ref: selected.source_ref,
        ...(passwordRef.current ? { password: passwordRef.current } : {}),
        financial_account_id: accountId,
        document_fingerprint: detection.document_fingerprint,
      });
      if (version !== requestVersion.current) return;
      clearSecret();
      onImported(result, accountId);
    } catch (cause) {
      if (version === requestVersion.current)
        setError(
          cause instanceof ApiError ? cause.message : 'The statement could not be imported.',
        );
    } finally {
      importPending.current = false;
      if (version === requestVersion.current) setIsImporting(false);
    }
  }

  function handlePassword(value: string) {
    passwordRef.current = value;
    setPassword(value);
  }

  if (!connected) {
    return (
      <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="gmail-statement-title">
        <div className="flex items-start gap-3">
          <Mail className="mt-1 h-5 w-5 text-intelligence" aria-hidden="true" />
          <div>
            <h2 id="gmail-statement-title" className="text-lg font-extrabold">
              From Gmail
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Connect Gmail to choose a statement already in your mailbox.
            </p>
          </div>
        </div>
        <div className="mt-5 rounded-lg border border-dashed border-border p-4 text-sm leading-6">
          <p className="font-bold">
            {needsReconnect ? 'Gmail needs to be reconnected.' : 'Gmail is not connected.'}
          </p>
          <p className="mt-1 text-muted-foreground">
            Choose a PDF attachment, then check it before importing.
          </p>
          {api.gmailConnectUrl(userId) ? (
            <ButtonLink className="mt-4" href={api.gmailConnectUrl(userId)}>
              <Link2 className="h-4 w-4" aria-hidden="true" />
              {needsReconnect ? 'Reconnect Gmail' : 'Connect Gmail'}
            </ButtonLink>
          ) : null}
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-xl bg-card p-5 sm:p-6" aria-labelledby="gmail-statement-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Mail className="mt-1 h-5 w-5 text-intelligence" aria-hidden="true" />
          <div>
            <h2 id="gmail-statement-title" className="text-lg font-extrabold">
              Find a statement in Gmail
            </h2>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Choose dates, select an attachment, then check its detected profile before import.
            </p>
          </div>
        </div>
        <Badge variant="success">Gmail connected</Badge>
      </div>
      <div className="mt-5 grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <div className="space-y-1.5">
          <Label htmlFor="gmail-start-date">From</Label>
          <input
            id="gmail-start-date"
            name="statement-start-date"
            autoComplete="off"
            type="date"
            value={dates.start}
            max={dates.end}
            disabled={isSearching || isImporting}
            onChange={(event) => {
              clearSelection();
              setCandidates([]);
              setCursor(null);
              setDates((current) => ({ ...current, start: event.target.value }));
            }}
            className="focus-ring min-h-11 w-full rounded-lg border border-input bg-card px-3.5 text-sm"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="gmail-end-date">Before</Label>
          <input
            id="gmail-end-date"
            name="statement-end-date"
            autoComplete="off"
            type="date"
            value={dates.end}
            min={dates.start}
            disabled={isSearching || isImporting}
            onChange={(event) => {
              clearSelection();
              setCandidates([]);
              setCursor(null);
              setDates((current) => ({ ...current, end: event.target.value }));
            }}
            className="focus-ring min-h-11 w-full rounded-lg border border-input bg-card px-3.5 text-sm"
          />
        </div>
        <Button type="button" onClick={() => search()} disabled={isSearching || isImporting}>
          <RefreshCw
            className={`h-4 w-4 motion-reduce:animate-none ${isSearching ? 'animate-spin' : ''}`}
            aria-hidden="true"
          />
          {isSearching ? 'Searching…' : 'Search Gmail'}
        </Button>
      </div>
      {messageFailures || truncated || !coverageComplete ? (
        <p className="mt-3 text-xs leading-5 text-warning">
          Some messages could not be checked or the window was capped. Search an older, smaller
          window if the statement you expect is missing.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-3 text-sm font-bold text-danger">
          {error}
        </p>
      ) : null}
      {candidates.length ? (
        <div className="mt-5 space-y-2" aria-label="Gmail statement candidates">
          {candidates.map((candidate) => (
            <button
              type="button"
              key={candidate.source_ref}
              onClick={() => selectCandidate(candidate)}
              disabled={isImporting}
              aria-pressed={selected?.source_ref === candidate.source_ref}
              style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 96px' }}
              className={`focus-ring w-full rounded-lg border p-3 text-left transition-colors ${selected?.source_ref === candidate.source_ref ? 'bg-intelligence/8 border-intelligence' : 'border-border/70 hover:bg-muted/45'}`}
            >
              <span className="flex items-start justify-between gap-3">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-extrabold">
                    {candidate.filename}
                  </span>
                  <span className="mt-1 block truncate text-xs text-muted-foreground">
                    {candidate.sender} · {candidate.subject}
                  </span>
                  {candidate.received_at ? (
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {formatDate(candidate.received_at)}
                    </span>
                  ) : null}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {Math.ceil(candidate.size_bytes / 1024)} KB
                </span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="mt-5 rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
          Search to see statement attachments from the selected window.
        </p>
      )}
      {cursor ? (
        <Button
          type="button"
          variant="outline"
          className="mt-3"
          onClick={() => search(cursor)}
          disabled={isSearching || isImporting}
        >
          Show older candidates
        </Button>
      ) : null}
      {selected ? (
        <div className="mt-5 rounded-lg bg-muted/55 p-4">
          <div className="flex items-start gap-2">
            <FileSearch className="mt-0.5 h-4 w-4 text-intelligence" aria-hidden="true" />
            <div>
              <p className="text-sm font-extrabold">{selected.filename}</p>
              <p className="mt-1 text-xs text-muted-foreground" aria-live="polite">
                {isDetecting
                  ? 'Reading attachment…'
                  : detection?.detection
                    ? `${detection.detection.institution?.toUpperCase() ?? 'Unidentified issuer'} · ${detection.detection.product_type.replace('_', ' ')}`
                    : 'Detection pending'}
              </p>
            </div>
          </div>
          {detection?.detection?.analysis ? (
            <div className="mt-4 space-y-2" aria-label="Statement preview">
              <p className="text-sm font-bold">
                {detection.detection.analysis.row_count} detected rows ·{' '}
                {detection.detection.analysis.status.replace('_', ' ')}
              </p>
              {detection.detection.analysis.lines.map((line) => (
                <div
                  key={line.line_number}
                  className="flex flex-wrap justify-between gap-2 text-xs"
                >
                  <span className="min-w-0 break-words">
                    {line.transaction_date ? formatDate(line.transaction_date) : 'Date unconfirmed'}{' '}
                    · {line.description}
                  </span>
                  <span>
                    {line.direction} ·{' '}
                    {line.amount == null ? 'Amount unconfirmed' : formatCurrency(line.amount)}
                  </span>
                </div>
              ))}
              {detection.detection.analysis.omitted_line_count > 0 ? (
                <p className="text-xs text-muted-foreground">
                  {detection.detection.analysis.omitted_line_count} additional rows omitted from
                  this preview.
                </p>
              ) : null}
            </div>
          ) : null}
          {detection?.status === 'password_required' ||
          detection?.status === 'incorrect_password' ? (
            <div className="mt-4 space-y-2">
              <Label htmlFor="gmail-pdf-password">PDF password</Label>
              <input
                id="gmail-pdf-password"
                name="statement-pdf-password"
                maxLength={256}
                type="password"
                value={password}
                onChange={(event) => handlePassword(event.target.value)}
                autoComplete="off"
                className="focus-ring min-h-11 w-full rounded-lg border border-input bg-card px-3.5 text-sm"
              />
              <p className="text-xs text-muted-foreground">
                The password stays in memory until import and is cleared when you change source or
                attachment.
              </p>
              <Button type="button" onClick={retryDetection} disabled={!password || isDetecting}>
                {isDetecting
                  ? 'Checking…'
                  : detection.status === 'incorrect_password'
                    ? 'Try password again'
                    : 'Unlock and detect'}
              </Button>
            </div>
          ) : null}
          {detection?.status === 'detected' &&
          detection.detection?.support_status !== 'supported' ? (
            <p role="status" className="mt-4 text-sm font-bold text-warning">
              PFIS recognized this statement family, but this layout remains read-only until
              reviewed.
            </p>
          ) : null}
          {detection?.status === 'detected' &&
          detection.detection?.support_status === 'supported' ? (
            <div className="mt-4 space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="gmail-statement-account">Matching financial account</Label>
                <Select
                  id="gmail-statement-account"
                  value={accountId}
                  onChange={(event) => setAccountId(event.target.value)}
                  disabled={!compatibleAccounts.length}
                >
                  <option value="">Choose a compatible account</option>
                  {compatibleAccounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.institution_name} · {account.masked_number}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <ShieldCheck className="h-4 w-4 text-success" aria-hidden="true" />
                Detected profile verified before ledger import.
              </div>
              <Button type="button" onClick={importSelected} disabled={!accountId || isImporting}>
                {isImporting ? 'Importing…' : 'Import verified statement'}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
