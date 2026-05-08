# Nexus Same-Window Day-Over-Day Context Design

## Purpose

Answer trader questions like:

- What is different in today's `09:30-10:00` window versus yesterday's `09:30-10:00` window?
- Did the same window become more bullish, bearish, noisy, or concentrated?
- Is today's opening flow materially different from the prior comparable window?

This is a comparison layer over completed Nexus window context. It is not a trade signal and must not suggest entries.

## Scope Boundary

This design compares the same symbol and same `window_key` across two trading sessions.

It is separate from `window_change_context`, which compares the current completed window to the previous completed window on the same day.

Use:

- `same_window_day_over_day_context`
- `comparison_window_key`
- `current_session_date`
- `baseline_session_date`

Do not use vague wording like "right now vs yesterday" unless both windows are explicitly named.

## Source Inputs

Primary source, once implemented:

```text
nexus_participant_flow_context:{symbol}:{window_key}
```

Fallback source for v1 if participant-flow is not yet available:

```text
nexus_option_market_context:{symbol}:{window_key}
```

API/persistence may also read archived persisted payloads for prior sessions if Redis TTL has expired.

## Proposed Artifact

Redis key:

```text
nexus_same_window_dod_context:{symbol}:{current_session_date}:{window_key}
nexus_same_window_dod_context:{symbol}:latest
```

Pub/Sub:

```text
signal:same_window_day_over_day_context
```

Persistence stream:

```text
live:persistence:events
```

TTL policy:

| Key | Suggested TTL | Notes |
|---|---:|---|
| `nexus_same_window_dod_context:{symbol}:{current_session_date}:{window_key}` | 48 hours | Same-day UI and next-day audit. |
| `nexus_same_window_dod_context:{symbol}:latest` | 8 hours | Full latest payload for fast reads. |

## Proposed Payload

```json
{
  "schema_version": 1,
  "symbol": "SPY",
  "comparison_type": "same_window_day_over_day",
  "window_key": "w0930_1000",
  "window_label": "09:30-10:00",
  "window_tz": "America/New_York",
  "current_session_date": "2026-05-08",
  "baseline_session_date": "2026-05-07",
  "current_window_id": "2026-05-08T10:00:00-04:00",
  "baseline_window_id": "2026-05-07T10:00:00-04:00",
  "as_of": "2026-05-08T14:00:10Z",
  "comparison_status": "complete",
  "changed_materially": true,
  "materiality_score": 78,
  "headline": "Today's opening window is more call-heavy and more concentrated than yesterday's same window.",
  "biggest_differences": [
    {
      "field": "call_premium",
      "direction": "higher",
      "current": 1200000,
      "baseline": 520000,
      "change_pct": 130.8,
      "reason_code": "CALL_PREMIUM_MATERIALLY_HIGHER",
      "text": "Call premium is 2.3x yesterday's same window."
    },
    {
      "field": "dominant_strategy_shape",
      "direction": "changed",
      "current": "directional_call_buying",
      "baseline": "chop_or_income_like",
      "reason_code": "STRATEGY_SHAPE_CHANGED",
      "text": "The dominant strategy shape changed from chop/income-like to directional call buying."
    }
  ],
  "what_stayed_same": [
    {
      "field": "liquidity_quality",
      "value": "good",
      "reason_code": "LIQUIDITY_STABLE"
    }
  ],
  "current_summary": {
    "premium_bias": "call_heavy",
    "directional_read": "bullish",
    "dominant_strategy_shape": "directional_call_buying",
    "pricing_quality": "usable",
    "liquidity_quality": "good"
  },
  "baseline_summary": {
    "premium_bias": "balanced",
    "directional_read": "neutral",
    "dominant_strategy_shape": "chop_or_income_like",
    "pricing_quality": "usable",
    "liquidity_quality": "good"
  },
  "data_quality": {
    "status": "usable",
    "missing": [],
    "degraded": ["baseline_dealer_context_unavailable"],
    "reason_codes": ["BASELINE_DEALER_CONTEXT_UNAVAILABLE"]
  },
  "caveats": [
    "This compares the same clock window, not the same market regime.",
    "Prior-session context may have expired from Redis and may require persisted history."
  ],
  "source": "sigmatiq_nexus"
}
```

## Fields To Compare

### P0 Fields

These can be compared from either participant-flow context or option-market context.

| Field | Comparison |
|---|---|
| `call_premium` | absolute and percent change |
| `put_premium` | absolute and percent change |
| `total_premium` | absolute and percent change |
| `premium_bias` / `net_premium_bias` | changed / unchanged |
| `trade_count` | absolute and percent change |
| `contract_count` | absolute and percent change |
| `sweep_count` | absolute and percent change |
| `large_trade_count` | absolute and percent change |
| top contracts | overlap, new dominant contracts, concentration shift |
| `liquidity_quality` | changed / unchanged |
| `pricing_quality` | changed / unchanged |

### P1 Fields

These require participant-flow context.

| Field | Comparison |
|---|---|
| `directional_read` | changed / unchanged |
| `retail_like_flow.bias` | changed / unchanged |
| `institutional_like_flow.bias` | changed / unchanged |
| `dominant_strategy_shape.shape` | changed / unchanged |
| `dealer_inferred_pressure.underlying_hedge_direction` | changed / unchanged |
| `dealer_inferred_pressure.impact_state` | changed / unchanged |
| `data_quality.status` | changed / unchanged |

## Materiality Rules

`changed_materially` should be true when one or more strong differences appear.

Initial examples:

- premium changed by at least 50% and at least `$100k`
- directional read changed, for example `neutral -> bullish`
- dominant strategy shape changed
- top contract concentration changed materially
- liquidity or pricing quality degraded
- sweep or large-trade count changed materially

`materiality_score` range: `0-100`.

Suggested scoring:

| Component | Max points |
|---|---:|
| Premium magnitude change | 25 |
| Directional read change | 20 |
| Strategy-shape change | 20 |
| Concentration/top-contract change | 15 |
| Liquidity/pricing quality change | 10 |
| Dealer inference change | 10 |

If source data is degraded, cap `materiality_score` at `60` unless the change is based on fresh P0 fields.

## Data Quality Rules

Return `comparison_status`:

- `complete`
- `partial`
- `missing_current`
- `missing_baseline`
- `schema_mismatch`
- `stale_or_expired`

If `schema_version` differs between current and baseline payloads, return `schema_mismatch` and avoid numeric comparison except for fields known to be compatible.

If baseline is unavailable in Redis, `sigmatiq-api` should try persisted history if implemented. If neither is available, return `missing_baseline`.

## Current Data Availability

| Data | Available now? | Notes |
|---|---:|---|
| Completed option-market context today | Yes | `nexus_option_market_context:{symbol}:{window_key}` exists from current Nexus market-context publisher. |
| Latest option-market context | Yes | `nexus_option_market_context:{symbol}:latest`. |
| Prior-day Redis context | Maybe | Current option-market context keys do not include session date and may expire/overwrite. Needs persistence/history for reliable prior-day comparison. |
| Participant-flow labels | Not yet | Requires `NEXUS_PARTICIPANT_FLOW_CONTEXT_DESIGN.md` implementation. |
| Persistent lookup by session/window | Partial/unknown | Persistence stream exists, but queryable typed history for this exact payload must be verified or added. |

## Implementation Options

### Option A: Nexus Builds Comparison

Nexus publishes comparison once the current window completes.

Pros:

- One producer owns all comparison semantics.
- Pub/Sub consumers receive comparison immediately.

Cons:

- Nexus needs access to prior-session payloads, likely from Redis or DB.
- Adds historical lookup responsibility to live worker.

### Option B: `sigmatiq-api` Builds Comparison From Stored Context

Nexus publishes only per-window context. `sigmatiq-api` reads current and baseline payloads and computes comparison on demand.

Pros:

- Keeps Nexus as producer of facts only.
- Easier to support arbitrary baseline dates.
- Better fit for trader queries.

Cons:

- No push event unless API/backend also publishes one.
- Requires reliable persisted payload access.

Recommended v1: Option B.

Nexus should publish durable per-window context. `sigmatiq-api` should expose comparison as a read-only computed endpoint.

## Proposed API Endpoint

```text
GET /v1/live/{symbol}/same-window-day-over-day-context?window_key=w0930_1000&baseline_date=previous_session
```

Query parameters:

| Parameter | Default | Meaning |
|---|---:|---|
| `window_key` | latest completed window | Nexus window key such as `w0930_1000`. |
| `baseline_date` | previous trading session | Baseline session date or `previous_session`. |
| `include_contracts` | true | Include top-contract comparison. |

The API should not ask an LLM to compare raw payloads. It should compute stable diffs and return reason codes.

## Trader Prompt Fit

Supports prompts like:

- "What is different in this window today than yesterday?"
- "Is today's opening flow stronger than yesterday's opening flow?"
- "Did the dominant strategy shape change from yesterday?"
- "Is this more concentrated or broader than yesterday?"

Prompt guardrails:

- Say `today's 09:30-10:00 window vs yesterday's 09:30-10:00 window`.
- Do not say `today is better` or `trade this`.
- Always mention that same clock window can occur in a different market regime.
- If baseline is missing or degraded, say the comparison is unavailable or partial.

## Test Plan

Add tests for:

- Current and baseline complete with higher call premium today.
- Current and baseline complete with strategy-shape change.
- No material change when differences are below thresholds.
- Missing baseline returns `missing_baseline`.
- Schema mismatch returns `schema_mismatch`.
- Top-contract concentration change is detected.
- Degraded baseline caps materiality score.
