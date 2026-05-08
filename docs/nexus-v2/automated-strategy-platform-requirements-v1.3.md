# Automated Strategy Platform — Product & Engineering Requirements

**Version:** 1.2 draft  
**Status:** Updated review draft — trader-risk revision  
**Audience:** Product, engineering, design, compliance, operations  
**Document intent:** Define a greenfield product and technical requirements package for a self-directed strategy automation platform. This document is intentionally platform-neutral and does not assume any existing application, message bus, schema, or trading engine.

**Revision summary from v1.2:** Adds stop-type arming rules, circuit-breaker liquidation semantics, fill-realism calibration reference, forced-flatten failure handling, deterministic stop precedence, aggregate portfolio controls, strategy-version history sufficiency rules, shadow-outcome display guardrails, and exportable trade reconstruction.

**Revision summary from v1.1:** This version preserves the compliance-first product model and adds trader-facing options controls: configurable paper-fill realism, cost/slippage attribution, time-of-day filters, DTE/delta/liquidity filters, stronger stop-loss and trailing profit-guard semantics, daily-loss circuit breaker behavior, halt/no-quote states, expectancy reporting, multiple-policy experiments, portfolio concentration controls, strategy-version diff views, shadow outcomes for rejected matches, trade reconstruction, stronger paper/live disclosures, and explicit MVP exclusions for multi-leg options and corporate-action adjustment modeling.

---

## 1. Executive Summary

The product is a self-directed automated strategy platform that allows users to view generic strategy events, configure technical automation policies, run paper trading simulations, and eventually create live order drafts or live automated orders under explicit user authorization.

The platform must be designed around one core rule:

> A strategy event is not a user-specific trade decision. A trade-like action may occur only when an enabled user-created technical automation policy matches that event and all execution, quote, risk, platform, and authorization checks pass.

The intended product model is:

```text
Generic strategy event
        +
User-configured technical automation policy
        +
Execution, quote, risk, and platform validation
        =
Paper trade, live order draft, or approved live automated order
```

The product must not be designed as:

```text
The company decides which securities/options a subscriber should trade.
The company selects suitable strategies for the user.
The company manages user accounts without a regulated advisory framework.
The system auto-enrolls users into strategies.
The system silently changes user policies or strategy versions.
```

Paper trading is the MVP. Live order drafts and live auto-execution are future phases gated by legal, compliance, broker, and operational approval.

---

## 2. Regulatory and Product Boundary Notes

This section is not legal advice. It defines product requirements that should reduce ambiguity and make the platform easier to review with counsel.

In the U.S., the SEC describes an investment adviser as an individual or firm engaged in the business of providing investment advice or issuing securities reports/analyses for compensation. See the SEC glossary: [Investment Adviser definition](https://www.sec.gov/resources-small-businesses/glossary). The SEC has also described robo-advisers as registered investment advisers that use computer algorithms to provide investment advisory services online with often limited human interaction. See: [SEC Robo-Adviser Guidance announcement](https://www.sec.gov/newsroom/press-releases/2017-52).

Broker-dealer recommendation obligations can be triggered depending on facts and circumstances, including whether a communication is a call to action or is likely to influence a retail investor to trade. See: [SEC Regulation Best Interest compliance guide](https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/regulation-best-interest).

FINRA has warned investors about auto-trading services offered by unregistered entities and about claims such as beginner-friendly, risk-free, or consistent high monthly returns. See: [FINRA auto-trading investor alert](https://www.finra.org/investors/insights/auto-trading-unregistered-entities).

Counsel must review whether any federal or state investment adviser, broker-dealer, commodity, money transmission, consumer protection, privacy, or data retention obligations apply before any live order draft or live auto-execution capability is released.

### 2.1 Required product posture

The product must consistently present itself as:

```text
Self-directed automation
User-configured rules
Technical event matching
Paper simulation
Order drafting
User-authorized execution
```

The product must not present itself as:

```text
Personalized investment advice
Managed account service
Adviser-selected strategy allocation
Guaranteed return system
Risk-free automated trading
Beginner-proof trading system
Consistent income system
```

### 2.2 Required implementation posture

The implementation must prove, through logs and data, that automated actions came from explicit user configuration.

Every paper or live order lifecycle must be traceable to:

```text
user_id
policy_id
strategy_event_id
strategy_id
strategy_version
policy_snapshot_at_match
risk_check_results
quote_check_results
execution_decision
order_lifecycle_state
created_at timestamp
correlation_id
```

### 2.3 Recommendation-avoidance requirement

The platform must not create user-specific trade intent from strategy events alone. The system may display generic strategy events and may process user-created policies, but it must not infer that a user should trade because a strategy event exists.

### 2.4 Compliance review gates

Formal compliance review is required before release of:

```text
Strategy catalog copy
Strategy descriptions
Performance display format
Automation setup copy
Disclosure text
Manual live order draft flow
Live auto-execution flow
Broker connection flow
Any public claims about performance, risk, or user outcomes
```

---

## 3. Product Goals

### 3.1 MVP goals

The MVP must allow users to:

1. Browse a catalog of generic algorithmic strategies with objective performance context.
2. View real-time and historical strategy events.
3. Create paper-only automation policies.
4. Simulate paper trades when user policies match strategy events.
5. Configure paper-fill realism and view modeled spread/slippage cost separately from P&L.
6. Configure options-specific contract filters including DTE, delta, spread, volume, and open interest when data is available.
7. Configure intraday time controls including entry windows, no-entry-before/after windows, and forced flatten time.
8. Configure stop-loss and profit-guard logic with clear option-premium, underlying-price, and trailing/high-water semantics.
9. Enforce daily-loss limits as a circuit breaker, not only as an entry gate.
10. Track open and closed paper positions with quote provenance, quote status, and exit-rule armed/suspended state.
11. Review why events matched or were rejected.
12. Run multiple enabled paper policies against the same strategy version for controlled user experiments.
13. Apply basic portfolio-level concentration controls across policies and strategies.
14. Pause, resume, or disable automation.
15. Use a user-level kill switch.
16. Review an immutable audit trail and user-facing trade reconstruction.
17. Review session-level paper performance summaries including expectancy and transaction-cost drag.
18. Inspect order lifecycle states including accepted, partially filled, filled, cancelled, expired, and rejected.

### 3.2 Future goals

Future phases may allow users to:

1. Connect a brokerage account.
2. Generate live order drafts from matched strategy events.
3. Manually confirm live orders.
4. Enable live auto-execution only after explicit authorization and compliance approval.
5. Compare paper, backtest, and live performance with clear labels.
6. Configure broker-supported time-in-force and order handling settings.
7. Use advanced option-risk logic such as IV/theta-adjusted stops if data quality and validation are approved.
8. Use deterministic backtests or paper-history readiness checks before enabling any live order-draft flow.
9. Model corporate actions, adjusted options, assignments, exercises, and multi-leg option structures after separate product, engineering, and compliance review.

### 3.3 Non-goals for MVP

The MVP must not include:

```text
Live broker order submission
Live auto-execution
Personalized strategy recommendations
Suitability scoring
User-specific portfolio advice
Auto-enrollment into strategies
Managed-account behavior
Strategy ranking as “best for you”
Claims of guaranteed or expected returns
Multi-leg options strategies
Corporate-action or adjusted-options modeling
Option assignment/exercise modeling
IV/theta-adjusted stop automation unless separately approved
Real-money buying power checks
Real-money broker order routing
```

---

## 4. Core Product Principles

### 4.1 Separation of concerns

The system must separate these layers:

```text
1. Strategy signal generation
2. User policy configuration
3. Policy snapshotting and matching
4. Quote, contract, risk, portfolio, and execution validation
5. Paper/live execution lifecycle
6. Position monitoring
7. Audit, reporting, and trade reconstruction
```

A strategy signal generator must not know how much a specific user should trade. A user automation policy defines whether and how a user wants the platform to react to a generic signal.

### 4.2 User control

The user must explicitly control:

```text
Strategy selected
Strategy version selected
Paper/manual-live/live-auto mode
Allowed symbols or instruments
Allowed direction
Maximum trade size
Maximum daily trades
Maximum daily loss
Entry order type
Entry pricing rule
Paper-fill realism setting
Order time-in-force
Exit pricing rule
Stop-loss type and threshold
Stop-loss arming delay
Profit-guard type and threshold
Time-of-day entry window
Forced flatten time
DTE and contract-risk filters
Delta and liquidity filters
Quote freshness tolerance
Spread tolerance
Duplicate position behavior
Multiple-policy experiment behavior
Portfolio concentration limits
Session close behavior
Automation enabled/disabled state
```

### 4.3 Version pinning

All automation policies must pin a strategy version. New strategy versions must not silently replace the version used by an enabled user policy.

Strategy-version upgrades must show, at minimum:

```text
Current pinned version
Available new version
Plain-English change summary
Release notes
Backtest comparison over the same historical window, when available
Paper performance comparison over the user's observed window, when available
Disclosure that upgrade choice remains self-directed
```

### 4.4 Auditability

Every meaningful user action and system action must be recorded. The product must be able to answer:

```text
Why did this paper/live order happen?
Which user policy caused it?
What did the user configure?
What policy snapshot was active?
What signal matched?
What checks passed or failed?
What quote and contract-risk data was used?
What price was requested?
What fill model and fill-realism mode was used?
What spread and slippage cost was modeled?
What position state changes occurred?
Who changed the policy and when?
```

### 4.5 Clear labels

Backtest, paper, simulated, shadow, draft, and live results must be clearly labeled. Paper performance must never be displayed as live performance. Shadow outcomes must never be presented as trades the user actually took.

### 4.6 Deterministic replay

Paper matching, paper order lifecycle decisions, paper fill decisions, position updates, exit triggers, daily-loss circuit breaker actions, and shadow outcomes must be reproducible from stored inputs. Any probabilistic fill model must store its seed, model version, probability, and realized decision.

### 4.7 Single-leg MVP scope

MVP supports single-leg option paper trades only. Multi-leg strategies require a future `legs[]` schema, multi-leg risk checks, multi-leg fill model, and separate compliance/product review.

### 4.8 Options-specific risk semantics

Options automation must not treat an option contract as a generic equity order. The platform must account for spread width, quote age, expiration, delta, liquidity, time of day, premium decay, and halt/no-quote states when matching policies, simulating fills, monitoring positions, and presenting results.

### 4.9 Performance and transaction-cost transparency

Paper performance must separate:

```text
Gross paper trade P&L
Modeled spread cost
Modeled slippage cost
Net paper P&L
Slippage versus mid
Fill model and fill-realism mode
```

The product must not allow users to confuse strategy behavior with modeled execution friction.

### 4.10 Internal event codes versus UI labels

Internal event codes may use precise system names such as `ENTRY_SIGNAL` and `EXIT_SIGNAL`. UI display labels must avoid recommendation-like phrasing and should use labels such as:

```text
Strategy entry condition met
Strategy exit condition met
Strategy observation
Strategy blocked by configured condition
```

---

## 5. Product Modes

### 5.1 Strategy discovery mode

Users can browse strategy metadata and observe strategy events. No execution occurs.

```text
Strategy emits event
User sees event
No policy match occurs
No paper order occurs
No live order draft occurs
```

### 5.2 Paper automation mode — MVP

Users configure paper-only policies. The system simulates order acceptance, fills, positions, P&L, exits, quote states, daily-loss circuit breaker actions, and portfolio limit effects.

```text
Strategy event occurs
Enabled user policy snapshot matches
Risk, quote, contract, portfolio, and execution checks pass
Paper order is created
Paper fill decision is simulated
Paper position is opened if fill occurs
Position is updated from market data
Exit rule, forced-flatten rule, or circuit breaker closes position
Session summary and trade reconstruction are generated
```

### 5.3 Manual live order draft mode — future

Users can allow the system to create live order drafts. The user must manually confirm before any broker order is submitted. Manual live order drafts must be gated by legal/compliance approval and a user-facing readiness checklist.

```text
Strategy event occurs
Enabled user policy snapshot matches
Risk checks pass
Readiness/disclosure checks pass
Live order draft is created
User reviews draft
User confirms
Broker order is submitted
```

### 5.4 Live auto-execution mode — future gated

Live auto-execution must remain disabled until formal approval.

```text
User connects broker
User accepts required agreements
User creates strict live automation policy
Strategy event matches
Risk checks pass
Broker order is submitted automatically
Position lifecycle is tracked
```

Requirements:

```text
Disabled by default
Feature-flagged
Requires explicit user authorization
Requires broker approval checks
Requires real-time kill switch behavior definition
Requires portfolio-level controls
Requires enhanced audit trail
Requires incident response workflow
Requires compliance approval before release
```

Future live kill-switch behavior must explicitly define whether the system cancels open orders, creates closing orders, blocks only new orders, or requires user confirmation for close/cancel actions.

---

## 6. Users and Roles

### 6.1 Self-directed user

Can:

```text
View strategies
View strategy events
Create paper automation policies
Enable/disable paper policies
Configure risk limits
Configure options-specific contract filters
Configure time-of-day controls
Configure paper-fill realism
Configure stop-loss and profit-guard rules
Run multiple paper policies for the same strategy version
Configure basic portfolio concentration limits
View paper positions and quote states
Manually cancel paper orders
Manually close paper positions
Review event timelines
Review trade reconstruction
Review audit trail
Trigger user kill switch
Create live order drafts in future phase
Authorize live automation in future phase
```

Cannot:

```text
Be auto-enrolled into strategies
Receive hidden personalized recommendations
Have policies changed without explicit action
Have strategy versions silently upgraded
Bypass required risk/execution checks
Bypass compliance gates for live modes
```

### 6.2 Admin/operator

Can:

```text
Pause a strategy globally
Pause a symbol globally
Pause an asset class globally
Pause a market data source
Activate platform kill switch
Review processing failures
Review dead-letter events
Review system health dashboards
Disable a broken strategy version
Configure platform-level maximums that constrain user policies
```

Cannot:

```text
Enable a user policy without user action
Increase a user's risk limits
Submit a live trade on behalf of a user
Silently change a user's automation policy
Silently upgrade a user's pinned strategy version
```

### 6.3 Compliance reviewer

Can:

```text
Review product copy
Review strategy descriptions
Review disclosures
Review performance display format
Review strategy-version upgrade copy
Review audit records
Review strategy release notes
Approve or reject live automation release
```

---

## 7. Core Product Objects

### 7.1 Strategy

A strategy is a generic algorithmic method that emits strategy events. A strategy is not a personalized recommendation engine.

```json
{
  "strategy_id": "strategy_001",
  "name": "Large Cap Intraday Options Flow",
  "description": "Detects intraday options flow alignment using predefined technical conditions.",
  "asset_classes": ["EQUITY_OPTIONS"],
  "supported_symbols": ["SPY", "QQQ", "AAPL"],
  "supported_directions": ["BULLISH", "BEARISH"],
  "time_horizon": "INTRADAY",
  "status": "ACTIVE",
  "created_at": "2026-05-07T14:00:00Z"
}
```

### 7.2 Strategy version

Every strategy must have immutable versions. Version upgrades are opt-in for each user policy.

```json
{
  "strategy_version_id": "strategy_001:v1.3.0",
  "strategy_id": "strategy_001",
  "version": "1.3.0",
  "config_hash": "sha256_config_hash",
  "model_hash": "sha256_model_hash",
  "release_notes": "Updated quote freshness, spread, and DTE filters.",
  "change_summary": "Narrowed entry conditions and changed default 0DTE flatten time.",
  "status": "ACTIVE",
  "created_at": "2026-05-07T14:00:00Z"
}
```

Required upgrade metadata:

```text
release_notes
change_summary
changed_parameters_json
backtest_comparison_json, if available
paper_observed_window_comparison_json, if available
known_limitations
approval_status
```

### 7.3 Strategy event

A strategy event is a generic output from a strategy. It is not personalized to any user. Internal event codes may include `ENTRY_SIGNAL` and `EXIT_SIGNAL`, but UI labels must use non-recommendation phrasing.

```json
{
  "strategy_event_id": "evt_123",
  "strategy_id": "strategy_001",
  "strategy_version": "1.2.0",
  "event_type": "ENTRY_SIGNAL",
  "display_label": "Strategy entry condition met",
  "symbol": "SPY",
  "instrument_type": "OPTION",
  "direction": "BULLISH",
  "underlying_price": 558.20,
  "contract": {
    "raw_symbol": "SPY   260507C00560000",
    "expiry": "2026-05-07",
    "strike": 560,
    "option_type": "CALL",
    "days_to_expiry": 0
  },
  "contract_risk": {
    "delta": 0.46,
    "gamma": 0.08,
    "theta": -0.12,
    "vega": 0.03,
    "intrinsic_value": 0.00,
    "extrinsic_value": 1.25,
    "extrinsic_value_pct": 100.0,
    "open_interest": 18250,
    "volume": 9400,
    "data_source": "market_data_vendor_primary",
    "data_timestamp": "2026-05-07T14:30:00Z"
  },
  "signal_price": {
    "bid": 1.20,
    "ask": 1.30,
    "mid": 1.25,
    "spread_pct": 8.0,
    "quote_source": "market_data_vendor_primary",
    "quote_timestamp": "2026-05-07T14:30:00Z",
    "quote_age_ms": 500
  },
  "confidence": 0.72,
  "confidence_usage": "DISPLAY_ONLY",
  "metadata": {
    "reason_code": "FLOW_ALIGNMENT",
    "evaluation_window": "10:30"
  },
  "created_at": "2026-05-07T14:30:01Z"
}
```

`confidence` is display-only in MVP and must not gate policy matching unless a future policy field explicitly allows the user to configure a confidence threshold. If confidence-based matching is added later, it must be user-configured and auditable.

### 7.4 Strategy blocked event

A `STRATEGY_BLOCKED` event indicates that a strategy did not emit actionable entry/exit events because a predefined strategy-level or platform-level condition prevented it.

Examples:

```text
MARKET_CLOSED
STRATEGY_PAUSED
SYMBOL_PAUSED
QUOTE_SOURCE_UNAVAILABLE
VOLATILITY_FILTER_FAILED
SPREAD_FILTER_FAILED
CONTRACT_UNAVAILABLE
CONTRACT_RISK_DATA_MISSING
CORPORATE_ACTION_FILTER
STRATEGY_VERSION_DISABLED
```

Consumer behavior:

```text
Store and display the event in the strategy feed.
Do not evaluate the event as an entry or exit signal.
Do not create paper orders, live order drafts, or live orders.
Include blocked-event counts in strategy/session reporting.
```

### 7.5 User automation policy

A user automation policy is the source of truth for whether a strategy event can become a paper trade, live order draft, or future live order.

All loss, stop, guard, spread, slippage, and threshold fields use positive values. The rule semantics determine whether the value represents downside, upside, cost, or range.

```json
{
  "policy_id": "policy_123",
  "user_id": "user_456",
  "mode": "PAPER",
  "enabled": true,
  "paused": false,
  "policy_group_id": "spy_0dte_experiment_group",
  "strategy_id": "strategy_001",
  "strategy_version": "1.2.0",
  "allowed_symbols": ["SPY", "QQQ"],
  "allowed_directions": ["BULLISH"],
  "allowed_instrument_types": ["OPTION"],
  "max_notional_per_trade": 500,
  "max_contracts_per_trade": 1,
  "max_trades_per_day": 3,
  "max_daily_loss": 300,
  "daily_loss_basis": "REALIZED_PLUS_UNREALIZED",
  "trading_day_basis": "PRIMARY_EXCHANGE_SESSION_DATE",
  "entry_order_type": "LIMIT",
  "entry_price_rule": "MID_WITH_SLIPPAGE_CAP",
  "paper_fill_realism": "REALISTIC",
  "fill_probability_model": "DETERMINISTIC_SPREAD_POSITION",
  "max_slippage_pct": 5,
  "time_in_force": "DAY",
  "entry_window_start": "09:45:00",
  "entry_window_end": "15:30:00",
  "entry_window_timezone": "EXCHANGE_LOCAL",
  "no_entry_within_minutes_of_close": 30,
  "forced_flatten_time": "15:45:00",
  "exit_price_rule": "BID_FOR_LONG_OPTION",
  "stop_loss_type": "OPTION_PREMIUM_PCT",
  "stop_loss_pct": 50,
  "underlying_stop_pct": 0.5,
  "underlying_stop_level": null,
  "stop_arm_delay_seconds": 300,
  "iv_theta_adjusted_stop_enabled": false,
  "profit_guard_type": "TRAILING_FROM_HIGH_WATER",
  "profit_guard_activate_pct": 15,
  "profit_guard_floor_pct": 5,
  "trailing_drawdown_pct": 20,
  "giveback_pct": 50,
  "min_days_to_expiry": 0,
  "max_days_to_expiry": 7,
  "min_delta": 0.25,
  "max_delta": 0.65,
  "min_extrinsic_value_pct": 5,
  "min_open_interest": 100,
  "min_volume": 10,
  "reject_stale_quotes": true,
  "max_quote_age_ms": 5000,
  "reject_wide_spreads": true,
  "max_spread_pct": 20,
  "allow_duplicate_symbol_positions": false,
  "duplicate_position_scope": "CONTRACT",
  "max_concurrent_positions_per_underlying": 2,
  "max_total_notional_per_underlying": 1000,
  "max_policies_firing_per_event_per_underlying": 2,
  "session_close_exit": true,
  "created_at": "2026-05-07T14:00:00Z",
  "updated_at": "2026-05-07T14:00:00Z"
}
```

### 7.6 Policy match result

Every enabled policy is evaluated independently. Multiple enabled policies for the same `(user_id, strategy_id, strategy_version)` are supported and must produce separate match/rejection records, separate order lifecycles, and separate P&L attribution.

```json
{
  "policy_match_id": "match_789",
  "strategy_event_id": "evt_123",
  "policy_id": "policy_123",
  "user_id": "user_456",
  "result": "MATCHED",
  "rejection_reason": null,
  "risk_check_results": {
    "quote_freshness": "PASS",
    "spread_check": "PASS",
    "dte_check": "PASS",
    "delta_check": "PASS",
    "liquidity_check": "PASS",
    "time_window_check": "PASS",
    "daily_trade_limit": "PASS",
    "daily_loss_limit": "PASS",
    "portfolio_concentration_check": "PASS",
    "duplicate_position_check": "PASS"
  },
  "policy_snapshot_json": {
    "policy_id": "policy_123",
    "strategy_version": "1.2.0",
    "max_daily_loss": 300,
    "paper_fill_realism": "REALISTIC",
    "stop_loss_type": "OPTION_PREMIUM_PCT",
    "profit_guard_type": "TRAILING_FROM_HIGH_WATER",
    "time_in_force": "DAY"
  },
  "created_at": "2026-05-07T14:30:02Z"
}
```

### 7.7 Paper order

```json
{
  "paper_order_id": "paper_order_001",
  "strategy_event_id": "evt_123",
  "policy_id": "policy_123",
  "user_id": "user_456",
  "position_id": null,
  "side": "BUY_TO_OPEN",
  "quantity": 1,
  "filled_quantity": 0,
  "remaining_quantity": 1,
  "order_type": "LIMIT",
  "time_in_force": "DAY",
  "requested_price": 1.25,
  "paper_fill_realism": "REALISTIC",
  "fill_probability_model": "DETERMINISTIC_SPREAD_POSITION",
  "fill_probability_pct": 52.0,
  "fill_decision_seed": "sha256_order_event_policy_quote",
  "fill_decision": "FILLED",
  "status": "ACCEPTED",
  "rejection_reason": null,
  "cancel_reason": null,
  "created_at": "2026-05-07T14:30:02Z",
  "accepted_at": "2026-05-07T14:30:02Z",
  "expires_at": "2026-05-07T20:00:00Z",
  "cancelled_at": null,
  "expired_at": null
}
```

### 7.8 Paper fill

```json
{
  "paper_fill_id": "paper_fill_001",
  "paper_order_id": "paper_order_001",
  "position_id": "paper_pos_001",
  "side": "BUY_TO_OPEN",
  "quantity": 1,
  "fill_price": 1.27,
  "fill_model": "REALISTIC_DETERMINISTIC_SPREAD_POSITION",
  "fill_model_version": "1.0.0",
  "paper_fill_realism": "REALISTIC",
  "fill_probability_pct": 52.0,
  "fill_decision_seed": "sha256_order_event_policy_quote",
  "slippage_applied_pct": 1.6,
  "slippage_vs_mid": 0.02,
  "spread_cost_estimate": 2.00,
  "bid": 1.20,
  "ask": 1.30,
  "mid": 1.25,
  "quote_source": "market_data_vendor_primary",
  "quote_timestamp": "2026-05-07T14:30:00Z",
  "quote_age_ms": 500,
  "created_at": "2026-05-07T14:30:02Z"
}
```

### 7.9 Paper position

```json
{
  "position_id": "paper_pos_001",
  "user_id": "user_456",
  "policy_id": "policy_123",
  "strategy_event_id": "evt_123",
  "strategy_id": "strategy_001",
  "strategy_version": "1.2.0",
  "symbol": "SPY",
  "instrument_type": "OPTION",
  "contract": {
    "raw_symbol": "SPY   260507C00560000",
    "expiry": "2026-05-07",
    "strike": 560,
    "option_type": "CALL",
    "days_to_expiry": 0
  },
  "direction": "BULLISH",
  "quantity": 1,
  "entry_price": 1.27,
  "current_price": 1.48,
  "underlying_price": 559.10,
  "current_price_source": "market_data_vendor_primary",
  "current_quote_timestamp": "2026-05-07T14:52:00Z",
  "current_quote_age_ms": 750,
  "current_spread_pct": 8.1,
  "quote_status": "FRESH",
  "market_state": "OPEN",
  "exit_rules_armed": true,
  "exit_rules_suspended_reason": null,
  "exit_price": null,
  "status": "GUARDED",
  "unrealized_pnl": 21.00,
  "realized_pnl": null,
  "unrealized_return_pct": 16.54,
  "realized_return_pct": null,
  "gross_unrealized_pnl": 23.00,
  "modeled_transaction_cost_drag": 2.00,
  "high_water_mark": 1.55,
  "drawdown_from_high_water_mark_pct": 4.5,
  "is_guarded": true,
  "guard_activated_at": "2026-05-07T14:52:00Z",
  "exit_reason": null,
  "quote_unavailable_at": null,
  "opened_at": "2026-05-07T14:30:02Z",
  "closed_at": null
}
```

### 7.10 Shadow paper outcome

A shadow paper outcome is an optional, clearly labeled learning artifact for rejected policy matches. It must never create an actual user position and must never be displayed as a trade the user took.

```json
{
  "shadow_outcome_id": "shadow_001",
  "policy_match_id": "match_rejected_001",
  "strategy_event_id": "evt_123",
  "policy_id": "policy_123",
  "user_id": "user_456",
  "rejection_reason": "SPREAD_TOO_WIDE",
  "shadow_fill_model": "REALISTIC_DETERMINISTIC_SPREAD_POSITION",
  "hypothetical_entry_price": 1.31,
  "hypothetical_exit_price": 1.44,
  "hypothetical_net_pnl": 13.00,
  "hypothetical_cost_drag": 4.00,
  "label": "Shadow result — not an actual paper trade",
  "created_at": "2026-05-07T21:00:00Z"
}
```

### 7.11 Portfolio exposure snapshot

Portfolio exposure snapshots support cross-policy and cross-strategy controls.

```json
{
  "snapshot_id": "exposure_001",
  "user_id": "user_456",
  "trading_day": "2026-05-07",
  "underlying_symbol": "SPY",
  "open_policy_count": 2,
  "open_position_count": 2,
  "directional_exposure": "BULLISH",
  "total_notional": 760,
  "total_contracts": 2,
  "created_at": "2026-05-07T14:30:02Z"
}
```

---

## 8. High-Level Architecture

```text
Strategy Engine
  Emits generic strategy events

Event Bus
  Transports strategy, policy, execution, position, quote, exposure, and audit events

Strategy Catalog Service
  Stores strategy metadata, versions, performance context, and version comparisons

User Automation Policy Service
  Stores user-selected automation rules and policy snapshots

Policy Matching Engine
  Matches strategy events against enabled user policy snapshots

Contract Risk and Market Data Service
  Provides quote, spread, DTE, Greeks, intrinsic/extrinsic value, liquidity, halt, and session-state data

Risk Guardrail Engine
  Applies user limits, contract filters, time windows, daily-loss circuit breakers, and portfolio limits

Paper Execution Engine
  Simulates orders, deterministic/probabilistic fills, cancellations, expirations, and cost attribution

Position Lifecycle Engine
  Updates P&L, quote state, guard state, stops, trailing exits, forced flatten, and daily-loss exits

Shadow Outcome Engine
  Optionally simulates clearly labeled hypothetical outcomes for rejected matches

Live Order Draft Service, future
  Creates order drafts requiring user confirmation

Broker Adapter, future
  Sends and reconciles live orders after approval

Audit Ledger
  Records all user and system actions

User Interface
  Displays strategy catalog, events, policies, positions, performance, trade reconstruction, and audit trail

Admin Console
  Provides operational controls, kill switches, and monitoring
```

---

## 9. Functional Requirements

## FR-01 — Strategy Catalog

The platform must provide a strategy catalog with objective metadata and performance context.

Required fields:

```text
Strategy name
Plain-English description
Asset classes
Supported symbols
Supported instruments
Supported directions
Time horizon
Trading frequency
Strategy version
Status
Risk notes
Backtest performance, clearly labeled
Paper performance, clearly labeled
Live performance, clearly labeled if available
Performance measurement period
Fill model and fill-realism mode used for displayed results
Slippage and spread assumptions
Policy parameters used for displayed results
Trade frequency
Equity curve
Drawdown profile
Market-regime breakdown, if available
Known limitations
```

The catalog must not display:

```text
Recommended for you
Best strategy for your profile
Suitable for your account
Guaranteed edge
Low risk
Risk free
Expected monthly income
Beginner-friendly profits
```

Acceptance criteria:

```gherkin
Given a user opens the strategy catalog
Then the user can see objective strategy metadata and performance context
And every performance figure identifies the measurement period, fill model, and assumptions
And no strategy is labeled as recommended, suitable, or best for the user.
```

---

## FR-02 — Strategy Event Feed

The platform must show strategy events independently of user execution.

Required event types:

```text
STRATEGY_STATUS
MARKET_OBSERVATION
ENTRY_CANDIDATE
ENTRY_SIGNAL
NO_SIGNAL
EXIT_SIGNAL
STRATEGY_BLOCKED
```

Users must be able to filter by:

```text
Strategy
Strategy version
Symbol
Direction
Instrument type
Event type
Session date
```

Display-label rules:

```text
Internal event code ENTRY_SIGNAL may be displayed as "Strategy entry condition met".
Internal event code EXIT_SIGNAL may be displayed as "Strategy exit condition met".
The UI must not label events as buy signals, sell signals, recommendations, or instructions.
```

`STRATEGY_BLOCKED` events must be stored and displayed but must not trigger policy matching as actionable entry/exit events.

Acceptance criteria:

```gherkin
Given a strategy emits an ENTRY_SIGNAL
When the event feed is viewed
Then the event appears even if no user policy matches it
And the UI label does not say "buy signal" or "recommended trade".
```

---

## FR-03 — Automation Policy Builder

The policy builder must allow users to define technical automation rules.

Required setup steps:

```text
1. Select strategy
2. Select strategy version
3. Select mode: PAPER, MANUAL_LIVE_DRAFT, or LIVE_AUTO
4. Select allowed symbols
5. Select allowed direction
6. Select allowed instrument types
7. Set trade size limits
8. Set daily limits and circuit breaker behavior
9. Set entry order type, price rule, fill realism, and time-in-force
10. Set time-of-day entry window and forced flatten time
11. Set DTE, delta, extrinsic value, spread, volume, and open-interest filters
12. Set stop-loss type, threshold, and arming delay
13. Set profit-guard type and trailing/high-water behavior
14. Set quote and spread rules
15. Set duplicate-position behavior
16. Set portfolio concentration controls
17. Review paper/live simulation disclosure
18. Review summary
19. Enable policy
```

Default values:

```text
mode = PAPER
enabled = false
paused = false
allow_duplicate_symbol_positions = false
duplicate_position_scope = CONTRACT
reject_stale_quotes = true
reject_wide_spreads = true
time_in_force = DAY
daily_loss_basis = REALIZED_PLUS_UNREALIZED
trading_day_basis = PRIMARY_EXCHANGE_SESSION_DATE
paper_fill_realism = REALISTIC
profit_guard_type = TRAILING_FROM_HIGH_WATER
stop_loss_type = OPTION_PREMIUM_PCT
stop_arm_delay_seconds = 0 unless the user configures a delay
```

Required review copy:

```text
You are enabling a self-directed automation rule.
The system will only act when a strategy event matches the conditions you selected.
You can disable this rule at any time.
Paper order fills, cancellations, expirations, and exits are simulated.
Paper fills do not include all real-world factors, including order queue position, partial fills, fast-market slippage, market-maker behavior, halts, broker routing differences, or execution venue differences. Live results may differ materially.
Option-price stops may trigger because of time decay, implied-volatility changes, spread movement, or quote quality, even when the underlying price has not moved against the strategy condition.
```

Acceptance criteria:

```gherkin
Given a user creates a policy
When the user reaches the review step
Then the system shows a full summary of strategy, version, symbols, size, risk, quote, spread, time-in-force, fill realism, time filters, contract filters, stop-loss, profit-guard, and portfolio controls
And the policy remains disabled until the user explicitly enables it.
```

---

## FR-04 — Policy Matching Engine

The policy matching engine must evaluate every actionable strategy event against all enabled user policy snapshots that reference the same strategy version.

Snapshot rule:

```text
Policy matching evaluates against a policy snapshot captured when the strategy event is accepted for processing.
In-flight event processing is not affected by concurrent policy edits.
Policy edits apply only to future event-processing attempts that capture a later policy snapshot.
The policy snapshot used for any match or rejection must be persisted in policy_match.policy_snapshot_json.
```

Multiple-policy rule:

```text
Multiple enabled policies per (user_id, strategy_id, strategy_version) are supported.
Each policy is evaluated independently.
Each matching policy may create a separate paper order, subject to portfolio and duplicate-position limits.
P&L, cost, rejections, and performance must be attributed by policy_id and policy_group_id.
```

Required checks:

```text
policy.enabled == true
policy.paused == false
event.event_type is actionable for the policy mode
event.strategy_id == policy.strategy_id
event.strategy_version == policy.strategy_version
event.symbol in policy.allowed_symbols
event.direction in policy.allowed_directions
event.instrument_type in policy.allowed_instrument_types
quote_age_ms <= policy.max_quote_age_ms
spread_pct <= policy.max_spread_pct
current time is inside policy.entry_window_start and policy.entry_window_end
current time is not within policy.no_entry_within_minutes_of_close
contract.days_to_expiry between policy.min_days_to_expiry and policy.max_days_to_expiry
contract_risk.delta between policy.min_delta and policy.max_delta, when delta filter is configured
contract_risk.extrinsic_value_pct >= policy.min_extrinsic_value_pct, when configured
contract_risk.open_interest >= policy.min_open_interest, when configured
contract_risk.volume >= policy.min_volume, when configured
daily_trade_count < policy.max_trades_per_day
daily_loss_amount < policy.max_daily_loss
not duplicate position unless policy allows duplicates
portfolio concentration limits pass
market is open for the instrument unless policy explicitly supports otherwise
contract is not expired
contract is not blocked by corporate-action filter if such data is available
platform kill switch inactive
user kill switch inactive
```

Daily loss definition for MVP:

```text
daily_loss_amount = max(0, -(realized_pnl_for_trading_day + unrealized_pnl_for_open_positions_for_trading_day))
```

Trading day definition for MVP:

```text
Trading day = session date of the instrument's primary exchange.
```

The engine must emit exactly one result per event-policy pair:

```text
POLICY_MATCHED
POLICY_REJECTED
```

The system must be idempotent. Duplicate strategy events must not create duplicate paper orders or live order drafts for the same policy.

Idempotency key:

```text
user_id + policy_id + strategy_event_id
```

Acceptance criteria:

```gherkin
Given the same strategy_event_id is processed twice
And the same enabled policy matches it
Then only one policy_match record is created for that policy
And only one paper order is created for that policy.
```

---

## FR-05 — Policy Rejection Reasons

Every rejected match must include a structured reason code.

Required reason codes:

```text
POLICY_DISABLED
POLICY_PAUSED
STRATEGY_MISMATCH
VERSION_MISMATCH
SYMBOL_NOT_ALLOWED
DIRECTION_NOT_ALLOWED
INSTRUMENT_NOT_ALLOWED
EVENT_TYPE_NOT_ACTIONABLE
ENTRY_WINDOW_CLOSED
NO_ENTRY_CLOSE_TO_SESSION_CLOSE
FORCED_FLATTEN_WINDOW_ACTIVE
QUOTE_STALE
QUOTE_SOURCE_UNAVAILABLE
QUOTE_HALTED_OR_NO_QUOTE
SPREAD_TOO_WIDE
CONTRACT_RISK_DATA_MISSING
DTE_OUT_OF_RANGE
DELTA_OUT_OF_RANGE
EXTRINSIC_VALUE_TOO_LOW
OPEN_INTEREST_TOO_LOW
VOLUME_TOO_LOW
DAILY_TRADE_LIMIT_REACHED
DAILY_LOSS_LIMIT_REACHED
DUPLICATE_POSITION
PORTFOLIO_UNDERLYING_LIMIT_REACHED
PORTFOLIO_EXPOSURE_LIMIT_REACHED
MARKET_CLOSED
CONTRACT_EXPIRED
CONTRACT_TOO_CLOSE_TO_EXPIRY
CORPORATE_ACTION_FILTER
PLATFORM_KILL_SWITCH_ACTIVE
USER_KILL_SWITCH_ACTIVE
BROKER_UNAVAILABLE
BROKER_PERMISSION_MISSING
INSUFFICIENT_BUYING_POWER
```

Example rejection event:

```json
{
  "event_type": "POLICY_REJECTED",
  "policy_match_id": "match_001",
  "strategy_event_id": "evt_123",
  "policy_id": "policy_123",
  "user_id": "user_456",
  "reason": "SPREAD_TOO_WIDE",
  "detail": {
    "spread_pct": 28.0,
    "max_spread_pct": 20.0,
    "shadow_outcome_enabled": true
  },
  "created_at": "2026-05-07T14:30:02Z"
}
```

---

## FR-06 — Paper Execution Engine

The paper execution engine must simulate order handling and fills. It must not simply treat a strategy event as a filled trade.

Lifecycle:

```text
POLICY_MATCHED
  ↓
PAPER_ORDER_CREATED
  ↓
PAPER_ORDER_ACCEPTED or PAPER_ORDER_REJECTED
  ↓
PAPER_ORDER_PARTIALLY_FILLED, PAPER_ORDER_FILLED, PAPER_ORDER_CANCELLED, or PAPER_ORDER_EXPIRED
  ↓
PAPER_FILL, if any fill occurs
  ↓
PAPER_POSITION_OPENED, if an opening fill occurs
```

Supported paper order statuses:

```text
CREATED
ACCEPTED
PARTIALLY_FILLED
FILLED
CANCELLED
EXPIRED
REJECTED
```

Supported time-in-force values for MVP:

```text
DAY
IOC
```

Future time-in-force values, if broker-supported and compliance-approved:

```text
GTC
GTD
FOK
```

MVP expiry behavior:

```text
DAY orders expire at the end of the primary exchange session for the instrument.
IOC orders fill immediately if fill conditions are met; any unfilled quantity is cancelled.
Unfilled DAY orders must transition to EXPIRED at session close.
User-cancelled orders must transition to CANCELLED.
Rejected orders must include a rejection reason.
No order may transition from EXPIRED, CANCELLED, REJECTED, or FILLED back to an active state.
```

Supported paper-fill realism settings:

```text
OPTIMISTIC     Simulates more favorable fills, such as mid-or-better fills in liquid markets.
REALISTIC      Default. Simulates fill probability based on limit price position inside the spread, quote age, spread width, liquidity tier, and contract data.
CONSERVATIVE   Simulates less favorable fills, such as entry near ask and exit near bid for long options.
```

Supported fill models:

```text
MID
MID_WITH_SLIPPAGE_CAP
ASK_FOR_LONG_ENTRY_BID_FOR_LONG_EXIT
CONSERVATIVE_BID_ASK
REALISTIC_DETERMINISTIC_SPREAD_POSITION
```

Realistic fill model requirements:

```text
The model must compute the limit price's position inside the bid/ask spread.
The model must compute and store fill_probability_pct.
The model may use deterministic pseudo-randomness, but must store the seed and realized decision.
The model must account for quote age, spread width, liquidity tier, order side, and time of day.
The model must store fill_model_version.
The model must be replayable from stored inputs.
```

Fill calibration requirements:

```text
REALISTIC fill probability curves must be defined in a separate Fill Realism Calibration document.
Liquidity tier classification must be version-controlled and must define inputs such as spread width, quote age, volume, open interest, and time of day.
Changing fill probability curves, liquidity tiers, or time-of-day adjustments must increment fill_model_version.
fill_decision_seed must be deterministically derived from stored identifiers, such as SHA256(paper_order_id, strategy_event_id, policy_id, quote_snapshot_id, fill_model_version).
Acceptance tests must validate replay determinism, not just field presence.
```

Cost attribution requirements:

```text
Every fill must store fill_model and paper_fill_realism.
Every fill must store bid, ask, mid, quote source, quote timestamp, and quote age.
Every fill must store slippage_vs_mid.
Every fill must estimate spread_cost and modeled transaction-cost drag.
Paper summaries must show gross strategy P&L, spread cost, slippage cost, and net paper P&L separately.
```

Acceptance criteria:

```gherkin
Given a matching paper policy
And paper_fill_realism is REALISTIC
When a paper fill decision is created
Then the order stores fill probability, fill model version, seed, decision, bid, ask, mid, quote source, quote timestamp, quote age, slippage versus mid, and modeled cost attribution.
```

---

## FR-07 — Position Lifecycle Engine

The position lifecycle engine must manage paper positions from open to close.

Position states:

```text
CREATED
OPEN
GUARDED
EXIT_PENDING
EXIT_PENDING_QUOTE
CLOSED
REJECTED
CANCELLED
```

Quote status values:

```text
FRESH
STALE
UNAVAILABLE
HALTED
WIDE_MARKET
UNKNOWN
```

Exit reasons:

```text
STOP_LOSS
PROFIT_GUARD
TRAILING_STOP
GIVEBACK_FROM_MAX_GAIN
UNDERLYING_STOP
STRATEGY_EXIT
USER_MANUAL_CLOSE
SESSION_CLOSE
FORCED_FLATTEN_TIME
DAILY_LOSS_CIRCUIT_BREAKER
KILL_SWITCH
QUOTE_UNAVAILABLE
HALT_OR_NO_QUOTE
CONTRACT_EXPIRATION
ORDER_CANCELLED
ORDER_EXPIRED
```

Required position update fields:

```text
position_id
user_id
policy_id
strategy_event_id
strategy_id
strategy_version
symbol
instrument_type
contract
entry_price
current_price
underlying_price
current_price_source
current_quote_timestamp
current_quote_age_ms
current_spread_pct
quote_status
market_state
exit_rules_armed
exit_rules_suspended_reason
quantity
unrealized_pnl
realized_pnl
gross_unrealized_pnl
modeled_transaction_cost_drag
unrealized_return_pct
realized_return_pct
high_water_mark
drawdown_from_high_water_mark_pct
stop_loss_type
stop_loss_threshold
stop_arm_delay_seconds
profit_guard_type
profit_guard_activation_threshold
profit_guard_floor
trailing_drawdown_pct
giveback_pct
is_guarded
guard_activated_at
position_status
exit_reason
timestamp
```

Stop-loss semantics:

```text
OPTION_PREMIUM_PCT: Trigger based on option premium decline from entry price.
UNDERLYING_PRICE_PCT: Trigger when the underlying moves against the position by the configured percent.
UNDERLYING_PRICE_LEVEL: Trigger when the underlying reaches the configured price level.
TIME_DELAYED_OPTION_STOP: Do not arm option-premium stop until stop_arm_delay_seconds has elapsed.
IV_THETA_ADJUSTED_OPTION_STOP: Future only unless separately approved and validated.
```

Stop arming requirements:

```text
stop_arm_delay_seconds applies only to OPTION_PREMIUM_PCT stops unless a future approved stop type explicitly states otherwise.
UNDERLYING_PRICE_PCT and UNDERLYING_PRICE_LEVEL stops must arm immediately at fill.
Daily-loss circuit breaker checks must always be armed while the position is open.
The position detail must show whether each stop type is armed, suspended, or waiting for its arm delay.
If any stop is waiting for an arm delay, show stops_not_yet_armed_seconds_remaining.
```

For `OPTION_PREMIUM_PCT`, `stop_loss_pct` is a positive number. For a long paper position, `stop_loss_pct = 50` means trigger an exit when:

```text
current_option_price <= entry_option_price * (1 - 50%)
```

The policy builder must disclose that option-premium stops can trigger because of theta decay, implied-volatility changes, and spread movement.

Profit-guard semantics:

```text
ENTRY_FLOOR: After activation, exit if return falls below a fixed floor from entry.
TRAILING_FROM_HIGH_WATER: After activation, exit if current price falls trailing_drawdown_pct from high_water_mark.
GIVEBACK_FROM_MAX_GAIN: After activation, exit if the position gives back giveback_pct of maximum unrealized gain.
```

Default MVP profit guard:

```text
profit_guard_type = TRAILING_FROM_HIGH_WATER
```

Forced flatten semantics:

```text
If forced_flatten_time is configured, open paper positions governed by the policy must create exit orders at or after that exchange-local time.
Forced flatten is independent from session_close_exit.
For 0DTE option policies, forced_flatten_time should be shown prominently in the policy summary.
If quotes are unavailable at forced_flatten_time, mark the position EXIT_PENDING_QUOTE and retry when quotes resume.
If a paper forced-flatten exit remains unfilled, escalate through documented paper-only liquidation tiers.
Escalation tiers must be auditable and must not imply that live marketable or worst-side orders will be submitted automatically in future live phases.
```

Paper forced-flatten escalation model:

```text
Tier 1: create a marketable-limit paper exit using the configured fill realism model.
Tier 2: if unfilled after N seconds, reprice using a more conservative closeout assumption.
Tier 3: if still open by session_close - K seconds, use a documented worst-side paper closeout mark.
All tier transitions must be stored in the audit log.
```

Stop precedence:

```text
If multiple exit rules trigger on the same evaluation tick, record the highest-precedence exit_reason.
Recommended precedence: DAILY_LOSS_CIRCUIT_BREAKER > KILL_SWITCH > UNDERLYING_PRICE_LEVEL > UNDERLYING_PRICE_PCT > OPTION_PREMIUM_PCT > TRAILING_STOP > GIVEBACK_FROM_MAX_GAIN > FORCED_FLATTEN_TIME > SESSION_CLOSE.
Store all other simultaneous triggers in secondary_exit_reasons for audit and reconstruction.
```

Acceptance criteria:

```gherkin
Given an open paper position reaches the profit guard activation threshold
And profit_guard_type is TRAILING_FROM_HIGH_WATER
When the position later draws down from its high_water_mark by trailing_drawdown_pct
Then an exit is triggered with reason TRAILING_STOP
And the high_water_mark and drawdown fields are visible in the position detail.
```

---

## FR-08 — Market Data, Quote State, Halts, and No-Quote Handling

Position monitoring must not rely only on strategy events. Open paper positions must be updated from a market data source independent of the strategy event feed.

Required quote fields:

```text
quote_source
symbol
instrument_type
contract
underlying_price
bid
ask
mid
spread_pct
quote_timestamp
quote_age_ms
market_session_state
halt_status
luld_status
```

MVP quote behavior:

```text
Use a primary market data source for position monitoring.
Store quote source and timestamp on each position update.
Refresh open paper positions no more than once per second per position.
Do not trigger stop-loss or profit-guard exits from quotes older than the policy's max_quote_age_ms.
If quotes are unavailable, stale, halted, or too wide, mark quote_status accordingly.
If exit rules cannot be evaluated safely, set exit_rules_armed = false and record exit_rules_suspended_reason.
If a daily-loss circuit breaker has already triggered but no valid quote exists, mark the position EXIT_PENDING_QUOTE and re-evaluate on the first fresh quote.
Session-close and forced-flatten exits may use the latest valid quote or a documented fallback model, but the fallback must be disclosed and auditable.
```

Halt/no-quote user experience:

```text
Emit POSITION_QUOTE_UNAVAILABLE when a position cannot be priced from a valid quote.
Show that stop-loss, profit-guard, and trailing exits are armed or suspended.
Show quote_unavailable_since.
Notify the user that automated exit rules may be inactive while no valid quote exists.
When quotes resume, re-evaluate exit rules before permitting new entries for the same policy.
```

Fallback behavior:

```text
If quote source is unavailable, emit QUOTE_SOURCE_UNAVAILABLE.
If quote is stale, emit QUOTE_STALE.
If the market is halted or no quote exists, emit POSITION_QUOTE_UNAVAILABLE.
If spread is too wide, emit QUOTE_REJECTED_FOR_SPREAD.
If position cannot be updated because no valid quote exists, preserve the prior current_price and record quote_unavailable_at.
```

Acceptance criteria:

```gherkin
Given an open paper position
When the option market has no valid quote
Then the position quote_status becomes UNAVAILABLE or HALTED
And exit_rules_armed is false unless a policy explicitly allows fallback exits
And the user sees a POSITION_QUOTE_UNAVAILABLE notification.
```

---

## FR-09 — Daily Loss Circuit Breaker and Portfolio Controls

Daily loss must be enforced continuously during the trading day, not only at entry.

Circuit breaker trigger:

```text
When realized_pnl_for_trading_day + unrealized_pnl_for_open_positions_for_trading_day <= -policy.max_daily_loss
```

Required paper-MVP behavior:

```text
Block new entries for the policy.
Cancel open entry orders for the policy.
Create exit orders for open positions governed by the policy when valid quotes are available.
Daily-loss-triggered exits must use CONSERVATIVE paper liquidation modeling unless a stricter approved model is configured.
Mark positions EXIT_PENDING_QUOTE if exits cannot be evaluated because quotes are unavailable.
When quotes resume, validate quote quality before exit modeling and record whether the resumed quote was stale, wide, or fresh.
Pause or disable the policy for the remainder of the trading day, according to configured behavior.
Emit DAILY_LOSS_CIRCUIT_BREAKER_TRIGGERED.
Notify the user.
Record an audit event with the P&L snapshot that triggered the circuit breaker.
```

Portfolio-level controls:

```text
max_concurrent_positions_per_underlying
max_total_notional_per_underlying
max_policies_firing_per_event_per_underlying
duplicate_position_scope = SYMBOL | CONTRACT | STRATEGY | POLICY | UNDERLYING
policy_group_id for experiments and comparisons
```

Portfolio controls must be evaluated after individual policy checks and before order creation. If a portfolio-level limit blocks a trade, the rejection reason must be portfolio-specific.

Portfolio limits are evaluated against aggregate user exposure across enabled policies unless explicitly scoped to a narrower policy group. Policy-level limits must not be interpreted as isolated per-policy exposure limits when the user has multiple enabled policies.

Policy groups may define aggregate ceilings such as policy_group_max_daily_loss, policy_group_max_concurrent_positions_per_underlying, and policy_group_max_directional_exposure_per_underlying. The policy review screen must show combined daily-loss and exposure ceilings across all enabled policies in the group.

Acceptance criteria:

```gherkin
Given a policy has max_daily_loss = 300
And the policy's realized plus unrealized P&L for the trading day reaches -300
When the next position update is processed
Then new entries are blocked
And open entry orders are cancelled
And open positions receive exit orders or EXIT_PENDING_QUOTE state
And an audit event and user notification are created.
```

---

## FR-10 — Session Summary and Expectancy Metrics

The platform must generate session-level paper trading summaries.

Required fields:

```text
Session date
Trading day basis
Total strategy events
Total blocked strategy events
Total policy matches
Total policy rejections
Total paper orders
Total paper orders accepted
Total paper orders rejected
Total paper orders cancelled
Total paper orders expired
Total paper fills
Total open positions
Total closed positions
Wins
Losses
Win rate
Average win
Average loss
Expectancy per trade
Expectancy after modeled costs
Profit factor
Total realized P&L
Total unrealized P&L
Gross paper P&L
Modeled spread cost
Modeled slippage cost
Net paper P&L
Slippage versus mid average
Daily loss amount
Best paper trade
Worst paper trade
Maximum drawdown
Maximum consecutive losses
Average trade duration
P&L per trade
Most common rejection reasons
Quote-quality rejection count
Spread rejection count
Shadow outcome summary, if enabled
```

Acceptance criteria:

```gherkin
Given a trading session ends
When the session summary job runs
Then a user can view operational counts, P&L, expectancy, cost drag, slippage versus mid, drawdown, and rejection reasons for that session.
```

---

## FR-11 — User Notifications

The platform should notify users of meaningful events.

Notification types:

```text
Policy matched
Policy rejected
Paper order created
Paper order accepted
Paper order rejected
Paper order partially filled
Paper order filled
Paper order cancelled
Paper order expired
Paper position opened
Paper position guarded
Paper position exited
Position quote unavailable
Position exit rules suspended
Position quote resumed
Daily loss circuit breaker triggered
Portfolio limit reached
Session summary ready
Policy disabled by kill switch
Strategy version upgrade available
Shadow outcome ready, if enabled
```

Notification channels for MVP:

```text
In-app notification
Real-time UI event
```

Future notification channels:

```text
Email
SMS
Push notification
Webhook
```

---

## FR-12 — User Kill Switch

Every user must have a kill switch.

MVP behavior:

```text
Disable all enabled automation policies for the user.
Prevent new paper orders.
Prevent new live order drafts.
Prevent future live orders if live mode exists.
Leave open paper positions unchanged by default unless the user selects a paper-close option.
Allow the user to manually close paper positions after kill switch activation.
Record audit event.
```

Future live behavior must be separately approved and must explicitly define whether the kill switch:

```text
Cancels open live orders
Creates live closing orders
Blocks only new live orders
Leaves existing live positions untouched
Requires user confirmation for close/cancel actions
```

Acceptance criteria:

```gherkin
Given the user has active automation policies
When the user activates the kill switch
Then all policies are disabled immediately
And new automation actions are blocked
And open paper positions remain visible
And an audit event is recorded.
```

---

## FR-13 — Platform Kill Switch

Admins must be able to pause the platform by:

```text
All strategies
Specific strategy
Specific strategy version
Specific symbol
Specific asset class
Paper execution
Live order drafts
Live auto-execution
Market data source
Shadow outcome simulation
```

MVP behavior:

```text
A platform kill switch blocks new order-creating actions.
Open paper positions remain visible.
Session-close exits and daily-loss exits continue only if the platform kill switch policy explicitly permits them.
All blocked actions must emit PLATFORM_KILL_SWITCH_ACTIVE.
```

Acceptance criteria:

```gherkin
Given an admin activates a platform kill switch for a specific strategy
When that strategy emits an entry signal
Then no policy match may create a paper order or live order draft
And policy rejections must use PLATFORM_KILL_SWITCH_ACTIVE.
```

---

## FR-14 — Audit Trail and Trade Reconstruction

Every meaningful action must be auditable.

User actions to audit:

```text
Policy created
Policy updated
Policy enabled
Policy disabled
Policy paused
Policy resumed
Policy deleted
Disclosure accepted
Strategy version upgrade accepted
Strategy version upgrade rejected
Kill switch triggered
Paper order manually cancelled
Paper position manually closed
Live order draft confirmed, future
```

System actions to audit:

```text
Strategy event received
Strategy blocked event received
Policy snapshot captured
Policy matched
Policy rejected
Paper order created
Paper order accepted
Paper order rejected
Paper order partially filled
Paper order filled
Paper order cancelled
Paper order expired
Paper fill created
Position opened
Position updated
Exit rules armed
Exit rules suspended
Exit triggered
Position quote unavailable
Daily loss circuit breaker triggered
Portfolio limit reached
Position closed
Shadow outcome created
Session summary generated
Live order draft created, future
Broker order submitted, future
Broker order rejected, future
Broker fill received, future
```

Required audit fields:

```text
audit_id
actor_type
actor_id
event_type
entity_type
entity_id
before_json
after_json
ip_address
user_agent
correlation_id
strategy_event_id
policy_id
policy_snapshot_hash
quote_id
paper_order_id
paper_fill_id
position_id
created_at
```

Trade reconstruction view:

```text
Users must be able to open any paper trade and see the full causal chain.
The view must show the strategy event, policy snapshot, match/rejection result, quote data, order lifecycle, fill model, fill realism, cost attribution, position updates, exit trigger, exit fill, and final P&L.
The view must clearly label simulated data and must not imply live execution quality.
The reconstruction must be exportable as CSV and JSON for user review, support, and compliance evidence.
```

Acceptance criteria:

```gherkin
Given a user opens a closed paper trade
Then the user can see the strategy event, policy snapshot, order lifecycle, fills, quote updates, exit reason, cost attribution, and audit timeline that produced the trade.
```

---

## FR-15 — Manual Live Order Drafts, Future

In manual live mode, the system may create an order draft but must not submit an order until the user confirms.

Order draft must show:

```text
Strategy event
User policy that matched
Policy snapshot used
Symbol
Contract
Side
Quantity
Estimated price
Bid/ask/mid
Quote source
Quote age
Spread
Max loss estimate
Expiration
Order type
Time-in-force
User-defined risk limits
Portfolio exposure impact
Warnings
Paper/live difference disclosure
```

Readiness checklist requirement:

```text
Before manual live draft mode is enabled, the product must require either a minimum paper-history window on the exact policy configuration or a deterministic backtest over an approved historical window.
The checklist must be presented as an educational readiness control, not as a certification that the strategy is suitable or likely profitable.
```

Acceptance criteria:

```gherkin
Given a user is in manual live draft mode
And a strategy event matches the user's policy
When risk checks and readiness checks pass
Then a live order draft is created
And no broker order is sent until the user confirms.
```

---

## FR-16 — Live Auto-Execution, Future Gated

Live auto-execution must not be part of MVP.

Before launch, it requires:

```text
Legal review
Compliance approval
Broker integration approval
User authorization flow
Disclosures
Broker permission checks
Buying power checks
Options approval checks, if applicable
Live order risk checks
Live order lifecycle reconciliation
Live portfolio exposure controls
Live kill switch behavior definition
Supervision dashboard
Incident response plan
Data retention review
```

Acceptance criteria:

```gherkin
Given live auto-execution is not approved
When a user attempts to select LIVE_AUTO mode
Then the UI prevents activation
And explains that this mode is not currently available.
```

---

## FR-17 — Strategy Version Upgrade Diff

Users must explicitly accept strategy version upgrades for policies pinned to older versions.

Upgrade view must show:

```text
Current pinned version
New version
Release notes
Changed parameters
Plain-English change summary
Backtest comparison over the same period, if available
User's observed paper performance under current version
Synthetic paper comparison for new version over the user's observed window, if available
History sufficiency status
Known limitations
```

Version comparison requirements:

```text
If the user's observed window is below the configured minimum sample size, show INSUFFICIENT_HISTORY instead of precise performance conclusions.
Synthetic paper comparison requires replayable historical strategy state, quote snapshots, fill model versions, and policy snapshots for the observed window.
If the new strategy version cannot be run against the user's observed historical sessions, label the comparison UNAVAILABLE and explain why.
```

Acceptance criteria:

```gherkin
Given a policy is pinned to strategy version 1.2.0
And version 1.3.0 is available
When the user opens the upgrade view
Then the user sees release notes, changed parameters, and available performance comparisons
And the policy remains pinned until the user explicitly accepts the upgrade.
```

---

## FR-18 — Shadow Outcomes for Rejected Matches

The platform may run a clearly labeled shadow paper simulation for rejected policy matches when data quality is sufficient and the feature is enabled.

Requirements:

```text
Shadow outcomes must be labeled as hypothetical and not actual paper trades.
Shadow outcomes must use deterministic fill and exit model requirements compatible with paper trades.
If the original rejection was caused by spread, stale quote, no quote, halt, or liquidity, the shadow simulation must store the compromised input and use conservative assumptions or mark the shadow as LOW_CONFIDENCE.
Shadow outcomes must store the rejection reason that was bypassed for the simulation.
Shadow outcomes must not affect P&L, win rate, expectancy, daily-loss limits, or portfolio exposure.
Shadow outcomes should be presented primarily in aggregate by rejection reason, not as prominent individual alternate-history wins.
Shadow outcomes must be shown in rejection detail views and policy tuning reports only.
```

Acceptance criteria:

```gherkin
Given a strategy event is rejected because SPREAD_TOO_WIDE
And shadow outcomes are enabled
When the shadow simulation completes
Then the rejection detail view shows a clearly labeled hypothetical result
And the hypothetical result includes the bypassed rejection reason and confidence label
And the user's actual paper P&L is unchanged.
```

---

## FR-19 — Corporate Actions and Adjusted Options

MVP does not model corporate actions, adjusted options, early exercise, or assignment.

MVP behavior:

```text
If corporate-action data is available and indicates upcoming or active contract adjustment risk, the strategy or policy matching layer should block or flag the event.
If corporate-action data is unavailable, the catalog and policy builder must disclose that MVP paper results do not model corporate actions or adjusted option contract behavior.
Future support requires contract adjustment modeling, option deliverable modeling, exercise/assignment handling, and separate review.
```

---

## 10. Event Taxonomy

### 10.1 Strategy events

```text
STRATEGY_STATUS
MARKET_OBSERVATION
ENTRY_CANDIDATE
ENTRY_SIGNAL
NO_SIGNAL
EXIT_SIGNAL
STRATEGY_BLOCKED
```

### 10.2 Policy events

```text
POLICY_CREATED
POLICY_UPDATED
POLICY_ENABLED
POLICY_DISABLED
POLICY_PAUSED
POLICY_RESUMED
POLICY_DELETED
POLICY_VERSION_UPGRADE_REQUESTED
POLICY_VERSION_UPGRADE_ACCEPTED
POLICY_VERSION_UPGRADE_REJECTED
POLICY_READINESS_CHECK_COMPLETED
```

### 10.3 Automation events

```text
POLICY_MATCHED
POLICY_REJECTED
AUTOMATION_PAUSED
AUTOMATION_RESUMED
USER_KILL_SWITCH_TRIGGERED
PLATFORM_KILL_SWITCH_TRIGGERED
DAILY_LOSS_CIRCUIT_BREAKER_TRIGGERED
PORTFOLIO_LIMIT_REACHED
SHADOW_OUTCOME_CREATED
```

### 10.4 Paper execution events

```text
PAPER_ORDER_CREATED
PAPER_ORDER_ACCEPTED
PAPER_ORDER_REJECTED
PAPER_ORDER_PARTIALLY_FILLED
PAPER_ORDER_FILLED
PAPER_ORDER_CANCELLED
PAPER_ORDER_EXPIRED
PAPER_FILL
PAPER_POSITION_OPENED
PAPER_POSITION_UPDATED
PAPER_EXIT_ORDER_CREATED
PAPER_EXIT_FILL
PAPER_POSITION_CLOSED
TRADE_RECONSTRUCTION_READY
```

### 10.5 Quote and market data events

```text
QUOTE_RECEIVED
QUOTE_STALE
QUOTE_SOURCE_UNAVAILABLE
QUOTE_REJECTED_FOR_SPREAD
POSITION_QUOTE_UPDATED
POSITION_QUOTE_UNAVAILABLE
POSITION_QUOTE_RESUMED
POSITION_EXIT_RULES_ARMED
POSITION_EXIT_RULES_SUSPENDED
HALT_DETECTED
LULD_DETECTED
```

### 10.6 Future live execution events

```text
LIVE_ORDER_DRAFT_CREATED
LIVE_ORDER_DRAFT_CONFIRMED
LIVE_ORDER_DRAFT_CANCELLED
LIVE_ORDER_SUBMITTED
LIVE_ORDER_ACKNOWLEDGED
LIVE_ORDER_REJECTED
LIVE_ORDER_PARTIALLY_FILLED
LIVE_ORDER_FILLED
LIVE_ORDER_CANCELLED
LIVE_ORDER_EXPIRED
LIVE_POSITION_OPENED
LIVE_POSITION_UPDATED
LIVE_POSITION_CLOSED
```

---

## 11. Data Model Requirements

### 11.1 `strategy`

```text
strategy_id PK
name
description
asset_classes
supported_instruments
supported_symbols
supported_directions
time_horizon
status
created_at
updated_at
```

### 11.2 `strategy_version`

```text
strategy_version_id PK
strategy_id FK
version
config_hash
model_hash
release_notes
change_summary
changed_parameters_json
backtest_comparison_json
paper_observed_window_comparison_json
known_limitations
status
created_at
```

### 11.3 `strategy_event`

```text
strategy_event_id PK
strategy_id FK
strategy_version
event_type
display_label
symbol
instrument_type
direction
underlying_price
contract_json
contract_risk_json
signal_price_json
confidence
confidence_usage
reason_code
metadata_json
created_at
```

### 11.4 `user_automation_policy`

```text
policy_id PK
user_id
mode
enabled
paused
policy_group_id
strategy_id FK
strategy_version
allowed_symbols
allowed_directions
allowed_instrument_types
max_notional_per_trade
max_contracts_per_trade
max_trades_per_day
max_daily_loss
daily_loss_basis
trading_day_basis
entry_order_type
entry_price_rule
paper_fill_realism
fill_probability_model
max_slippage_pct
time_in_force
entry_window_start
entry_window_end
entry_window_timezone
no_entry_within_minutes_of_close
forced_flatten_time
exit_price_rule
stop_loss_type
stop_loss_pct
underlying_stop_pct
underlying_stop_level
stop_arm_delay_seconds
iv_theta_adjusted_stop_enabled
profit_guard_type
profit_guard_activate_pct
profit_guard_floor_pct
trailing_drawdown_pct
giveback_pct
min_days_to_expiry
max_days_to_expiry
min_delta
max_delta
min_extrinsic_value_pct
min_open_interest
min_volume
reject_stale_quotes
max_quote_age_ms
reject_wide_spreads
max_spread_pct
allow_duplicate_symbol_positions
duplicate_position_scope
max_concurrent_positions_per_underlying
max_total_notional_per_underlying
max_policies_firing_per_event_per_underlying
session_close_exit
created_at
updated_at
```

### 11.5 `policy_match`

```text
policy_match_id PK
strategy_event_id FK
policy_id FK
user_id
result
rejection_reason
rejection_detail_json
risk_check_results_json
quote_check_results_json
contract_risk_check_results_json
portfolio_check_results_json
policy_snapshot_json
policy_snapshot_hash
created_at
```

### 11.6 `paper_order`

```text
paper_order_id PK
strategy_event_id FK
policy_id FK
user_id
position_id
side
quantity
filled_quantity
remaining_quantity
order_type
time_in_force
requested_price
paper_fill_realism
fill_probability_model
fill_probability_pct
fill_decision_seed
fill_decision
status
rejection_reason
cancel_reason
created_at
accepted_at
expires_at
cancelled_at
expired_at
```

### 11.7 `paper_fill`

```text
paper_fill_id PK
paper_order_id FK
position_id FK
side
quantity
fill_price
fill_model
fill_model_version
paper_fill_realism
fill_probability_pct
fill_decision_seed
slippage_applied_pct
slippage_vs_mid
spread_cost_estimate
bid
ask
mid
quote_source
quote_timestamp
quote_age_ms
created_at
```

### 11.8 `paper_position`

```text
position_id PK
user_id
policy_id FK
strategy_event_id FK
strategy_id FK
strategy_version
symbol
instrument_type
contract_json
direction
quantity
entry_price
current_price
underlying_price
current_price_source
current_quote_timestamp
current_quote_age_ms
current_spread_pct
quote_status
market_state
exit_rules_armed
exit_rules_suspended_reason
exit_price
status
unrealized_pnl
realized_pnl
gross_unrealized_pnl
modeled_transaction_cost_drag
unrealized_return_pct
realized_return_pct
high_water_mark
drawdown_from_high_water_mark_pct
is_guarded
guard_activated_at
exit_reason
quote_unavailable_at
opened_at
closed_at
created_at
updated_at
```

### 11.9 `audit_event`

```text
audit_id PK
actor_type
actor_id
event_type
entity_type
entity_id
before_json
after_json
ip_address
user_agent
correlation_id
strategy_event_id
policy_id
policy_snapshot_hash
quote_id
paper_order_id
paper_fill_id
position_id
created_at
```

### 11.10 `market_quote`

```text
quote_id PK
quote_source
symbol
instrument_type
contract_json
underlying_price
bid
ask
mid
spread_pct
quote_timestamp
received_at
market_session_state
halt_status
luld_status
created_at
```

### 11.11 `shadow_paper_outcome`

```text
shadow_outcome_id PK
policy_match_id FK
strategy_event_id FK
policy_id FK
user_id
rejection_reason
shadow_fill_model
shadow_fill_model_version
hypothetical_entry_price
hypothetical_exit_price
hypothetical_gross_pnl
hypothetical_cost_drag
hypothetical_net_pnl
label
created_at
```

### 11.12 `portfolio_exposure_snapshot`

```text
snapshot_id PK
user_id
trading_day
underlying_symbol
open_policy_count
open_position_count
directional_exposure
total_notional
total_contracts
policy_ids_json
position_ids_json
created_at
```

### 11.13 `trade_reconstruction`

```text
trade_reconstruction_id PK
position_id FK
user_id
strategy_event_id
policy_id
policy_snapshot_hash
order_lifecycle_json
fill_lifecycle_json
quote_timeline_json
position_update_timeline_json
exit_decision_json
cost_attribution_json
audit_event_ids_json
created_at
```

---

## 12. API Requirements

### 12.1 Strategy APIs

```http
GET /api/strategies
GET /api/strategies/{strategy_id}
GET /api/strategies/{strategy_id}/versions
GET /api/strategies/{strategy_id}/versions/{version}/diff
GET /api/strategies/{strategy_id}/performance
GET /api/strategies/{strategy_id}/events
```

### 12.2 Automation policy APIs

```http
GET    /api/automation/policies
POST   /api/automation/policies
GET    /api/automation/policies/{policy_id}
PATCH  /api/automation/policies/{policy_id}
POST   /api/automation/policies/{policy_id}/enable
POST   /api/automation/policies/{policy_id}/disable
POST   /api/automation/policies/{policy_id}/pause
POST   /api/automation/policies/{policy_id}/resume
GET    /api/automation/policies/{policy_id}/readiness
GET    /api/automation/policies/{policy_id}/performance
GET    /api/automation/policy-groups/{policy_group_id}/comparison
DELETE /api/automation/policies/{policy_id}
```

API state-change rule:

```text
PATCH /api/automation/policies/{policy_id} must not change enabled or paused state.
Enable, disable, pause, and resume must use their dedicated endpoints.
This avoids multiple audit paths for the same state transition.
```

### 12.3 Paper trading APIs

```http
GET  /api/paper/orders
GET  /api/paper/orders/{paper_order_id}
POST /api/paper/orders/{paper_order_id}/cancel
GET  /api/paper/fills
GET  /api/paper/positions
GET  /api/paper/positions/{position_id}
POST /api/paper/positions/{position_id}/close
GET  /api/paper/positions/{position_id}/reconstruction
GET  /api/paper/session-summaries
GET  /api/paper/session-summaries/{session_date}
GET  /api/paper/performance/expectancy
GET  /api/paper/rejections/{policy_match_id}/shadow-outcome
```

### 12.4 Portfolio APIs

```http
GET /api/portfolio/exposure
GET /api/portfolio/exposure/{underlying_symbol}
```

### 12.5 Event APIs

```http
GET /api/events/strategy
GET /api/events/automation
GET /api/events/paper
GET /api/events/quotes
GET /api/events/live
```

### 12.6 Audit APIs

```http
GET /api/audit/events
GET /api/audit/events/{audit_id}
```

### 12.7 Future live order draft APIs

```http
GET  /api/live/order-drafts
POST /api/live/order-drafts
GET  /api/live/order-drafts/{draft_id}
POST /api/live/order-drafts/{draft_id}/confirm
POST /api/live/order-drafts/{draft_id}/cancel
```

---

## 13. UI Requirements

### 13.1 Strategy catalog page

Must show:

```text
Strategy cards
Objective descriptions
Supported assets
Supported instruments
Supported directions
Time horizon
Version
Status
Risk notes
Backtest results, clearly labeled
Paper results, clearly labeled
Live results, clearly labeled if available
Measurement period
Fill model and assumptions
Equity curve
Drawdown profile
Trade frequency
Market-regime breakdown, if available
Policy parameters used for displayed results
Known limitations
```

Must not show:

```text
Recommended for you
Best match
Suitable for your profile
Guaranteed profit
Risk-free strategy
Projected income
```

### 13.2 Strategy detail page

Required tabs:

```text
Overview
Events
Versions
Version comparison
Risk notes
Paper performance
Automation setup
```

### 13.3 Automation setup page

Required steps:

```text
1. Strategy
2. Version
3. Mode
4. Symbols
5. Direction
6. Instruments
7. Size limits
8. Daily limits and circuit breaker
9. Entry rules and fill realism
10. Time-in-force
11. Time-of-day controls
12. Contract filters
13. Exit rules
14. Stop-loss rules
15. Profit-guard rules
16. Quote and spread rules
17. Portfolio controls
18. Review disclosures
19. Enable
```

### 13.4 Event timeline

The event timeline must show the full causal chain:

```text
Strategy event created
Policy snapshot captured
Policy matched or rejected
Contract-risk checks passed or failed
Portfolio checks passed or failed
Paper order created
Paper order accepted/rejected
Paper order filled/cancelled/expired
Paper fill simulated
Paper position opened
Position quote updated
Exit rules armed or suspended
Position updated
Exit triggered
Exit fill simulated
Position closed
Trade reconstruction ready
```

### 13.5 Paper positions page

Must show:

```text
Open paper positions
Closed paper positions
Entry price
Current price
Underlying price
Current quote source
Current quote age
Quote status
Exit rules armed/suspended state
Exit rules suspended reason
Exit price
Unrealized P&L
Realized P&L
Gross P&L
Modeled cost drag
High-water mark
Drawdown from high-water mark
Stop level
Profit guard status
Exit reason
Fill model
Fill realism
Slippage versus mid
Spread
```

### 13.6 Paper orders page

Must show:

```text
Order status
Strategy event
Policy
Side
Quantity
Filled quantity
Remaining quantity
Order type
Time-in-force
Requested price
Paper-fill realism
Fill probability
Fill decision
Accepted time
Expiration time
Cancellation/expiry/rejection reason
Associated fills
```

### 13.7 Session summary page

Must show:

```text
Operational counts
Realized and unrealized P&L
Gross P&L
Net P&L
Spread cost
Slippage cost
Slippage versus mid
Win rate
Average win
Average loss
Expectancy per trade
Expectancy after modeled costs
Profit factor
Maximum drawdown
Maximum consecutive losses
Average trade duration
Most common rejection reasons
Shadow outcome summary, if enabled
```

### 13.8 Policy experiment comparison page

If multiple policies share a `policy_group_id`, the UI must allow the user to compare:

```text
Policy configuration differences
Match count
Rejection count
Fill rate
Net P&L
Cost drag
Win rate
Expectancy
Max drawdown
Most common rejection reasons
```

### 13.9 Trade reconstruction view

Must show:

```text
Strategy event
Display label
Policy snapshot
Match result and checks
Order lifecycle
Fill lifecycle
Quote timeline
Position update timeline
Exit rule evaluation
Circuit breaker events, if any
Cost attribution
Audit timeline
```

### 13.10 Copy guidelines

Avoid:

```text
Recommended
Best for you
Suitable
Advisor
Managed for you
We trade for you
Guaranteed
Risk free
Buy signal
Sell signal
Beginner-friendly profits
Consistent monthly returns
```

Use:

```text
Strategy event
Strategy entry condition met
Strategy exit condition met
User-configured rule
Paper automation
Technical trigger
Self-directed automation
Order draft
Matched your rule
Enabled by you
```

Good copy:

```text
Your paper automation rule matched this strategy event.
```

Bad copy:

```text
The platform recommends this trade for you.
```

---

## 14. Non-Functional Requirements

### 14.1 Reliability

```text
Duplicate events must not create duplicate orders for the same policy.
Multiple policies may create separate orders from the same event only when each policy independently matches and portfolio checks pass.
Open positions must recover after service restart.
Open orders must recover after service restart.
All execution events must be persisted.
Paper fills must be reproducible from stored quote and fill model data.
Probabilistic paper fills must store seed, probability, and realized decision.
Paper order expiry and cancellation must be reproducible from stored order lifecycle data.
Policy matching must be deterministic.
Daily-loss circuit breaker decisions must be replayable.
Shadow outcomes must be replayable and clearly separated from actual paper results.
Event processing must support replay.
Dead-letter queues must exist for failed events.
```

### 14.2 Latency targets

```text
Strategy event to policy decision: < 500 ms
Policy decision to paper order created: < 500 ms
Paper order created to paper fill decision: < 500 ms
End-to-end strategy event to paper fill decision: < 1.5 seconds
Position update frequency: max 1 update per second per position
Daily-loss circuit breaker evaluation: on every position update
UI real-time event delay target: < 1 second
```

### 14.3 Security

```text
Users can only access their own policies, positions, orders, fills, shadow outcomes, trade reconstructions, and audit records.
Admin access must be role-based.
Broker credentials, if added later, must be encrypted.
Policy changes require authenticated user action.
Policy enable/disable/pause/resume changes require dedicated audited endpoints.
Live trading actions require elevated confirmation.
Audit logs must be immutable or append-only.
```

### 14.4 Observability

Required metrics:

```text
strategy_events_received_total
strategy_blocked_events_total
policy_matches_total
policy_rejections_total
paper_orders_created_total
paper_orders_accepted_total
paper_orders_rejected_total
paper_orders_cancelled_total
paper_orders_expired_total
paper_fills_total
paper_fill_probability_avg
paper_fill_rate_by_realism_mode
slippage_vs_mid_avg
spread_cost_estimate_total
modeled_cost_drag_total
open_paper_positions
paper_positions_closed_total
daily_loss_circuit_breaker_triggered_total
portfolio_limit_rejections_total
position_quote_unavailable_total
position_exit_rules_suspended_total
shadow_outcomes_created_total
live_order_drafts_created_total
event_processing_latency_ms
policy_matching_latency_ms
paper_execution_latency_ms
quote_rejection_total
quote_source_unavailable_total
spread_rejection_total
duplicate_rejection_total
kill_switch_events_total
persistence_failures_total
dead_letter_events_total
```

Required dashboards:

```text
Strategy event health
Policy matching health
Paper execution health
Paper order lifecycle health
Position lifecycle health
Quote-quality failures
Quote-unavailable positions
Open paper positions
Open paper orders
Daily-loss circuit breaker activity
Portfolio exposure by underlying
Rejected events by reason
Fill realism and fill-rate analysis
Slippage and cost-drag analysis
User kill-switch activity
Platform kill-switch activity
Dead-letter queue
Persistence lag
```

### 14.5 Data retention and privacy review

The platform must support a data retention policy approved by legal/compliance before launch.

Requirements:

```text
Define retention periods for audit events, policy snapshots, order records, fill records, quote records, shadow outcomes, trade reconstructions, and user activity logs.
Define which records are immutable or append-only.
Define how privacy deletion requests interact with immutable audit records.
Define whether and how PII is minimized, redacted, tokenized, or separated from trading/audit records.
Define export requirements for user-facing audit/history data.
```

Default product proposal, pending counsel:

```text
Keep trading and audit records for a minimum approved retention period.
Minimize PII in append-only audit logs.
Store user identifiers as internal IDs where possible.
Keep personal profile data logically separate from immutable trading/audit records.
```

---

## 15. Acceptance Criteria

### AC-01 — No policy, no execution

```gherkin
Given a strategy emits an ENTRY_SIGNAL
And the user has no enabled automation policy
When the event is processed
Then no paper order is created
And no live order draft is created
And the strategy event is stored.
```

### AC-02 — Matching paper policy creates paper trade

```gherkin
Given the user has an enabled paper automation policy
And the policy allows the strategy, version, symbol, direction, and instrument
And quote, contract-risk, time-window, portfolio, and spread checks pass
When a matching ENTRY_SIGNAL is received
Then a policy match record is created
And a paper order is created
And a paper fill decision is created
And a paper position is opened if the order fills.
```

### AC-03 — Stale quote rejection

```gherkin
Given the user has an enabled paper automation policy
And the strategy event matches the policy
And the quote age is greater than the user's max quote age
When the event is processed
Then the policy is rejected
And the rejection reason is QUOTE_STALE
And no paper order is created.
```

### AC-04 — Duplicate signal protection

```gherkin
Given a strategy event has already created a paper order for a policy
When the same strategy event is received again
Then no duplicate paper order is created for that policy.
```

### AC-05 — Strategy version pinning

```gherkin
Given the user enabled strategy version 1.2.0
And strategy version 1.3.0 is released
When new events from version 1.3.0 arrive
Then the user's policy does not match those events
Until the user explicitly upgrades the policy.
```

### AC-06 — User kill switch

```gherkin
Given the user has active automation policies
When the user activates the kill switch
Then all automation policies are disabled
And new paper orders are blocked
And new live order drafts are blocked
And an audit event is recorded.
```

### AC-07 — Platform kill switch

```gherkin
Given an admin activates a strategy-level kill switch
When that strategy emits an ENTRY_SIGNAL
Then no policy may create a paper order or live order draft
And rejection reason must be PLATFORM_KILL_SWITCH_ACTIVE.
```

### AC-08 — Manual live order draft

```gherkin
Given the user is in manual live draft mode
And a strategy event matches the user's policy
When risk checks and readiness checks pass
Then a live order draft is created
And no broker order is submitted
Until the user manually confirms.
```

### AC-09 — Live auto-execution disabled by default

```gherkin
Given live auto-execution is not approved
When a user attempts to enable LIVE_AUTO mode
Then activation is blocked
And the UI indicates that this mode is unavailable.
```

### AC-10 — Time-in-force expiry

```gherkin
Given a DAY paper limit order remains unfilled
When the primary exchange session closes
Then the order status becomes EXPIRED
And expired_at is set
And no paper position is opened from the expired quantity.
```

### AC-11 — Concurrent policy edits use snapshots

```gherkin
Given a strategy event is being processed
And the policy snapshot has been captured
When the user edits the policy before processing completes
Then the in-flight match uses the captured snapshot
And the policy edit applies only to later event-processing attempts.
```

### AC-12 — Deterministic replay

```gherkin
Given stored event, policy snapshot, quote, order, fill model, fill probability, seed, and fill decision data
When the paper execution is replayed
Then the replay produces the same order lifecycle and fill result.
```

### AC-13 — Position quote provenance

```gherkin
Given an open paper position
When a fresh quote updates the position
Then the position update stores quote source, quote timestamp, quote age, spread, and price used for P&L.
```

### AC-14 — Fill realism and cost attribution

```gherkin
Given a policy uses REALISTIC paper_fill_realism
When a paper fill decision is made
Then the fill stores fill probability, seed, fill model version, slippage versus mid, spread cost, and net cost drag
And the session summary separates gross P&L from modeled costs.
```

### AC-15 — Daily loss circuit breaker

```gherkin
Given a policy has max_daily_loss = 300
And realized plus unrealized P&L reaches -300 during an open position
When the position update is processed
Then new entries are blocked
And open entry orders are cancelled
And open positions are closed or marked EXIT_PENDING_QUOTE
And the policy is paused or disabled for the remainder of the trading day.
```

### AC-16 — Time-of-day filters

```gherkin
Given a policy has entry_window_end = 15:30 exchange-local time
When a matching strategy event arrives at 15:35
Then the policy is rejected with ENTRY_WINDOW_CLOSED
And no paper order is created.
```

### AC-17 — DTE and delta filters

```gherkin
Given a policy allows max_days_to_expiry = 7 and max_delta = 0.65
When a strategy event references a 30-DTE contract or a contract with delta 0.80
Then the policy is rejected with DTE_OUT_OF_RANGE or DELTA_OUT_OF_RANGE.
```

### AC-18 — Trailing profit guard

```gherkin
Given a paper position has profit_guard_type = TRAILING_FROM_HIGH_WATER
And the position reaches a high_water_mark after activation
When the current price draws down by trailing_drawdown_pct from the high_water_mark
Then an exit is triggered with reason TRAILING_STOP.
```

### AC-19 — Quote unavailable state

```gherkin
Given an open option paper position
When the contract has no valid quote or the underlying is halted
Then quote_status becomes UNAVAILABLE or HALTED
And exit_rules_armed is false
And the user receives POSITION_QUOTE_UNAVAILABLE.
```

### AC-20 — Multiple policies same strategy version

```gherkin
Given a user has two enabled policies pinned to the same strategy version
And both policies match the same strategy event
When portfolio limits allow both
Then the system creates separate match records and separate paper order lifecycles for each policy.
```

### AC-21 — Portfolio concentration limit

```gherkin
Given a user already has max_concurrent_positions_per_underlying open for SPY
When another SPY event matches an enabled policy
Then the policy is rejected with PORTFOLIO_UNDERLYING_LIMIT_REACHED
And no paper order is created.
```

### AC-22 — Exportable trade reconstruction

```gherkin
Given a closed paper trade
When the user opens trade reconstruction
Then the user can see the strategy event, policy snapshot, match checks, quote timeline, order lifecycle, fills, exit reason, cost attribution, and audit timeline
And the user can export the reconstruction as CSV and JSON.
```

### AC-23 — Strategy version upgrade diff

```gherkin
Given a new strategy version is available
When the user opens the upgrade dialog
Then the dialog shows release notes, changed parameters, and available backtest or paper comparison
And the policy remains pinned until explicit acceptance.
```

### AC-24 — Shadow outcomes

```gherkin
Given a policy rejects an event
And shadow outcomes are enabled
When the shadow simulation completes
Then the rejection detail shows a clearly labeled hypothetical outcome
And actual paper P&L is unchanged.
```

### AC-25 — Copy and disclosure guardrails

```gherkin
Given the UI displays an ENTRY_SIGNAL event
Then the display label says "Strategy entry condition met" or equivalent
And the UI does not call it a buy signal, sell signal, recommendation, or suitable trade.
```

---

## 16. MVP Scope

### 16.1 MVP includes

```text
Strategy catalog
Strategy versions
Strategy version diff metadata
Strategy event feed
Single-leg option paper policies
Paper-only automation policies
Multiple enabled policies per strategy version
Policy matching engine
Policy rejection reasons
Time-of-day entry filters
Forced flatten time
DTE and basic contract-risk filters
Delta and liquidity filters when data is available
Basic portfolio concentration controls
Daily-loss circuit breaker
Paper order lifecycle
Time-in-force and order expiry
Paper fill realism settings
Paper fill models
Cost attribution and slippage versus mid
Paper position tracking
Quote state and quote provenance
Paper P&L
Option-premium and underlying-price stops
Trailing/high-water profit guard
Session summary and expectancy metrics
User kill switch
Platform kill switch
Audit trail
Trade reconstruction
Admin monitoring
```

### 16.2 MVP excludes

```text
Broker connection
Live order submission
Live auto-execution
Personalized recommendations
Suitability questionnaire
Portfolio management as advice
Auto strategy selection
Tax optimization
External notifications beyond in-app events
Multi-leg options
Corporate-action or adjusted-options modeling
Assignment/exercise modeling
Full IV/theta-adjusted stop automation
Guarantees that paper fills approximate a specific broker's live fills
```

---

## 17. Implementation Phases

### Phase 1 — Foundation

```text
Strategy catalog service
Strategy versioning
Strategy event model
Event display label mapping
Event persistence
Event feed UI
Audit ledger foundation
```

### Phase 2 — Paper automation core

```text
Automation policy service
Policy builder UI
Policy snapshotting
Policy matching engine
Rejection reason model
Paper order lifecycle
Time-in-force handling
Paper fill engine
Open paper positions
```

### Phase 3 — Options risk and position monitoring

```text
Market data and contract-risk integration
DTE and delta filters
Liquidity and spread filters
Time-of-day filters
Forced flatten behavior
Stop-loss variants
Trailing profit guard
Quote unavailable/halt state handling
Daily-loss circuit breaker
Basic portfolio exposure controls
```

### Phase 4 — Paper reporting and learning loops

```text
Position dashboard
Session summary
Expectancy and cost attribution
Policy experiment comparison
Shadow outcomes for rejected matches
Trade reconstruction view
User kill switch
Platform kill switch
Admin monitoring
Replay/recovery tooling
```

### Phase 5 — Manual live order drafts

```text
Broker connection foundation
Policy readiness checklist
Live order draft model
Manual confirmation flow
Broker order preview
Live order audit events
```

### Phase 6 — Live auto-execution, gated

```text
Compliance-approved authorization flow
Broker permission checks
Buying power checks
Live order routing
Live fill reconciliation
Live portfolio controls
Enhanced kill switch
Supervision dashboard
Incident response workflow
```

---

## 18. Developer Epics

### Epic 1 — Strategy catalog and versioning

```text
Create strategy schema
Create strategy version schema
Add version diff metadata
Create strategy APIs
Create catalog UI
Add performance-context display
Add admin strategy/version management
```

### Epic 2 — Strategy event ingestion

```text
Create normalized strategy event model
Add display label mapping
Ingest events from strategy engine
Persist events
Publish real-time events to UI
Add event replay support
```

### Epic 3 — Automation policy service

```text
Create expanded policy schema
Build policy CRUD APIs
Add validation rules
Add enable/disable flow
Add pause/resume flow
Add strategy version pinning
Support multiple policies per strategy version
Add audit logging
```

### Epic 4 — Policy matching engine

```text
Subscribe to strategy events
Load enabled policies
Capture policy snapshots
Evaluate deterministic match rules
Evaluate time, contract, quote, portfolio, and daily-loss gates
Emit POLICY_MATCHED or POLICY_REJECTED
Prevent duplicate execution per policy
Persist match results
```

### Epic 5 — Risk guardrail engine

```text
Quote freshness validation
Spread validation
DTE validation
Delta validation
Liquidity validation
Duplicate position validation
Portfolio exposure validation
Daily trade limit
Daily loss circuit breaker
Kill switch validation
Session close and forced-flatten handling
```

### Epic 6 — Paper execution engine

```text
Create paper order model
Create paper fill model
Implement fill-realism settings
Implement deterministic fill probability model
Track fill probability and seed
Track slippage versus mid
Track modeled cost drag
Open paper positions
Update paper positions
Close paper positions
Persist full lifecycle
```

### Epic 7 — Market data and position monitoring

```text
Create market quote model
Integrate position monitoring quote source
Track quote provenance
Track quote status
Handle stale quotes
Handle quote source unavailable
Handle halt/no-quote states
Suspend and re-arm exit rules
```

### Epic 8 — Reporting, audit, and learning loops

```text
Session summary
Expectancy metrics
Cost attribution metrics
Policy experiment comparison
Shadow outcome engine
Trade reconstruction view
Audit trail UI
```

### Epic 9 — User interface

```text
Strategy catalog UI
Strategy detail UI
Version comparison UI
Automation policy builder
Event timeline
Paper order tracker
Paper position tracker
Session summary
Policy experiment comparison
Trade reconstruction
Audit trail
Kill switch controls
```

### Epic 10 — Observability and operations

```text
Metrics
Dashboards
Dead-letter queue
Replay tooling
Admin pause controls
Platform kill switch
Daily-loss circuit breaker monitoring
Quote-unavailable monitoring
Portfolio exposure monitoring
Error monitoring
Persistence lag monitoring
```

---

## 19. Open Questions

1. Which precise market data vendors and quote-quality SLAs will be used for options quotes, Greeks, volume, open interest, halt state, and LULD state?
2. What default DTE, delta, liquidity, spread, and time-window values should be proposed for common intraday option policy templates without implying suitability?
3. What fill-probability model should define `REALISTIC` by asset class and liquidity tier?
4. Should shadow outcomes be MVP, beta, or Phase 4 only?
5. How long should shadow outcomes be tracked after a rejected event?
6. Which market-regime classifications should be used in strategy catalog reporting?
7. What minimum paper-history or deterministic-backtest window should be required before manual live order drafts?
8. What product copy must be reviewed by legal/compliance before release?
9. Which performance metrics can be displayed publicly in the strategy catalog?
10. What broker integrations are future candidates, and what order types must be supported?
11. What additional controls are needed if live auto-execution is pursued?
12. What disclosures and agreements are required before manual live order drafts or live auto-execution?
13. How should corporate-action risk be detected or flagged in MVP if full adjustment modeling is excluded?

Answered scope decisions in this version:

```text
MVP supports single-leg options only.
Multiple enabled policies per user/strategy/version are supported.
Daily loss uses realized plus unrealized P&L.
Trading day uses the primary exchange session date.
Daily loss is enforced as a circuit breaker during open positions.
Paper fill realism defaults to REALISTIC.
Internal ENTRY_SIGNAL/EXIT_SIGNAL codes require safer UI display labels.
```

---

## 20. Product Review Checklist

Before development starts, confirm:

```text
[ ] Product mode definitions are approved.
[ ] MVP excludes live execution.
[ ] Strategy event model is approved.
[ ] Display label mapping is approved.
[ ] User automation policy model is approved.
[ ] Multiple-policy support is approved.
[ ] Policy matching rules are approved.
[ ] Contract-risk filters are approved.
[ ] Time-of-day filters are approved.
[ ] Portfolio concentration controls are approved.
[ ] Daily-loss circuit breaker behavior is approved.
[ ] Paper fill realism model is approved.
[ ] Cost attribution metrics are approved.
[ ] Position lifecycle and quote-state handling are approved.
[ ] Rejection reason codes are approved.
[ ] UI copy restrictions are approved.
[ ] Paper/live disclosure copy is approved.
[ ] Strategy catalog performance format is approved.
[ ] Strategy version diff view is approved.
[ ] Shadow outcome scope is approved.
[ ] Trade reconstruction requirements are approved.
[ ] Audit requirements are approved.
[ ] Kill switch behavior is approved.
[ ] Strategy version pinning is approved.
[ ] Corporate-action MVP exclusion disclosure is approved.
[ ] Legal/compliance review path is defined.
[ ] Engineering epics are sequenced.
```

---

## 21. One-Sentence Engineering Rule

> Never execute, simulate, draft, or submit a user-specific order from a strategy event unless an enabled user-created policy snapshot matches that event and all required quote, contract-risk, portfolio, execution, platform, and authorization checks pass.
