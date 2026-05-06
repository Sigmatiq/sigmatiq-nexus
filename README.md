# Sigmatiq Nexus

A high-performance strategy engine for real-time institutional flow analysis.

## Architecture
The Nexus acts as a middle-tier between **Ingestion** and **Execution**.

1. **Ingest (C#):** Pushes raw option trades to `md:options:trades` Redis Stream.
2. **Nexus (Python/Polars):** 
   - **Stage 1 (Heuristic):** Uses Polars to calculate Delta-Skew/Aggressor bias in microseconds.
   - **Stage 2 (AI):** Uses ONNX Runtime to validate trajectories with the RL Brain.
3. **Decisions:** Publishes `BET` or `PASS` results to `signal:final:*` Redis channels.

## Live decision contract

- Decisions are based on completed New York trading windows, not wall-clock time on the worker host.
- `10:00` evaluates `09:30-10:00`, `10:30` evaluates `10:00-10:30`, `11:00` evaluates `10:30-11:00`, and `12:00` evaluates `11:30-12:00`.
- First trigger wins by default per `session_date + symbol`, so only one final live overlay is published per symbol per NY session.
- Set `NEXUS_FIRST_TRIGGER_SCOPE=strategy` only when each strategy is allowed to fire independently.
- `spy_low_sweep_core` is evaluated before `spy_sharpened_alpha` because it is the research-backed low-sweep candidate.

## Runtime configuration

- `REDIS_URL`: Redis connection URL used by the worker.
- `NEXUS_INPUT_STREAM`: Redis stream to consume, default `md:options:trades`.
- `NEXUS_SYMBOLS`: comma-separated symbols to process, default `SPY`.
- `NEXUS_IV_RANK_KEY`, `NEXUS_ATM_IV_KEY`, `NEXUS_NET_GEX_KEY`: Redis key templates for live context, each using `{symbol}`.
- `NEXUS_MIN_WINDOW_PREMIUM` and `NEXUS_SIDE_DOMINANCE`: window-level premium and side-dominance thresholds.

## Tech Stack
- **Polars:** Vectorized trade processing.
- **ONNX Runtime:** Native execution of TCN and RL models.
- **Redis Streams:** Persistent, high-throughput message bus.

## Extension
To add a new strategy:
1. Define a new logic class in `src/sigmatiq_nexus/strategies/`.
2. Add the corresponding `.onnx` model to the `models/` folder.
3. Register the strategy in the main `worker.py` loop.
