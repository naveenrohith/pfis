# Parser Corpus

This directory is the regression corpus for sanitized financial-notification formats. Each JSON case has an opaque `id`, parser input, and its expected deterministic extraction result.

Do not commit real emails, full account numbers, email addresses, reference numbers, OAuth material, or personally identifiable spending data. Replace values with synthetic equivalents while preserving the notification structure.

Add a corpus case whenever a production format is fixed. A parser change is accepted only after the complete corpus passes.
