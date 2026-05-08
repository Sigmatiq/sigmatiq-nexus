# Automated Strategy Platform: Multi-Leg Options Extension Requirements v0.2

**Status:** Architecture/design extension, not MVP scope  
**Supports:** `automated-strategy-platform-requirements-v1.2.md`  
**Purpose:** Define future multi-leg requirements so core architecture can be designed leg-aware from the start without expanding the MVP beyond single-leg paper trading.

**Revision summary from v0.1:** Adds defined-risk validation, naked/ratio risk guardrails, live combo-order disclosure requirements, max-loss assumptions, conservative marking conventions, and reward/risk calculation semantics.

---

## 1. Relationship to MVP v1.2

The v1.2 MVP remains **single-leg paper options only**.

This document does not change MVP scope. It defines forward-compatible requirements for future phases involving spreads and other multi-leg option structures.

The platform should avoid hard-coding assumptions that every strategy event, policy, order, position, fill, stop, P&L calculation, or audit record has exactly one option contract.

Recommended design posture:

```text
MVP behavior: enforce one leg
Architecture: support legs[] shape internally where practical
Future behavior: enable multiple legs after separate approval
```

---

## 2. Multi-Leg Scope

Future supported structures may include:

```text
Debit call spread
Debit put spread
Credit call spread
Credit put spread
Iron condor
Iron butterfly
Calendar spread
Diagonal spread
Straddle
Strangle
Risk reversal
Ratio spread
Custom user-defined multi-leg basket
```

Initial multi-leg rollout should start with **defined-risk vertical spreads only**.

Iron condors and custom structures should come later because they require more complex fill, exit, margin, and user-explanation logic.

---

## 3. Non-Goals for First Multi-Leg Phase

The first multi-leg phase should not include:

```text
Naked short options
Undefined-risk spreads
Early assignment automation
Exercise decision automation
Portfolio margin optimization
Broker-specific smart routing assumptions
Complex tax-lot optimization
Auto-roll recommendations
User-specific suitability scoring
Guaranteed spread fill assumptions
```

---

## 4. Core Principle

A multi-leg trade must be treated as **one atomic strategy position**, not as unrelated single-leg trades.

The system must track:

```text
Parent strategy event
Parent user policy match
Parent order intent
Child legs
Atomic fill state
Net debit or net credit
Defined max loss and max profit where calculable
Exit lifecycle for the full structure
Per-leg quote and execution provenance
```

---

## 5. Canonical Leg Schema

Every multi-leg-capable object should support a `legs[]` array.

Example:

```json
{
  "legs": [
    {
      "leg_id": "leg_1",
      "action": "BUY_TO_OPEN",
      "instrument_type": "OPTION",
      "underlying_symbol": "SPY",
      "option_symbol": "SPY 2026-05-08 C 675",
      "expiry": "2026-05-08",
      "right": "CALL",
      "strike": 675.0,
      "quantity_ratio": 1,
      "delta": 0.42,
      "bid": 1.22,
      "ask": 1.28,
      "mid": 1.25,
      "quote_ts_utc": "2026-05-08T14:45:00Z"
    },
    {
      "leg_id": "leg_2",
      "action": "SELL_TO_OPEN",
      "instrument_type": "OPTION",
      "underlying_symbol": "SPY",
      "option_symbol": "SPY 2026-05-08 C 680",
      "expiry": "2026-05-08",
      "right": "CALL",
      "strike": 680.0,
      "quantity_ratio": 1,
      "delta": 0.24,
      "bid": 0.52,
      "ask": 0.57,
      "mid": 0.545,
      "quote_ts_utc": "2026-05-08T14:45:00Z"
    }
  ]
}
```

MVP can validate `len(legs) == 1`, while future phases can allow `len(legs) > 1`.

---

## 6. Strategy Event Requirements

A strategy event may include one or more candidate structures.

The event must distinguish between:

```text
Market signal
Candidate contract or structure
User policy eligibility
Final paper/live order intent
```

For compliance safety, the event should not imply that the platform is making a user-specific recommendation.

Preferred wording:

```text
Strategy condition matched. Candidate structure available for user policy evaluation.
```

Avoid wording like:

```text
Buy this spread.
This is the best contract.
Recommended trade.
```

---

## 7. User Policy Requirements

Multi-leg user policies must define allowed structures explicitly.

Required policy fields:

```text
allowed_structure_types
max_legs
allowed_opening_actions
max_net_debit
max_net_credit
max_defined_risk
min_credit_received
min_reward_to_risk
reward_to_risk_calculation = MAX_PROFIT_DIVIDED_BY_MAX_LOSS for first multi-leg phase
max_width_between_strikes
allowed_expiry_range_dte
allowed_delta_range_per_long_leg
allowed_delta_range_per_short_leg
max_total_spread_pct
min_open_interest_per_leg
min_volume_per_leg
max_quote_age_seconds_per_leg
require_same_expiry
require_same_underlying
allow_custom_legs
```

Defined-risk structures must calculate max loss before policy approval.

If max loss cannot be calculated, the match must fail closed.

---

## 8. Risk Checks

Multi-leg risk checks must include both per-leg and structure-level checks.

Per-leg checks:

```text
Quote exists
Quote age acceptable
Spread acceptable
OI acceptable
Volume acceptable
Contract not expired
Contract not halted or no-quote
Delta/DTE/extrinsic constraints pass
```

Structure-level checks:

```text
All legs have compatible underlying
All legs have compatible expiry if required
Net debit or credit can be calculated
Max loss can be calculated for defined-risk spreads
Max profit can be calculated where applicable
Reward/risk passes policy using max_profit / max_loss for the first multi-leg phase
Combined bid/ask spread passes policy
All legs are fillable under the selected paper-fill model
No duplicate leg identity conflict
Portfolio concentration checks pass
Daily loss and kill-switch checks pass
Defined-risk validation passes across the full relevant price range
No naked short option exposure exists
No ratio structure creates undefined risk
```

Defined-risk validation requirements:

```text
If any short leg is not paired with a covering long leg of the same expiry and same or further-OTM strike, reject as STRUCTURE_HAS_UNDEFINED_RISK.
If total short-leg quantity exceeds covering long-leg quantity in a way that creates residual naked exposure, reject as STRUCTURE_HAS_UNDEFINED_RISK.
If max loss cannot be calculated deterministically from the legs, quotes, multipliers, and expiry relationship, fail closed.
First multi-leg phase must reject ratio spreads, custom baskets, and any structure whose payoff cannot be proven defined-risk.
```

---

## 9. Paper Fill Model

Multi-leg fills must be atomic.

Valid final states:

```text
FILLED_ALL
REJECTED
EXPIRED_UNFILLED
CANCELLED
```

Avoid treating a partial leg fill as a valid paper position unless the platform explicitly supports partial-fill simulation.

First multi-leg phase should use:

```text
Atomic fill only
No partial fills
No legging simulation
No broker smart-routing assumptions
```

Disclosure requirement:

```text
Paper multi-leg fills are atomic by design.
Live broker behavior for combo orders varies by broker, order type, venue, and market condition.
Some brokers may reject combo orders, partially fill, or create legging risk.
Before live multi-leg can be enabled, the user must be shown broker-specific combo-order behavior and must explicitly acknowledge the difference from paper atomic fills.
```

Fill model must store:

```text
fill_model_version
fill_realism_mode
random_seed if probabilistic
per_leg_fill_price
net_fill_price
net_debit_or_credit
per_leg_slippage
total_slippage
per_leg_spread_cost
total_spread_cost
quote_snapshot_id per leg
```

---

## 10. Position Lifecycle

A multi-leg position must have one parent position record and child leg records.

The parent position must track:

```text
position_id
user_id
policy_id
strategy_event_id
structure_type
status
opened_at
closed_at
net_open_price
net_close_price
quantity
max_loss_at_entry
max_loss_assumptions
max_profit_at_entry
current_mark
unrealized_pnl
realized_pnl
exit_reason
```

Each leg must track:

```text
leg_id
parent_position_id
action
quantity_ratio
open_price
current_mark
close_price
per_leg_pnl
quote_provenance
```

Position status values:

```text
PENDING_OPEN
OPEN
PENDING_CLOSE
CLOSED
REJECTED
EXPIRED
ERROR_NEEDS_REVIEW
```

---

## 11. Exit Rules

Multi-leg exits must support structure-level exits first.

Required exit types:

```text
Net premium stop-loss
Net premium profit target
Trailing net premium giveback
Underlying price stop
Underlying price target
Time-based forced flatten
Expiration-risk flatten
Manual paper close
Kill-switch close
```

Per-leg exits should not be supported in the first phase unless explicitly designed. Closing one leg while leaving another open can change risk materially.

---

## 12. P&L and Marking

The platform must calculate:

```text
Per-leg mark
Structure-level net mark
Gross P&L
Spread cost
Slippage cost
Net P&L
Max favorable excursion
Max adverse excursion
Return on debit
Return on defined risk
```

For debit spreads:

```text
max_loss = net_debit_paid
max_profit = spread_width - net_debit_paid
max_loss_assumptions = AT_EXPIRATION_NO_ASSIGNMENT
```

For credit spreads:

```text
max_profit = net_credit_received
max_loss = spread_width - net_credit_received
max_loss_assumptions = AT_EXPIRATION_NO_ASSIGNMENT
```

Max-loss disclosure requirements:

```text
Displayed max_loss for first-phase multi-leg paper trading is theoretical at expiration and assumes no early assignment, no exercise, no corporate action, and valid contract multipliers.
The UI must show max_loss_assumptions near max_loss.
Live multi-leg support must not rely only on AT_EXPIRATION_NO_ASSIGNMENT if assignment, exercise, dividend, or pin-risk modeling is required.
```

Marking conventions:

```text
Open-position unrealized P&L must store mark_realism = OPTIMISTIC | REALISTIC | CONSERVATIVE.
Default displayed mark_realism for open multi-leg positions should be CONSERVATIVE closeout mark.
For long/debit structures, conservative closeout mark should use proceeds available to close, such as long-leg bid minus short-leg ask where applicable.
For short/credit structures, conservative closeout mark should use cost required to close, such as short-leg ask minus long-leg bid where applicable.
If any leg lacks a valid quote, mark quote_status on the structure and avoid presenting precise unrealized P&L as reliable.
```

If formula inputs are unavailable or invalid, the system must fail closed.

---

## 13. Audit and Replay

Every multi-leg decision must be replayable.

Audit records must include:

```text
Strategy event snapshot
Policy snapshot
All leg quotes
All risk-check inputs
All risk-check outputs
Fill model inputs
Fill model version
Fill seed
Per-leg fills
Net fill
Position updates
Exit decision inputs
Exit fills
Final P&L
```

Replay must reproduce:

```text
Policy match result
Rejection reasons
Fill decision
Fill price
Exit decision
Final paper outcome
```

---

## 14. API Response Requirements

Multi-leg API responses must avoid flattening the trade into one contract.

Recommended shape:

```json
{
  "structure_type": "DEBIT_CALL_SPREAD",
  "side": "BULLISH",
  "quantity": 1,
  "legs": [],
  "net_debit": 0.70,
  "net_credit": null,
  "max_loss": 70.0,
  "max_profit": 430.0,
  "reward_risk": 6.14,
  "fill_realism_mode": "REALISTIC",
  "risk_checks": [],
  "audit_id": "audit_123"
}
```

UI must show:

```text
Structure name
All legs
Net debit/credit
Max loss
Max profit
Breakeven
Exit rules
Modeled fill quality
Why accepted or rejected
```

---

## 15. Data Requirements

Multi-leg support requires reliable option-chain data for all legs.

Required data:

```text
Bid/ask/mid per leg
Quote timestamp per leg
Option volume per leg
Open interest per leg
Greeks per leg when available
Underlying price
Expiry calendar
Contract multiplier
Halt/no-quote state
Corporate-action/adjusted contract flag when available
```

If corporate-action or adjusted-contract state is unknown, multi-leg automation should reject affected contracts.

---

## 16. Implementation Guidance

Design now:

```text
Use legs[] in schemas where practical
Use parent-child order and position models
Use policy checks that can operate on one leg or many legs
Use audit records that store arrays of quote snapshots and fills
Keep MVP validator enforcing exactly one leg
```

Do not implement yet:

```text
Multi-leg broker routing
Partial leg fills
Assignment/exercise modeling
Undefined-risk strategies
Custom ratio strategy builder
Live multi-leg execution
```

---

## 17. Recommended Rollout Order

1. Make schemas leg-aware while enforcing one leg in MVP.
2. Add parent/child order and position storage models.
3. Add vertical-spread paper-only support.
4. Add structure-level risk checks and deterministic replay.
5. Add vertical-spread UI and audit reconstruction.
6. Add credit spreads after debit spreads are validated.
7. Add iron condors after credit spread lifecycle is stable.
8. Consider live order drafts only after legal, compliance, broker, and operational review.

---

## 18. Acceptance Criteria for Architecture Readiness

Architecture is multi-leg-ready when:

```text
Strategy event schema can represent legs[]
Policy schema can validate len(legs) == 1 for MVP
Order model has parent order and child legs
Position model has parent position and child legs
Audit model stores per-leg quote and fill provenance
Risk-check engine accepts a structure object, not only one contract
Paper-fill engine can be extended from one-leg atomic fill to multi-leg atomic fill
API response can represent one-leg and multi-leg positions consistently
UI can render a leg table even when there is only one leg
```

