# Nexus UI Designer Requirements v0.1

## Purpose

Design the first productized Nexus experience for a disciplined 0DTE index-options trader. The UI must show what the system knows, what it does not know, and why it is allowing, blocking, invalidating, or standing down.

This is not an order-entry UI and must not look like one. It is a decision-support and audit interface.

For detailed strategy-lane and Nexus message requirements, use `docs/nexus-v2/nexus-strategy-message-ui-requirements-v0.1.md` alongside this document. That companion document is the source for how `WINDOW_VIEW`, `BLOCKED`, `INTERMEDIATE`, `BET`, spread `BET`, `LIQUIDATE`, `WINDOW_PRICING`, `OPTION_MARKET_CONTEXT`, `PARTICIPANT_FLOW_CONTEXT`, and `WINDOW_LATE_EVENT` should appear in the UI.

## Primary User

The primary user is a disciplined 0DTE `SPY` / `QQQ` / `IWM` options trader who already uses charting, dealer-level tools, and flow tools. They need live permission, structure fit, and post-session accountability.

Design for fast scanning during market hours and deeper review after close.

## Product Positioning In The UI

The UI should say:

- What the active plan is.
- Whether live data permits action.
- Why the system is waiting, blocked, triggered, invalidated, or superseded.
- Which structure family fits the live state.
- Which data is fresh, stale, missing, or degraded.
- What happened after the fact.

The UI should not say:

- Buy this.
- Sell this.
- Enter now.
- Guaranteed.
- High confidence means safe.
- Dealer is definitely doing X.

## Core Screens To Design

### 0. Nexus Strategy Board

Goal:

Show the current status of every implemented Nexus strategy for the selected symbol and session.

Required strategy lanes:

- `etf_confluence_sniper`
- `etf_open_specialist`
- `etf_low_sweep_core`
- `etf_flow_specialist`
- `etf_momentum_specialist`
- `etf_put_credit_open30_spread`
- `etf_call_credit_open30_spread`

Each lane must show:

- Strategy display name and code name.
- Window label and decision time.
- Latest message state: `WINDOW_VIEW`, `BLOCKED`, `INTERMEDIATE`, `BET`, `LIQUIDATE`, `NO_SIGNAL`, or `NOT_SCHEDULED`.
- Directional read when available: `BULLISH`, `BEARISH`, `CHOP`, or `UNKNOWN`.
- Top reason, using `summary` or `reason_summary` when available.
- Required data freshness.
- Paper-only or research-only label when applicable.

Design requirement:

The strategy board is the main Nexus product surface. It should not be hidden behind raw endpoint pages or generic cards.

### 1. Live Plan Permission Screen

Goal:

Show whether the active EOD plan is live-permitted now.

Primary states:

- `WAITING`
- `ALLOWED`
- `BLOCKED`
- `TRIGGER_FIRED`
- `INVALIDATED`
- `SUPERSEDED`
- `FAIL_CLOSED`

Required modules:

- Symbol selector: `SPY`, `QQQ`, `IWM`.
- Current session date and market status.
- Active EOD plan branch: bull, bear, neutral/no-trade.
- Live permission status.
- Trigger checklist.
- Required data freshness.
- Invalidation condition.
- Supersession status.
- Event timeline.

Critical UX requirement:

The trader must be able to answer within five seconds: "Can I consider this setup, and if not, why not?"

### 2. Trigger Checklist Component

Goal:

Show every required live gate and its current status.

Each row must show:

- Gate label.
- Status: pass, waiting, blocked, stale, missing.
- Current value.
- Required condition.
- Whether the gate is required or optional.
- Source freshness.

Example rows:

- `clock.minutes_after_open >= 20`.
- `live_health.health_score >= 0.80`.
- `market_status.trade_allowed == true`.
- `event_calendar.lockout_active == false`.
- `clock.minutes_to_close >= 90`.

Design requirement:

Required stale or missing data should visually fail closed. It should not look like a neutral warning.

### 3. Strategy Fit Card

Goal:

Show which option structure family fits current live state.

Required sections:

- Direction read: bullish, bearish, neutral, conflicted, unavailable.
- Regime read: contained, expansion, transitional, unavailable.
- Pricing read: buy premium, sell premium, avoid wide vol, unavailable.
- Ranked structures.
- No-trade explanation.
- Source breakdown.
- Freshness table.

Ranked structure cards:

- `long_call`
- `long_put`
- `call_debit_spread`
- `put_debit_spread`
- `put_credit_spread`
- `call_credit_spread`
- `iron_condor`
- `no_trade`

Each structure row must show:

- Rank.
- Fit score.
- Confidence.
- Why.
- Blocked reasons.
- Source contribution.

Design requirement:

`no_trade` is a first-class outcome, not an error state.

### 4. Option Market Context Card

Goal:

Show what the completed option window looked like without turning it into a trade recommendation.

Required sections:

- Window label and status: latest completed window, not tick-now.
- Call premium vs put premium.
- Most traded contracts.
- Cheap/costly contract read when pricing evidence is reliable.
- Pricing quality and reason.
- Liquidity quality.
- Late-event impact.
- Deterministic summary and caveats.

Design requirement:

If `pricing_quality` is `unknown` or `degraded`, cheap/costly reads must be visually muted or hidden.

### 5. Participant Flow Context Card

Goal:

Explain trade-shape flow in the latest completed window.

Required sections:

- Window side read: call-heavy, put-heavy, balanced, unknown.
- Directional read: bullish, bearish, chop, unknown.
- Confidence.
- Retail-like flow.
- Institutional-like or block-like flow.
- Positioning or hedge-like flow.
- Dominant strategy shape.
- Top contracts.
- Data quality.
- Caveats.

Language requirement:

Use inferred language:

- "appears"
- "looks like"
- "trade-shape suggests"
- "not true account identity"

Avoid definitive identity claims:

- Do not say "retail is buying".
- Do not say "institutions are buying".
- Do not say "dealers are betting".

### 6. Why No Trade Fired Screen

Goal:

Explain why a trade did not trigger.

Required modules:

- Active plan summary.
- Trigger timeline.
- Blocked gates.
- Stale or missing data.
- Window views.
- Pricing warnings.
- Late events.
- Current no-trade reason.

Key interaction:

User asks: "Why did SPY not fire?"

UI must answer with:

- The top blocking reason.
- Supporting gates.
- Whether data quality was the cause.
- Whether the plan was invalidated.
- Whether the system was waiting rather than blocked.

### 7. Post-Session Review Screen

Goal:

Show whether the system's allowed, blocked, invalidated, and no-trade decisions were good after the session.

Required modules:

- Session summary by symbol.
- Active plans and branches.
- Trigger events.
- Blocked events.
- Invalidations.
- Supersessions.
- Outcome classification.
- Shadow outcome for blocked triggers when available.

Outcome classifications:

- good trigger
- bad trigger
- good block
- bad block
- invalidated
- insufficient data

Design requirement:

Review rows must be concrete. Avoid abstract plan scores without event evidence.

## Information Architecture

Recommended navigation:

1. **Today**
   - Live permission
   - Strategy fit
   - Context cards
   - Event timeline

2. **Why / Audit**
   - No-trade explanation
   - Blocked gates
   - Late events
   - Freshness history

3. **Review**
   - Post-session review
   - Trigger outcome
   - Block outcome
   - Strategy Fit outcome

4. **System Health**
   - Live source status
   - Redis/source freshness
   - Monitor status
   - Fail-closed reasons

## Visual Hierarchy

The most important visual hierarchy during market hours:

1. Permission state.
2. Trigger or invalidation status.
3. Required data freshness.
4. Strategy Fit.
5. Option/participant context.
6. Detailed evidence.

Do not make large charts the first thing on the page unless they directly explain permission, invalidation, or structure fit.

## Status Semantics

Use consistent state colors and wording:

| State | Meaning | Visual treatment |
|---|---|---|
| `ALLOWED` | Live gates permit considering setup | Clear positive state, but not a buy instruction |
| `TRIGGER_FIRED` | Exact trigger group fired | High attention state with trigger evidence |
| `WAITING` | Not enough conditions yet, data is usable | Neutral/amber state |
| `BLOCKED` | Required condition failed | Strong warning state |
| `FAIL_CLOSED` | Required data stale/missing | Strongest safety state |
| `INVALIDATED` | Original thesis no longer valid | Strong negative state |
| `SUPERSEDED` | Better/updated plan replaced current one | Informational state with link to new plan |

## Copy Rules

Allowed language:

- "Live permission is blocked because flow is stale."
- "Strategy Fit ranks no_trade first because direction is conflicted."
- "Call premium dominated the latest completed window, but confidence is low."
- "This is a paper signal, not broker execution."

Avoid:

- "Buy calls now."
- "This trade will work."
- "Institutions are buying."
- "Dealers are betting bullish."
- "Guaranteed edge."

## Data Freshness Requirements

Every screen that uses live data must show freshness directly or through an obvious status indicator.

Required freshness display:

- Source name.
- Last updated time.
- Age.
- Max allowed age.
- Status: fresh, stale, missing, degraded.

Fail-closed behavior must be explicit. If required data is stale, the UI should say the system is not allowed to form a trade-permission decision.

## Designer Deliverables

### Required Figma Pages

1. Product overview flow.
2. Live Plan Permission screen.
3. Strategy Fit screen/card.
4. Option Market Context card.
5. Participant Flow Context card.
6. Why No Trade Fired screen.
7. Post-Session Review screen.
8. System Health screen.
9. Mobile alert/read-only variants.
10. Empty, stale, missing, degraded, and fail-closed states.

### Required Components

- Symbol selector.
- Session status bar.
- Permission status badge.
- Trigger checklist row.
- Freshness chip.
- Source breakdown row.
- Strategy Fit ranking row.
- Context summary card.
- Event timeline item.
- Blocked reason panel.
- Review outcome row.
- Narrative/caveat block.

### Required States For Each Major Component

- Loading.
- Fresh/valid.
- Waiting.
- Blocked.
- Stale.
- Missing.
- Degraded.
- Fail-closed.
- No data because market is closed.

## API Surfaces To Design Against

Current or near-current:

- `GET /v1/live/symbols`
- `GET /v1/live/{symbol}/strategy-fit`
- `GET /v1/live/{symbol}/participant-flow-context`
- Live context endpoints: `/flow`, `/gex`, `/dex`, `/chex`, `/vol-context`, `/pin`

Needed for productized Nexus UI:

- Live permission state endpoint.
- Nexus window audit endpoint over `WINDOW_VIEW`, `BLOCKED`, `WINDOW_PRICING`, `WINDOW_LATE_EVENT`.
- Direct option-market-context endpoint.
- Post-session trigger review endpoint.
- Same-window comparison endpoint.

## Non-Goals For The First Design

- Broker execution.
- Full account management.
- Complex portfolio analytics.
- Social feed.
- Generic chatbot-first UI.
- Broad multi-asset support beyond 0DTE index focus.

## Success Criteria

A real 0DTE trader should be able to use the design to answer:

- What is my active plan?
- Is live permission open?
- If not, exactly why not?
- If yes, what structure family fits?
- Is data fresh enough to trust?
- What invalidates this?
- What happened after the session?

If the UI cannot answer those questions quickly, it is not the right design.
