
import asyncio
import os
import json
import numpy as np
import polars as pl
import redis.asyncio as redis
import onnxruntime as ort
from datetime import datetime, timezone, time
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
        
        print("Loading AI Brains (ONNX)...")
        # 1. Hybrid Brain (v6)
        self.v6_hybrid = ort.InferenceSession(MODEL_V6_HYBRID)
        scaler_data = np.load(SCALER_V6_PATH)
        self.scaler_mean = scaler_data['mean']
        self.scaler_scale = scaler_data['scale']
        
        # State: One Signal Total per Day (across all strategies)
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
        now_ny = datetime.now(self.tz_ny).time()
        
        # --- PARALLEL EVALUATION OF STRATEGIES ---
        # 1. Strategy: Sharpened Hybrid Alpha (v6)
        asyncio.create_task(self.evaluate_hybrid_alpha(trades_df, symbol, now_ny))
        
        # 2. Strategy: Low-Sweep Core (Strategy #2 Leader)
        asyncio.create_task(self.evaluate_low_sweep_core(trades_df, symbol, now_ny))

    async def evaluate_hybrid_alpha(self, trades_df, symbol, now_ny):
        if symbol in self.signaled_today: return
        
        sentiment, stage1_valid = await self.calculate_hybrid_heuristic(trades_df, symbol, now_ny)
        if stage1_valid:
            # Event 1: Intermediate
            await self._publish_intermediate("spy_sharpened_alpha", symbol, sentiment)
            
            # Event 2: Final
            decision, prob = await self.calculate_hybrid_validation(trades_df, symbol)
            if decision == "BET":
                await self._publish_final("spy_sharpened_alpha", symbol, sentiment, prob)

    async def evaluate_low_sweep_core(self, trades_df, symbol, now_ny):
        if symbol in self.signaled_today: return
        
        # Strategy #2 Heuristic: sweep_pct <= 0.10
        sentiment, stage1_valid = await self.calculate_low_sweep_heuristic(trades_df, now_ny)
        if stage1_valid:
            # This is a pure-heuristic strategy (Stage 1 is the signal)
            await self._publish_intermediate("spy_low_sweep_core", symbol, sentiment)
            # For Strategy 2, Stage 1 meeting the rules is the BET
            await self._publish_final("spy_low_sweep_core", symbol, sentiment, 1.0)

    async def calculate_hybrid_heuristic(self, df, symbol, now_ny):
        # Fetch Context
        iv_rank = float(await self.redis.get(f"stats:{symbol}:iv_rank") or 50.0)
        atm_iv = float(await self.redis.get(f"stats:{symbol}:atm_iv") or 15.0)
        net_gex = float(await self.redis.get(f"stats:{symbol}:net_gex") or 0.0)
        
        stats = df.select([
            pl.col("premium").sum().alias("total_p"),
            (pl.col("premium").filter(pl.col("side") == "C").sum()).alias("call_p"),
            (pl.col("premium").filter(pl.col("side") == "P").sum()).alias("put_p"),
            (pl.col("is_sweep").mean()).alias("sweep")
        ])
        
        if stats[0, "total_p"] < 200000: return None, False

        # Windows (As per Backtest Portfolio)
        if now_ny < time(10, 30, 0): # 10:00 & 10:30 windows
            if stats[0, "put_p"] > stats[0, "call_p"] * 2 and atm_iv > 0.15 and net_gex > -2e9: return "BEARISH", True
            if stats[0, "call_p"] > stats[0, "put_p"] * 2 and iv_rank < 30 and stats[0, "sweep"] > 0.10: return "BULLISH", True
        elif now_ny < time(11, 0, 0): # 11:00 window
            if stats[0, "put_p"] > stats[0, "call_p"] * 2 and iv_rank > 30: return "BEARISH", True
            if stats[0, "call_p"] > stats[0, "put_p"] * 2 and iv_rank < 30: return "BULLISH", True
        elif time(11, 30, 0) <= now_ny < time(12, 0, 0): # Lunch
            if net_gex < -1e9: return ("BEARISH", True) if stats[0, "put_p"] > stats[0, "call_p"] else ("BULLISH", True)
            
        return None, False

    async def calculate_low_sweep_heuristic(self, df, now_ny):
        stats = df.select([
            pl.col("premium").sum().alias("total_p"),
            (pl.col("premium").filter(pl.col("side") == "C").sum()).alias("call_p"),
            (pl.col("premium").filter(pl.col("side") == "P").sum()).alias("put_p"),
            (pl.col("is_sweep").mean()).alias("sweep")
        ])
        
        if stats[0, "total_p"] < 200000: return None, False
        if stats[0, "sweep"] > 0.10: return None, False # MUST be low-sweep
        
        # 10:00 window: Calls only
        if now_ny < time(10, 0, 0):
            if stats[0, "call_p"] > stats[0, "put_p"] * 2: return "BULLISH", True
        # 10:30 window: Both
        elif now_ny < time(10, 30, 0):
            if stats[0, "call_p"] > stats[0, "put_p"] * 2: return "BULLISH", True
            if stats[0, "put_p"] > stats[0, "call_p"] * 2: return "BEARISH", True
            
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

    async def _publish_intermediate(self, strategy, symbol, sentiment):
        msg = {"strategy": strategy, "symbol": symbol, "stage": 1, "sentiment": sentiment, "timestamp": datetime.now(timezone.utc).isoformat()}
        await self.redis.publish(f"signal:intermediate:{strategy}", json.dumps(msg))

    async def _publish_final(self, strategy, symbol, sentiment, confidence):
        msg = {"strategy": strategy, "symbol": symbol, "stage": 2, "decision": "BET", "sentiment": sentiment, "confidence": float(confidence), "timestamp": datetime.now(timezone.utc).isoformat()}
        self.signaled_today.add(symbol)
        await self.redis.set(f"nexus_live_overlay:{symbol}", json.dumps(msg))
        await self.redis.publish("nexus_live_overlay:updates", symbol)
        print(f"🚀 [BET] Signal generated for {symbol} via {strategy} (Conf: {confidence:.4f})")

if __name__ == "__main__":
    nexus = SigmatiqNexus()
    asyncio.run(nexus.run())
