# Nexus Product Strategy And 90-Day Plan v0.1

## Purpose

This document defines the near-term product direction for Sigmatiq across three existing systems:

- **Nexus**: live monitoring, trigger evaluation, invalidation, supersession, live option-market context, participant-flow context, and paper signal lifecycle messages.
- **Intelligence API**: EOD playbooks, live strategy fit, live context endpoints, and EOD review.
- **MCP Server**: programmatic lifecycle surface for plan generation, activation, retraction, consensus, in-session state, and review tools.

The goal is not to build a generic AI trading assistant. The goal is to build a credible 0DTE decision-support product that a disciplined index-options trader would pay for and trust with real money.

## Product Principles

- EOD owns planning.
- Live owns current-session permission.
- Live wins for entry gating.
- Fail closed on stale or missing required live data.
- Claim `system_monitored` only when a verified monitor evaluates the exact trigger group.
- No broker execution in the core platform.
- Users decide and act.
- Current focus surface is 0DTE index options: `SPY`, `QQQ`, `IWM`.
- Product language must distinguish facts, reads, paper signals, and user actions.

## Primary Trader Persona

### Persona: Evan, The Disciplined 0DTE Index-Options Trader

Evan trades `SPY`, `QQQ`, and sometimes `IWM` 0DTE options. He is not a YOLO trader. He trades one to three setups per day, mostly between `09:45` and `14:30` ET.

Current tools:

- TradingView or Thinkorswim for charts.
- SpotGamma or MenthorQ for dealer levels.
- Unusual Whales or FlowAlgo for flow.
- Discord or private chat rooms for narrative.

Daily workflow today:

- **Pre-market**: checks futures, prior-day levels, gamma walls, macro events, and whether the day may trend, chop, or reverse.
- **Open**: watches price, VWAP, opening range, volume, and option flow.
- **Midday**: decides whether premium is worth buying or selling.
- **Close**: avoids late 0DTE theta and liquidity risk unless the signal is strong.
- **Post-close**: reviews manually and inconsistently.

Where Evan loses money or time:

- Enters when the EOD thesis is good but live data is stale or contradictory.
- Chases after the move has already consumed most of the implied move.
- Buys premium when vol is too expensive.
- Treats unusual flow as directional when it may be hedging, closing, or spread-related.
- Cannot consistently review why rejected or missed trades would have worked or failed.

What Evan would pay for:

- Live permission on top of an EOD plan.
- Clear blocked reasons.
- Structure fit that says when to prefer long premium, debit spread, credit spread, iron condor, or no trade.
- A post-session review that proves whether the system was right to trigger, block, invalidate, or stand down.

### Personas Not Optimized For

- **Fully automated execution traders**: core platform does not place broker orders.
- **Long-horizon investors**: the current product is intraday 0DTE index decision support, not portfolio allocation or fundamental investing.

## Core Product Loop

### Prior Day, 16:00-18:00 ET: EOD Plan Creation

Systems:

- Intelligence API generates conditional playbooks.
- MCP exposes generation, consensus, activation, and lifecycle tools.

Trader sees:

- Tomorrow's plan per symbol.
- Bull branch, bear branch, no-trade conditions.
- Entry, confirmation, invalidation, evidence, trigger groups, and risk context.
- Whether the plan is monitorable by Nexus.

Trader action:

- Reviews plan.
- Activates only plans they are willing to trade.
- Rejects weak plans.

### Pre-Market, 08:00-09:20 ET: Readiness Check

Systems:

- Intelligence API checks market status, events, overnight context, EOD anchors, and live readiness.
- Nexus verifies live feed warmup and monitor readiness.

Trader sees:

- Active plans.
- Live readiness.
- Event lockouts.
- Required live sources that are stale or missing.

Trader action:

- Chooses which symbols to watch.
- Does not enter yet.

### Open, 09:30-10:00 ET: No-Chase Period

Systems:

- Nexus evaluates live data and completed-window context.
- Intelligence API serves live context and strategy fit.

Trader sees:

- Window read: bullish, bearish, chop, or unknown.
- Whether data is fresh.
- Whether the active branch is close to trigger.
- Whether premium is cheap, fair, expensive, or unsafe.

Trader action:

- Watches.
- Acts only if the plan explicitly allows open-window trades and Nexus confirms.

### Primary Window, 10:00-12:00 ET: Live Permission And Triggering

Systems:

- Nexus evaluates exact trigger groups.
- Intelligence API serves `/v1/live/{symbol}/strategy-fit`, `/flow`, `/gex`, `/vol-context`, `/participant-flow-context`, and current playbook state.
- MCP exposes in-session lifecycle state.

Trader sees:

- Active branch state.
- Trigger fired, waiting, blocked, invalidated, or superseded.
- Best-fit structure family.
- Invalidation condition.

Trader action:

- Decides whether to take the trade.
- Chooses structure based on Strategy Fit.
- Acts manually in broker.

### Midday, 12:00-14:30 ET: Permission Decay

Systems:

- Nexus monitors invalidation, supersession, stale data, pricing deterioration, and context changes.
- Intelligence API continues live context and strategy fit.

Trader sees:

- Whether the original thesis remains live-permitted.
- Move-consumed context.
- Strategy Fit changes.
- Conflicted flow or pricing warnings.

Trader action:

- Holds, trims, or avoids new entries.

### Late Day, 14:30-16:00 ET: Exit And Review Capture

Systems:

- Nexus monitors invalidation and late-day risk gates.
- MCP records lifecycle state.
- Intelligence API prepares EOD review inputs.

Trader sees:

- Late-day theta/liquidity risk.
- Trigger validity.
- Invalidation status.
- Flatten guidance as context, not execution.

Trader action:

- Exits manually.
- Marks whether they acted.

### Post-Close, 16:00-18:00 ET: EOD Review

Systems:

- Intelligence API review pipeline scores plan quality.
- MCP exposes review publishing and retrieval.
- Nexus event history provides live decision evidence.

Trader sees:

- Whether the plan was directionally right.
- Whether Nexus correctly permitted or blocked.
- Whether rejected triggers would have worked or failed.
- Whether live data failed.
- Whether Strategy Fit was useful.

Trader action:

- Reviews outcome.
- Adjusts trust in the system.

## Ranked Use Cases

### 1. Live-Permissioned EOD Playbook

Pitch:

Turn tomorrow's EOD playbook into a live allowed, blocked, invalidated, or waiting decision system.

Pain solved:

A bullish SPY plan can still be untradeable if live flow is mixed, GEX is contained, and IV is expensive. Sigmatiq should stop the trader from taking that setup.

Systems involved:

- Intelligence API creates EOD playbooks.
- MCP activates and manages lifecycle.
- Nexus evaluates live trigger groups and emits trigger, invalidation, and supersession events.

Exists today:

- EOD conditional playbooks.
- MCP lifecycle tools.
- Nexus trigger evaluator concepts and live message infrastructure.
- Honest monitor semantics are established.

Needs building:

- Productized Nexus surface.
- Exact trigger-group monitor verification.
- Trader-facing live permission card.
- Alerting for trigger, invalidation, and supersession.
- Audit trail connecting EOD plan to live gates and outcomes.

Defensibility:

Competitors usually provide levels, flow, alerts, or strategy ideas. This ties a prior-day thesis to live permission and post-session review.

Risk:

Loose triggers create noise. Overly strict triggers miss trades.

Rank:

Highest willingness to pay and feasible inside two quarters.

### 2. Live Strategy Fit For Structure Selection

Pitch:

Given current live state, rank which option structure fits: long call, long put, debit spread, credit spread, iron condor, or no trade.

Pain solved:

A trader can be directionally right and still lose by buying the wrong structure. Bullish but contained and expensive vol may favor a put credit spread or no trade over a long call.

Systems involved:

- Intelligence API computes direction, regime, pricing, and ranked structures.
- Nexus supplies enriched option-market context.
- MCP exposes the result to agents and prompts.

Exists today:

- `GET /v1/live/{symbol}/strategy-fit`.
- Live context endpoints.
- Nexus option-market context feed.

Needs building:

- Validation of scoring.
- UI explanation.
- Direct option-market-context endpoint.
- Confidence calibration.
- Historical replay review of recommended structures.

Defensibility:

This combines live flow, GEX, vol context, and intraday option-market context into a structure fit, not just a static strategy suggestion.

Risk:

Ranking can sound more precise than it is. Confidence must remain display-only until validated.

### 3. Why No Trade Fired

Pitch:

Explain exactly why the system did not allow a trade.

Pain solved:

If SPY rips and no alert fires, the trader needs to know whether the system missed it or correctly blocked it because data was stale, price was extended, vol was unsafe, or trigger criteria were not met.

Systems involved:

- Nexus emits blocked and window diagnostics.
- Intelligence API exposes state and audit endpoints.
- MCP answers lifecycle questions.

Exists today:

- Nexus emits `BLOCKED`, `WINDOW_VIEW`, `WINDOW_PRICING`, and late-event messages.
- Some live readiness gates exist.

Needs building:

- API endpoint for Nexus window audit.
- Persistence of blocked reasons.
- UI timeline.
- MCP tool: `explain_no_trigger`.

Defensibility:

Most platforms alert on events. Few explain why nothing happened.

Risk:

Incomplete explanations damage trust faster than silence.

### 4. Same-Window Comparison

Pitch:

Show how today's completed window differs from yesterday or from a recent same-window baseline.

Pain solved:

A trader needs to know whether today's 10:00-10:30 call premium is genuinely unusual or just normal QQQ morning noise.

Systems involved:

- Nexus produces completed-window market and participant-flow context.
- Intelligence API reads persisted context and computes comparisons.
- MCP answers comparison questions.

Exists today:

- Nexus option-market and participant-flow context.
- Same-window comparison design.

Needs building:

- Persisted historical context store.
- API endpoint.
- Baseline logic by symbol/window/day type.
- UI comparison block.

Defensibility:

This moves beyond unusual prints to contextualized window behavior.

Risk:

Baselines can mislead on macro days, expiration days, FOMC days, and high-vol regimes.

### 5. Post-Session Plan Review

Pitch:

Score whether the plan, live gates, triggers, blocked decisions, and invalidations were actually good after the session.

Pain solved:

A trader cannot improve if they do not know whether they ignored a good system or the system missed the trade.

Systems involved:

- Intelligence API EOD review pipeline.
- MCP review tools.
- Nexus event logs.

Exists today:

- EOD review pipeline.
- MCP review tools.
- Some Nexus messages can be persisted.

Needs building:

- Unified review view.
- Links from review items to plan branches and live events.
- Shadow outcome for blocked triggers.
- Daily trust score by symbol/setup.

Defensibility:

A closed review loop is harder to copy than a signal feed.

Risk:

Generic review text will not build trust. It must show concrete event and outcome evidence.

## Capability Gap Analysis

| Capability needed | What exists today | Need to build | Size |
|---|---|---|---|
| Signal quality | EOD playbooks, `/v1/live/{symbol}/strategy-fit`, live context endpoints, Nexus trigger evaluator concepts | Trigger outcome tracking, confidence validation, shadow outcomes | L |
| Latency | Nexus reads Redis, live workers publish Redis keys | End-to-end latency measurement from ingestion to UI | M |
| Alerting and notification | Nexus Redis/PubSub messages, MCP lifecycle tools | Web/mobile/email alert preferences, dedupe, delivery audit | L |
| Backtesting and validation | EOD review pipeline, research/backtest repos | Replay harness for exact Nexus trigger groups and Strategy Fit outputs | XL |
| User trust building | Evidence fields, fail-closed rules, deterministic narratives | Trust timeline with allowed/blocked/freshness/outcome trail | M |
| Monetization surface | No clear paid packaging | Paid tiers around live permission, strategy fit, review archive, alerts | M |
| Mobile experience | Web direction and existing API surfaces | Read-only mobile alerts and plan state | L |
| Brokerage-adjacent flows | No broker execution by principle | Copyable/manual order-ticket handoff with risk and structure context | M |
| Live symbol readiness | `GET /v1/live/symbols` | UI and MCP integration | S |
| Strategy Fit API | `GET /v1/live/{symbol}/strategy-fit` | Scoring validation, explanation UI, direct option-market context | M |
| Participant flow context | `GET /v1/live/{symbol}/participant-flow-context` | Persist history and improve dealer-pressure inference | M |
| Nexus audit | `WINDOW_VIEW`, `BLOCKED`, `WINDOW_PRICING`, `WINDOW_LATE_EVENT` | API endpoint and UI timeline | M |
| Plan lifecycle | MCP tools for generation, activation, retraction, consensus, review | Product UI around lifecycle and permission state | L |
| Data freshness safety | Fail-closed rules and freshness fields | Consistent freshness contract across live endpoints and UI | M |

## Moat

### Defensible

The defensible part is the closed loop:

```text
EOD plan -> live permission -> trigger audit -> strategy fit -> post-session review
```

The moat improves when every trade idea has:

- prior thesis,
- live permission,
- exact data freshness,
- blocked reason,
- post-session outcome.

### Not Defensible

These are easy to copy:

- LLM explanations.
- Generic live dashboards.
- Redis-backed live feeds.
- Basic unusual-trade labels.
- Static strategy cards.
- Gamma wall display.

### Replicable In Six Months By A Funded Competitor

- Live flow dashboards.
- Gamma overlays.
- AI chat over market data.
- Basic strategy recommendations.
- Basic alerts.

### Harder To Replicate

- Audited history of triggered, blocked, invalidated, superseded, and reviewed 0DTE decisions.
- Exact monitor verification semantics.
- Outcome dataset for rejected and accepted live decisions.
- Product trust built from daily post-session review.

Current honest assessment:

The moat is not strong until event persistence and outcome review are consistently shipped. Without that, Sigmatiq is another live options dashboard.

## Would-Trade Test

The use case that could be traded with real money first is Live-Permissioned EOD Playbook.

Setup:

- `SPY` 0DTE bullish continuation plan.
- EOD bull branch active.
- Market tradable.
- No macro/event lockout.
- Live data health good.
- Spot above VWAP or reclaiming VWAP after pullback.
- HIRO/flow bullish.
- GEX expansionary or not strongly containing.
- Vol context does not say avoid wide vol.
- Implied move is not mostly consumed.
- Strategy Fit ranks call debit spread or long call with acceptable pricing.

Entry signal:

- Nexus emits `trigger_fired` for the exact active bull trigger group.
- Strategy Fit status is `ok`.
- `call_debit_spread` or `long_call` ranks in the top two.

Exit:

- Target: first structural resistance or 25-35% option gain.
- Invalidation: lose VWAP after entry and HIRO flips neutral/bearish.
- Premium stop: option down 40-50%.
- Time stop: no follow-through within 20-30 minutes.
- Late-day rule: no fresh entry inside 90 minutes to close.

Sizing for $50k account:

- First use risk: 0.5-0.75% of account.
- Dollar risk: $250-$375 max loss.
- Scale only after review loop proves the system.

Required before clicking:

- End-to-end data age visible and fresh.
- Exact trigger group visible.
- Invalidation visible before entry.
- Quote freshness visible for structure.
- No missing required live inputs.
- Clear reason why no-trade is not ranked first.
- Event persisted for review.

## 90-Day Build Plan

### Sprint 1, Weeks 1-3: Ship Nexus Live Permission Timeline

Artifact:

- Live permission timeline for one symbol showing active EOD branch, required live gates, trigger status, invalidation status, and stale/missing data.

Systems:

- Nexus.
- Intelligence API.
- MCP.

User-visible change:

- Trader sees allowed, blocked, invalidated, or waiting for active `SPY` playbook.

Metric:

- At least 80% of active plan states have a concrete reason rather than unknown.

### Sprint 2, Weeks 4-6: Ship Strategy Fit Card With Audit-Quality Inputs

Artifact:

- Strategy Fit card for `SPY`, `QQQ`, `IWM` showing direction, regime, pricing, ranked structures, no-trade reason, freshness, and source breakdown.

Systems:

- Intelligence API.
- Nexus.

User-visible change:

- Trader sees whether current state favors long premium, defined-risk debit, credit spread, iron condor, or no trade.

Metric:

- Every `strategy-fit` response exposes required source freshness and fails closed when required sources are stale.

### Sprint 3, Weeks 7-9: Ship Why No Trade Fired

Artifact:

- API and UI timeline over `WINDOW_VIEW`, `BLOCKED`, `WINDOW_PRICING`, trigger checks, and late events.

Systems:

- Nexus.
- Intelligence API.
- MCP.

User-visible change:

- Trader can ask why `SPY` did not fire and get exact failed gates.

Metric:

- 90% of no-trigger sessions have at least one explicit blocked, waiting, or no-trade explanation.

### Sprint 4, Weeks 10-12: Ship Post-Session Review For Trigger Decisions

Artifact:

- Daily review page connecting EOD plan branches, Nexus trigger decisions, blocked reasons, invalidations, and outcome.

Systems:

- Intelligence API.
- Nexus.
- MCP.

User-visible change:

- Trader sees whether the system's allowed or blocked decisions were good after the close.

Metric:

- Every active monitored plan has a review classification: good trigger, bad trigger, good block, bad block, invalidated, or insufficient data.

Research spike:

- Strategy Fit confidence calibration.

Decision deadline:

- End of week 12. Confidence stays display-only unless validated.

## Top Risks

| Rank | Risk | Early warning | Mitigation |
|---|---|---|---|
| 1 | Live data quality is inconsistent | Frequent fail-closed states, stale Redis keys, low live health score, unexplained gaps | Daily market-open health dashboard, source freshness alerts, explicit fail-closed UI |
| 2 | Triggers are not tradable | Triggers fire after move is extended or spreads are too wide | Move-consumed gate, quote-quality gate, spread gate, post-trigger outcome review |
| 3 | Strategy Fit sounds smarter than it is | Users treat rankings as recommendations and lose money | Keep confidence display-only until validated, show no-trade and source breakdown |
| 4 | Product is right but traders do not pay | Users like review but do not use the platform live | Alert-first workflow and broker-adjacent manual handoff |
| 5 | Review loop is generic | EOD review lacks exact event and outcome evidence | Require concrete review rows with trigger time, blocked reason, and outcome |
