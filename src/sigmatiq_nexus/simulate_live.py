
import asyncio
import json
import redis.asyncio as redis
import pandas as pd
import time
from datetime import datetime, timezone

REDIS_URL = "redis://localhost:6379/0"
STREAM_KEY = "md:options:trades"

async def simulate_live_flow():
    r = await redis.from_url(REDIS_URL)
    
    # 1. Load a few real trades from our backtest results as a sample
    # (Using a day we know had institutional activity)
    sample_path = "backtest-results/SPY/tier1/schema=opra_open30_unusual_trades_1d/date=2025-05-01/SPY.parquet"
    df = pd.read_parquet(sample_path).head(100)
    
    print(f"Starting simulation: Pushing {len(df)} trades to {STREAM_KEY}...")
    
    for _, row in df.iterrows():
        # Create a payload that matches what the C# Ingestion worker would send
        payload = {
            "symbol": row['symbol'],
            "price": float(row['price']),
            "size": int(row['contracts']),
            "premium": float(row['premium']),
            "side": row['side'],
            "aggressor": row['aggressor'],
            "is_sweep": bool(row['is_sweep']),
            "ts_utc": row['ts_utc'].isoformat(),
            "delta": float(row['delta']) if pd.notna(row['delta']) else 0.0,
            "gamma": float(row['gamma']) if pd.notna(row['gamma']) else 0.0
        }
        
        # Add to Redis Stream
        await r.xadd(STREAM_KEY, {"payload": json.dumps(payload)})
        
        # Simulate real-time arrival
        await asyncio.sleep(0.1) 
        
    print("Simulation complete. Check Nexus logs for signals.")

if __name__ == "__main__":
    asyncio.run(simulate_live_flow())
