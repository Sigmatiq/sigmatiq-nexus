from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import msgpack
import numpy as np
import onnxruntime as ort
import polars as pl
import redis.asyncio as redis
from redis.asyncio.cluster import RedisCluster

# --- CONFIGURATION ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
REDIS_CLUSTER = os.environ.get("NEXUS_REDIS_CLUSTER", "false").strip().lower() == "true"
SYMBOLS = {s.strip().upper() for s in os.environ.get("NEXUS_SYMBOLS", "SPY").split(",") if s.strip()}
INPUT_STREAM = os.environ.get("NEXUS_INPUT_STREAM")
FIRST_TRIGGER_SCOPE = os.environ.get("NEXUS_FIRST_TRIGGER_SCOPE", "symbol").strip().lower()
MIN_WINDOW_PREMIUM = float(os.environ.get("NEXUS_MIN_WINDOW_PREMIUM", "200000"))
SIDE_DOMINANCE = float(os.environ.get("NEXUS_SIDE_DOMINANCE", "2.0"))

# Context keys are configurable because producer naming can drift between live stacks.
IV_RANK_KEY_TEMPLATE = os.environ.get("NEXUS_IV_RANK_KEY", "stats:{symbol}:iv_rank")
ATM_IV_KEY_TEMPLATE = os.environ.get("NEXUS_ATM_IV_KEY", "stats:{symbol}:atm_iv")
NET_GEX_KEY_TEMPLATE = os.environ.get("NEXUS_NET_GEX_KEY", "stats:{symbol}:net_gex")
IV_SURFACE_KEY_TEMPLATE = os.environ.get("NEXUS_IV_SURFACE_KEY", "options:live:iv_surface:{symbol}")
VRP_KEY_TEMPLATE = os.environ.get("NEXUS_VRP_KEY", "options:live:vrp:{symbol}")
GEX_KEY_TEMPLATE = os.environ.get("NEXUS_GEX_KEY", "options:live:gex:{symbol}")

MODEL_V6_HYBRID = os.environ.get("NEXUS_HYBRID_MODEL", "models/hybrid_spy_v6.onnx")
SCALER_V6_PATH = os.environ.get("NEXUS_HYBRID_SCALER", "models/hybrid_scaler_v6.npz")

NY = ZoneInfo("America/New_York")

# Decision slots evaluate completed windows. This matches the research scripts.
DECISION_SLOTS = [
    {"entry": time(10, 0), "end": time(10, 30), "window_start": time(9, 30), "window_end": time(10, 0), "entry_label": "10:00"},
    {"entry": time(10, 30), "end": time(11, 0), "window_start": time(10, 0), "window_end": time(10, 30), "entry_label": "10:30"},
    {"entry": time(11, 0), "end": time(11, 30), "window_start": time(10, 30), "window_end": time(11, 0), "entry_label": "11:00"},
    {"entry": time(12, 0), "end": time(12, 30), "window_start": time(11, 30), "window_end": time(12, 0), "entry_label": "12:00"},
]


def parse_event_datetime(payload: dict) -> datetime:
    raw = payload.get("ts_utc") or payload.get("timestamp")
    if not raw:
        return datetime.now(timezone.utc)
    if isinstance(raw, datetime):
        dt = raw
    else:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def input_streams() -> dict[str, str]:
    if INPUT_STREAM:
        return {INPUT_STREAM: "$"}
    return {f"md:{symbol}:options:trades": "$" for symbol in sorted(SYMBOLS)}


def _option_side_from_raw_symbol(raw_symbol: str | None) -> str | None:
    if not raw_symbol:
        return None
    compact = str(raw_symbol).replace(" ", "").upper()
    if len(compact) >= 9 and compact[-9] in {"C", "P"}:
        return compact[-9]
    for marker in ("C", "P"):
        if marker in compact[-10:]:
            return marker
    return None


def normalize_trade_payload(payload: dict) -> dict:
    raw_symbol = payload.get("raw_symbol") or payload.get("rawSymbol")
    symbol = payload.get("symbol") or payload.get("underlying")
    price = float(payload.get("price") or 0.0)
    size = float(payload.get("size") or payload.get("contracts") or 0.0)
    ts_utc = payload.get("ts_utc") or payload.get("timestamp")
    ts_event_ns = payload.get("ts_event_ns")
    if not ts_utc and ts_event_ns:
        ts_utc = datetime.fromtimestamp(int(ts_event_ns) / 1_000_000_000, tz=timezone.utc).isoformat()

    return {
        **payload,
        "symbol": str(symbol or "").strip().upper(),
        "raw_symbol": raw_symbol,
        "ts_utc": ts_utc,
        "side": str(payload.get("side") or _option_side_from_raw_symbol(raw_symbol) or "").strip().upper(),
        "premium": float(payload.get("premium") or price * size * 100.0),
        "is_sweep": bool(payload.get("is_sweep") or payload.get("isSweep") or False),
        "aggressor": str(payload.get("aggressor") or payload.get("trade_side") or "").strip().upper(),
    }


def decode_stream_entry(data: dict) -> dict:
    if "payload" in data or b"payload" in data:
        raw = data.get("payload") or data.get(b"payload")
        payload = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode("utf-8"))
        return normalize_trade_payload(payload)
    if "data" in data or b"data" in data:
        raw = data.get("data") or data.get(b"data")
        payload = msgpack.unpackb(raw, raw=False)
        return normalize_trade_payload(payload)
    return normalize_trade_payload(data)


def ny_session_date(dt_utc: datetime):
    return dt_utc.astimezone(NY).date()


def decision_slot(dt_utc: datetime) -> dict | None:
    t = dt_utc.astimezone(NY).time()
    for slot in DECISION_SLOTS:
        if slot["entry"] <= t < slot["end"]:
            return slot
    return None


def signal_key(session_date, symbol: str, strategy: str) -> str:
    if FIRST_TRIGGER_SCOPE == "strategy":
        return f"{session_date}:{symbol}:{strategy}"
    return f"{session_date}:{symbol}"


def _parse_df_ts_expr() -> pl.Expr:
    return pl.col("ts_utc").str.to_datetime(strict=False, time_zone="UTC")


def window_df_for_slot(df: pl.DataFrame, slot: dict) -> pl.DataFrame:
    if df.is_empty() or "ts_utc" not in df.columns:
        return df.clear()
    if df.schema["ts_utc"].is_temporal():
        ts_expr = pl.col("ts_utc")
    else:
        ts_expr = _parse_df_ts_expr()
    with_ts = df.with_columns(ts_expr.alias("_dt_utc"))
    with_ts = with_ts.with_columns(pl.col("_dt_utc").dt.convert_time_zone("America/New_York").dt.time().alias("_time_ny"))
    return with_ts.filter((pl.col("_time_ny") >= slot["window_start"]) & (pl.col("_time_ny") < slot["window_end"]))


def window_stats(df: pl.DataFrame) -> dict:
    if df.is_empty():
        return {"total_p": 0.0, "call_p": 0.0, "put_p": 0.0, "sweep": 0.0}
    stats = df.select([
        pl.col("premium").cast(pl.Float64, strict=False).fill_null(0).sum().alias("total_p"),
        pl.col("premium").cast(pl.Float64, strict=False).fill_null(0).filter(pl.col("side").cast(pl.Utf8).str.to_uppercase() == "C").sum().alias("call_p"),
        pl.col("premium").cast(pl.Float64, strict=False).fill_null(0).filter(pl.col("side").cast(pl.Utf8).str.to_uppercase() == "P").sum().alias("put_p"),
        pl.col("is_sweep").cast(pl.Float64, strict=False).fill_null(0).mean().alias("sweep"),
    ])
    return {k: float(stats[0, k] or 0.0) for k in ["total_p", "call_p", "put_p", "sweep"]}


def dominant_side(stats: dict) -> str | None:
    if stats["call_p"] > stats["put_p"] * SIDE_DOMINANCE:
        return "C"
    if stats["put_p"] > stats["call_p"] * SIDE_DOMINANCE:
        return "P"
    return None


class SigmatiqNexus:
    def __init__(self):
        self.buffers = {}
        self.max_buffer = 5000

        print("Loading AI Brains (ONNX)...")
        self.v6_hybrid = ort.InferenceSession(MODEL_V6_HYBRID)
        scaler_data = np.load(SCALER_V6_PATH)
        self.scaler_mean = scaler_data["mean"]
        self.scaler_scale = scaler_data["scale"]

        self.last_reset_session_date = ny_session_date(datetime.now(timezone.utc))
        self.signaled_today = set()
        self.redis = None

    async def connect(self):
        if REDIS_CLUSTER:
            self.redis = RedisCluster.from_url(REDIS_URL, decode_responses=False, ssl_cert_reqs=None)
        else:
            self.redis = await redis.from_url(REDIS_URL, decode_responses=False)
        print(f"Connected to Redis at {REDIS_URL}")

    async def run(self):
        if not self.redis:
            await self.connect()
        streams = input_streams()
        print(f"Nexus starting. Subscribing to {', '.join(streams.keys())}...")

        while True:
            try:
                replies = await self.redis.xread(streams, count=10, block=1000)
                for stream, messages in replies:
                    stream_name = stream.decode("utf-8") if isinstance(stream, bytes) else stream
                    for msg_id, data in messages:
                        streams[stream_name] = msg_id
                        await self.process_message(data)
            except Exception as e:
                print(f"Error in main loop: {e}")
                await asyncio.sleep(1)

    def reset_if_new_session(self, event_dt_utc: datetime):
        current_session_date = ny_session_date(event_dt_utc)
        if current_session_date > self.last_reset_session_date:
            print(f"New NY trading session: {current_session_date}. Resetting first-trigger state.")
            self.signaled_today.clear()
            self.last_reset_session_date = current_session_date

    async def process_message(self, data):
        try:
            payload = decode_stream_entry(data)
            symbol = str(payload["symbol"]).strip().upper()
            if symbol not in SYMBOLS:
                return

            event_dt_utc = parse_event_datetime(payload)
            self.reset_if_new_session(event_dt_utc)

            if symbol not in self.buffers:
                self.buffers[symbol] = deque(maxlen=self.max_buffer)
            self.buffers[symbol].append(payload)

            slot = decision_slot(event_dt_utc)
            if slot:
                await self.evaluate_strategy(symbol, slot, event_dt_utc)
        except Exception as e:
            print(f"Failed to process: {e}")

    async def evaluate_strategy(self, symbol, slot: dict, event_dt_utc: datetime):
        session_date = ny_session_date(event_dt_utc)
        if signal_key(session_date, symbol, "*") in self.signaled_today:
            return

        trades_df = pl.DataFrame(list(self.buffers[symbol]))
        slot_df = window_df_for_slot(trades_df, slot)
        if slot_df.height == 0:
            return

        # First-trigger wins must be deterministic; parallel final publishes can race.
        await self.evaluate_low_sweep_core(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*"):
            await self.evaluate_hybrid_alpha(slot_df, symbol, slot, session_date)

    def already_signaled(self, session_date, symbol: str, strategy: str) -> bool:
        return signal_key(session_date, symbol, strategy) in self.signaled_today or signal_key(session_date, symbol, "*") in self.signaled_today

    async def evaluate_hybrid_alpha(self, trades_df, symbol, slot: dict, session_date):
        strategy = "spy_sharpened_alpha"
        if self.already_signaled(session_date, symbol, strategy):
            return

        sentiment, stage1_valid = await self.calculate_hybrid_heuristic(trades_df, symbol, slot)
        if stage1_valid:
            await self._publish_intermediate(strategy, symbol, sentiment, slot)
            decision, prob = await self.calculate_hybrid_validation(trades_df, symbol)
            if decision == "BET":
                await self._publish_final(strategy, symbol, sentiment, prob, session_date, slot)

    async def evaluate_low_sweep_core(self, trades_df, symbol, slot: dict, session_date):
        strategy = "spy_low_sweep_core"
        if self.already_signaled(session_date, symbol, strategy):
            return

        sentiment, stage1_valid = await self.calculate_low_sweep_heuristic(trades_df, slot)
        if stage1_valid:
            await self._publish_intermediate(strategy, symbol, sentiment, slot)
            await self._publish_final(strategy, symbol, sentiment, 1.0, session_date, slot)

    async def get_context(self, symbol: str) -> tuple[float, float, float]:
        iv_rank_raw = await self.redis.get(IV_RANK_KEY_TEMPLATE.format(symbol=symbol))
        atm_iv_raw = await self.redis.get(ATM_IV_KEY_TEMPLATE.format(symbol=symbol))
        net_gex_raw = await self.redis.get(NET_GEX_KEY_TEMPLATE.format(symbol=symbol))

        iv_rank = float(iv_rank_raw or 50.0)
        atm_iv = float(atm_iv_raw or 0.15)
        net_gex = float(net_gex_raw or 0.0)

        if not atm_iv_raw:
            atm_iv = await self._context_float(IV_SURFACE_KEY_TEMPLATE.format(symbol=symbol), "atmIv", atm_iv)
        if not net_gex_raw:
            net_gex = await self._context_float(GEX_KEY_TEMPLATE.format(symbol=symbol), "netGex", net_gex)
        if not iv_rank_raw:
            iv_rank = await self._iv_rank_from_vrp(symbol, iv_rank)
        return iv_rank, atm_iv, net_gex

    async def _context_float(self, key: str, field: str, default: float) -> float:
        raw = await self.redis.get(key)
        if not raw:
            return default
        try:
            payload = json.loads(raw)
            value = payload.get(field)
            return float(value) if value is not None else default
        except Exception:
            return default

    async def _iv_rank_from_vrp(self, symbol: str, default: float) -> float:
        raw = await self.redis.get(VRP_KEY_TEMPLATE.format(symbol=symbol))
        if not raw:
            return default
        try:
            payload = json.loads(raw)
            if payload.get("ivRank") is not None:
                return float(payload["ivRank"])
            regime = str(payload.get("vrpRegime") or "").lower()
            return {"cheap": 20.0, "fair": 50.0, "moderate": 60.0, "rich": 80.0, "elevated": 90.0}.get(regime, default)
        except Exception:
            return default

    async def calculate_hybrid_heuristic(self, df, symbol, slot: dict):
        iv_rank, atm_iv, net_gex = await self.get_context(symbol)
        stats = window_stats(df)
        side = dominant_side(stats)
        if stats["total_p"] < MIN_WINDOW_PREMIUM or side is None:
            return None, False

        entry = slot["entry_label"]
        if entry == "10:00":
            if side == "C" and iv_rank < 30:
                return "BULLISH", True
            if side == "P" and iv_rank > 30:
                return "BEARISH", True
        elif entry == "10:30":
            if side == "P" and atm_iv > 0.15 and net_gex > -2e9:
                return "BEARISH", True
            if side == "C" and iv_rank < 30 and stats["sweep"] > 0.10:
                return "BULLISH", True
        elif entry == "11:00":
            if side == "P" and iv_rank > 30:
                return "BEARISH", True
            if side == "C" and iv_rank < 30:
                return "BULLISH", True
        elif entry == "12:00" and net_gex < -1e9:
            return ("BULLISH", True) if side == "C" else ("BEARISH", True)

        return None, False

    async def calculate_low_sweep_heuristic(self, df, slot: dict):
        stats = window_stats(df)
        side = dominant_side(stats)
        if stats["total_p"] < MIN_WINDOW_PREMIUM or side is None:
            return None, False
        if stats["sweep"] > 0.10:
            return None, False

        # Research candidate: 10:00 calls, 10:30 calls, and 10:30 puts only.
        if slot["entry_label"] == "10:00" and side == "C":
            return "BULLISH", True
        if slot["entry_label"] == "10:30" and side == "C":
            return "BULLISH", True
        if slot["entry_label"] == "10:30" and side == "P":
            return "BEARISH", True
        return None, False

    async def calculate_hybrid_validation(self, df, symbol):
        try:
            latest_df = df.tail(100)
            features = latest_df.select([
                (pl.arange(0, pl.len()) / 100.0).alias("time_rel"),
                pl.col("premium").cast(pl.Float64, strict=False).clip(1).log10().alias("log_premium"),
                pl.col("delta").cast(pl.Float64, strict=False).fill_null(0.0),
                pl.col("gamma").cast(pl.Float64, strict=False).fill_null(0.0),
                pl.when(pl.col("side").cast(pl.Utf8).str.to_uppercase() == "C").then(1.0).otherwise(-1.0).alias("side_val"),
                pl.when(pl.col("aggressor") == "A").then(1.0).when(pl.col("aggressor") == "B").then(-1.0).otherwise(0.0).alias("aggressor_val"),
                pl.col("is_sweep").cast(pl.Float32, strict=False).fill_null(0.0).alias("sweep_val"),
            ])
            seq = features.to_numpy().astype(np.float32)
            if len(seq) < 100:
                seq = np.vstack([np.zeros((100 - len(seq), 7), dtype=np.float32), seq])
            tensor_seq = seq.transpose(1, 0).reshape(1, 7, 100)

            iv_rank, _, net_gex = await self.get_context(symbol)
            context_scaled = (np.array([[iv_rank, net_gex]]) - self.scaler_mean) / self.scaler_scale

            logits = self.v6_hybrid.run(None, {"trades": tensor_seq, "context": context_scaled.astype(np.float32)})[0]
            exp_logits = np.exp(logits[0] - np.max(logits[0]))
            prob_bet = exp_logits[1] / np.sum(exp_logits)
            return ("BET", prob_bet) if prob_bet > 0.45 else ("PASS", prob_bet)
        except Exception as e:
            print(f"AI Error: {e}")
            return "PASS", 0.0

    async def _publish_intermediate(self, strategy, symbol, sentiment, slot: dict):
        msg = {
            "strategy": strategy,
            "symbol": symbol,
            "stage": 1,
            "sentiment": sentiment,
            "entry_time": slot["entry_label"],
            "window_start": slot["window_start"].isoformat(),
            "window_end": slot["window_end"].isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.redis.publish(f"signal:intermediate:{strategy}", json.dumps(msg))

    async def _publish_final(self, strategy, symbol, sentiment, confidence, session_date, slot: dict):
        msg = {
            "strategy": strategy,
            "symbol": symbol,
            "stage": 2,
            "decision": "BET",
            "sentiment": sentiment,
            "confidence": float(confidence),
            "entry_time": slot["entry_label"],
            "window_start": slot["window_start"].isoformat(),
            "window_end": slot["window_end"].isoformat(),
            "session_date": str(session_date),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.signaled_today.add(signal_key(session_date, symbol, strategy))
        if FIRST_TRIGGER_SCOPE == "symbol":
            self.signaled_today.add(signal_key(session_date, symbol, "*"))
        await self.redis.set(f"nexus_live_overlay:{symbol}", json.dumps(msg))
        await self.redis.publish("nexus_live_overlay:updates", symbol)
        print(f"[BET] Signal generated for {symbol} via {strategy} (Conf: {confidence:.4f})")


def main():
    nexus = SigmatiqNexus()
    asyncio.run(nexus.run())


if __name__ == "__main__":
    main()
