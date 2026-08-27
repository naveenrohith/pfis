import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, FileCheck2, FileSearch, LockKeyhole, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/features/auth/AuthContext';
import { queryKeys, useStatementAnalysisReviews } from '@/features/workspace/queries';
import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/format';
import type { StatementAnalysisReview, StatementDetection } from '@/lib/types';

const supportCopy: Record<StatementAnalysisReview['support_status'], string> = {
  supported: 'Profile is write-enabled',
  recognized_not_supported: 'Recognized layout needs review',
  ambiguous: 'Product or direction is ambiguous',
  unsupported: 'Issuer/layout is unsupported',
};

const reviewStatusCopy: Record<StatementAnalysisReview['status'], string> = {
  ready_to_import: 'Ready for explicit account mapping',
  pending_review: 'Pending layout/account review',
};

const analysisStatusCopy: Record<StatementAnalysisReview['analysis']['status'], string> = {
  available: 'Analysis available',
  partial: 'Partial analysis',
  signature_only: 'Signature-only analysis',
  failed: 'Analysis failed',
};

function productLabel(item: Pick<StatementAnalysisReview, 'institution' | 'product_type'>): string {
  const institution = item.institution?.toUpperCase() ?? 'Unidentified issuer';
  if (item.product_type === 'credit_card') return `${institution} credit card`;
  if (item.product_type === 'deposit_account') return `${institution} bank account`;
  return `${institution} statement`;
}

function reconciliationLabel(value: boolean | null | undefined): string {
  if (value === true) return 'Balance chain reconciled';
  if (value === false) return 'Balance chain needs review';
  return 'Balance chain not proven';
}

export function StatementAnalysisReviewPanel({
  file,
  detection,
}: {
  file?: File | null;
  detection?: StatementDetection;
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const reviews = useStatementAnalysisReviews();
  const saveReview = useMutation({
    mutationFn: (candidate: File) => {
      if (!user) throw new Error('Sign in before saving a statement analysis');
      return api.reviewStatementPdf(user.id, candidate);
    },
    onSuccess: async () => {
      if (!user) return;
      await queryClient.invalidateQueries({
        queryKey: queryKeys.statementAnalysisReviews(user.id),
      });
    },
  });

  const items = reviews.data ?? [];
  const hasSurface =
    Boolean(file) || reviews.isLoading || Boolean(reviews.error) || items.length > 0;
  if (!hasSurface) return null;

  return (
    <section
      className="rounded-xl border border-border/70 bg-card p-5 sm:p-6"
      aria-labelledby="statement-analysis-review-title"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-intelligence/10 text-intelligence">
            <FileSearch className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              STATEMENT ANALYSIS REVIEW
            </p>
            <h2
              id="statement-analysis-review-title"
              className="mt-1 text-xl font-extrabold tracking-[-0.03em]"
            >
              Keep unfamiliar layouts reviewable
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
              Save only detection metadata and a small redacted row preview. The PDF bytes, source
              text, and ledger activity are not retained by this review path.
            </p>
          </div>
        </div>
        <LockKeyhole className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
      </div>

      {file ? (
        <div className="mt-4 flex flex-col gap-3 rounded-lg border border-intelligence/20 bg-intelligence/5 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-sm font-extrabold">
              <FileCheck2 className="h-4 w-4 shrink-0 text-intelligence" aria-hidden="true" />
              {file.name}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {detection
                ? `${productLabel(detection)} / ${supportCopy[detection.support_status]}`
                : 'Recognition is still running; the bounded review can be saved explicitly.'}
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            disabled={saveReview.isPending}
            onClick={() => saveReview.mutate(file)}
          >
            {saveReview.isPending ? 'Saving…' : 'Save redacted analysis'}
          </Button>
        </div>
      ) : null}

      {saveReview.error ? (
        <p role="alert" className="mt-3 text-sm font-bold text-danger">
          Analysis could not be saved. Refresh the Statements workspace and try again; no ledger
          data changed.
        </p>
      ) : null}
      {saveReview.data ? (
        <p role="status" className="mt-3 text-sm font-bold text-success" aria-live="polite">
          Redacted analysis saved. Account mapping and import remain separate explicit steps.
        </p>
      ) : null}

      {reviews.isLoading ? (
        <div
          className="mt-4 animate-soft-pulse space-y-3"
          role="status"
          aria-label="Loading statement review artifacts…"
        >
          <div className="h-5 w-64 rounded bg-muted" />
          <div className="h-20 rounded-lg bg-muted/70" />
        </div>
      ) : null}
      {reviews.error ? (
        <p role="alert" className="mt-4 text-sm font-bold text-danger">
          Saved analyses could not be loaded. No statement source or ledger row was exposed.
        </p>
      ) : null}

      {items.length ? (
        <div className="mt-5 space-y-3">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-xs font-extrabold tracking-[0.08em] text-muted-foreground">
              SAVED ANALYSIS ARTIFACTS
            </p>
            <p className="text-xs text-muted-foreground">{items.length} retained</p>
          </div>
          <ul className="space-y-3">
            {items.slice(0, 50).map((item) => (
              <ReviewArtifact key={item.id} item={item} currency={user?.currency ?? 'INR'} />
            ))}
          </ul>
          {items.length > 50 ? (
            <p className="text-xs leading-5 text-muted-foreground">
              Showing the newest 50 artifacts. Older artifacts remain owned but are not loaded here.
            </p>
          ) : null}
        </div>
      ) : !file && !reviews.isLoading && !reviews.error ? (
        <p className="mt-4 rounded-lg border border-dashed border-border p-4 text-sm leading-6 text-muted-foreground">
          No saved analysis artifacts yet. Choose a statement above, then save its bounded analysis
          when the layout needs review.
        </p>
      ) : null}
    </section>
  );
}

function ReviewArtifact({ item, currency }: { item: StatementAnalysisReview; currency: string }) {
  const analysis = item.analysis;
  return (
    <li className="rounded-lg border border-border/65 bg-muted/20 p-4">
      <details>
        <summary className="focus-ring cursor-pointer rounded">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="truncate text-sm font-extrabold">{productLabel(item)}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {reviewStatusCopy[item.status]} / {supportCopy[item.support_status]}
              </p>
            </div>
            <span className="shrink-0 text-xs font-extrabold text-muted-foreground">
              {formatDate(item.created_at)} / {Math.round(item.confidence * 100)}% confidence
            </span>
          </div>
        </summary>
        <div className="mt-4 border-t border-border/65 pt-4">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Analysis</dt>
              <dd className="mt-1 text-sm font-extrabold">{analysisStatusCopy[analysis.status]}</dd>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Period</dt>
              <dd className="mt-1 text-sm font-extrabold">
                {analysis.period_start && analysis.period_end
                  ? `${formatDate(analysis.period_start)} - ${formatDate(analysis.period_end)}`
                  : 'Not available'}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Debit / credit</dt>
              <dd className="money-value mt-1 text-sm font-extrabold">
                {formatCurrency(analysis.debit_total, currency)} /{' '}
                {formatCurrency(analysis.credit_total, currency)}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-bold text-muted-foreground">Balance evidence</dt>
              <dd className="mt-1 text-sm font-extrabold">
                {reconciliationLabel(analysis.reconciled)}
              </dd>
            </div>
          </dl>

          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
            <span>{analysis.row_count} rows observed</span>
            <span>{analysis.preview_count} previewed</span>
            {analysis.omitted_line_count ? (
              <span>{analysis.omitted_line_count} omitted</span>
            ) : null}
            <span>Source: {analysis.source_kind.replaceAll('_', ' ')}</span>
            <span>Ruleset: {analysis.ruleset_version}</span>
          </div>

          {analysis.lines.length ? (
            <div className="mt-4 overflow-x-auto rounded-lg border border-border/65 bg-card/70">
              <table className="w-full min-w-[56rem] border-collapse text-left text-sm">
                <caption className="sr-only">Redacted statement analysis preview</caption>
                <thead>
                  <tr className="border-b border-border/65 text-xs text-muted-foreground">
                    <th scope="col" className="px-3 py-2 font-bold">
                      Date
                    </th>
                    <th scope="col" className="px-3 py-2 font-bold">
                      Description
                    </th>
                    <th scope="col" className="px-3 py-2 font-bold">
                      Direction / rail
                    </th>
                    <th scope="col" className="px-3 py-2 font-bold">
                      Amount
                    </th>
                    <th scope="col" className="px-3 py-2 font-bold">
                      Confidence
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.lines.slice(0, 25).map((line) => (
                    <tr key={line.line_number} className="border-b border-border/45 last:border-0">
                      <td className="whitespace-nowrap px-3 py-2 font-bold">
                        {formatDate(line.transaction_date)}
                      </td>
                      <td className="max-w-[22rem] break-words px-3 py-2">{line.description}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                        {line.direction} / {line.payment_rail}
                      </td>
                      <td className="money-value whitespace-nowrap px-3 py-2">
                        {line.amount == null
                          ? 'Unavailable'
                          : formatCurrency(line.amount, currency)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                        {Math.round(line.confidence * 100)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-4 flex items-start gap-2 text-sm leading-6 text-muted-foreground">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
              No row preview was safe to retain. Keep the artifact in review until an explicit
              layout/account decision is available.
            </p>
          )}

          <p className="mt-4 flex items-start gap-2 text-xs leading-5 text-muted-foreground">
            <ShieldCheck
              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-intelligence"
              aria-hidden="true"
            />
            <span>
              This is bounded analysis evidence only. PFIS did not retain source text or PDF bytes,
              and this artifact does not import a transaction or balance.
            </span>
          </p>
        </div>
      </details>
    </li>
  );
}
