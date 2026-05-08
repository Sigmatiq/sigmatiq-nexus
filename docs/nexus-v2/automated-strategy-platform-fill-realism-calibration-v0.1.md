# Automated Strategy Platform: Fill Realism Calibration v0.1

**Status:** Supporting specification  
**Supports:** Automated Strategy Platform Requirements v1.3  
**Purpose:** Define how paper fills are modeled so `REALISTIC` mode is testable, replayable, and comparable across versions.

---

## 1. Core Principle

Paper fills must not assume that a strategy event becomes a filled trade.

The fill model must use the quote, limit price, spread, quote age, liquidity, order side, and time of day to decide whether a paper order fills and at what modeled price.

---

## 2. Fill Realism Modes

```text
OPTIMISTIC
REALISTIC
CONSERVATIVE
```

MVP default:

```text
REALISTIC
```

Daily-loss circuit-breaker exits and forced liquidation simulations should use:

```text
CONSERVATIVE
```

---

## 3. Liquidity Tier Classification

Liquidity tier must be computed from observable contract data.

Inputs:

```text
spread_pct
quote_age_ms
option_volume_today
open_interest
underlying_symbol
minutes_after_open
minutes_to_close
```

Suggested tiers:

```text
TIER_1_DEEP_LIQUID
TIER_2_LIQUID
TIER_3_THIN
TIER_4_ILLIQUID
TIER_5_UNFILLABLE
```

Initial classification:

```text
TIER_1_DEEP_LIQUID: spread_pct <= 5, quote_age_ms <= 1000, volume >= 1000, open_interest >= 5000
TIER_2_LIQUID: spread_pct <= 10, quote_age_ms <= 2000, volume >= 300, open_interest >= 1000
TIER_3_THIN: spread_pct <= 20, quote_age_ms <= 5000, volume >= 50, open_interest >= 250
TIER_4_ILLIQUID: spread_pct <= 35, quote_age_ms <= 10000, volume >= 10, open_interest >= 50
TIER_5_UNFILLABLE: otherwise
```

If open interest is unavailable intraday, use the latest available OI snapshot and store `oi_staleness`.

---

## 4. Time-of-Day Adjustment

Fills near the open and close should be less favorable.

Suggested multipliers applied to base fill probability:

```text
09:30-09:45 ET: 0.70
09:45-10:00 ET: 0.85
10:00-15:30 ET: 1.00
15:30-15:50 ET: 0.85
15:50-16:00 ET: 0.60
```

0DTE contracts may use stricter close-window multipliers.

---

## 5. Spread-Position Probability Curve

The model must compute where the limit price sits inside the spread.

For buy orders:

```text
spread_position = (limit_price - bid) / (ask - bid)
```

For sell orders:

```text
spread_position = (ask - limit_price) / (ask - bid)
```

Clamp to `[0, 1]`.

Initial REALISTIC base fill probabilities:

```text
spread_position <= 0.10: 10%
spread_position <= 0.25: 25%
spread_position <= 0.50: 50%
spread_position <= 0.75: 75%
spread_position <= 1.00: 95%
```

Then apply liquidity tier and time-of-day multipliers.

---

## 6. Liquidity Multipliers

```text
TIER_1_DEEP_LIQUID: 1.10
TIER_2_LIQUID: 1.00
TIER_3_THIN: 0.75
TIER_4_ILLIQUID: 0.40
TIER_5_UNFILLABLE: 0.00
```

Final fill probability:

```text
fill_probability_pct = base_probability * liquidity_multiplier * time_of_day_multiplier
```

Clamp to `[0, 100]`.

---

## 7. Deterministic Replay

Every probabilistic fill must store:

```text
fill_model_version
fill_decision_seed
fill_probability_pct
fill_random_draw_pct
fill_decision
quote_snapshot_id
```

Seed format:

```text
SHA256(paper_order_id, strategy_event_id, policy_id, quote_snapshot_id, fill_model_version)
```

Replay must reproduce the same fill decision from the stored inputs.

---

## 8. Cost Attribution

Every fill must store:

```text
bid
ask
mid
limit_price
fill_price
slippage_vs_mid
spread_cost_estimate
modeled_transaction_cost_drag
liquidity_tier
time_of_day_multiplier
```

Session summaries must show gross P&L, slippage cost, spread cost, and net paper P&L separately.

---

## 9. Versioning

Any change to these items must increment `fill_model_version`:

```text
Probability curve
Liquidity tier thresholds
Time-of-day multipliers
Spread-cost formula
Conservative closeout convention
Random seed composition
```

Old paper results must retain the model version used at the time.

