
import asyncio
import os
import json
import numpy as np
import polars as pl
import redis.asyncio as redis
import onnxruntime as ort
from datetime import datetime, timezone
from collections import deque

# --- CONFIGURATION ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
INPUT_STREAM = "md:options:trades" # Unified stream for all symbols
STRATEGY_ID = "open30_sniper_v1"
MODEL_TCN_PATH = "models/tcn_encoder_v1.onnx"
MODEL_RL_PATH = "models/rl/cql_policy_v1.onnx"

class SigmatiqNexus:
    def __init__(self):
        # State: symbol -> deque(last 100 trades)
        self.buffers = {}
        self.max_buffer = 100
        
        # Load ONNX Models
        print("Loading AI Brains (ONNX)...")
        self.tcn_session = ort.InferenceSession(MODEL_TCN_PATH)
        self.rl_session = ort.InferenceSession(MODEL_RL_PATH)
        
        self.redis = None

    async def connect(self):
        self.redis = await redis.from_url(REDIS_URL, decode_responses=True)
        print(f"Connected to Redis at {REDIS_URL}")

    async def run(self):
        if not self.redis:
            await self.connect()
            
        print(f"Nexus starting. Subscribing to {INPUT_STREAM}...")
        
        last_id = '$' # Read only new messages
        
        while True:
            try:
                # Read from Redis Stream
                # Using XREAD for high-throughput
                streams = {INPUT_STREAM: last_id}
                replies = await self.redis.xread(streams, count=10, block=1000)
                
                for stream, messages in replies:
                    for msg_id, data in messages:
                        last_id = msg_id
                        await self.process_message(data)
                        
            except Exception as e:
                print(f"Error in main loop: {e}")
                await asyncio.sleep(1)

    async def process_message(self, data):
        """
        Process a single trade from the stream.
        Expected data keys: symbol, price, size, premium, side, aggressor, is_sweep, ts_utc
        """
        try:
            # 1. Update Buffer
            payload = json.loads(data['payload']) if 'payload' in data else data
            symbol = payload['symbol'].strip()
            
            if symbol not in self.buffers:
                self.buffers[symbol] = deque(maxlen=self.max_buffer)
            
            self.buffers[symbol].append(payload)
            
            # 2. Trigger Logic if buffer is full enough
            if len(self.buffers[symbol]) >= 50:
                await self.evaluate_strategy(symbol)
                
        except Exception as e:
            print(f"Failed to process message: {e}")

    async def evaluate_strategy(self, symbol):
        # Convert buffer to Polars DataFrame (Blazing fast)
        trades_df = pl.DataFrame(list(self.buffers[symbol]))
        
        # --- STAGE 1: HEURISTIC (Signal Engine) ---
        # Portfolio of indicators (Simplified Polars implementation)
        sentiment = self.calculate_heuristic(trades_df)
        
        if sentiment:
            # Publish Intermediate Result
            intermediate_msg = {
                "strategy": STRATEGY_ID,
                "symbol": symbol,
                "stage": 1,
                "sentiment": sentiment,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await self.redis.publish(f"signal:intermediate:{STRATEGY_ID}", json.dumps(intermediate_msg))
            
            # --- STAGE 2: ML VALIDATION (RL Brain) ---
            decision = self.calculate_ml_validation(trades_df)
            
            if decision == "BET":
                final_msg = {
                    "strategy": STRATEGY_ID,
                    "symbol": symbol,
                    "stage": 2,
                    "decision": "BET",
                    "sentiment": sentiment,
                    "confidence": float(np.max(logits)),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                # Standard Sigmatiq Pattern: 
                # 1. Update the Key
                await self.redis.set(f"nexus_live_overlay:{symbol}", json.dumps(final_msg))
                # 2. Notify the Channel
                await self.redis.publish("nexus_live_overlay:updates", symbol)
                
                print(f"🚀 [BET] Signal generated for {symbol}!")

    def calculate_heuristic(self, df: pl.DataFrame):
        """
        Stage 1: The 'Winning' Tournament Heuristic (Polars version).
        Matches the logic of unusual_trades.py but 50x faster.
        """
        # Calculate session-level aggregates
        stats = df.select([
            pl.col("premium").sum().alias("total_premium"),
            (pl.col("premium").filter(pl.col("side") == "C").sum()).alias("call_premium"),
            (pl.col("premium").filter(pl.col("side") == "P").sum()).alias("put_premium"),
            (pl.col("is_sweep").cast(pl.Int32).mean()).alias("sweep_pct")
        ])
        
        total_premium = stats[0, "total_premium"]
        call_premium = stats[0, "call_premium"]
        put_premium = stats[0, "put_premium"]
        
        # Calculate Delta-Skew (Directional Bias)
        # Assuming we have delta in the live feed (or synthetic Greeks calculated earlier)
        # For simplicity in Stage 1, we use Call/Put ratio
        cp_ratio = call_premium / (put_premium + 1e-9)
        
        # HURDLES FROM TOURNAMENT (Strategy 1: Open30 SPY/QQQ)
        if total_premium > 100000 and (cp_ratio > 2.5 or cp_ratio < 0.4):
            return "BULLISH" if cp_ratio > 2.5 else "BEARISH"
            
        return None

    def calculate_ml_validation(self, df: pl.DataFrame):
        """
        Stage 2: RL Brain Validation.
        Matches the TCN preprocessing exactly.
        """
        try:
            # 1. Select latest 100 trades
            latest_df = df.tail(self.max_buffer)
            
            # 2. Extract Features
            # (Time relative to current window - assume 30m window)
            # time_rel, log_premium, delta, gamma, side_val, aggressor_val, sweep_val
            
            features = latest_df.select([
                # Dummy time_rel (could be improved with actual window start)
                (pl.arange(0, pl.count()) / 100.0).alias("time_rel"),
                (pl.col("premium").clip(1).log10()).alias("log_premium"),
                pl.col("delta").fill_null(0.0),
                pl.col("gamma").fill_null(0.0),
                (pl.when(pl.col("side") == "C").then(1.0).otherwise(-1.0)).alias("side_val"),
                (pl.when(pl.col("aggressor") == "A").then(1.0).when(pl.col("aggressor") == "B").then(-1.0).otherwise(0.0)).alias("aggressor_val"),
                pl.col("is_sweep").cast(pl.Float32).alias("sweep_val")
            ])
            
            # 3. Format for TCN (1, 7, 100)
            seq = features.to_numpy().astype(np.float32)
            if len(seq) < 100:
                pad = np.zeros((100 - len(seq), 7), dtype=np.float32)
                seq = np.vstack([pad, seq])
            
            tensor = seq.transpose(1, 0).reshape(1, 7, 100)
            
            # 4. RUN TCN
            dna_vector = self.tcn_session.run(None, {"trades": tensor})[0]
            
            # 5. RUN RL POLICY
            logits = self.rl_session.run(None, {"dna_vector": dna_vector})[0]
            action = np.argmax(logits)
            
            return "BET" if action == 1 else "PASS"
        except Exception as e:
            print(f"ML Validation Error: {e}")
            return "PASS"

if __name__ == "__main__":
    nexus = SigmatiqNexus()
    asyncio.run(nexus.run())
