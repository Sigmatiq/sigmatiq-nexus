# Sigmatiq Nexus

A high-performance strategy engine for real-time institutional flow analysis.

## Architecture
The Nexus acts as a middle-tier between **Ingestion** and **Execution**.

1. **Ingest (C#):** Pushes raw option trades to `md:options:trades` Redis Stream.
2. **Nexus (Python/Polars):** 
   - **Stage 1 (Heuristic):** Uses Polars to calculate Delta-Skew/Aggressor bias in microseconds.
   - **Stage 2 (AI):** Uses ONNX Runtime to validate trajectories with the RL Brain.
3. **Decisions:** Publishes `BET` or `PASS` results to `signal:final:*` Redis channels.
4. **Persistence:** Appends final/intermediate signal payloads to `live:persistence:events`; `Sigmatiq.Options.LivePersistenceWorker` stores them in `live.nexus_strategy_signal` for EOD review.

## Live decision contract

- Decisions are based on completed New York trading windows, not wall-clock time on the worker host.
- `10:00` evaluates `09:30-10:00`, `10:30` evaluates `10:00-10:30`, `11:00` evaluates `10:30-11:00`, `11:30` evaluates `11:00-11:30`, and `12:00` evaluates `11:30-12:00`.
- First trigger wins by default per `session_date + symbol`, so each symbol has one independent trade lane per NY session.
- `etf_confluence_sniper` also participates in a separate shared group lock across the configured ETF universe, controlled by `NEXUS_GROUP_LOCK_STRATEGIES`.
- Result: `SPY` and `QQQ` can each fire independently, while the group confluence lane still remains single-fire.
- `etf_confluence_sniper` is evaluated first for each eligible window.
- `etf_open_specialist` is the explicit 10:00 ET cheap-call rule for the completed 09:30-10:00 window.
- `etf_low_sweep_core` remains available as the tested low-sweep candidate; `etf_flow_specialist` and `etf_momentum_specialist` are restricted to their researched 10:30 and 11:00 entry windows.
- Every implemented strategy now publishes a per-window `WINDOW_VIEW` sentiment for every completed window from `09:30-12:00` ET, independent of whether that strategy is allowed to emit a trade candidate in that slot.
- Nexus also publishes one per-window `WINDOW_PRICING` message per symbol/window with the cheapest contract, costliest contract, and cheap/costly side summary derived from pricing-lag inside that completed window.
- Each strategy now has a fail-closed feature gate. If required live fields are missing, Nexus emits a stage `0` `BLOCKED` diagnostic to `live:persistence:events` and skips the strategy instead of defaulting missing booleans/numbers.
- Final `BET` payloads now carry the exact option `raw_symbol`, and runtime liquidation tracks that exact contract via `options:live:contract_state:{raw_symbol}` / `options:live:tradability:{raw_symbol}` instead of comparing against unrelated same-symbol option trades.

## Runtime configuration

- `REDIS_URL`: Redis connection URL used by the worker.
- `NEXUS_REDIS_CLUSTER`: set to `true` for Azure clustered Redis. In cluster mode Nexus reads each configured input stream separately so Redis does not reject multi-key `XREAD` calls across hash slots.
- `NEXUS_INPUT_STREAM`: optional explicit Redis stream. If absent, Nexus consumes `md:{symbol}:options:trades`.
- `NEXUS_SYMBOLS`: comma-separated symbols to process, default `SPY,QQQ`.
- `NEXUS_GROUP_LOCK_STRATEGIES`: comma-separated strategy names that should also share one cross-symbol group lock, default `etf_confluence_sniper`.
- `NEXUS_IV_RANK_KEY`, `NEXUS_ATM_IV_KEY`, `NEXUS_NET_GEX_KEY`: optional direct Redis key templates for live context, each using `{symbol}`.
- `NEXUS_IV_SURFACE_KEY`, `NEXUS_VRP_KEY`, `NEXUS_GEX_KEY`: live options-worker fallback key templates, defaulting to `options:live:*:{symbol}` keys.
- `NEXUS_EQUITY_CONTEXT_KEY`: equity live context key template, default `equity:live:context:{symbol}`.
- `NEXUS_CONTRACT_TRADABILITY_KEY`: option tradability key template, default `options:live:tradability:{raw_symbol}`.
- `NEXUS_CONTRACT_STATE_KEY`: per-contract quote plus Greek state key template, default `options:live:contract_state:{raw_symbol}`.
- `NEXUS_REQUIRE_CONTEXT_TIMESTAMPS`: default `true`; timestamp-less scalar context keys are blocked for live strategy decisions.
- `NEXUS_VOL_CONTEXT_MAX_AGE_SECONDS`: max IV/VRP context age, default `120`.
- `NEXUS_GEX_CONTEXT_MAX_AGE_SECONDS`: max GEX context age, default `120`.
- `NEXUS_UNDERLYING_MAX_AGE_SECONDS`: max underlying state age on enriched events, default `5`.
- `NEXUS_OPTION_QUOTE_MAX_AGE_SECONDS`: max option quote/mid age on enriched events, default `5`.
- `NEXUS_GREEK_MAX_AGE_SECONDS`: max Greek age on enriched events, default `60`.
- `NEXUS_SWEEP_PREMIUM_USD`: quote-derived sweep threshold when raw `is_sweep` is absent, default `25000`.
- `NEXUS_MIN_WINDOW_PREMIUM` and `NEXUS_SIDE_DOMINANCE`: window-level premium and side-dominance thresholds.
- `NEXUS_OPEN_CALL_DOMINANCE`: opening cheap-call dominance threshold, default `1.5`.
- `LIVE_PERSISTENCE_EVENT_STREAM`: Redis Stream for durable signal capture, default `live:persistence:events`.

## Feature audit

Before enabling a live strategy, verify the Redis payload shape:

```bash
nexus-audit-features --symbol SPY --limit 5
```

The audit reports which implemented strategies are `ready`, `degraded`, or `blocked` based on the sampled trade event plus live IV/GEX context. It also reports `stale` or `unknown_freshness` when a required field exists but cannot be trusted at decision time. The full feature contract is documented in `docs/NEXUS_LIVE_FEATURE_CONTRACT.md`.

At runtime Nexus enriches raw option trade events from:

- `equity:live:context:{symbol}` for `underlying_mid` and spot freshness.
- `options:live:tradability:{raw_symbol}` for option bid/ask/mid, quote timestamp, spread, and executable/tradability flags.
- `options:live:contract_state:{raw_symbol}` for option mid, quote quality, tradability flags, underlying spot, and Greeks.
- If raw trades omit `aggressor` or `is_sweep`, Nexus derives them only from fresh quote state; stale or untradable quotes still block the relevant strategy.

## Operational logging

Nexus now emits structured JSON logs for the decision path so production checks can separate input, gating, and signal failures quickly.

- `worker_started`, `redis_connected`, `stream_batch_received`: confirms the worker is alive and reading Redis streams.
- `slot_candidate_received`, `window_evaluation_started`: confirms events are arriving for a symbol and a completed NY window is being evaluated with real premium totals.
- `strategy_blocked`: emitted when fail-closed feature gates reject a strategy due to missing or stale live fields.
- `strategy_window_view_published`: emitted when a strategy publishes its directional read of a completed window as `BULLISH`, `BEARISH`, or `CHOP`.
- `window_pricing_published`: emitted when Nexus publishes the separate cheap-versus-costly contract summary for the completed window.
- `strategy_no_signal`: emitted when data is present but the heuristic or model threshold did not qualify.
- `strategy_intermediate_published`, `strategy_final_published`, `position_liquidated`: emitted when Nexus actually produces a signal or exits a live position.

Example grep targets:

```bash
rg '"event":"window_evaluation_started"|\"event\":\"strategy_no_signal\"|\"event\":\"strategy_final_published\"'
```

## Tech Stack
- **Polars:** Vectorized trade processing.
- **ONNX Runtime:** Native execution of TCN and RL models.
- **Redis Streams:** Persistent, high-throughput message bus.

## Extension
To add a new strategy:
1. Define a new logic class in `src/sigmatiq_nexus/strategies/`.
2. Add the corresponding `.onnx` model to the `models/` folder.
3. Register the strategy in the main `worker.py` loop.
