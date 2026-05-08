# Nexus Strategy And Message UI Requirements v0.1

## Purpose

This document gives UI designers the concrete Nexus strategy and message requirements that were missing from the broader UI brief. The Nexus product should be message-driven: every trader-facing screen should be grounded in a specific Nexus message, strategy, state, freshness field, or audit event.

The UI must help a trader decide what to do next, but it must not tell them to place an order. The product language is decision support, not execution instruction.

## Design Premise

Nexus has evolved from a simple trigger worker into a live strategy and context publisher. The UI should therefore focus on three layers:

1. **Strategy reads**: what each implemented strategy thinks about a completed window.
2. **Paper signal lifecycle**: candidate, final paper signal, liquidation, blocked, late-event audit.
3. **Market context**: option-market context, participant-flow context, pricing quality, contract activity, and freshness.

`sigmatiq-api` has many endpoints. The Nexus UI should not expose them as an API catalog. It should translate the Nexus messages and the few relevant Intelligence API endpoints into a trader workflow.

## Current Strategy Surface

Designers must understand that these are different strategy engines, not one generic signal.

| Strategy | Current role | Decision window | Trader-facing interpretation | UI requirement |
|---|---|---|---|---|
| `etf_confluence_sniper` | Phase 1 primary | `10:00-12:30` ET | Higher-priority confluence read using flow, pricing lag, and momentum alignment. | Show as a priority strategy lane and mark when shared group lock applies. |
| `etf_open_specialist` | Phase 2 primary | `10:00` ET from `09:30-10:00` window | Cheap-call open rule: call premium dominates while IV rank is low. | Show as open-window specialist with IV-rank and call-dominance evidence. |
| `etf_low_sweep_core` | Phase 2 compatibility | `10:00-10:30` ET entries | Low-sweep directional flow candidate retained from research. | Show sweep availability and block clearly if sweep classification is unavailable. |
| `etf_flow_specialist` | Phase 2 support | `10:30` ET from `10:00-10:30` window | Strong option-flow dominance with IV/GEX context. | Show flow dominance, aggressor quality, IV/GEX freshness, and model threshold if used. |
| `etf_momentum_specialist` | Phase 2 support | `11:00` ET from `10:30-11:00` window | Underlying persistence plus option-flow confirmation. | Show underlying persistence and flow confirmation separately. |
| `etf_put_credit_open30_spread` | Research paper-only | `10:00` ET from `09:30-10:00` window | Bullish open30 call dominance expressed as same-expiry put credit spread. | Show as spread/paper-only, not as single-leg signal; display short/long legs and net credit. |
| `etf_call_credit_open30_spread` | Research paper-only | `10:00` ET from `09:30-10:00` window | Bearish open30 put dominance expressed as same-expiry call credit spread. | Show as spread/paper-only, not as single-leg signal; display short/long legs and net credit. |

## Strategy Lane Requirements

Each strategy lane should be a compact card or row that can appear in a larger symbol dashboard.

Required fields:

- Strategy display name.
- Strategy code name for audit drilldown.
- Strategy status: `waiting`, `window_view`, `blocked`, `intermediate`, `bet`, `liquidated`, `no_signal`, `not_scheduled`.
- Window label, for example `09:30-10:00`.
- Decision time, for example `10:00 ET`.
- Directional read: `BULLISH`, `BEARISH`, `CHOP`, or `UNKNOWN`.
- Whether the read is informational or a paper candidate.
- Key evidence summary.
- Required data freshness summary.
- Blocked reason or no-signal reason.
- Latest message timestamp.
- Persistence/audit status when available.

Primary user question:

> What did each strategy think, did any strategy produce a candidate, and why did the others stand down?

## Message Taxonomy For UI

The UI should group Nexus messages by trader meaning, not by Redis key.

### Strategy Read Messages

Messages:

- `WINDOW_VIEW`
- `BLOCKED`

Trader meaning:

- `WINDOW_VIEW`: strategy formed a directional read for a completed window.
- `BLOCKED`: strategy could not safely form a view or candidate because required inputs were missing, stale, or untradable.

UI behavior:

- Show these in the strategy lane even when no trade candidate exists.
- Treat `BLOCKED` as a safety state, not as a neutral state.
- Show `reason_summary`, missing fields, and stale/missing source names.

### Candidate Lifecycle Messages

Messages:

- `INTERMEDIATE`
- `BET`
- `LIQUIDATE`

Trader meaning:

- `INTERMEDIATE`: heuristic passed and a stage-1 paper candidate exists.
- `BET`: final paper signal passed quote gate and lock rules.
- `LIQUIDATE`: paper lifecycle exit context for the exact tracked contract.

UI behavior:

- Show `INTERMEDIATE` as candidate forming, not final signal.
- Show `BET` as paper signal with exact contract evidence.
- Show `LIQUIDATE` as paper lifecycle exit, not a broker fill.
- Always show `paper_only` or equivalent copy for research/paper posture.

### Spread Paper Messages

Messages:

- Spread `BET` via `nexus_spread_overlay:{symbol}:{strategy}:{entry_label}` and `signal:spread:{strategy}`.

Trader meaning:

- Paper spread candidate, not managed by the current single-leg liquidation loop.

UI behavior:

- Spread candidates must be visually distinct from single-leg candidates.
- Show `instrument_type = vertical_credit_spread`.
- Show short leg and long leg separately.
- Show net credit, width, max theoretical risk, and quote freshness assumptions when available.
- Show a warning that current runtime does not attach spreads to the single-leg liquidation loop.

### Pricing And Market Context Messages

Messages:

- `WINDOW_PRICING`
- `OPTION_MARKET_CONTEXT`
- `PARTICIPANT_FLOW_CONTEXT`

Trader meaning:

- `WINDOW_PRICING`: cheap/costly read for completed window, if pricing evidence is reliable.
- `OPTION_MARKET_CONTEXT`: full-session option-market context, most active contracts, premium totals, pricing quality, liquidity quality.
- `PARTICIPANT_FLOW_CONTEXT`: trade-shape read: call-heavy/put-heavy, participant-like buckets, dominant strategy shape, data quality.

UI behavior:

- Put these in context cards below the strategy lanes.
- Do not make them look like strategy signals.
- If pricing quality is unknown/degraded, hide or mute cheap/costly interpretations.
- Use “latest completed window” language.

### Audit Messages

Messages:

- `WINDOW_LATE_EVENT`
- `BLOCKED`
- no-signal logs when exposed through API.

Trader meaning:

- Evidence for why the system did or did not act.

UI behavior:

- Show in an audit timeline.
- Do not allow late events to retroactively rewrite the displayed trade decision unless a separate corrected-review state exists.

## Recommended Dashboard Layout

### Desktop Layout

Top row:

- Symbol selector: `SPY`, `QQQ`, `IWM`.
- Session clock and market status.
- Live data health summary.
- Current active EOD plan branch.
- Overall Nexus state: `monitoring`, `waiting`, `blocked`, `triggered`, `invalidated`, `fail_closed`.

Second row:

- Strategy lane board with one row/card per implemented strategy.
- Each lane shows latest message state and the most important reason.

Third row:

- Strategy Fit card from Intelligence API.
- Option Market Context card from Nexus.
- Participant Flow Context card from Nexus.

Bottom row:

- Event timeline.
- Blocked/no-signal reasons.
- Data freshness detail.

### Mobile Layout

Mobile should not show all strategy details at once.

Primary mobile hierarchy:

1. Overall permission state.
2. Latest triggered/blocked strategy state.
3. Top reason.
4. Exact contract or no-trade explanation if relevant.
5. Swipe/drilldown for strategy lanes and context cards.

Mobile push alert copy should be short and non-instructional:

- `SPY: etf_flow_specialist paper signal formed. Quote fresh. View structure and invalidation.`
- `SPY: live permission blocked. GEX stale and vol context missing.`
- `QQQ: latest window reads CHOP. No candidate emitted.`

## Screen Requirements By Message

### `WINDOW_VIEW`

Show:

- Strategy name.
- Window label.
- Sentiment: `BULLISH`, `BEARISH`, `CHOP`.
- Summary and reason summary.
- Lead contract if present.
- Lead contract pricing lag and cheapness score if present.
- Freshness of required inputs.

Do not show:

- Entry button.
- Contract order ticket.
- Language implying trade permission.

### `BLOCKED`

Show:

- Strategy name.
- Window label.
- `FAIL_CLOSED` or `BLOCKED` badge.
- Missing or stale required fields.
- Source names and freshness status.
- `reason_summary`.

Designer instruction:

`BLOCKED` must look materially different from `CHOP`. `CHOP` is a market read. `BLOCKED` is a data or safety failure.

### `INTERMEDIATE`

Show:

- Candidate forming badge.
- Strategy.
- Direction.
- Lead contract if available.
- Evidence summary.
- What still must happen before final paper signal.

Designer instruction:

This should feel provisional. Do not use final-signal color treatment.

### Single-Leg `BET`

Show:

- Paper signal badge.
- Strategy.
- Direction.
- Exact `raw_symbol`.
- Expiry date.
- Strike.
- Option side.
- Entry quote snapshot.
- Quote freshness.
- Quote valid until.
- Execution reference price and max slippage metadata.
- Invalidation or liquidation policy if present.
- Persistence/audit status.

Designer instruction:

The trader should be able to manually reconstruct the option candidate in their broker, but the UI must not present a broker execution button in v1.

### Spread `BET`

Show:

- Paper spread signal badge.
- Strategy.
- `instrument_type`.
- Short leg: raw symbol, expiry, strike, side, quote.
- Long leg: raw symbol, expiry, strike, side, quote.
- Net credit/debit.
- Width.
- Theoretical max loss assumptions.
- Quote freshness for both legs.
- Paper-only limitation.

Designer instruction:

Spread cards should use a two-leg structure layout, not reuse the single-leg card with hidden fields.

### `LIQUIDATE`

Show:

- Paper exit badge.
- Strategy.
- Exact tracked `raw_symbol`.
- Exit reason.
- Entry reference price.
- Exit reference price.
- Return percentage.
- Quote freshness.
- Execution metadata.

Designer instruction:

This is not a broker fill. Label it as paper lifecycle exit context.

### `WINDOW_PRICING`

Show:

- Window label.
- Cheap side and costly side when reliable.
- Cheapest contract.
- Costliest contract.
- Pricing quality.
- Pricing quality reason.

Designer instruction:

If pricing quality is not reliable, the card should say why and avoid showing a directional cheap/costly interpretation as primary content.

### `OPTION_MARKET_CONTEXT`

Show:

- Latest completed window.
- Premium totals.
- Call/put premium bias.
- Trade count and contract count.
- Most traded contracts.
- Cheap/costly side if reliable.
- Liquidity quality.
- Pricing quality.
- Late-event impact.
- Narrative and caveats.

Designer instruction:

This card answers “what happened in options this window,” not “what should I trade.”

### `PARTICIPANT_FLOW_CONTEXT`

Show:

- Latest completed window.
- Window side read.
- Directional read.
- Confidence.
- Retail-like flow.
- Institutional-like or block-like flow.
- Positioning/hedge-like flow.
- Dominant strategy shape.
- Top contracts.
- Data quality and caveats.

Designer instruction:

Use inferred identity language. Prefer `block-like`, `small-lot-like`, and `trade-shape suggests` over hard identity claims.

### `WINDOW_LATE_EVENT`

Show:

- Window label.
- Late event count.
- Late premium impact.
- Raw symbols if available.
- Whether this changed review context.

Designer instruction:

This is an audit marker, not a new signal.

## Trader Decision Map

| Trader question | Primary UI module | Backing message/API | Required answer style |
|---|---|---|---|
| Is anything actionable now? | Overall permission + strategy lanes | Nexus messages plus active plan state | “Allowed to consider,” “waiting,” “blocked,” or “paper signal formed.” |
| Which strategy is firing? | Strategy lane board | `INTERMEDIATE`, `BET`, spread `BET` | Show strategy name, window, direction, evidence, and paper-only state. |
| What do the strategies think if no trade fired? | Strategy lane board | `WINDOW_VIEW`, `BLOCKED` | Show per-strategy BULLISH/BEARISH/CHOP or fail-closed reason. |
| Why did it not fire? | Audit timeline | `BLOCKED`, no-signal reasons, `WINDOW_PRICING` | Show top blocking/no-signal reason first. |
| Is premium cheap or expensive? | Pricing/context card | `WINDOW_PRICING`, `OPTION_MARKET_CONTEXT`, `/strategy-fit` | Show pricing quality before interpretation. |
| What side is flow leaning? | Participant/context card | `PARTICIPANT_FLOW_CONTEXT` | Say latest completed window and show confidence/caveats. |
| What exact contract is being tracked? | Paper signal card | `BET`, `LIQUIDATE` | Show exact `raw_symbol`, strike, expiry, side, quote freshness. |
| Did the paper signal work? | Review screen | `BET`, `LIQUIDATE`, EOD review | Show entry/exit references and outcome classification. |

## Intelligence API Integration In The Nexus UI

The UI should use Intelligence API endpoints as product answers, not as a raw endpoint list.

Current important endpoints:

- `GET /v1/live/symbols`: live-ready symbol universe and readiness.
- `GET /v1/live/{symbol}/strategy-fit`: direction/regime/pricing and ranked structure families.
- `GET /v1/live/{symbol}/participant-flow-context`: Nexus participant-flow read-through.
- `/flow`, `/gex`, `/dex`, `/chex`, `/vol-context`, `/pin`: drilldown context, not primary navigation.

Needed endpoints for the UI to be complete:

- Live permission state endpoint that joins active EOD plan state with Nexus live gates.
- Nexus strategy message endpoint over `WINDOW_VIEW`, `BLOCKED`, `INTERMEDIATE`, `BET`, spread `BET`, `LIQUIDATE`.
- Nexus window audit endpoint over `WINDOW_PRICING`, `WINDOW_LATE_EVENT`, no-signal reasons, and freshness failures.
- Direct option-market-context endpoint over `nexus_option_market_context:{symbol}:latest`.
- Post-session Nexus review endpoint linking plan branch, message history, and outcome.

## Designer Instructions

### Do

- Design around strategy lanes and message states.
- Make stale/missing data visually explicit.
- Make `no trade`, `blocked`, and `chop` visibly different.
- Show exact window labels and session date.
- Show exact contract identity for paper signals.
- Show paper-only and research-only labels where applicable.
- Use deterministic `summary`, `narrative`, and `reason_summary` fields as the primary text source.
- Give users a clear audit trail from plan to message to outcome.

### Do Not

- Collapse all Nexus strategies into one generic “AI signal.”
- Treat context feeds as trade signals.
- Hide blocked reasons behind an info tooltip.
- Show a green “buy” affordance.
- Present spread candidates as if they are managed like single-leg candidates.
- Use color as the only status indicator.
- Let Strategy Fit override fail-closed Nexus states.

## Required Designer Deliverables

Add these to the existing UI requirements deliverables:

1. Strategy lane board for all current Nexus strategies.
2. Message timeline showing `WINDOW_VIEW`, `BLOCKED`, `INTERMEDIATE`, `BET`, spread `BET`, `LIQUIDATE`, `WINDOW_PRICING`, `OPTION_MARKET_CONTEXT`, `PARTICIPANT_FLOW_CONTEXT`, and `WINDOW_LATE_EVENT`.
3. Single-leg paper signal card.
4. Spread paper signal card.
5. Blocked/fail-closed state component.
6. No-signal explanation component.
7. Context cards for option market and participant flow.
8. API missing-state designs for endpoints that are not built yet.
9. Mobile alert variants for trigger, blocked, window view, paper signal, and liquidation.
10. Post-session review row connected to exact Nexus message history.

## Acceptance Criteria For Design Review

A design passes review only if a trader can answer these questions without reading raw JSON:

- Which strategies are active for this symbol and session?
- What did each strategy read for the latest completed window?
- Did any strategy produce a paper candidate?
- If a strategy was blocked, which required data failed?
- Is the latest context from a completed window or current tick state?
- Is the signal single-leg or spread?
- Is the signal paper-only?
- What exact contract or spread legs are involved?
- What is the source freshness?
- Why should the trader not act when data is stale, conflicted, or untradable?
