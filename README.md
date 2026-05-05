# Sigmatiq Nexus

A high-performance strategy engine for real-time institutional flow analysis.

## Architecture
The Nexus acts as a middle-tier between **Ingestion** and **Execution**.

1. **Ingest (C#):** Pushes raw option trades to `md:options:trades` Redis Stream.
2. **Nexus (Python/Polars):** 
   - **Stage 1 (Heuristic):** Uses Polars to calculate Delta-Skew/Aggressor bias in microseconds.
   - **Stage 2 (AI):** Uses ONNX Runtime to validate trajectories with the RL Brain.
3. **Decisions:** Publishes `BET` or `PASS` results to `signal:final:*` Redis channels.

## Tech Stack
- **Polars:** Vectorized trade processing.
- **ONNX Runtime:** Native execution of TCN and RL models.
- **Redis Streams:** Persistent, high-throughput message bus.

## Extension
To add a new strategy:
1. Define a new logic class in `src/sigmatiq_nexus/strategies/`.
2. Add the corresponding `.onnx` model to the `models/` folder.
3. Register the strategy in the main `worker.py` loop.
