# PFIS Product Feature Roadmap

This is the consolidated record of the product discussion. It preserves every
feature idea discussed so far, while separating the approved core direction
from enabling capabilities, later opportunities, and ideas deliberately not
being built now.

PFIS should remain transparent and deterministic. Every financial calculation
must identify its source, its as-of date, and whether it is verified or an
estimate.

## Product Model

PFIS should organise the product around financial positions and obligations,
not merely around payment labels.

```text
Bank account
  -> spending routes: UPI, debit card, ATM, transfer

Credit card
  -> bill, due date, limit, payments, statement, card EMI

Loan / EMI
  -> outstanding principal, monthly EMI, tenure, next due date
```

- A **credit card** is a liability product. It has a statement, bill, due date,
  limit, and potentially EMIs, so it merits a detailed workspace.
- A **debit card** is a way to spend from a bank account. It has no separate
  outstanding amount or billing cycle, so debit-card activity belongs inside a
  bank-account view.
- **UPI** is a payment rail. It may be funded by a bank account or an eligible
  credit card. It is useful as a transaction filter and funding-source signal,
  but it is not itself an account with a bill or outstanding balance.

## The Approved Core Direction

The following four features are the current product shortlist. They form one
connected financial system and should be designed together, but delivered in
sequence.

```text
Credit-card statement
        -> verified card liability
        -> bank-account available cash
        -> confirmed commitments
        -> ability to meet obligations and spend safely
```

### 1. Credit Card Bill and Statement Management

**User decision:** What exactly do I owe, when must I pay, and what changed
since my last bill?

**Inputs:** A supported card statement as the verified monthly record, email
alerts as later activity, and user review for uncertain matches.

**What PFIS should provide:**

- Statement date, billing period, total due, minimum due, and due date.
- Statement-backed credit limit and available-credit limit.
- Purchases, card payments, refunds, cashback/credits, fees, taxes, and
  interest in one reconciled ledger.
- Statement-to-email matching, so a purchase is never added twice.
- A card payment represented as a transfer from the paying bank account to the
  card liability, not as a second expense.
- Purchases, payments, and refunds after the statement date.
- A post-statement balance only when labelled **estimated**, with the statement
  date and matched activity behind the estimate visible.

**Why it matters:** It prevents missed payments, confusion about card dues, and
double-counted spending.

**Hard boundaries:**

- Do not call a calculated value a live outstanding balance.
- Do not invent a blocked limit when the issuer has not supplied one.
- Do not show EMI progress unless a complete issuer-provided schedule supports
  tenure, instalment amount, and remaining instalments.

### 2. Bank Account Position and Reconciliation

**User decision:** How much money is actually available in this bank account,
and does PFIS accurately account for it?

**Inputs:** A user-entered or statement/connector-provided balance snapshot,
imported activity, transfers, and user review of unexplained movement.

**What PFIS should provide:**

- Latest verified balance, source, and as-of date.
- Inflows and outflows for the chosen period.
- Spending split by UPI, debit card, ATM, transfer, and other routes.
- Transfers to credit cards visible on both the paying bank account and the
  receiving card liability.
- Account-specific transaction history.
- A reconciliation status and a focused review queue for missing, duplicate, or
  untracked activity.

**Why it matters:** This is the trustworthy cash position needed for card
payments, budgets, reports, and any safe-to-spend calculation.

**Hard boundary:** PFIS must not claim a live bank balance from partial email
alerts alone.

### 3. Commitment-Aware Cash Plan

**User decision:** Is this money genuinely free to spend, or is it already
needed before my next income?

**Inputs:** Verified bank-account position, credit-card dues, loan EMIs, and
only commitments that are confirmed by the user or a reliable source.

**What PFIS should provide:**

```text
Verified bank balance
- confirmed commitments due before next income
- chosen reserve allocations
= flexible money available
```

- A dated timeline of income and commitments: rent, card bills, EMIs, SIPs,
  insurance, subscriptions, and other approved bills.
- Clear source and date for every commitment.
- Safe-to-spend/flexible-money amount until the next confirmed income date.
- A daily allowance only when the user chooses to see one.

**Why it matters:** It turns a raw bank balance into an answer to the actual
question: "Can I spend this money without missing something important?"

**Hard boundaries:** Do not guess a salary date, assume that a repeated payment
is a bill, or use an unverified balance as available cash.

### 4. Liability and EMI Management

**User decision:** What fixed debt obligations do I carry, what is due next,
and when will they end?

**Inputs:** Credit-card statements, explicit issuer EMI schedules, loan
statements, or user-entered loan schedules.

**What PFIS should provide:**

- Credit-card total and minimum dues.
- Card EMI plans when the issuer explicitly provides the schedule.
- Personal, vehicle, education, home-loan, and pay-later obligations when the
  user adds or imports them.
- Monthly total of fixed debt commitments.
- Next due dates, known end dates, and remaining principal only when sourced
  from a statement or confirmed schedule.
- Later extension: compare deterministic debt payoff approaches, such as
  highest-interest-first and smallest-balance-first.

**Why it matters:** It makes the user's fixed debt pressure visible and feeds
the Cash Plan with commitments that cannot safely be ignored.

## Enabling Capabilities Required Before the Core Features

These are not decorative user features. They are the data and trust layer
required for the four core features to be reliable.

### Accurate instrument detection and account linking

PFIS currently needs a stronger distinction between money direction, payment
rail, funding account, product type, and card event.

| Concept | Meaning | Example |
| --- | --- | --- |
| Transaction direction | Did money move out, in, or return? | Debit, credit, refund |
| Payment rail | How was it initiated? | UPI, debit card, credit card, transfer |
| Funding account | Which owned account paid? | Savings account ending 1234 |
| Product type | What is the account? | Savings account, credit card, loan |
| Card event | What happened to the card? | Purchase, payment, fee, interest, reversal |

Rules to implement:

- An email saying "amount debited" must not be interpreted as a debit-card
  payment. It only indicates a money-out direction.
- An explicit credit-card or account identifier must outrank generic keywords.
- A UPI payment made using an eligible credit card is both a UPI rail and a
  credit-card-funded transaction.
- An EMI is a financing plan, not a payment rail.
- Every imported transaction should resolve to a user-owned bank account,
  credit card, or review queue; it must never be silently attached to the
  wrong instrument.
- User corrections should become user-owned learning rules and enable safe,
  reviewable historical correction.

### Source provenance, review, and reconciliation

Every record must state whether it came from an email alert, uploaded statement,
manual entry, or future consented connection. PFIS needs:

- Source and parser version.
- Confidence and review state.
- A clear "matched / newly imported / ignored by rule / needs review" outcome
  for every imported statement line.
- Duplicate prevention using document fingerprint plus statement/card identity.
- Matching based first on issuer reference ID, then on card, date, amount, and
  normalized merchant with a controlled posting-date tolerance.
- No automatic overwrite of a user correction.

## Validated HDFC Statement Opportunity

Five consecutive HDFC Millennia credit-card statements were reviewed privately
as source samples. No statement values or personal details are stored in this
repository.

### What was validated

- The samples were unencrypted, digitally generated PDFs rather than scanned
  images, and their text and tables were extractable.
- Each used a consistent 2-3 page layout.
- The billing summary contained statement date and billing period, previous
  dues, payments/credits received, purchases/debits, finance charges, total
  due, minimum due, due date, total credit limit, available credit limit, and
  available cash limit.
- The domestic ledger contained date/time, transaction description, amount,
  and purchase-indicator columns. Credits were visibly marked.
- EMI-labelled and fee/tax-related rows appeared in most samples.

### HDFC statement-first MVP

1. Support one known HDFC digital statement layout; reject or review an
   unfamiliar format instead of silently extracting unreliable values.
2. Verify issuer, card identifier, billing period, and document fingerprint.
3. Extract verified billing fields and statement rows.
4. Reconcile statement rows against existing email alerts.
5. Add only genuinely missing transactions; route ambiguous lines to review.
6. Store statement-date values as official and later activity as estimates.

### Explicit HDFC limitations

- Available credit is a statement-time snapshot, not necessarily a live figure
  after later activity.
- The reviewed samples did not expose a separate blocked-limit field.
- EMI-related rows do not prove that a full EMI schedule is available.
- A PDF parser for this format does not automatically support all HDFC layouts
  or other card issuers.

### Acceptance criteria before implementation

- Build a larger de-identified fixture set with zero-spend, payment, refund,
  fee, tax, EMI, and multi-page examples.
- Manually confirm expected billing fields and transaction-line counts.
- Re-importing the same document must create no financial events.
- Every line must be matched, newly imported, ignored by a documented rule, or
  placed in review.
- Do not persist PDF passwords, full card/account numbers, or unnecessary
  address/contact data. If source PDFs are retained, they need encryption,
  strict user scope, and a defined retention policy.

## Important Supporting and Later Features

These ideas remain recorded, but are not part of the current four-feature core.
They should be built only when their underlying financial data is reliable.

### Future-expense reserve system (possible fifth core feature)

This is the refined form of sinking funds. It lets a user reserve money for
known future expenses such as annual insurance, school fees, festivals, travel,
repairs, or annual subscriptions.

Example: an annual Rs. 24,000 insurance premium due in 12 months needs a
Rs. 2,000 monthly reserve.

It should integrate with the Cash Plan rather than become an isolated goal
widget.

### Card management extensions

- Credit-utilisation guardrails chosen by the user.
- Card payment planner: total/minimum due, selected paying bank account, and
  intended payment amount.
- Card payment routing comparison for multiple cards, based only on explicit
  user-entered reward/cashback rules.
- Statement-to-ledger coverage score: matched, new, and review counts.
- Card renewal, annual-fee, fee-reversal, and milestone-spend calendar.
- Transaction dispute tracker with complaint date, reference number, and status.
- Security/activity centre for duplicate alerts, high-value activity, and
  pending reversals; it must not claim to block a card at the bank.

### Cash and household extensions

- Cash pocket: an ATM withdrawal becomes a transfer to a cash balance; later
  manual cash spending is deducted from that pocket.
- Shared-expense support: household annotations and settlement workflows, with
  separate privacy and ownership design.

### Transaction and review enhancements

- Transaction notes and tags.
- Split transactions across categories.
- Bill reminders with paid/skipped/due-soon status.
- Subscription and recurring-payment view.
- Monthly snapshot: income, spend, savings, and largest period change.
- Budget drill-down with transactions and remaining amount.
- Financial-health checklist for emergency fund, insurance, and nominee tasks.
- Deterministic unusual-spending alerts based on the user's own history.
- Exportable monthly reports.

## Explicitly Deferred or Excluded Ideas

- **Standalone UPI payment assurance:** not a core feature. UPI activity remains
  a useful bank-account filter and funding-source signal.
- **Standalone debit-card financial position:** debit-card activity belongs to
  the linked bank account.
- **Live card balance, available limit, or blocked limit from email alone:**
  not trustworthy enough to show as live data.
- **Universal PDF statement parsing:** begin with a tested HDFC format, not all
  banks or all document variants.
- **Bank portal scraping or collection of bank-login credentials:** out of
  scope.
- **Generic AI financial advice:** out of scope for this roadmap.

## Delivery Order

1. Financial-instrument detection, account linking, source provenance, and
   review/correction flows.
2. HDFC Credit Card Bill and Statement Management.
3. Bank Account Position and Reconciliation.
4. Commitment-Aware Cash Plan.
5. Liability and EMI Management.
6. Consider the Future-expense Reserve System once the previous features have
   reliable cash and liability data.

## Mobile Delivery Requirement

Every core feature must be designed and tested for mobile before completion.
The critical mobile flows are statement upload, import review, card due-date
and payment action, account reconciliation, commitment review, and debt/EMI
detail. At a minimum, validate the flows at 360 px and 768 px widths, in light
and dark themes, with keyboard-accessible controls and readable financial
amounts.
