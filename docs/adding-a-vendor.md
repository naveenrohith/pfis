# Adding A Financial Source Or Parser

This filename is kept for compatibility with the agent workflow. PFIS does not have utility vendors. In PFIS, "vendor" maps to a financial source such as a bank, card issuer, UPI app, or email sender.

## Add A New Source

1. Identify sender domains and sample email formats.
2. Add or update sender classification.
3. Add bank/source parser patterns.
4. Add expected parser outputs to tests.
5. Verify demo or fixture sync produces raw emails and pipeline output.
6. Document source-specific behavior in `docs/parser.md`.

## Required Test Samples

Cover debit, credit, refund, UPI, card, missing merchant, missing reference ID, and HTML-only body when applicable.

