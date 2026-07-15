# PFIS Product Experience Specification

Status: locked for the UI/UX revamp
Supersedes the workspace model in `docs/ui-ux-masterplan.md` for new UI work. Existing API contracts and legacy section hashes remain supported during migration.

## 1. Product intent

PFIS is a personal financial command center that turns fragmented bank, UPI, card, and email activity into a clear, trustworthy daily plan.

The primary user is a time-poor, financially aware individual opening PFIS after money has moved across several services. They are not arriving to operate a database. They want to understand their position in under ten seconds, see what changed, take one useful action, and return to their life.

Every primary screen must help the user accomplish at least one of four things:

1. Know their current financial position.
2. Understand why it changed.
3. Take the next highest-impact action.
4. Verify the evidence behind the recommendation.

The intended feeling is a **quiet financial instrument and personal morning briefing**: calm, precise, reassuring, and purposeful. “Clean” and “modern” are insufficient on their own.

## 2. Experience principles

### 2.1 Decision before data

Lead with the conclusion and its implication. Supporting metrics, charts, and transactions follow as evidence.

### 2.2 One dominant idea per view

Each destination has one primary question. Secondary modules support it instead of competing with it.

### 2.3 Progressive disclosure

Show the sentence, the signal, and the recommended action first. Reveal calculations, raw transactions, parser details, and provenance on demand.

### 2.4 Trust is visible

Recommendations expose their reason, time range, source data, and confidence. PFIS must never imply certainty it does not have.

### 2.5 Calm does not mean empty

Whitespace creates rhythm and hierarchy. It must not produce oversized blank cards or weak information density.

### 2.6 AI is embedded, not bolted on

PFIS explains and prioritizes throughout the product. A generic chat panel is not the centerpiece and is never a substitute for a designed workflow.

## 3. Domain language and visual source material

The design language comes from financial behavior rather than generic SaaS dashboards.

Domain concepts:

- Ledger: a trustworthy record and evidence trail.
- Cash movement: money flowing in, out, and between accounts.
- Financial pulse: the small set of signals that describe the present.
- Runway: how current behavior affects the near future.
- Commitments: recurring costs and obligations already in motion.
- Signal versus noise: what deserves attention now.
- Horizon: the connection between today’s position and the month’s likely outcome.
- Confidence: how strongly the available evidence supports a conclusion.
- Settlement: when imported activity becomes clean, classified, and usable.

Color world:

- Ledger ink: near-black navy for durable financial information.
- Statement paper: warm off-white rather than sterile white.
- Banknote jade: positive movement, completion, and healthy progress.
- Settlement blue: neutral linked data, navigation, and evidence.
- Intelligence indigo: PFIS explanations and predictive guidance.
- Amber caution: commitments and conditions that need consideration.
- Coral outflow: negative movement and spending pressure without alarmist red.

Exact accessible light and dark tokens are defined in Phase 3. Semantic meaning takes priority over decoration.

## 4. Signature interaction: the Financial Horizon

The signature of PFIS is the **Financial Horizon**: a continuous, annotated narrative on Today that connects:

`current position -> recent change -> likely month outcome -> recommended action -> supporting evidence`

It is not a row of KPI cards. Visually it behaves like one calm financial instrument: a prominent position statement, an understated movement trace, forecast context, and one anchored action. Selecting a point or explanation reveals the evidence without navigating away.

The Financial Horizon should make PFIS recognizable even if the logo is removed.

## 5. Defaults explicitly rejected

| Rejected default | PFIS replacement |
|---|---|
| Equal KPI card grid | A Financial Horizon narrative with only three supporting pulse signals |
| Nested workspace sidebar with item counts | Five stable destinations with contextual local navigation |
| Separate AI chat card | Embedded explanations, evidence drawers, and an optional global coach entry point |
| Donut-first analytics | Annotated trends, ranked contributions, and sentence-led comparisons |
| Border around every element | Grouping through spacing, tone, alignment, and selective surfaces |
| Status badges as decoration | Status text only when it changes meaning or enables an action |
| Raw operational jargon in the consumer journey | Plain-language states with technical detail available in Data & settings |

## 6. Locked information architecture

### Today

Primary question: **What is my financial position, and what should I do next?**

- Financial Horizon
- Daily guidance and highest-impact action
- Financial pulse: a maximum of three supporting signals
- Recent evidence and meaningful changes
- Data freshness and explanation provenance

### Activity

Primary question: **Where did my money move, and what needs verification?**

- Transaction ledger
- Review queue
- Chronological activity timeline
- Recurring commitments
- Merchant and category drill-downs

### Plan

Primary question: **Where am I heading, and what can I change?**

- Cash-flow outlook
- Net worth and accounts
- Budgets
- Goals
- Scenario and commitment context

### Insights

Primary question: **What patterns are shaping my finances?**

- Period comparisons
- Spending and income patterns
- Category and merchant intelligence
- Anomalies and recurring-cost analysis
- Forecast explanations

### Data & settings

Primary question: **Is my data connected, accurate, and configured correctly?**

- Accounts and data sources
- Inbox and synchronization
- Import and pipeline health
- Preferences, personalization, privacy, and exports

Operational detail is intentionally separated from the daily consumer experience. Serious data-quality issues can surface as a concise alert elsewhere, but remediation happens here.

## 7. Navigation model

Desktop uses a slim collapsible destination rail with icons and short labels. It may expand by explicit user action; it does not expose a permanently expanded nested tree. The active destination owns a compact contextual sub-navigation or view switcher in the content header.

Mobile uses five persistent bottom destinations. Quick add is available as a contextual action, not a sixth navigation destination. Search, global coach, period controls, theme, and profile live in the application header or command surface.

The selected financial period is global where the destination supports it. Data & settings uses current operational state instead of implying that all system health is month-bound.

## 8. Legacy route and hash compatibility

Existing bookmarks and cross-feature links continue to resolve during the migration.

| Legacy section/hash | New destination and view |
|---|---|
| `#overview` | Today / Overview |
| `#guidance` | Today / Brief |
| `#recommendations` | Today / Actions |
| `#transactions` | Activity / Transactions |
| `#review` | Activity / Review |
| `#timeline` | Activity / Timeline |
| `#merchants` | Activity / Merchants |
| `#categories` | Activity / Categories |
| `#networth` | Plan / Net worth |
| `#budgets` | Plan / Budgets |
| `#analytics` | Insights / Trends |
| `#insights` | Insights / Intelligence |
| `#inbox` | Data & settings / Sync |
| `#pipeline` | Data & settings / Pipeline |

The old workspace identifiers `home`, `understand`, `plan`, `act`, and `system` are accepted as aliases until all internal links and persisted preferences have migrated.

## 9. Today: locked content hierarchy

Today is the first production slice and the reference quality bar for every later destination.

1. **Orientation** — personal greeting, selected period, last successful data refresh.
2. **Position** — one plain-language conclusion derived from the guidance brief and workspace snapshot.
3. **Financial Horizon** — current net cash flow or savings position, comparison context, and projected month outcome when sufficient data exists.
4. **Priority action** — one highest-impact guidance action with reason, estimated consequence where available, and a direct verb-led CTA.
5. **Financial pulse** — at most three signals selected by relevance, such as spending change, health score, recurring burden, or projected net.
6. **What changed** — a compact set of meaningful changes or recent evidence, not an exhaustive transaction feed.
7. **Trust footer** — data-through timestamp, ruleset or explanation provenance, and an explanation entry point.

Available frontend queries already provide the required inputs: workspace snapshot, guidance brief, cash-flow projection, month comparison, financial health, recommendations, and timeline evidence. Phase 5 should not require a backend contract change.

## 10. Today state model

| State | Narrative behavior |
|---|---|
| Healthy | Reinforce progress, show the strongest positive change, and recommend maintenance or an achievable next gain |
| Attention | Explain the emerging pressure and present one bounded corrective action |
| Deficit | State the shortfall plainly, avoid celebratory visuals, and prioritize the action with the greatest near-term impact |
| Low data | Explain what PFIS needs, make connection/import the primary action, and avoid unsupported forecasts |
| Stale sync | Preserve the last known values but label their age and prioritize refreshing the source |
| Loading | Preserve layout with meaningful skeleton groups; never show a wall of identical placeholders |
| Partial error | Keep usable sections visible and explain which signal could not be refreshed |
| Full error | Give a human-readable recovery action and retain access to Data & settings |

## 11. Primary user journeys

### Daily check-in

Open Today -> understand position -> inspect one change if needed -> take or dismiss the priority action.

Success: the conclusion is understood within ten seconds and the next action is discoverable without scrolling on a typical laptop.

### Explain a change

Select an annotation or “Explain” -> view calculation, comparison period, contributing categories or merchants, and linked transactions -> move into Activity or Insights without losing context.

### Review uncertain activity

Open Activity / Review -> select an item -> compare source evidence and proposed classification -> confirm or correct -> advance to the next item with keyboard or pointer.

### Adjust the plan

Open Plan -> understand projected outcome -> inspect the relevant budget, goal, account, or commitment -> make one change -> see the expected consequence.

### Repair data trust

Follow a stale or degraded-data notice -> Data & settings -> inspect the affected source -> retry or resolve -> return to the prior destination with refreshed status.

## 12. Content and language rules

- Use sentences for conclusions and labels for facts.
- Lead actions with verbs: Review, Connect, Reduce, Move, Confirm, Create.
- Reserve red/coral for meaningful negative financial movement or blocking errors.
- Do not place “deterministic”, parser names, dead-letter terminology, retry counts, or raw email bodies in primary consumer surfaces.
- Never say “AI says”. Attribute an explanation to the underlying period, behavior, and evidence.
- Avoid judgmental language such as “bad spending”. Describe behavior and consequence.
- Use Indian currency formatting consistently, including compact representations only when precision is not required.
- Explanations must distinguish observed facts, deterministic calculations, and forecasts.

## 13. Responsive behavior

- Below the desktop breakpoint, content becomes a single narrative column in priority order.
- The Financial Horizon remains intact rather than fragmenting into separate metric cards.
- Supporting detail becomes drawers, disclosures, or destination links where inline density would harm comprehension.
- Tables provide a mobile row representation; they do not force horizontal page scrolling for primary tasks.
- Touch targets are at least 44 by 44 CSS pixels and bottom navigation accounts for safe areas.
- Mobile overlays trap focus, restore focus on close, prevent background scroll, and remain dismissible without precision gestures.

## 14. Phase 1 acceptance criteria

- [x] Product purpose, primary user, accomplishment, and emotional target are explicit.
- [x] Domain concepts, color world, signature interaction, and rejected defaults are explicit.
- [x] Five destinations and their primary questions are locked.
- [x] Every legacy section hash has a migration destination.
- [x] Today has a fixed information hierarchy, data-source plan, and state model.
- [x] Primary journeys and responsive behavior are defined.
- [x] No new backend contract is required for the first production slice.

Changes to these decisions require a short decision record describing the user evidence, affected destinations, compatibility impact, and migration cost.
