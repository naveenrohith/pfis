# Parser Corpus

This directory is the regression corpus for sanitized financial-notification
formats. Each JSON case has an opaque `id`, parser input, and its expected
deterministic extraction result. Transaction cases also carry a stable
`format_id` so repeated examples of one provider layout cannot be mistaken for
format diversity.

Do not commit real emails, full account numbers, email addresses, reference numbers, OAuth material, or personally identifiable spending data. Replace values with synthetic equivalents while preserving the notification structure.

Add a corpus case whenever a production format is fixed. A parser change is accepted only after the complete corpus passes.

Every case is fixture-only unless it carries an explicit `cohort` value. Use
`cohort: "sanitized_production"` only for a de-identified, adjudicated sample
whose layout and expected fields are traceable to a real supported source;
`production_safe` is reserved for an independently reviewed release cohort.
Unlabelled cases intentionally remain `synthetic_fixture` in the quality report
and cannot satisfy the representative release gate.

Representative labels are not release evidence by themselves. Create an
independent cohort manifest and pass it with `--cohort-manifest`; the manifest
must pin the evaluated corpus fingerprint, list opaque case IDs, and attest that
the cases are de-identified and independently reviewed. Cases absent from the
manifest remain fixture-only. A missing, stale, or malformed manifest keeps the
strict release gate deferred (or failed when the manifest is invalid).

`transaction_alerts.json` measures field extraction and confidence.
`source_classification.json` measures financial/non-financial routing and
institution recognition. Run `python scripts/evaluate_parser_corpus.py` to emit
the content-addressed version 2 quality report; add
`--cohort-manifest <manifest.json>` for independently attested representative
evidence. The report publishes cohort coverage (cases, formats, institutions)
without exposing message bodies. The default gate enforces exact accuracy, macro
recall, critical-field accuracy, representative-cohort coverage, and
non-shrinking corpus case counts. Use `--baseline <report.json>` to reject
comparable metric regressions.
