from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, time, timezone
from urllib.parse import quote, urlparse
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

IV_RANK_KEY_TEMPLATE = os.environ.get("NEXUS_IV_RANK_KEY", "stats:{symbol}:iv_rank")
ATM_IV_KEY_TEMPLATE = os.environ.get("NEXUS_ATM_IV_KEY", "stats:{symbol}:atm_iv")
NET_GEX_KEY_TEMPLATE = os.environ.get("NEXUS_NET_GEX_KEY", "stats:{symbol}:net_gex")
IV_SURFACE_KEY_TEMPLATE = os.environ.get("NEXUS_IV_SURFACE_KEY", "options:live:iv_surface:{symbol}")
VRP_KEY_TEMPLATE = os.environ.get("NEXUS_VRP_KEY", "options:live:vrp:{symbol}")
GEX_KEY_TEMPLATE = os.environ.get("NEXUS_GEX_KEY", "options:live:gex:{symbol}")

MODEL_V6_PATH = os.environ.get("NEXUS_V6_MODEL", "models/hybrid_spy_v6.onnx")
SCALER_V6_PATH = os.environ.get("NEXUS_V6_SCALER", "models/hybrid_scaler_v6.npz")
MODEL_V10_PATH = os.environ.get("NEXUS_V10_MODEL", "models/alpha_fusion_spy_v10.onnx")
SCALER_P_V10_PATH = os.environ.get("NEXUS_V10_PRICE_SCALER", "models/scaler_p_v10.npz")
SCALER_S_V10_PATH = os.environ.get("NEXUS_V10_CONTEXT_SCALER", "models/scaler_s_v10.npz")

NY = ZoneInfo("America/New_York")
DECISION_SLOTS = [
    {"entry": time(10, 0), "end": time(10, 30), "window_start": time(9, 30), "window_end": time(10, 0), "entry_label": "10:00"},
    {"entry": time(10, 30), "end": time(11, 0), "window_start": time(10, 0), "window_end": time(10, 30), "entry_label": "10:30"},
    {"entry": time(11, 0), "end": time(11, 30), "window_start": time(10, 30), "window_end": time(11, 0), "entry_label": "11:00"},
    {"entry": time(12, 0), "end": time(12, 30), "window_start": time(11, 30), "window_end": time(12, 0), "entry_label": "12:00"},
]


def parse_event_datetime(payload: dict) -> datetime:
    raw = payload.get("ts_utc") or payload.get("timestamp")
    if not raw and payload.get("ts_event_ns") is not None:
        raw = datetime.fromtimestamp(int(payload["ts_event_ns"]) / 1_000_000_000, tz=timezone.utc).isoformat()
    if not raw:
        return datetime.now(timezone.utc)
    if isinstance(raw, datetime):
        dt = raw
    else:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ny_session_date(dt_utc: datetime):
    return dt_utc.astimezone(NY).date()


def decision_slot(dt_utc: datetime) -> dict | None:
    t = dt_utc.astimezone(NY).time()
    for slot in DECISION_SLOTS:
        if slot["entry"] <= t < slot["end"]:
            return slot
    return None


def input_streams() -> dict[str, str]:
    if INPUT_STREAM:
        return {INPUT_STREAM: "$"}
    return {f"md:{symbol}:options:trades": "$" for symbol in sorted(SYMBOLS)}


def signal_key(session_date, symbol: str, strategy: str) -> str:
    if FIRST_TRIGGER_SCOPE == "strategy":
        return f"{session_date}:{symbol}:{strategy}"
    return f"{session_date}:{symbol}"


def _option_side_from_raw_symbol(raw_symbol: str | None) -> str | None:
    if not raw_symbol:
        return None
    compact = str(raw_symbol).replace(" ", "").upper()
    if len(compact) >= 9 and compact[-9] in {"C", "P"}:
        return compact[-9]
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
        "delta": float(payload.get("delta") or 0.0),
        "gamma": float(payload.get("gamma") or 0.0),
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


def window_df_for_slot(df: pl.DataFrame, slot: dict) -> pl.DataFrame:
    if df.is_empty() or "ts_utc" not in df.columns:
        return df.clear()
    ts_expr = pl.col("ts_utc") if df.schema["ts_utc"].is_temporal() else pl.col("ts_utc").str.to_datetime(strict=False, time_zone="UTC")
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

        print("Loading Dual-Brain AI (SPY only)...")
        self.session_v6 = ort.InferenceSession(MODEL_V6_PATH)
        scaler_v6 = np.load(SCALER_V6_PATH)
        self.v6_mean = scaler_v6["mean"]
        self.v6_scale = scaler_v6["scale"]

        self.session_v10 = ort.InferenceSession(MODEL_V10_PATH)
        scaler_p = np.load(SCALER_P_V10_PATH)
        self.v10_p_mean = scaler_p["mean"]
        self.v10_p_scale = scaler_p["scale"]
        scaler_s = np.load(SCALER_S_V10_PATH)
        self.v10_s_mean = scaler_s["mean"]
        self.v10_s_scale = scaler_s["scale"]

        self.last_reset_session_date = ny_session_date(datetime.now(timezone.utc))
        self.signaled_today = set()
        self.redis = None

    async def connect(self):
        if REDIS_CLUSTER:
            self.redis = self._connect_cluster(REDIS_URL)
        else:
            self.redis = await redis.from_url(self._redis_url(REDIS_URL), decode_responses=False)
        print("Connected to Redis")

    def _connect_cluster(self, value: str):
        if value.startswith("redis://") or value.startswith("rediss://"):
            return RedisCluster.from_url(value, decode_responses=False, ssl_cert_reqs=None)
        if ",password=" in value:
            host, rest = value.split(",", 1)
            password = rest.split("password=", 1)[1].split(",", 1)[0]
            hostname, port = host.rsplit(":", 1)
            return RedisCluster(host=hostname, port=int(port), password=password, ssl=True, ssl_cert_reqs=None, decode_responses=False)
        parsed = urlparse(value)
        return RedisCluster(host=parsed.hostname, port=parsed.port or 6379, password=parsed.password, ssl=parsed.scheme == "rediss", ssl_cert_reqs=None, decode_responses=False)

    def _redis_url(self, value: str) -> str:
        if value.startswith("redis://") or value.startswith("rediss://"):
            return value
        if ",password=" not in value:
            return value
        host, rest = value.split(",", 1)
        password = rest.split("password=", 1)[1].split(",", 1)[0]
        scheme = "rediss" if ":6380" in host or ":10000" in host or "ssl=True" in value else "redis"
        return f"{scheme}://:{quote(password, safe='')}@{host}/0"

    async def run(self):
        if not self.redis:
            await self.connect()
        streams = input_streams()
        print(f"Nexus sniper started. Monitoring {', '.join(streams.keys())}.")
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
        slot_df = window_df_for_slot(pl.DataFrame(list(self.buffers[symbol])), slot)
        if slot_df.height == 0:
            return

        # Deterministic order: research low-sweep first, then v6 flow, then v10 momentum.
        await self.evaluate_low_sweep_core(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*"):
            await self.evaluate_flow_specialist(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*"):
            await self.evaluate_momentum_specialist(slot_df, symbol, slot, session_date)

    def already_signaled(self, session_date, symbol: str, strategy: str) -> bool:
        return signal_key(session_date, symbol, strategy) in self.signaled_today or signal_key(session_date, symbol, "*") in self.signaled_today

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
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(raw).get(field)
            return float(value) if value is not None else default
        except Exception:
            return default

    async def _iv_rank_from_vrp(self, symbol: str, default: float) -> float:
        raw = await self.redis.get(VRP_KEY_TEMPLATE.format(symbol=symbol))
        if not raw:
            return default
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if payload.get("ivRank") is not None:
                return float(payload["ivRank"])
            regime = str(payload.get("vrpRegime") or "").lower()
            return {"cheap": 20.0, "fair": 50.0, "moderate": 60.0, "rich": 80.0, "elevated": 90.0}.get(regime, default)
        except Exception:
            return default

    async def evaluate_low_sweep_core(self, df, symbol, slot: dict, session_date):
        strategy = "spy_low_sweep_core"
        if self.already_signaled(session_date, symbol, strategy):
            return
        sentiment, valid = await self.calculate_low_sweep_heuristic(df, slot)
        if valid:
            await self._publish_intermediate(strategy, symbol, sentiment, slot)
            await self._publish_final(strategy, symbol, sentiment, 1.0, session_date, slot)

    async def calculate_low_sweep_heuristic(self, df, slot: dict):
        stats = window_stats(df)
        side = dominant_side(stats)
        if stats["total_p"] < MIN_WINDOW_PREMIUM or side is None or stats["sweep"] > 0.10:
            return None, False
        if slot["entry_label"] == "10:00" and side == "C":
            return "BULLISH", True
        if slot["entry_label"] == "10:30" and side == "C":
            return "BULLISH", True
        if slot["entry_label"] == "10:30" and side == "P":
            return "BEARISH", True
        return None, False

    async def evaluate_flow_specialist(self, df, symbol, slot: dict, session_date):
        strategy = "spy_flow_specialist"
        if self.already_signaled(session_date, symbol, strategy):
            return
        sentiment, valid = await self.check_flow_heuristics(df, symbol, slot)
        if valid:
            await self._publish_intermediate(strategy, symbol, sentiment, slot)
            prob = await self.predict_v6(df, symbol)
            if prob > 0.45:
                await self._publish_final(strategy, symbol, sentiment, prob, session_date, slot)

    async def check_flow_heuristics(self, df, symbol, slot: dict):
        iv_rank, atm_iv, net_gex = await self.get_context(symbol)
        stats = window_stats(df)
        side = dominant_side(stats)
        if stats["total_p"] < MIN_WINDOW_PREMIUM or side is None:
            return None, False
        entry = slot["entry_label"]
        if entry in {"10:00", "10:30", "11:00"}:
            if side == "P" and atm_iv > 0.15 and net_gex > -2e9:
                return "BEARISH", True
            if side == "C" and iv_rank < 30 and stats["sweep"] > 0.10:
                return "BULLISH", True
        return None, False

    async def evaluate_momentum_specialist(self, df, symbol, slot: dict, session_date):
        strategy = "spy_momentum_specialist"
        if self.already_signaled(session_date, symbol, strategy):
            return
        sentiment, valid, p_feat = await self.check_momentum_heuristics(df, symbol)
        if valid:
            await self._publish_intermediate(strategy, symbol, sentiment, slot)
            prob = await self.predict_v10(df, symbol, p_feat)
            if prob > 0.55:
                await self._publish_final(strategy, symbol, sentiment, prob, session_date, slot)

    async def check_momentum_heuristics(self, df, symbol):
        if "underlying_mid" not in df.columns:
            return None, False, None
        iv_rank, _, _ = await self.get_context(symbol)
        if iv_rank >= 40:
            return None, False, None
        try:
            bars = df.with_columns(pl.col("ts_utc").str.to_datetime(strict=False, time_zone="UTC")).group_by_dynamic("ts_utc", every="1m").agg([
                pl.col("underlying_mid").cast(pl.Float64, strict=False).first().alias("o"),
                pl.col("underlying_mid").cast(pl.Float64, strict=False).last().alias("c"),
            ])
            if bars.height < 10:
                return None, False, None
            bars = bars.with_columns([(pl.col("c") > pl.col("o")).alias("bul"), (pl.col("c") < pl.col("o")).alias("ber")])
            bull_m = bars.select(pl.col("bul").sum()).item()
            bear_m = bars.select(pl.col("ber").sum()).item()
            persistence = (max(bull_m, bear_m) / (bull_m + bear_m + 1e-9)) * 100.0
            if abs(bull_m - bear_m) >= 5 and persistence > 50.0:
                p_feat = [float(bull_m), float(bear_m), float(persistence), 0.1]
                return ("BULLISH" if bull_m > bear_m else "BEARISH"), True, p_feat
        except Exception as e:
            print(f"Momentum calc error: {e}")
        return None, False, None

    async def predict_v6(self, df, symbol):
        tensor = self._prepare_seq(df)
        iv, _, gex = await self.get_context(symbol)
        ctx = (np.array([[iv, gex]]) - self.v6_mean) / self.v6_scale
        logits = self.session_v6.run(None, {"trades": tensor, "context": ctx.astype(np.float32)})[0]
        return self._prob_bet(logits)

    async def predict_v10(self, df, symbol, p_feat):
        tensor = self._prepare_seq(df)
        iv, atm, gex = await self.get_context(symbol)
        ctx = (np.array([[iv, atm, gex]]) - self.v10_s_mean) / self.v10_s_scale
        p_scaled = (np.array([p_feat]) - self.v10_p_mean) / self.v10_p_scale
        logits = self.session_v10.run(None, {"trades": tensor, "price_action": p_scaled.astype(np.float32), "context": ctx.astype(np.float32)})[0]
        return self._prob_bet(logits)

    def _prepare_seq(self, df):
        feats = df.tail(100).select([
            (pl.arange(0, pl.len()) / 100.0).alias("t"),
            pl.col("premium").cast(pl.Float64, strict=False).clip(1).log10().alias("lp"),
            pl.col("delta").cast(pl.Float64, strict=False).fill_null(0.0),
            pl.col("gamma").cast(pl.Float64, strict=False).fill_null(0.0),
            pl.when(pl.col("side").cast(pl.Utf8).str.to_uppercase() == "C").then(1.0).otherwise(-1.0).alias("s"),
            pl.when(pl.col("aggressor") == "A").then(1.0).when(pl.col("aggressor") == "B").then(-1.0).otherwise(0.0).alias("a"),
            pl.col("is_sweep").cast(pl.Float32, strict=False).fill_null(0.0).alias("sw"),
        ])
        seq = feats.to_numpy().astype(np.float32)
        if len(seq) < 100:
            seq = np.vstack([np.zeros((100 - len(seq), 7), dtype=np.float32), seq])
        return seq.transpose(1, 0).reshape(1, 7, 100)

    def _prob_bet(self, logits):
        exp_logits = np.exp(logits[0] - np.max(logits[0]))
        return float(exp_logits[1] / np.sum(exp_logits))

    async def _publish_intermediate(self, strategy, symbol, sentiment, slot: dict | None = None):
        msg = {"strategy": strategy, "symbol": symbol, "stage": 1, "sentiment": sentiment, "timestamp": datetime.now(timezone.utc).isoformat()}
        if slot:
            msg.update({"entry_time": slot["entry_label"], "window_start": slot["window_start"].isoformat(), "window_end": slot["window_end"].isoformat()})
        await self.redis.publish(f"signal:intermediate:{strategy}", json.dumps(msg))

    async def _publish_final(self, strategy, symbol, sentiment, confidence, session_date=None, slot: dict | None = None):
        msg = {"strategy": strategy, "symbol": symbol, "stage": 2, "decision": "BET", "sentiment": sentiment, "confidence": float(confidence), "timestamp": datetime.now(timezone.utc).isoformat()}
        if session_date:
            msg["session_date"] = str(session_date)
        if slot:
            msg.update({"entry_time": slot["entry_label"], "window_start": slot["window_start"].isoformat(), "window_end": slot["window_end"].isoformat()})
        key_date = session_date or ny_session_date(datetime.now(timezone.utc))
        self.signaled_today.add(signal_key(key_date, symbol, strategy))
        if FIRST_TRIGGER_SCOPE == "symbol":
            self.signaled_today.add(signal_key(key_date, symbol, "*"))
        await self.redis.set(f"nexus_live_overlay:{symbol}", json.dumps(msg))
        await self.redis.publish("nexus_live_overlay:updates", symbol)
        print(f"[BET] {strategy} for {symbol} (Conf: {confidence:.4f})")


def main():
    nexus = SigmatiqNexus()
    asyncio.run(nexus.run())


if __name__ == "__main__":
    main()
