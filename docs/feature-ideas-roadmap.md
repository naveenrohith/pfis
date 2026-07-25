# PFIS Feature Ideas Roadmap

This document preserves product ideas discussed during planning. These are
non-AI features intended to make PFIS more useful through clear, practical
financial actions.

## Product Principle

Prioritize features that use PFIS's existing transaction, account, budget,
goal, and recurring-payment data to answer a practical user question:

- What changed?
- What is due next?
- How much can I safely use?
- What should I set aside now?

## Small, Helpful Transaction Features

### Transaction notes and tags

Let a user add context to a payment, such as a `Family` tag and the note
"Birthday gift for Mom." This makes later spending reviews more meaningful.

### Split transactions

Allow a single payment to be allocated across categories. For example, a
Rs. 3,000 supermarket transaction could be split into Rs. 2,000 for groceries
and Rs. 1,000 for household supplies.

### Bill reminders and paid status

Show that an electricity bill is due in two days, then let the user mark it as
paid or match it with an imported transaction.

### Subscription view

Group recurring small payments, such as streaming or fitness subscriptions,
and show their combined monthly cost.

### Monthly snapshot

Provide a short monthly view: income, spending, savings, and the largest
change from the previous month.

### Budget drill-down

Show the transactions behind a category budget and the amount remaining. For
example: "Food: Rs. 800 remaining for 10 days."

### Financial health checklist

Offer a user-controlled checklist for foundational tasks such as maintaining
an emergency fund, recording insurance details, or adding nominees.

### Unusual-spending alert

Flag a category when its spending is materially higher than the user's own
recent history. Example: shopping is Rs. 8,000 this month instead of the usual
Rs. 1,000 to Rs. 2,000.

### Exportable monthly report

Let the user download or share a simple monthly overview of income, spending,
savings, and investments.

### Shared-expense support

Future option: let household members add annotations or settle shared costs.
This needs separate design for privacy, ownership, and settlement rules.

## High-Value Product Additions

These extend capabilities PFIS already has rather than creating disconnected
tools.

### 1. Financial calendar

Show expected income and known commitments in date order.

Example for August:

| Date | Item | Amount |
| --- | --- | ---: |
| 1 Aug | Salary | +Rs. 60,000 |
| 3 Aug | Rent | -Rs. 18,000 |
| 5 Aug | EMI | -Rs. 8,000 |
| 10 Aug | SIP | -Rs. 5,000 |

Value: users can anticipate cash pressure before the money leaves their
account. PFIS's recurring-payment knowledge can suggest items, while the user
confirms dates and amounts.

### 2. Safe-to-spend amount

Calculate the amount that remains available after reserving money for confirmed
upcoming commitments and the user's chosen savings allocations.

Example:

- Current balance: Rs. 22,000
- Rent and EMI still due: Rs. 13,000
- Saved for a goal this month: Rs. 5,000
- Safe to spend until the next income date: Rs. 4,000

Value: turns account balances and transaction history into one simple,
actionable number. The screen must explain the calculation and distinguish
confirmed commitments from estimates.

### 3. Sinking funds

A sinking fund is a planned reserve for a known future expense, separate from
a general savings goal.

Example: a Rs. 24,000 annual health-insurance premium due in 12 months becomes
a suggested monthly set-aside of Rs. 2,000.

Useful funds include insurance, school fees, festivals, travel, home repairs,
and annual subscriptions.

Value: prevents predictable annual expenses from becoming sudden financial
problems.

### 4. Bill and EMI planner

Convert detected recurring payments into user-confirmed commitments with due
date, expected amount, payment account, and paid/missed status.

Example commitments:

- Rent: Rs. 18,000, due on the 3rd
- Bike EMI: Rs. 4,500, due on the 5th
- Wi-Fi: Rs. 699, due on the 12th

Value: this turns recurring-payment detection into a daily planning tool. A
matching imported transaction can automatically propose that a commitment has
been paid, but the user should retain control over confirmation.

### 5. Balance reconciliation

Let the user enter an actual bank-account balance and compare it with tracked
activity.

Example: the bank shows Rs. 14,200 but PFIS differs by Rs. 1,150. PFIS can ask
the user to review potential cash withdrawals, untracked manual payments, or
missing imported transactions.

Value: improves user confidence in imported data and highlights data gaps.

### 6. Debt payoff planner

Let a user record debts and compare deterministic payoff strategies.

Example: with a Rs. 25,000 high-interest credit-card balance and a Rs. 80,000
lower-interest personal loan, PFIS can show:

- Interest-saving plan: pay extra toward the highest-interest debt first.
- Momentum plan: clear the smallest balance first.

Value: converts debt data into an understandable plan without making AI-driven
or opaque recommendations.

## Existing PFIS Building Blocks

PFIS already includes transaction tracking, budgets, goals, financial accounts
and balance snapshots, transfers, recurring-payment analysis, cash-flow
projection, scenarios, reports, and deterministic guidance. New work should
reuse these services and introduce new data models only where the user must
explicitly manage information such as a bill due date or a sinking-fund target.

## Suggested Delivery Order

1. Safe-to-spend amount
2. Financial calendar
3. Sinking funds
4. Bill and EMI planner
5. Balance reconciliation
6. Debt payoff planner

Start with the first four because they work together: confirmed bills feed the
calendar; the calendar and balance inform safe-to-spend; sinking funds reserve
money for future known expenses.

## Scope Note

All ideas above should remain transparent and deterministic. PFIS should show
the amounts, dates, assumptions, and source data behind every calculation.

## Account Intelligence: Cards, Debit Accounts, and UPI

### Why this is a high-value addition

Users do not think of their money as one undifferentiated transaction list.
They think in terms of the instruments they use: a credit card that has a bill
to pay, a debit account that has an available balance, and UPI activity that
needs to be understood quickly. PFIS should give each instrument the right
view, rather than merely placing a payment-method filter over the ledger.

### Current foundation and gaps

PFIS already stores a transaction direction (`debit`, `credit`, or `refund`),
an attempted payment method, account last four digits, and optional financial
accounts. It also has balance snapshots and recurring-payment analysis.

The current implementation needs a stronger data foundation before smart views
are reliable:

- Payment-method detection is currently keyword-based. It can see text such as
  `UPI`, `CREDIT CARD`, or `DEBIT CARD`, but does not make a robust,
  evidence-based decision per bank format.
- A parsed email is not automatically linked to a user financial-account row.
  It retains the last four digits but currently enters the pipeline without a
  `financial_account_id`.
- Account type is a free text value, so PFIS does not yet have a strict
  distinction between savings/current accounts, debit cards, credit cards,
  wallets, and UPI handles.
- Credit-card statements are classified as statements and skipped by the
  transaction pipeline. They are not yet parsed as a source document.

### Core data principle

These concepts must stay separate:

| Concept | Meaning | Example |
| --- | --- | --- |
| Transaction direction | Did money move out, in, or return? | A purchase is a debit; a refund is a refund. |
| Payment rail | How was the payment initiated? | UPI, card, bank transfer, wallet. |
| Funding account | Which user-owned account actually paid? | HDFC savings account ending 1234. |
| Product type | What sort of account is it? | Savings account, credit card, debit card. |
| Card event | What happened to the credit card? | Purchase, payment, fee, interest, EMI instalment, reversal. |

For example, a RuPay credit card payment made through UPI is both `UPI` as the
payment rail and `credit card` as the funding product. One simple
`payment_method` field cannot represent this accurately by itself.

Also, an EMI is not a payment rail. A card purchase may be converted into an
EMI; the purchase, instalment schedule, and monthly statement charge need to
be connected as one financing plan.

### Workstream 1: Accurate instrument detection and account linking

The first deliverable should improve accuracy before introducing new screens.

1. Build a versioned, evidence-based classifier that considers known sender,
   issuer/card wording, masked number, account wording, UPI/VPA/reference
   signals, and bank-specific message format. It should record why it selected
   a payment rail and account type.
2. Use a clear precedence order. An explicit "credit card ending 1234" should
   outweigh a generic word such as "debited." A UPI reference should identify
   the rail, while the source wording identifies whether the funding account is
   a bank account or a RuPay credit card.
3. Resolve the institution, account type, and masked number into a user-owned
   financial account. If PFIS cannot safely match one, create a review item;
   never silently attach it to the wrong card or bank account.
4. Let the user correct the detected instrument in the review queue. The
   correction should create a user-owned learning rule for that issuer/message
   pattern, then permit a safe bulk correction of matching history.
5. Measure accuracy by payment rail, issuing institution, and parser version.
   Low-confidence classifications should remain reviewable.

Success condition: each imported transaction can say both "this was a UPI
payment" and "it was funded by this particular bank account or credit card,"
with evidence and confidence.

### Workstream 2: Credit-card statement upload and ingestion

A statement must enrich the ledger, not create a duplicate copy of every
purchase notification already received by email.

#### User flow

1. The user chooses a known credit card, uploads a statement PDF or CSV, and
   enters a PDF password only when required. The password is used transiently
   for processing and is never stored or logged.
2. PFIS extracts the statement metadata: issuer, masked card number, statement
   period, bill date, due date, total amount due, minimum amount due, credit
   limit, available credit, and any reported blocked amount.
3. PFIS extracts the line items: purchases, payments, refunds, fees, interest,
   taxes, cash advances, reversals, and EMI charges.
4. Before import, PFIS displays a review: new transactions, records matched to
   existing email imports, and ambiguous items. The user can correct the card
   and approve the import.
5. The statement becomes a traceable source record. Existing transactions are
   linked or enriched; only missing transactions are added. PFIS must never
   overwrite a user correction without an explicit review action.

#### De-duplication rules

- Match first by a trusted issuer transaction/reference ID when present.
- Otherwise match using card last four digits, transaction date, amount, and
  normalized merchant, allowing a small date window for posting delays.
- Treat a credit-card bill payment as a transfer from the paying bank account
  to the card liability, not as a second expense. The original card purchase
  is the expense.
- Keep statements as source evidence with an import status so the same document
  cannot be imported twice.

#### Privacy and reliability rules

- The original statement and extracted data are financial records: encrypt or
  protect them at rest, scope them to the user, and never log their text or PDF
  password.
- Preserve provenance for every line: uploaded statement, email alert, or
  manual entry.
- Parsing failures must be recoverable and reviewable. Each supported bank and
  format needs fixtures and regression tests before production support.
- A statement can provide authoritative billing values; email alerts provide
  more timely purchase events. The UI must label the source and "as of" date
  rather than pretending every figure is live.

### Workstream 3: Smart account views

The navigation may contain Credit cards, Debit accounts, and UPI, but the
screens should not force the same fields onto different products. Each screen
should answer the questions that matter for that instrument.

#### Credit-card view

The main card is an account-level financial position, not a generic chart.

Show:

- Card name, masked number, issuer, and statement coverage date.
- Current outstanding, clearly labelled as either statement-reported or
  PFIS-estimated from complete data.
- Statement/bill date, due date, total due, and minimum due.
- Credit limit, available limit, utilization percentage, and reported blocked
  amount. Blocked amount must come from a statement or issuer notification;
  it cannot be reliably guessed from purchase emails.
- Purchases since the statement, payments since the statement, refunds, fees,
  and interest as a transparent balance movement list.
- Upcoming card EMIs, each with instalments paid, instalments remaining,
  monthly instalment amount, next due/statement month, and remaining principal
  only where the issuer provides enough evidence.
- Actions: upload statement, record a payment, review unmatched transactions,
  and open the card ledger.

Example: a card with a Rs. 1,00,000 limit, Rs. 31,000 outstanding, and Rs.
4,000 blocked should display Rs. 65,000 available, with the source and date of
each figure visible. If its bill date is 20 August and payment is due on 7
September, those dates are primary information, not hidden details.

#### Debit-account view

Debit accounts should focus on money currently available and the account's
activity.

Show:

- Available balance, source, and as-of timestamp.
- Incoming money, outgoing money, UPI spend, debit-card spend, ATM cash
  withdrawals, and bank transfers for the chosen period.
- Upcoming commitments that will use this account and a safe-to-spend figure,
  when data coverage is sufficient.
- Reconciliation status: does the latest bank-reported balance agree with the
  activity PFIS knows about?
- Account-specific transaction history and a clear way to correct an item
  assigned to the wrong account.

PFIS must not claim a live balance solely from partial email alerts. When it
has only an older snapshot, the screen should say so plainly.

#### UPI view

UPI is a payment rail, not normally an independent account with a balance or a
bill due. Its view should therefore focus on payment behaviour and linked
funding accounts.

Show:

- UPI paid, received, refunded/reversed, and pending/failed amounts.
- Recent recipients and merchants, with reference IDs for investigation.
- The bank account or RuPay credit card used to fund each payment when known.
- Recurring UPI mandates/autopay and their next expected charge.
- Duplicate, failed, or reversal-pending payments that need attention.

Example: a Rs. 1,200 UPI payment is shown as paid through UPI and funded by
HDFC savings ending 1234. A RuPay-card UPI purchase instead appears as funded
by the corresponding credit card and contributes to that card's utilization.

### Suggested delivery order

1. Instrument-detection audit, classifier, user correction, and account
   linking.
2. Credit-card account model and read-only smart view using manually entered
   statement values where needed.
3. Statement upload with a review-and-match flow for one bank/issuer and one
   statement format.
4. Credit-card bill, due-date, utilization, and EMI views backed by extracted
   statement data.
5. Debit-account and UPI smart views, balance reconciliation, and rail/funding
   filters.

This order improves data trust before the app displays financially sensitive
figures as if they were authoritative.

### HDFC statement feasibility validation (July 2026)

Five consecutive HDFC Millennia credit-card statements were reviewed as private
sample documents. The files were unencrypted, digitally generated PDFs rather
than scanned images, and their text and table layout were extractable. The
review did not retain statement values or personal details in this repository.

Across the sample set, the following structure was consistent:

- 2-3 pages per statement.
- A first-page billing summary containing statement date and billing period,
  previous statement dues, payments/credits received, current-cycle
  purchases/debits, finance charges, total amount due, minimum due, due date,
  total credit limit, available credit limit, and available cash limit.
- A domestic transaction ledger with date/time, transaction description, amount,
  and purchase-indicator columns. Incoming credits are visibly marked, allowing
  deterministic classification candidates for card payments, refunds, and
  cashback after review.
- EMI-labelled and fee/tax-related transaction rows appeared in most of the
  samples.

This validates a narrow, statement-first HDFC importer. It does not validate
claims that need a live issuer source:

- The available-credit figure is a statement-time snapshot, not a guaranteed
  live amount after later transactions.
- The samples did not expose a separate blocked-limit field. Do not invent or
  estimate one.
- EMI-related rows do not by themselves prove that the statement provides a
  complete instalment plan with original principal, tenure, and instalments
  remaining. Those fields need an explicit issuer-provided schedule before PFIS
  shows EMI progress.

#### Recommended HDFC statement-first MVP

1. Accept one known HDFC digital statement layout and reject/review unknown
   layouts rather than silently producing incorrect values.
2. Verify issuer, card identifier, billing period, and a document fingerprint;
   prevent a statement from being imported twice.
3. Extract only verified billing fields and ledger rows. Store the source and
   statement date for every displayed value.
4. Reconcile each statement row against imported email alerts. Link a confident
   match, add a genuinely missing item, and place ambiguous items in a review
   queue. Never duplicate spending.
5. Classify a card payment as a transfer to the credit-card liability, not as a
   second expense.
6. Display the official statement figures first. Any post-statement balance is
   an explicitly labelled estimate built from reconciled later activity.

#### Deliberately out of scope for this MVP

- Live card balance, live available limit, and blocked limit.
- A generic parser for every HDFC document variation or every issuer.
- Full EMI-progress calculations without an explicit issuer schedule.
- Bank portal scraping or bank-login credential collection.

#### Acceptance criteria before implementation is approved

- Manually verify the expected fields and line-item counts against a larger,
  de-identified fixture set, including a zero-spend period, payment, refund,
  fee, tax, and EMI examples.
- The importer must make every line exactly one of: matched, newly imported,
  ignored by a documented rule, or sent to review.
- Re-importing the same document must create no new financial events.
- The parser must never persist full card/account numbers, PDF passwords, or
  unnecessary address/contact data. Source documents require strict user scope,
  encrypted-at-rest storage if retained, and a documented retention choice.

## Further High-Value Ideas in the Same Direction

### Payment routing comparison

When a user has multiple cards, show which card was used where and compare
their utilization, upcoming dues, recurring charges, and reward/cashback rules
that the user has entered. It should not recommend a card unless the rule and
the evidence are explicit.

Example: "Your streaming subscriptions total Rs. 1,498/month across two
cards; card ending 4567 has the next due date."

### Credit utilisation guardrails

Show utilization per card and across all cards, with user-configured thresholds
such as 30% or 50%. Explain that the threshold is a personal guardrail, not a
credit-score guarantee.

Example: "Card ending 1234 is at 48% utilization; Rs. 2,000 more will cross
your 50% guardrail."

### Card payment planner

Before a credit-card due date, show the total due, minimum due, available cash
in the selected bank account, and the amount the user intends to pay. The user
can record or match the payment as an account-to-card transfer.

### Transaction dispute and follow-up tracker

Allow the user to mark a card or UPI transaction as disputed, attach the
reference number, record the complaint date and expected resolution date, and
follow its status. It should not alter the original transaction until a refund
or reversal is actually confirmed.

### Statement-to-ledger coverage score

For each imported statement, show how many line items matched known email
transactions, how many were newly imported, and which need review. This makes
data quality visible and helps the user trust the account view.

### Card renewal and fee calendar

Track annual fees, card-expiry/renewal dates, scheduled fee reversals, and
milestone spending requirements when the user chooses to add them.

### Cash withdrawal and cash-spend pocket

When an ATM withdrawal occurs, offer to create a separate cash pocket. The
withdrawal is a transfer from the bank account; later manual cash payments draw
from that pocket instead of appearing as unexplained spending.

### Security and unusual-activity centre

Group failed card payments, duplicate alerts, unusual card locations when
explicitly available in issuer notifications, high-value transactions, and
pending reversals. Provide actions such as "mark as known" or "begin dispute
record," but never claim to block a card at the bank.
