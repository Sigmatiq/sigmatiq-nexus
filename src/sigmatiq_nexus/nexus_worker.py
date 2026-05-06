
import asyncio
import os
import json
import numpy as np
import polars as pl
import redis.asyncio as redis
import onnxruntime as ort
from datetime import datetime, timezone
from collections import deque
import pytz

# --- CONFIGURATION ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
INPUT_STREAM = "md:options:trades" 

# Model Paths
MODEL_V6_HYBRID = "models/hybrid_spy_v6.onnx"
SCALER_V6_PATH = "models/hybrid_scaler_v6.npz"

class SigmatiqNexus:
    def __init__(self):
        self.buffers = {}
        self.max_buffer = 100
        
        print("Loading Hybrid Sniper Brain (ONNX)...")
        # Hybrid Brain (v6)
        self.v6_hybrid = ort.InferenceSession(MODEL_V6_HYBRID)
        scaler_data = np.load(SCALER_V6_PATH)
        self.scaler_mean = scaler_data['mean']
        self.scaler_scale = scaler_data['scale']
        
        # State: First Trigger Wins per Day
        self.last_reset_date = datetime.now(timezone.utc).date()
        self.signaled_today = set()
        
        self.tz_ny = pytz.timezone('America/New_York')
        self.redis = None

    async def connect(self):
        self.redis = await redis.from_url(REDIS_URL, decode_responses=True)
        print(f"Connected to Redis at {REDIS_URL}")

    async def run(self):
        if not self.redis:
            await self.connect()
        print(f"Nexus starting. Subscribing to {INPUT_STREAM}...")
        
        last_id = '$'
        while True:
            try:
                # Daily Reset
                current_date = datetime.now(timezone.utc).date()
                if current_date > self.last_reset_date:
                    print(f"New trading day: {current_date}. Resetting filters.")
                    self.signaled_today.clear()
                    self.last_reset_date = current_date

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
        try:
            payload = json.loads(data['payload']) if 'payload' in data else data
            symbol = payload['symbol'].strip()
            if symbol != "SPY": return
            if symbol in self.signaled_today: return
            
            if symbol not in self.buffers:
                self.buffers[symbol] = deque(maxlen=self.max_buffer)
            self.buffers[symbol].append(payload)
            
            if len(self.buffers[symbol]) >= 50:
                await self.evaluate_strategy(symbol)
        except Exception as e:
            print(f"Failed to process: {e}")

    async def evaluate_strategy(self, symbol):
        trades_df = pl.DataFrame(list(self.buffers[symbol]))
        
        # Get Current NY Time to determine the Window
        now_ny = datetime.now(self.tz_ny).time()
        
        # --- STAGE 1: TIME-AWARE HEURISTIC ---
        sentiment, stage1_valid = await self.calculate_time_aware_heuristic(trades_df, symbol, now_ny)
        
        if stage1_valid:
            # Event 1: Intermediate
            intermediate_msg = {
                "strategy": "spy_sharpened_alpha",
                "symbol": symbol,
                "stage": 1,
                "sentiment": sentiment,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await self.redis.publish("signal:intermediate:spy_sharpened", json.dumps(intermediate_msg))
            
            # --- STAGE 2: HYBRID ML VALIDATION ---
            decision, prob = await self.calculate_hybrid_validation(trades_df, symbol)
            
            if decision == "BET":
                # Event 2: Final (First Trigger Wins)
                final_msg = {
                    "strategy": "spy_sharpened_alpha",
                    "symbol": symbol,
                    "stage": 2,
                    "decision": "BET",
                    "sentiment": sentiment,
                    "confidence": float(prob),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                self.signaled_today.add(symbol)
                await self.redis.set(f"nexus_live_overlay:{symbol}", json.dumps(final_msg))
                await self.redis.publish("nexus_live_overlay:updates", symbol)
                print(f"🚀 [BET] SHARPENED Alpha for {symbol} (Time: {now_ny}, Conf: {prob:.4f})")

    async def calculate_time_aware_heuristic(self, df, symbol, now_ny):
        # Fetch Market Context
        iv_rank = float(await self.redis.get(f"stats:{symbol}:iv_rank") or 50.0)
        atm_iv = float(await self.redis.get(f"stats:{symbol}:atm_iv") or 15.0)
        net_gex = float(await self.redis.get(f"stats:{symbol}:net_gex") or 0.0)
        
        stats = df.select([
            pl.col("premium").sum().alias("total_premium"),
            (pl.col("premium").filter(pl.col("side") == "C").sum()).alias("call_premium"),
            (pl.col("premium").filter(pl.col("side") == "P").sum()).alias("put_premium"),
            (pl.col("is_sweep").mean()).alias("sweep_pct")
        ])
        total_p = stats[0, "total_premium"]
        call_p = stats[0, "call_premium"]
        put_p = stats[0, "put_premium"]
        sweep = stats[0, "sweep_pct"]

        if total_p < 200000: return None, False

        # --- WINDOW-SPECIFIC RULES ---
        
        # 1. Open Window (09:30 - 10:00)
        if now_ny < time(10, 0, 0):
            if call_p > put_p * 2.0 and iv_rank < 30: return "BULLISH", True
            if put_p > call_p * 2.0 and iv_rank > 30: return "BEARISH", True

        # 2. Morning Window (10:00 - 10:30)
        elif now_ny < time(10, 30, 0):
            if put_p > call_p * 2.0 and atm_iv > 0.15 and net_gex > -2e9: return "BEARISH", True
            if call_p > put_p * 2.0 and iv_rank < 30 and sweep > 0.10: return "BULLISH", True

        # 3. Pre-Lunch Window (10:30 - 11:00)
        elif now_ny < time(11, 0, 0):
            if put_p > call_p * 2.0 and iv_rank > 30: return "BEARISH", True
            if call_p > put_p * 2.0 and iv_rank < 30: return "BULLISH", True

        # 4. Lunch Sniper (11:30 - 12:00)
        elif time(11, 30, 0) <= now_ny < time(12, 0, 0):
            if put_p > call_p * 2.0 and net_gex < -1e9 and iv_rank > 30: return "BEARISH", True
            if call_p > put_p * 2.0 and net_gex < -1e9: return "BULLISH", True

        return None, False

    async def calculate_hybrid_validation(self, df, symbol):
        try:
            latest_df = df.tail(self.max_buffer)
            features = latest_df.select([
                (pl.arange(0, pl.count()) / 100.0).alias("time_rel"),
                (pl.col("premium").clip(1).log10()).alias("log_premium"),
                pl.col("delta").fill_null(0.0),
                pl.col("gamma").fill_null(0.0),
                (pl.when(pl.col("side") == "C").then(1.0).otherwise(-1.0)).alias("side_val"),
                (pl.when(pl.col("aggressor") == "A").then(1.0).when(pl.col("aggressor") == "B").then(-1.0).otherwise(0.0)).alias("aggressor_val"),
                pl.col("is_sweep").cast(pl.Float32).alias("sweep_val")
            ])
            seq = features.to_numpy().astype(np.float32)
            if len(seq) < 100:
                seq = np.vstack([np.zeros((100 - len(seq), 7), dtype=np.float32), seq])
            tensor_seq = seq.transpose(1, 0).reshape(1, 7, 100)
            
            iv_rank = float(await self.redis.get(f"stats:{symbol}:iv_rank") or 50.0)
            net_gex = float(await self.redis.get(f"stats:{symbol}:net_gex") or 0.0)
            context_scaled = (np.array([[iv_rank, net_gex]]) - self.scaler_mean) / self.scaler_scale
            
            logits = self.v6_hybrid.run(None, {"trades": tensor_seq, "context": context_scaled.astype(np.float32)})[0]
            prob_bet = np.exp(logits[0, 1]) / np.sum(np.exp(logits[0]))
            return ("BET", prob_bet) if prob_bet > 0.45 else ("PASS", prob_bet)
        except Exception as e:
            print(f"AI Error: {e}"); return ("PASS", 0.0)

if __name__ == "__main__":
    from datetime import time # Import for NY time comparison
    nexus = SigmatiqNexus()
    asyncio.run(nexus.run())
