# Nexus Web App v1 UI Requirements v0.2

Status: locked scope for the first shippable trader web app. Supersedes ambiguous parts of v0.1 docs by binding requirements to the actual buildable backend surface.

## How To Use This Document

Designers should work from this doc as the primary source of truth for v1 scope. The v0.1 docs remain canonical for:

- Copy rules, language do's/don'ts, status semantics — `nexus-ui-designer-requirements-v0.1.md`
- Per-message UI behavior, paper-only treatment, freshness rules — `nexus-strategy-message-ui-requirements-v0.1.md`
- Persona, daily loop, product principles — `nexus-product-strategy-90-day-v0.1.md`

This doc adds:

- The exact buildable scope for v1.
- New screens not covered in v0.1 (multi-symbol watchlist, personal trigger library, plan reader).
- Data contracts pointing to `sigmatiq-api/docs/api/nexus-surface.md`.
- Explicit out-of-scope items.

## Positioning — Technology Platform, Not Advisor

Sigmatiq is a market-monitoring and decision-audit platform. Every screen, label, badge, narrative, and tooltip must reinforce that the platform **surfaces what the system observes and computes**, not what the trader should do. The trader is always the actor; Sigmatiq is always the instrumentation.

**Voice:**

- The platform shows, surfaces, computes, observes, ranks, monitors, blocks, fails closed, archives.
- The trader watches, decides, accepts, rejects, builds, configures, acts in their broker, reviews.

**Not allowed anywhere in product copy, narratives, or labels:**

- "We recommend…", "Sigmatiq suggests…", "You should…", "Best trade now…", "Recommended structure", "Top pick", "Our advice", "Confidence: high → take it".
- "Buy", "sell", "enter", "exit" used in the imperative.
- "Edge", "alpha", "guaranteed", "winning", "outperformance" as forward-looking claims.
- Confidence scores presented as buy-strength meters.

**Allowed framing:**

- "Strategy Fit ranks `long_call` first; `no_trade` second."
- "Confluence Sniper's read for the 10:00–10:30 window is BULLISH; this lane has not produced a paper candidate."
- "The platform is monitoring 3 symbols; SPY has 1 open paper position."
- "Live permission is blocked because GEX is stale."
- "Pricing Guide: cheap side appears to be puts; pricing quality is reliable."
- "Paper signal observed at 10:32 ET; tracked contract SPY 260510C00750000."

The platform never tells the trader to act. Paper signals are descriptions of what the system computed under research conditions, not instructions. Even when displayed prominently, every paper-signal card carries a `paper-only` badge and a `not broker execution` caveat.

This positioning is the product's defensibility. A platform that ranks structures and explains why is a tool. A platform that tells you what to buy is liability and noise.

## Product Framing For v1

Sigmatiq publishes daily 0DTE playbooks for `SPY`, `QQQ`, `IWM`. The trader uses the platform to:

1. Monitor live state across watched symbols.
2. Read today's published playbook for context.
3. See which strategies are producing reads, candidates, paper signals, or fail-closed states.
4. See computed direction, regime, retail-like vs institutional-like flow, structure-fit ranking, and pricing context.
5. Build a personal trigger-group library to be notified when conditions they configure are observed.
6. Review the platform's allowed / blocked / triggered / invalidated decisions after the close.

Plans are admin-curated; trigger groups are user-owned. The trader does not generate or activate plans in v1.

The v1 product is monitoring and audit infrastructure. No order entry, no broker integration, no advice.

## Locked Scope

### Strategies (8 lanes)

| Code | Display | Posture | Decision window |
|---|---|---|---|
| `etf_confluence_sniper` | Confluence Sniper | Phase 1 primary | 10:00–12:30 ET |
| `etf_open_specialist` | Open Specialist | Phase 2 primary | 10:00 ET |
| `etf_low_sweep_core` | Low Sweep Core | Phase 2 compatibility | 10:00–10:30 ET |
| `etf_flow_specialist` | Flow Specialist | Phase 2 support | 10:30 ET |
| `etf_momentum_specialist` | Momentum Specialist | Phase 2 support | 11:00 ET |
| `etf_put_credit_open30_spread` | Open30 Put Credit Spread | Research, paper-only spread | 10:00 ET |
| `etf_call_credit_open30_spread` | Open30 Call Credit Spread | Research, paper-only spread | 10:00 ET |
| `etf_allday_specialist` | All-day Specialist | Optional, alert-driven | Ad hoc |

`etf_allday_specialist` is conditional on deployment (`NEXUS_ALLDAY_ENABLED`). The Strategy Board must handle a variable lane count gracefully — design for 7 or 8 lanes with no layout breakage.

### Symbols (3 in v1)

`SPY`, `QQQ`, `IWM`. All other symbols out of scope.

### Backend surfaces consumed

| Surface | Repo | Auth |
|---|---|---|
| Live monitoring (all Nexus messages) | sigmatiq-api `/v1/live/*` (per `nexus-surface.md`) | JWT |
| Composite signal card | sigmatiq-api `/v1/app/strip/*` | JWT |
| Live symbols readiness | sigmatiq-api `/v1/live/symbols` | JWT |
| Strategy fit ranking | sigmatiq-api `/v1/live/{symbol}/strategy-fit` | JWT |
| Published playbook | sigmatiq-api `/v1/app/playbook/*` | JWT |
| Historical Nexus state | sigmatiq-api `/v1/historical/{symbol}/nexus-*` | JWT |
| Trigger groups CRUD | intelligence-api `/api/v1/triggers/*` | JWT |
| Trigger capabilities catalog | intelligence-api `/api/v1/triggers/capabilities` | JWT |
| EOD review (read) | intelligence-api `/api/v1/zero-dte/eod-review/*` | JWT |

JWT is shared (auth-dotnet). Both APIs hosted in Azure.

## Screens For v1

Eight screens, organized into four areas. Each screen lists the API endpoints it consumes — designers don't need to reverse-engineer this from the v0.1 docs.

### Today

#### S1 — Watchlist (home)

The first screen a trader sees when they open the app during market hours. Shows all 3 symbols at a glance, plus any open paper positions across the watchlist.

- Source: `GET /v1/live/{symbol}/nexus-snapshot` for each symbol; subscribe to `/nexus-snapshot/stream`.
- Source: `GET /v1/live/positions` for currently-open paper positions across all symbols (from `nexus:active_position:*`); subscribe to `/v1/live/positions/stream`.
- Per-symbol tile: overall state (`monitoring` / `waiting` / `blocked` / `triggered` / `fail_closed`), top-priority lane summary, current direction, freshness indicator.
- **Open Positions strip** (top of screen, only when count > 0): one row per open paper position with strategy, raw_symbol or spread legs, running return %, time held, distance to stop-loss / guard floor.
- Tap a tile to open Strategy Board for the symbol; tap an open position row to open Lane Drilldown filtered to that strategy.

The v0.1 docs do not define this screen. It is added in v1 because traders watch all 3 symbols concurrently.

#### S2 — Strategy Board (per symbol)

Centerpiece. The full lane view for one symbol.

- Source: `GET /v1/live/{symbol}/strategies` + `/strategies/stream`.
- Lane requirements per `nexus-strategy-message-ui-requirements-v0.1.md` §"Strategy Lane Requirements".
- Lane state machine per `nexus-surface.md` §"Lane state machine".
- Paper-signal lifecycle (BET / spread BET / LIQUIDATE) is **embedded as lane state**, not a separate screen. When a lane is in `bet` or `liquidated`, the lane card expands to show the paper signal detail (single-leg or spread) inline.
- When a lane is in `bet`, the inline detail shows **running P&L** sourced from `GET /v1/live/{symbol}/paper-position` (joins `nexus:active_position:*` with the latest contract quote from `options:live:contract_state:*`): current quote, running return %, time held, distance to stop-loss and guard floor. Updated live via `/paper-position/stream`.

#### S3 — Lane Drilldown (per strategy)

Tap a lane on S2 to open this screen.

- Source: `GET /v1/live/{symbol}/strategies/{strategy}` (full session message history).
- Show: chronological timeline of every message this lane published today, with full payloads.
- Single-leg paper signal card per v0.1 doc §"Single-Leg `BET`".
- Spread paper signal card per v0.1 doc §"Spread `BET`".
- Liquidation card per v0.1 doc §"`LIQUIDATE`".

#### S4 — Live Plan (per symbol)

Read-only view of today's published playbook for the selected symbol.

- Source: `GET /v1/app/playbook/{symbol}` for the published playbook with branches, triggers, levels.
- Source: `GET /v1/live/{symbol}/strategy-fit` for the live structure-fit ranking.
- Source: `GET /v1/live/{symbol}/participant-flow-context` for the latest flow context card.
- Source: `GET /v1/live/{symbol}/option-market-context` for the latest OMC card (premium totals, call/put bias, top contracts, cheap/costly side).
- Source: `GET /v1/live/{symbol}/window-audit` head for the latest `WINDOW_PRICING` (cheapest/costliest contract per window with pricing-quality flag).
- Show: active branch (bull/bear/neutral), entry / invalidation / evidence per branch, attached trigger group, current live permission state.
- Strategy Fit card per v0.1 doc §"Strategy Fit Card".
- Option Market Context card per v0.1 doc §"Option Market Context Card".
- Participant Flow Context card per v0.1 doc §"Participant Flow Context Card".
- **Pricing Guide card** (new) — see §Components. Shows cheap/costly read from latest reliable `WINDOW_PRICING`, plus call/put premium bias from OMC. Hides or mutes interpretation when `pricing_quality` is `unknown` or `degraded`.

This screen replaces v0.1's "Live Plan Permission Screen" and merges the four context cards (Strategy Fit, OMC, Participant Flow, Pricing Guide) into one canvas. The trader sees plan + permission + structure fit + flow + cost together because they think about them together.

### Why / Audit

#### S5 — Why No Trade Fired & Window Audit (per symbol)

The screen has two views, both backed by `GET /v1/live/{symbol}/window-audit` + `/window-audit/stream`. Tabs or a toggle switch between them; both must be reachable in one tap.

**View A — Window Audit Timeline** (default)

Per-window timeline ordered chronologically. Per v0.1 doc §"Why No Trade Fired Screen". Each entry shows: window label, per-strategy view summaries (with state, direction, fail-closed fields), pricing read if reliable, late event marker if any.

**View B — Strategy Reads Matrix** (new)

A matrix laid out as windows (rows, e.g. `09:30-10:00`, `10:00-10:30`, `10:30-11:00`, …) × strategies (columns, the 8 lanes). Each cell shows the per-strategy `WINDOW_VIEW` (`BULLISH` / `BEARISH` / `CHOP` / `UNKNOWN`) or `BLOCKED` for that completed window, with a freshness dot. Tap a cell to open the lane drilldown filtered to that window.

This view answers the trader's direct question: *"What did each strategy think about each completed window?"* Without it the only way to compare strategy reads across windows is to scroll through the timeline.

**Pricing Guide column** (new)

Append a "Pricing Guide" column to View B that shows the `WINDOW_PRICING` cheap/costly read per window with the `pricing_quality` flag. When `pricing_quality` is `degraded` or `unknown`, mute the cell and surface only the reason.

**System health tab**

A third tab surfaces system health: `GET /v1/live/symbols` readiness for all 3 symbols and source freshness across all live feeds. This is the same content as S8 — designers can either embed it here or link to S8; the requirement is that the trader can verify "is the data trustworthy right now" without leaving the audit context.

### My Library

#### S6 — My Triggers

The only authoring surface in v1. Trader builds, edits, deletes their own trigger groups.

- Source: intelligence-api `GET /api/v1/triggers/groups` (filter by `created_by=me`), `POST/PATCH/DELETE /api/v1/triggers/groups`.
- Source: intelligence-api `GET /api/v1/triggers/capabilities` for the source/field/operator catalog used by the builder.
- List view: trigger groups owned by the current user, with name, tags, last-evaluated state if available.
- Builder view: ordered conditions; each condition picks source → field → operator → value, with state_change and duration modifiers, required vs advisory.
- Test view: evaluate the group against current live state (read-only sandbox).

This is the single biggest UX-design ask not covered in v0.1. Trigger group authoring is novel and must be designed from scratch, but the data contract is fixed by the trigger capabilities catalog. Designers should treat it as a structured form builder, not a free-text editor.

In v1, traders **cannot attach a trigger group to a published plan** (admin-only path). Trigger groups are personal alerts. Make this distinction visible in copy.

### Review

#### S7 — Post-Session Review (per symbol, per date)

- Source: `GET /v1/historical/{symbol}/nexus-snapshot?date=YYYY-MM-DD`, `/nexus-strategies?date=...`, `/window-audit?date=...`.
- Source: intelligence-api EOD review reads (read-only).
- Layout per v0.1 doc §"Post-Session Review Screen".
- Outcome classifications per v0.1 doc.
- Note: OMC and participant-flow history is limited to last 48h until the EOD persistence worker is extended. Older sessions show those cards as "archive pending".

#### S8 — System Health

- Source: `GET /v1/live/symbols` readiness, freshness fields embedded in every snapshot/strategies response.
- Per v0.1 doc §"System Health".

## Components

Designers must produce these components with all required states. Most carry over from v0.1; new ones are flagged.

### Carried over from v0.1

- Symbol selector (3 symbols, locked list)
- Session status bar
- Permission status badge
- Trigger checklist row (display-only on S4)
- Freshness chip
- Source breakdown row
- Strategy Fit ranking row
- Context summary card
- Event timeline item
- Blocked reason panel
- Review outcome row
- Narrative / caveat block
- Single-leg paper signal card
- Spread paper signal card

### New in v1

- **Watchlist tile** (S1): symbol + overall state + top-lane summary + direction arrow + freshness dot.
- **Lane card** (S2): strategy display name + state badge + window label + direction + reason headline + freshness. Expandable for `bet` / `liquidated` to show paper signal detail inline.
- **Trigger group list row** (S6): group name + tags + condition count + last-evaluated state.
- **Trigger condition row** (S6 builder): source → field → operator → value picker with state_change and duration modifiers and required/advisory toggle.
- **Trigger group test result panel** (S6): per-condition pass/fail with current value vs required value.
- **Plan branch card** (S4): branch name (bull/bear/neutral) + entry condition + invalidation + evidence + attached trigger group reference.
- **Pricing Guide card** (S4, S5): cheap side / costly side / cheapest contract / costliest contract / `pricing_quality` flag + reason. Sourced from latest reliable `WINDOW_PRICING` and `OPTION_MARKET_CONTEXT` call/put bias. Mutes interpretation when pricing quality is unknown or degraded.
- **Strategy Reads Matrix** (S5 View B): rows = completed windows, columns = strategies, cells = `WINDOW_VIEW` direction or `BLOCKED` state with freshness dot. Tap cell to drill into that strategy + window.
- **Window Reads cell** (matrix component): direction badge (`BULLISH` / `BEARISH` / `CHOP` / `UNKNOWN`) or `BLOCKED` badge + freshness dot + tooltip with `reason_summary` headline.
- **Open Position row** (S1 strip, S2 lane expansion): symbol + strategy + raw_symbol or spread legs + entry quote + current quote + running return % + time held + stop-loss distance + guard-floor distance + quote freshness. Visually distinct from a settled `LIQUIDATE` card.

### Required states for every component

Loading / fresh / waiting / blocked / stale / missing / degraded / fail-closed / no-data-because-market-closed.

Color must not be the only status indicator (icon, label, or pattern always paired).

## Data Contracts

For every screen above, the response shapes are defined in `sigmatiq-api/docs/api/nexus-surface.md`. Designers can mock against those types directly. No need to invent fields.

Key contract guarantees:
- Every Nexus message body is passed through unchanged. Narrative, summary, reason_summary, freshness fields are always available where Nexus emits them.
- Freshness is on every live response.
- Empty / blocked / stale states are explicit, not inferred from missing fields.

## Out Of Scope For v1

Explicitly not designed in v1. Designers should not reserve space or wireframe these:

- Order entry, broker integration, broker handoff buttons.
- Plan authoring, editing, activation, retraction (admin-only backend; trader read-only).
- Attaching personal trigger groups to published plans (admin-only backend).
- Publishing ratings on plans (admin-only backend).
- Symbols beyond `SPY` / `QQQ` / `IWM`.
- Same-window day-over-day comparison (backend not built).
- Multi-tenant collaboration (sharing trigger groups, etc.).
- Mobile-only experience. v1 is responsive web; mobile push alerts deferred.
- Onboarding flows, billing, account settings beyond auth. Sigmatiq web shell already handles these.
- Full feature explainability layer (glossary, tour). Tooltips on hover are sufficient for v1.

## Acceptance Criteria

A v1 design passes review if a disciplined 0DTE trader can answer all of these without reading raw JSON:

1. Are SPY / QQQ / IWM monitorable now, and which is most active? (S1)
2. What does each Sigmatiq strategy think about SPY's latest completed window? (S2)
3. Did any strategy produce a paper signal? Single-leg or spread? Exact contract or legs? (S2 → S3)
3a. Are any paper positions currently open across my watchlist, and how are they doing right now? (S1 Open Positions strip)
4. What did Sigmatiq plan for SPY today, and is live permission open? (S4)
5. Which structure family fits SPY right now, and what is the no-trade reason if it ranks first? (S4)
6. Is flow leaning bullish / bearish / chop, and is it retail-like or institutional-like? (S4)
7. Why did SPY not fire? Which gates failed, which data was stale? (S5 Timeline)
7a. What did each strategy think about each completed window today? (S5 Matrix)
7b. Is premium cheap or expensive right now, and which side? (S4 Pricing Guide / S5 Matrix Pricing column)
8. Build a personal trigger group with three conditions and test it against current state. (S6)
9. After close, was Sigmatiq's allowed/blocked decision good? Did the strategy that fired work? (S7)
10. Is any required live source stale or down right now? (S8)

If a screen cannot answer its assigned questions in under 5 seconds during market hours, it fails review.

## Designer Deliverables

### Figma pages

1. Watchlist (S1)
2. Strategy Board (S2)
3. Lane Drilldown (S3) — with single-leg, spread, intermediate, liquidated, blocked variants
4. Live Plan (S4) — with strategy-fit, OMC, participant flow integrated
5. Why No Trade Fired & Window Audit (S5) — Timeline view, Strategy Reads Matrix view, System Health tab
6. My Triggers — list, builder, test (S6, three sub-pages)
7. Post-Session Review (S7) — date picker + per-symbol view
8. System Health (S8)
9. Empty / stale / missing / degraded / fail-closed / no-data states for every screen
10. Responsive web layout (desktop + tablet); mobile read-only out of scope for v1 designs

### Components

Per the components list above, with all 9 required states.

### Tokens

Color, typography, spacing tokens must distinguish:

- `chop` (market read) from `blocked` (data/safety failure) — different visual weight, not just color.
- `paper signal` from `informational` from `paper exit` — different badge treatment.
- Required vs advisory data freshness — required failure is a stronger fail-closed treatment.

### Copy

Use deterministic Nexus narratives (`summary`, `narrative`, `reason_summary`) as the primary text source on every screen. Designers do not write trade-decision copy; they write structural copy (labels, empty states, error states, helper text).

Forbidden language per v0.1 §"Copy Rules" applies to every screen, plus the platform-positioning constraints in §"Positioning — Technology Platform, Not Advisor". A copy review pass must verify no screen violates either set before design hand-off.

## Related Docs

- `nexus-ui-designer-requirements-v0.1.md` — copy rules, status semantics, original screen briefs.
- `nexus-strategy-message-ui-requirements-v0.1.md` — message taxonomy, lane-state behavior.
- `nexus-product-strategy-90-day-v0.1.md` — persona, daily loop, principles.
- `sigmatiq-api/docs/api/nexus-surface.md` — backend response shapes for every screen.
- `sigmatiq-api/docs/api/strategy-fit.md` — strategy fit ranking shape.
- `sigmatiq-api/docs/api/live-symbols.md` — readiness gate for the watchlist.
- `intelligence-api` API docs (in repo) — trigger groups CRUD and capabilities catalog.
