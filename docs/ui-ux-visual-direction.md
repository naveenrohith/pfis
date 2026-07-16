# PFIS Visual Direction and UI Stack Decision

Status: selected for implementation
Related archived visual exploration: `docs/archive/prototypes/visual-directions.html`

## 1. Research frame

Research was organized around PFIS design problems, not around copying complete products:

- Financial briefing: communicate position, change, consequence, and next action in one reading path.
- Ledger density: support fast scanning without turning every row into a bordered card.
- Recommendation trust: connect guidance to reason, evidence, freshness, and reversibility.
- Planning: make future outcomes feel adjustable rather than merely reported.
- Navigation: separate daily personal-finance work from data operations.
- Empty and degraded states: make the next step useful without filling blank space for decoration.

Three directions were explored against the same Today content so hierarchy, not feature count, determined the result.

## 2. Explored directions

### A. Quiet Horizon — selected

Warm statement-paper surfaces, ledger-ink typography, banknote jade for positive movement, restrained coral for outflow, and intelligence indigo for PFIS explanations. The Financial Horizon forms a single narrative instrument rather than a dashboard grid.

Why it wins:

- Best expression of calm, trust, and daily usefulness.
- Creates a distinctive signature without relying on glass, gradients, or novelty effects.
- Works in light and dark modes without changing the product personality.
- Supports both sparse daily guidance and dense ledgers.
- Makes AI guidance prominent while keeping evidence and human control visible.

### B. Midnight Treasury — rejected as the default

Dark-first, high-contrast market-terminal energy with luminous values and compact modules.

Useful qualities retained: strong numerical scanning and focused high-attention states.

Reason for rejection: it overstates urgency, feels closer to trading software than a personal financial assistant, and would make routine spending feel unnecessarily dramatic.

### C. Intelligence Canvas — rejected as the default

Bright neutral canvas with indigo AI surfaces, modular insight blocks, and more conversational copy.

Useful qualities retained: approachable explanations and obvious evidence affordances.

Reason for rejection: it is too close to the current generation of generic AI SaaS products and weakens the financial identity of PFIS.

## 3. Selected visual grammar

### Composition

- Content follows an editorial reading path, not a uniformly tiled grid.
- Primary surfaces can be large, but only when their information justifies the space.
- Supporting modules use alignment and spacing before borders.
- Dense records use calm rows, group dividers, sticky controls, and a detail panel or drawer.
- Section widths and line lengths remain intentional; the entire desktop viewport is not filled merely because space exists.

### Typography

- Primary family: Manrope Variable, selected for open forms, precise numerals, and a warmer voice than the current Inter-only treatment.
- Monetary values use tabular numerals and tighter tracking at display sizes.
- A single family keeps the system coherent; hierarchy comes from size, weight, measure, and placement.
- Uppercase labels are rare and never used as the dominant section-heading pattern.

### Shape and depth

- Radius scale: 10, 14, 20, and full-pill only for appropriate compact controls.
- Most content has no shadow. Floating navigation, overlays, and a small number of foreground surfaces may use soft layered shadows.
- Hairlines separate ledgers and technical detail. Borders do not define every module.

### Color behavior

- Warm neutral canvas and surfaces establish calm.
- Ink carries hierarchy; muted copy remains readable and is never low-contrast decoration.
- Jade, coral, amber, blue, and indigo are semantic accents, not a rainbow dashboard palette.
- Category colors appear only in visualizations and drill-downs where distinction is necessary.

### Motion

- 140–220 ms for direct feedback and local transitions.
- Shared-layout movement is reserved for navigation indicators, selected ledger rows, and evidence expansion.
- Financial values may count only on first meaningful load, never on every render.
- The Financial Horizon draws once when data becomes available; reduced-motion users receive the final state immediately.

## 4. UI stack decision

PFIS will not become dependent on a single visual library. It will use a layered stack with one owner per responsibility.

| Responsibility | Decision | Rationale |
|---|---|---|
| PFIS visual identity | Own in repository | Tokens, composition, financial components, and content hierarchy are product-specific |
| Accessible interactive primitives | Adopt Base UI incrementally | Unstyled, tree-shakeable primitives cover focus, keyboard, pointer, and ARIA behavior while preserving full PFIS styling control |
| Registry/MCP discovery | Retain shadcn MCP as reference and scaffolding | Useful for locating patterns and implementation examples; generated code must be adapted and audited |
| Alternative primitive systems | Do not add Radix or React Aria in Phase 3 | Both are capable, but adding overlapping primitive systems would duplicate behavior and increase bundle and maintenance cost |
| Motion | Retain Motion | Already installed; supports reduced-motion-aware direct feedback and layout transitions |
| Tabular data | Retain TanStack Table | Headless control fits the Activity ledger and current code already uses it |
| Charts | Retain Recharts during the first slice; evaluate v3 migration separately | Current code is stable on v2; the shadcn chart layer now targets Recharts v3, so combining redesign and major chart migration would add avoidable risk |
| Icons | Retain Lucide | Consistent, tree-shakeable, and already integrated; icons support labels rather than replace them indiscriminately |
| Command surface | Retain cmdk | Already integrated and appropriate for global search and actions |
| Forms and validation | Retain React Hook Form and Zod | Already integrated and adequate for goals, accounts, review corrections, and preferences |
| Drag and reorder | Retain dnd-kit only where personalization justifies it | Reordering is optional customization, not a core layout mechanism |

### Why Base UI is the primitive foundation

Base UI currently provides a single tree-shakeable package and unstyled components, including dialog, drawer, menu, popover, select, tabs, tooltip, fields, and scroll area. Its accessibility guidance explicitly covers keyboard navigation, focus management, labels, pointer behavior, and WAI-ARIA patterns. That lets PFIS replace fragile local behavior incrementally without importing another product’s visual language.

Radix and React Aria remain valid references. Radix offers mature low-level primitives and incremental adoption; React Aria is especially strong for internationalization and complex adaptive interactions. PFIS will revisit React Aria only if a future control—such as an advanced date, calendar, or collection interaction—has requirements Base UI and current headless tools cannot meet.

## 5. MCP policy

The shadcn MCP server is active and the standard `@shadcn` registry is reachable. Discovery during this phase found current sidebar blocks and the chart component. The chart registry item now depends on Recharts 3, while PFIS currently uses Recharts 2, which confirms that registry output cannot be installed blindly.

Use MCP to:

- Find accessible behavioral patterns and complete examples.
- Compare current APIs before implementing a primitive.
- Identify dependencies and migration assumptions.
- Generate a starting point when the selected component matches PFIS architecture.

Do not use MCP to:

- Select the product’s visual language.
- Install a block without dependency, accessibility, performance, and privacy review.
- Replace PFIS content hierarchy with a registry demo.
- Mix several primitive foundations for superficial variety.

Every imported pattern receives an `adopt`, `adapt`, or `reject` decision in the relevant implementation change.

## 6. Initial pattern decisions

| Need | Decision | Notes |
|---|---|---|
| Collapsible destination rail | Adapt | Use shadcn sidebar behavior as a reference, but implement the locked five-destination PFIS model and legacy alias handling |
| Mobile navigation | Own | Five stable bottom destinations, safe-area support, and contextual quick add are product-specific |
| Dialog, drawer, popover, tooltip, menu, tabs, select | Adopt Base UI behavior; own styling | Replace local implementations incrementally and test focus restoration and keyboard behavior |
| Financial Horizon | Own | Signature PFIS component; no registry equivalent |
| Insight and action surfaces | Own | Must encode evidence, freshness, consequence, and semantic severity |
| Ledger | Adapt TanStack Table | Desktop semantic table plus mobile rows and a responsive detail surface |
| Chart frame and tooltip | Adapt | Own accessible summary, evidence table, annotations, and PFIS token layer around Recharts |
| Empty state | Own | Compact, contextual, and action-led; illustrations are optional and never used to justify excessive height |
| Toast | Adapt existing implementation first | Reassess only if behavior fails Phase 8 accessibility review |

## 7. Verified official sources

- [Base UI quick start](https://base-ui.com/react/overview/quick-start)
- [Base UI accessibility](https://base-ui.com/react/overview/accessibility)
- [Radix Primitives introduction](https://www.radix-ui.com/primitives/docs/overview/introduction)
- [React Aria overview](https://react-aria.adobe.com/)
- [Motion accessibility guidance](https://motion.dev/docs/react-accessibility)
- [shadcn MCP documentation](https://ui.shadcn.com/docs/mcp)
- [shadcn chart documentation](https://ui.shadcn.com/docs/components/base/chart)
- [TanStack Table introduction](https://tanstack.com/table/latest/docs/introduction)

## 8. Phase 2 exit decision

Quiet Horizon is the implementation direction. PFIS owns its financial visual system, adopts Base UI incrementally for accessible behavior, keeps its proven specialist libraries, and uses shadcn MCP as a discovery channel rather than as the design system.

No unresolved visual-system or foundation-library decision remains for Phase 3.
