# Nexus Participant Flow Context Design

## Purpose

Publish a live completed-window market-context payload that answers trader questions like:

- What side does retail-like flow appear to favor in the latest completed window?
- What side does institutional-like flow appear to favor in the latest completed window?
- What strategy shape is most active in the latest completed window?
- Is dealer hedging pressure likely stabilizing, destabilizing, buying, or selling underlying?
- Is the current read useful, noisy, or degraded?

This is not a trade signal. It is a labeled observation layer over live option trades, quote context, and optional dealer-context inputs.

## Naming Guardrail

Do not publish language such as `dealers_are_betting`, `retail_is_buying`, or `institutions_are_selling`.

Use:

- `retail_like_flow`
- `institutional_like_flow`
- `dealer_inferred_pressure`
- `dominant_strategy_shape`
- `window_side_read`

Reason: Nexus can observe trades and infer pressure. It cannot know true account type, opening/closing status, or dealer intent unless the feed explicitly provides that information.

## Scope Boundary

v1 returns completed-window context only. It does not claim tick-level current state.

Use this wording in API and prompt layers:

> latest completed window

Do not use:

> right now

unless the payload has `window_status = "partial"` in a future version.

## Proposed Artifact

Redis keys:

```text
nexus_participant_flow_context:{symbol}:{window_key}
nexus_participant_flow_context:{symbol}:latest
```

Pub/Sub:

```text
signal:participant_flow_context
```

Persistence stream:

```text
live:persistence:events
```

TTL policy:

| Key | Suggested TTL | Notes |
|---|---:|---|
| `nexus_participant_flow_context:{symbol}:{window_key}` | 48 hours | Allows same-day UI, EOD audit, and next-day debugging. |
| `nexus_participant_flow_context:{symbol}:latest` | 8 hours | Store full payload, not a pointer, for fast API reads. |

Windowing:

- Same market-context windows as `nexus_option_market_context`.
- Every 30 minutes from `09:30-16:00` ET.
- Optional `16:00-16:15` if OPRA after-close prints are useful.
- v1 publishes completed windows only.

## Window Identity

Use the existing Nexus window key for Redis compatibility and explicit ET timestamps for API/UI clarity.

```json
{
  "schema_version": 1,
  "symbol": "SPY",
  "window_key": "w0930_1000",
  "window_id": "2026-05-08T10:00:00-04:00",
  "window_label": "09:30-10:00",
  "window_tz": "America/New_York",
  "window_start": "2026-05-08T09:30:00-04:00",
  "window_end": "2026-05-08T10:00:00-04:00",
  "window_status": "completed",
  "is_partial": false,
  "as_of": "2026-05-08T14:00:05Z"
}
```

`window_key` is the Redis-compatible key suffix and should match existing Nexus option-market context keys such as `w0930_1000`.

`window_id` is the ET window-end timestamp. `window_label` is display-only.

## Proposed Payload

```json
{
  "schema_version": 1,
  "symbol": "SPY",
  "window_key": "w0930_1000",
  "window_id": "2026-05-08T10:00:00-04:00",
  "window_label": "09:30-10:00",
  "window_tz": "America/New_York",
  "window_start": "2026-05-08T09:30:00-04:00",
  "window_end": "2026-05-08T10:00:00-04:00",
  "window_status": "completed",
  "is_partial": false,
  "as_of": "2026-05-08T14:00:05Z",
  "redis_key": "nexus_participant_flow_context:SPY:w0930_1000",
  "window_side_read": {
    "premium_bias": "call_heavy",
    "aggressor_bias": "ask_side_call_heavy",
    "directional_read": "bullish",
    "confidence": "medium",
    "call_premium": 1200000,
    "put_premium": 650000,
    "reason_codes": ["CALL_PREMIUM_DOMINANCE", "ASK_SIDE_CALL_LARGE_PRINTS"],
    "why": [
      { "code": "CALL_PREMIUM_DOMINANCE", "text": "Call premium was 1.8x put premium" },
      { "code": "ASK_SIDE_CALL_LARGE_PRINTS", "text": "Ask-side call flow dominated large prints" }
    ]
  },
  "retail_like_flow": {
    "bias": "bullish",
    "confidence": "low",
    "premium": 180000,
    "trade_count": 42,
    "dominant_side": "calls",
    "dominant_shape": "lottery_calls",
    "reason_codes": ["SMALL_LOT_FAR_OTM_CALLS"],
    "why": [
      { "code": "SMALL_LOT_FAR_OTM_CALLS", "text": "Small-lot far-OTM calls dominated retail-like tags" }
    ]
  },
  "institutional_like_flow": {
    "bias": "bearish",
    "confidence": "medium",
    "premium": 850000,
    "trade_count": 5,
    "dominant_side": "puts",
    "dominant_shape": "put_sweep_or_tail_hedge",
    "reason_codes": ["LARGE_ASK_SIDE_PUT_PREMIUM", "HIGH_PREMIUM_CONTRACT_CLUSTER"],
    "why": [
      { "code": "LARGE_ASK_SIDE_PUT_PREMIUM", "text": "Large premium ask-side put trades clustered in one expiry" }
    ]
  },
  "dealer_inferred_pressure": {
    "underlying_hedge_direction": "sell_underlying",
    "impact_state": "destabilizing",
    "confidence": "low",
    "source": "gex_dex_hiro_plus_trade_direction",
    "reason_codes": ["NEGATIVE_GAMMA_AMPLIFICATION", "CUSTOMER_FLOW_BULLISH"],
    "why": [
      { "code": "NEGATIVE_GAMMA_AMPLIFICATION", "text": "Negative gamma regime would amplify directional hedging" },
      { "code": "CUSTOMER_FLOW_BULLISH", "text": "Customer-side flow leaned bullish in the completed window" }
    ]
  },
  "dominant_strategy_shape": {
    "shape": "directional_call_buying",
    "confidence": "medium",
    "supporting_shapes": ["lottery_calls", "call_sweeps"],
    "conflicting_shapes": ["put_tail_hedge"],
    "reason_codes": ["CALL_AGGRESSOR_DOMINANCE"]
  },
  "top_contracts": [
    {
      "raw_symbol": "SPY260508C00520000",
      "expiry": "2026-05-08",
      "strike": 520,
      "side": "C",
      "premium": 450000,
      "trade_count": 7,
      "participant_label": "institutional_like",
      "strategy_shape": "directional_call_buying",
      "reason_codes": ["LARGE_PREMIUM_CONTRACT"]
    }
  ],
  "data_quality": {
    "status": "usable",
    "missing": [],
    "degraded": [],
    "reason_codes": []
  },
  "source": "sigmatiq_nexus"
}
```

## Observed Facts vs Inference

Separate facts from interpretation.

| Field | Type | Meaning |
|---|---|---|
| `premium_bias` | observed | Call vs put premium imbalance. |
| `aggressor_bias` | observed/derived | Ask/bid side dominance after quote-gated aggressor classification. |
| `directional_read` | inferred | Bullish/bearish/neutral/conflicted read from premium + aggressor + quality. |
| `dealer_inferred_pressure` | inferred | Hedge-direction and market-impact inference from fresh net GEX plus completed-window flow, with pricing-side alignment only as a secondary tiebreaker. |

Allowed `directional_read` values:

- `bullish`
- `bearish`
- `neutral`
- `conflicted`
- `unknown`

## Dealer Inference Contract

Do not mix hedge direction and regime impact in one field.

```json
{
  "underlying_hedge_direction": "buy_underlying",
  "impact_state": "stabilizing",
  "confidence": "low"
}
```

Allowed `underlying_hedge_direction` values:

- `buy_underlying`
- `sell_underlying`
- `two_sided`
- `unknown`

Allowed `impact_state` values:

- `stabilizing`
- `destabilizing`
- `conflicted`
- `unknown`

Dealer inference is optional. If live dealer context is stale or missing, publish:

```json
{
  "underlying_hedge_direction": "unknown",
  "impact_state": "unknown",
  "confidence": "low",
  "source": "unavailable",
  "reason_codes": ["DEALER_CONTEXT_STALE_OR_MISSING"]
}
```

## Label Taxonomy

### Participant-Like Labels

These are heuristics, not identity claims.

| Label | Meaning | Example features |
|---|---|---|
| `retail_like` | Small, cheap, speculative flow. | Low premium per trade, far OTM, many small prints, lottery call/put shape. |
| `institutional_like` | Large or coordinated high-premium flow. | Large premium, block/sweep-like execution, or repeated high-premium cluster. |
| `positioning_or_hedge_like` | Flow that looks like protection or exposure management. | Large puts, wing puts, skew-heavy, mixed with rising underlying, tail-hedge tags. |
| `coordinated_or_clustered_like` | Repeated activity without enough premium/size to claim institutional-like. | Repeated same contract but below large premium threshold. |
| `unclear` | Cannot classify safely. | Missing aggressor, missing quote quality, balanced flow, ambiguous bid-side prints. |

Important rule:

`repeat_cluster` alone must not force `institutional_like`. It qualifies only when aggregate premium, size, or execution quality clears a configured threshold.

### Strategy Shape Labels

| Shape | Meaning | Needed features |
|---|---|---|
| `directional_call_buying` | Aggressive call buying dominates. | Side C, ask/aggressive flow, premium dominance. |
| `directional_put_buying` | Aggressive put buying dominates. | Side P, ask/aggressive flow, premium dominance. |
| `lottery_calls` | Cheap far-OTM call speculation. | Side C, low option price, far OTM, short DTE, many small prints. |
| `lottery_puts` | Cheap far-OTM put speculation. | Side P, low option price, far OTM, short DTE, many small prints. |
| `tail_hedge_puts` | Downside protection/tail risk demand. | Side P, far OTM or high skew, large premium, defensive context. |
| `premium_shock` | One or few trades dominate the window. | Single-trade/window premium concentration. |
| `repeat_cluster` | Same contract repeatedly traded. | Repeated raw_symbol in short time span. |
| `spread_or_structure_like` | Multi-leg or structured flow likely. | Same timestamp/near timestamp, same expiry, related strikes, opposite sides/aggressors. |
| `chop_or_income_like` | Balanced call/put or spread-heavy flow. | Mixed sides, high spread-like clustering, low directional dominance. |
| `unclear` | Cannot classify safely. | Missing key fields or conflicting tags. |

## Configurable Thresholds

Thresholds must be configurable and eventually symbol-aware.

Initial config shape:

```json
{
  "large_premium_threshold": 100000,
  "small_premium_threshold": 5000,
  "cheap_option_mid_threshold": 0.25,
  "far_otm_delta_threshold": 0.15,
  "repeat_cluster_window_seconds": 120,
  "repeat_cluster_min_aggregate_premium": 100000,
  "aggressor_max_spread_pct": 0.20
}
```

Threshold source order:

1. Symbol-specific override.
2. Symbol-class default, for example ETF vs mega-cap single stock.
3. Global default.
4. Future: percentile thresholds from recent trade distribution.

The full config does not need to be in every user-facing payload, but tests must pin the effective values.

## Reason Codes

Human `why` text is useful, but stable reason codes are required for tests, API consumers, and prompt consistency.

Initial reason-code examples:

| Code | Meaning |
|---|---|
| `CALL_PREMIUM_DOMINANCE` | Call premium materially exceeds put premium. |
| `PUT_PREMIUM_DOMINANCE` | Put premium materially exceeds call premium. |
| `ASK_SIDE_CALL_LARGE_PRINTS` | Large call prints were ask-side/aggressive. |
| `ASK_SIDE_PUT_LARGE_PRINTS` | Large put prints were ask-side/aggressive. |
| `BID_SIDE_AMBIGUOUS` | Bid-side flow is ambiguous without open/close. |
| `MISSING_FRESH_CONTRACT_QUOTE` | Quote data was missing or stale. |
| `WIDE_SPREAD_LOW_CONFIDENCE` | Spread was too wide for confident aggressor classification. |
| `REPEAT_CLUSTER_BELOW_INSTITUTIONAL_THRESHOLD` | Repeats exist but not enough premium/size for institutional-like. |
| `DEALER_CONTEXT_STALE_OR_MISSING` | Dealer inference could not be computed safely. |
| `LOW_CONFIDENCE_LABELS` | Most labels were inferred with low confidence, usually from bid-side or wide-spread ambiguity. |

## Data Quality And Confidence Degradation

Confidence must degrade when:

- quote is stale
- bid/ask spread is too wide
- trade price is between bid/ask but not near either side
- bid/ask is missing
- underlying price is stale
- OPRA print is late or out of sequence
- sample size is too small
- one trade dominates but aggressor is ambiguous

Opening/closing status remains unknown in Nexus v1, but that alone does not degrade a completed-window payload. Degradation should reflect missing aggressor coverage, thin samples, or low-confidence trade labels.

One bounded exception is allowed for main-symbol windows with strong repeated institutional clustering: if a completed window has a repeat-cluster institutional read above the configured premium threshold, a clear call-vs-put premium bias, and no materially stronger bid-side premium imbalance, the payload can remain `usable` even when many individual labels are low-confidence due to quote width. That preserves structurally meaningful windows without pretending the labels were high-quality.

Suggested `data_quality.status` values:

- `usable`
- `degraded`
- `thin`
- `stale`
- `unknown`

## Current Nexus Data Availability

| Required data | Current status | Evidence in code | Notes |
|---|---|---|---|
| `symbol` | Available | `normalize_trade_payload()` normalizes `symbol`. | Present from raw stream or underlying field. |
| `raw_symbol` | Available | `normalize_trade_payload()` keeps `raw_symbol`; `_contract_details_from_raw_symbol()` parses expiry/strike/side. | Required for contract grouping. |
| option side C/P | Available/derived | Parsed from `side` or `raw_symbol`. | Enough for call/put premium bias. |
| timestamp | Available/derived | `ts_utc` or `ts_event_ns` normalized. | Enough for windowing and clusters. |
| price and size | Available | `premium` derived from `price * size * 100`. | Needed for premium labels. |
| premium | Available/derived | `normalize_trade_payload()` and `window_stats()`. | Already used by strategies and context payload. |
| sweep flag | Available/derived with quote gate | `_derive_sweep_from_quote()` if no raw flag. | Uses premium threshold, not venue-level multi-exchange sweep truth. |
| aggressor side | Available/derived with quote gate | `_derive_aggressor_from_quote()`. | Requires fresh bid/ask and acceptable spread. |
| option bid/ask/mid | Available when Redis contract state exists | `_merge_contract_payload()` enriches bid/ask/mid/spread. | Missing quotes should degrade label confidence. |
| bid/ask spread pct | Available/derived | `_contract_contexts()` computes `bid_ask_spread_pct`. | Already in option market context. |
| delta/gamma | Available when contract-state/greeks exist | `_merge_contract_payload()` enriches delta/gamma. | Useful for moneyness/shape confidence. |
| underlying mid | Available when equity context exists | `_merge_underlying_context()` enriches `underlying_mid`. | Needed for moneyness if strike-only is insufficient. |
| IV rank / ATM IV / GEX | Available for some strategy gates | global context and feature gates reference IV/GEX. | Needed for dealer-pressure confidence, not participant labels. |
| GEX/DEX/HIRO dealer context | Partial | Strategy-fit and existing worker context use live inputs; Nexus has stream/Redis enrichment paths. | Need explicit read in participant context builder if dealer pressure is included. |
| opening vs closing trade | Not available | No open/close field in current normalized payload. | Must mark as unknown; do not infer actual position opening. |
| true account type retail/institution | Not available | Not present in OPRA/options trades. | Use `*_like`, never true identity. |
| multi-leg linkage ID | Not available | No spread ID or order ID. | Spread/structure labels must be heuristic. |

## What Nexus Already Publishes That Is Close

`nexus_option_market_context:{symbol}:{window_key}` already includes:

- call/put premium totals
- net premium bias
- trade count
- contract count
- sweep count
- large trade count
- most-traded contracts
- cheapest contracts
- costliest contracts
- cheap side
- costly side
- liquidity quality
- pricing quality
- late-event impact

The participant-flow context can reuse the same buffered window and many of the same aggregations.

## Missing Work

### P0: Pure Trade Labeler

Add a pure function that labels each normalized trade:

```text
label_trade_participant_shape(row, window_context, config) -> {
  participant_label,
  strategy_shape,
  direction_bias,
  confidence,
  reason_codes[],
  why[]
}
```

Initial rules:

- `institutional_like`: large premium, block/sweep-like execution, or coordinated high-premium cluster.
- `retail_like`: small premium, low option_mid, far OTM, many same-side small trades.
- `positioning_or_hedge_like`: put-side large premium, far OTM, elevated skew/defensive context when available.
- `coordinated_or_clustered_like`: repeated same contract but below institutional-like threshold.
- `unclear`: missing aggressor, missing quote freshness, bid-side ambiguity, or conflicting features.

### P0: Window Aggregator

Aggregate labeled trades into:

- `window_side_read`
- `retail_like_flow`
- `institutional_like_flow`
- `dominant_strategy_shape`
- `top_contracts`
- `data_quality`

### P0: Payload Publisher

Publish:

- completed-window key
- latest full-payload key
- pub/sub event
- persistence event

### P1: Dealer Inference

Dealer inference is optional in v1. The first implementation may publish `unknown` until explicit dealer-context reads and freshness rules are wired.

Add computed `dealer_inferred_pressure` only when live dealer context is fresh enough.

Inputs:

- live GEX regime
- net GEX sign/magnitude
- DEX bias if available
- HIRO/flow bias if available
- current window side read

### P1: Spread/Structure Heuristic

Detect likely spreads/structures without claiming certainty:

- same expiry
- related strikes
- close timestamps
- opposite side or mixed aggressor
- repeated paired contracts

Output should be `spread_or_structure_like`, not a named exact spread unless confidence is high.

## Implementation Location

Recommended files:

```text
src/sigmatiq_nexus/nexus_worker.py
  - publish_participant_flow_context_for_slot()

src/sigmatiq_nexus/participant_flow.py
  - label_trade_participant_shape()
  - aggregate_participant_flow_window()
  - infer_dealer_pressure()
  - build_participant_flow_payload()

tests/test_nexus_worker.py
  - Redis publish contract test

tests/test_participant_flow.py
  - trade-label unit tests
  - window aggregation tests
  - dealer inference tests

docs/NEXUS_LIVE_FEATURE_CONTRACT.md
  - add published message/key/channel contract
```

## API Consumption

After Nexus publishes this, `sigmatiq-api` should expose it as read-only live context:

```text
GET /v1/live/{symbol}/participant-flow-context
```

Query options:

| Parameter | Default | Meaning |
|---|---:|---|
| `window_key` | latest | Optional completed Nexus window key such as `w0930_1000`. |
| `window_id` | latest | Optional completed ET window-end timestamp if supported by the API mapper. |
| `include_contracts` | true | Include top contract details. |

This endpoint should not recompute labels. It should read Nexus Redis payloads and apply freshness/schema checks.

## Trader Prompt Fit

This payload supports prompts such as:

- "What side does retail-like flow appear to favor in the latest completed window?"
- "Is institutional-like flow aligned or opposite?"
- "What option strategy shape is most active in the latest completed window?"
- "Is dealer-inferred pressure likely helping or fighting the move?"

Prompt language must preserve uncertainty:

- say `retail-like`, not `retail`
- say `institutional-like`, not `institutions`
- say `dealer-inferred pressure`, not `dealers are betting`
- say `strategy shape`, not `confirmed strategy`
- say `latest completed window`, not `right now`, for v1

## Test Plan

Add explicit tests for:

- `retail_like` lottery calls from many small far-OTM prints.
- `institutional_like` large ask-side put sweep.
- Large bid-side trade degrades directional confidence.
- Missing quotes return `unclear` or low confidence.
- Repeat cluster does not force `institutional_like` if aggregate premium is small.
- Tail-hedge puts require put-side large premium or defensive context.
- Spread structure-like label from same-expiry related strikes near the same timestamp.
- Window side read is call-heavy but low confidence when aggressor is missing.
- Dealer pressure is `unknown` when dealer context is stale.
- Latest Redis payload matches completed-window contract and includes `schema_version`.
