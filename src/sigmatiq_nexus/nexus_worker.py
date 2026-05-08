from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ssl
from collections import deque
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import msgpack
import numpy as np
import onnxruntime as ort
import polars as pl
import redis.asyncio as redis
from redis.asyncio.cluster import RedisCluster

from sigmatiq_nexus import narratives
from sigmatiq_nexus import participant_flow as pf

# --- CONFIGURATION ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
REDIS_CLUSTER = os.environ.get("NEXUS_REDIS_CLUSTER", "false").strip().lower() == "true"
SYMBOLS = {s.strip().upper() for s in os.environ.get("NEXUS_SYMBOLS", "SPY,QQQ").split(",") if s.strip()}
INPUT_STREAM = os.environ.get("NEXUS_INPUT_STREAM")
STREAM_START_ID = os.environ.get("NEXUS_STREAM_START_ID", "0-0")
FIRST_TRIGGER_SCOPE = os.environ.get("NEXUS_FIRST_TRIGGER_SCOPE", "symbol").strip().lower()
GROUP_LOCK_STRATEGIES = {
    s.strip()
    for s in os.environ.get("NEXUS_GROUP_LOCK_STRATEGIES", "etf_confluence_sniper").split(",")
    if s.strip()
}
MIN_WINDOW_PREMIUM = float(os.environ.get("NEXUS_MIN_WINDOW_PREMIUM", "200000"))
SIDE_DOMINANCE = float(os.environ.get("NEXUS_SIDE_DOMINANCE", "2.0"))
OPEN_CALL_DOMINANCE = float(os.environ.get("NEXUS_OPEN_CALL_DOMINANCE", "1.5"))
LIVE_PERSISTENCE_EVENT_STREAM = os.environ.get("LIVE_PERSISTENCE_EVENT_STREAM", "live:persistence:events")
STREAM_OFFSET_KEY_TEMPLATE = os.environ.get("NEXUS_STREAM_OFFSET_KEY", "nexus:stream_offset:{stream}")
LOCK_TTL_SECONDS = int(os.environ.get("NEXUS_LOCK_TTL_SECONDS", str(60 * 60 * 8)))
ACTIVE_POSITION_TTL_SECONDS = int(os.environ.get("NEXUS_ACTIVE_POSITION_TTL_SECONDS", str(60 * 60 * 8)))
WINDOW_EVALUATION_GRACE_SECONDS = int(os.environ.get("NEXUS_WINDOW_EVALUATION_GRACE_SECONDS", "15"))

IV_RANK_KEY_TEMPLATE = os.environ.get("NEXUS_IV_RANK_KEY", "stats:{symbol}:iv_rank")
ATM_IV_KEY_TEMPLATE = os.environ.get("NEXUS_ATM_IV_KEY", "stats:{symbol}:atm_iv")
NET_GEX_KEY_TEMPLATE = os.environ.get("NEXUS_NET_GEX_KEY", "stats:{symbol}:net_gex")
IV_SURFACE_KEY_TEMPLATE = os.environ.get("NEXUS_IV_SURFACE_KEY", "options:live:iv_surface:{symbol}")
VRP_KEY_TEMPLATE = os.environ.get("NEXUS_VRP_KEY", "options:live:vrp:{symbol}")
GEX_KEY_TEMPLATE = os.environ.get("NEXUS_GEX_KEY", "options:live:gex:{symbol}")
EQUITY_CONTEXT_KEY_TEMPLATE = os.environ.get("NEXUS_EQUITY_CONTEXT_KEY", "equity:live:context:{symbol}")
CONTRACT_STATE_KEY_TEMPLATE = os.environ.get("NEXUS_CONTRACT_STATE_KEY", "options:live:contract_state:{raw_symbol}")
CONTRACT_TRADABILITY_KEY_TEMPLATE = os.environ.get("NEXUS_CONTRACT_TRADABILITY_KEY", "options:live:tradability:{raw_symbol}")
NEXUS_REQUIRE_CONTEXT_TIMESTAMPS = os.environ.get("NEXUS_REQUIRE_CONTEXT_TIMESTAMPS", "true").strip().lower() == "true"
VOL_CONTEXT_MAX_AGE_SECONDS = int(os.environ.get("NEXUS_VOL_CONTEXT_MAX_AGE_SECONDS", "120"))
GEX_CONTEXT_MAX_AGE_SECONDS = int(os.environ.get("NEXUS_GEX_CONTEXT_MAX_AGE_SECONDS", "120"))
UNDERLYING_MAX_AGE_SECONDS = int(os.environ.get("NEXUS_UNDERLYING_MAX_AGE_SECONDS", "5"))
OPTION_QUOTE_MAX_AGE_SECONDS = int(os.environ.get("NEXUS_OPTION_QUOTE_MAX_AGE_SECONDS", "5"))
GREEK_MAX_AGE_SECONDS = int(os.environ.get("NEXUS_GREEK_MAX_AGE_SECONDS", "60"))
AGGRESSOR_EDGE_PCT = float(os.environ.get("NEXUS_AGGRESSOR_EDGE_PCT", "0.20"))
AGGRESSOR_MAX_SPREAD_PCT = float(os.environ.get("NEXUS_AGGRESSOR_MAX_SPREAD_PCT", "0.25"))
SWEEP_PREMIUM_USD = float(os.environ.get("NEXUS_SWEEP_PREMIUM_USD", "25000"))
STOP_LOSS_PCT = float(os.environ.get("NEXUS_STOP_LOSS_PCT", "-50.0"))
GUARD_ACTIVATE_PCT = float(os.environ.get("NEXUS_GUARD_ACTIVATE_PCT", "15.0"))
GUARD_FLOOR_PCT = float(os.environ.get("NEXUS_GUARD_FLOOR_PCT", "5.0"))
EXECUTION_MAX_SLIPPAGE_PCT = float(os.environ.get("NEXUS_EXECUTION_MAX_SLIPPAGE_PCT", "5.0"))
SPREAD_STRIKE_WIDTH = float(os.environ.get("NEXUS_SPREAD_STRIKE_WIDTH", "5.0"))
SPREAD_TARGET_DELTA = float(os.environ.get("NEXUS_SPREAD_TARGET_DELTA", "0.15"))
SPREAD_MIN_ENTRY_CREDIT = float(os.environ.get("NEXUS_SPREAD_MIN_ENTRY_CREDIT", "0.30"))
SPREAD_TAKE_PROFIT_PCT = float(os.environ.get("NEXUS_SPREAD_TAKE_PROFIT_PCT", "20.0"))
SPREAD_STOP_LOSS_PCT = float(os.environ.get("NEXUS_SPREAD_STOP_LOSS_PCT", "75.0"))
SPREAD_HOLD_SECONDS = int(os.environ.get("NEXUS_SPREAD_HOLD_SECONDS", "1800"))
SPREAD_MAX_IV_RANK = float(os.environ.get("NEXUS_SPREAD_MAX_IV_RANK", "30.0"))

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
    {"entry": time(11, 30), "end": time(12, 0), "window_start": time(11, 0), "window_end": time(11, 30), "entry_label": "11:30"},
    {"entry": time(12, 0), "end": time(12, 30), "window_start": time(11, 30), "window_end": time(12, 0), "entry_label": "12:00"},
]
MARKET_CONTEXT_WINDOWS = [
    {"entry": time(10, 0), "end": time(10, 0), "window_start": time(9, 30), "window_end": time(10, 0), "entry_label": "w0930_1000"},
    {"entry": time(10, 30), "end": time(10, 30), "window_start": time(10, 0), "window_end": time(10, 30), "entry_label": "w1000_1030"},
    {"entry": time(11, 0), "end": time(11, 0), "window_start": time(10, 30), "window_end": time(11, 0), "entry_label": "w1030_1100"},
    {"entry": time(11, 30), "end": time(11, 30), "window_start": time(11, 0), "window_end": time(11, 30), "entry_label": "w1100_1130"},
    {"entry": time(12, 0), "end": time(12, 0), "window_start": time(11, 30), "window_end": time(12, 0), "entry_label": "w1130_1200"},
    {"entry": time(12, 30), "end": time(12, 30), "window_start": time(12, 0), "window_end": time(12, 30), "entry_label": "w1200_1230"},
    {"entry": time(13, 0), "end": time(13, 0), "window_start": time(12, 30), "window_end": time(13, 0), "entry_label": "w1230_1300"},
    {"entry": time(13, 30), "end": time(13, 30), "window_start": time(13, 0), "window_end": time(13, 30), "entry_label": "w1300_1330"},
    {"entry": time(14, 0), "end": time(14, 0), "window_start": time(13, 30), "window_end": time(14, 0), "entry_label": "w1330_1400"},
    {"entry": time(14, 30), "end": time(14, 30), "window_start": time(14, 0), "window_end": time(14, 30), "entry_label": "w1400_1430"},
    {"entry": time(15, 0), "end": time(15, 0), "window_start": time(14, 30), "window_end": time(15, 0), "entry_label": "w1430_1500"},
    {"entry": time(15, 30), "end": time(15, 30), "window_start": time(15, 0), "window_end": time(15, 30), "entry_label": "w1500_1530"},
    {"entry": time(16, 0), "end": time(16, 0), "window_start": time(15, 30), "window_end": time(16, 0), "entry_label": "w1530_1600"},
    {"entry": time(16, 15), "end": time(16, 15), "window_start": time(16, 0), "window_end": time(16, 15), "entry_label": "w1600_1615"},
]
EVENT_FEATURES = {
    "ts_utc",
    "symbol",
    "raw_symbol",
    "side",
    "premium",
    "is_sweep",
    "aggressor",
    "delta",
    "gamma",
    "underlying_mid",
    "option_mid",
}
CONTEXT_FEATURES = {"iv_rank", "atm_iv", "net_gex"}
FEATURE_MAX_AGE_SECONDS = {
    "underlying_mid": UNDERLYING_MAX_AGE_SECONDS,
    "option_mid": OPTION_QUOTE_MAX_AGE_SECONDS,
    "delta": GREEK_MAX_AGE_SECONDS,
    "gamma": GREEK_MAX_AGE_SECONDS,
    "iv_rank": VOL_CONTEXT_MAX_AGE_SECONDS,
    "atm_iv": VOL_CONTEXT_MAX_AGE_SECONDS,
    "net_gex": GEX_CONTEXT_MAX_AGE_SECONDS,
}
UNDERLYING_FRESHNESS_FIELDS = (
    "underlying_ts_utc",
    "underlyingTsUtc",
    "underlying_as_of",
    "underlyingAsOf",
    "spot_ts_utc",
    "spotTsUtc",
    "spot_as_of",
    "spotAsOf",
    "lastPriceUtc",
    "last_price_utc",
)
OPTION_FRESHNESS_FIELDS = (
    "option_mid_ts_utc",
    "optionMidTsUtc",
    "option_quote_ts_utc",
    "optionQuoteTsUtc",
    "quote_ts_utc",
    "quoteTsUtc",
    "quote_as_of",
    "quoteAsOf",
)
GREEK_FRESHNESS_FIELDS = (
    "greeks_ts_utc",
    "greeksTsUtc",
    "greek_ts_utc",
    "greekTsUtc",
    "iv_ts_utc",
    "ivTsUtc",
)
CONTEXT_TIMESTAMP_FIELDS = (
    "asOf",
    "as_of",
    "tsUtc",
    "ts_utc",
    "timestamp",
    "sourceUpdatedAt",
    "source_updated_at",
    "updatedAt",
    "updated_at",
)
FRESH_STATUSES = {"available", "derived", "fallback"}
STRATEGY_REQUIRED_FEATURES = {
    "etf_open_specialist": ("ts_utc", "symbol", "side", "premium", "iv_rank"),
    "etf_low_sweep_core": ("ts_utc", "symbol", "raw_symbol", "side", "premium", "is_sweep"),
    "etf_flow_specialist": (
        "ts_utc",
        "symbol",
        "raw_symbol",
        "side",
        "premium",
        "is_sweep",
        "aggressor",
        "delta",
        "gamma",
        "iv_rank",
        "atm_iv",
        "net_gex",
    ),
    "etf_momentum_specialist": ("ts_utc", "symbol", "side", "premium", "underlying_mid", "iv_rank"),
    "etf_confluence_sniper": (
        "ts_utc",
        "raw_symbol",
        "side",
        "premium",
        "underlying_mid",
        "delta",
        "option_mid",
        "iv_rank",
    ),
    "etf_put_credit_open30_spread": (
        "ts_utc",
        "symbol",
        "raw_symbol",
        "side",
        "premium",
        "delta",
        "option_mid",
        "iv_rank",
    ),
    "etf_call_credit_open30_spread": (
        "ts_utc",
        "symbol",
        "raw_symbol",
        "side",
        "premium",
        "delta",
        "option_mid",
        "iv_rank",
    ),
}


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


def parse_optional_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _payload_datetime(payload: dict, names: tuple[str, ...]) -> datetime | None:
    for name in names:
        if name in payload:
            dt = parse_optional_datetime(payload.get(name))
            if dt:
                return dt
    return None


def _payload_age_seconds(payload: dict, *names: str) -> float | None:
    for name in names:
        if name not in payload:
            continue
        try:
            value = float(payload[name])
        except (TypeError, ValueError):
            continue
        if "ms" in name.lower():
            return value / 1000.0
        return value
    return None


def _freshness_status(reference_time: datetime | None, feature_time: datetime | None, max_age_seconds: int, missing_is_stale: bool) -> str:
    if not feature_time or not reference_time:
        return "unknown_freshness" if missing_is_stale else "available"
    age_seconds = abs((reference_time - feature_time).total_seconds())
    return "available" if age_seconds <= max_age_seconds else "stale"


def _quote_valid_until(reference_time: datetime | None, max_age_seconds: int = OPTION_QUOTE_MAX_AGE_SECONDS) -> str | None:
    if not reference_time:
        return None
    return (reference_time + timedelta(seconds=max_age_seconds)).astimezone(timezone.utc).isoformat()


def _quote_execution_snapshot(quote: dict | None, reference_time: datetime | None = None, *, price_field: str = "option_mid") -> dict:
    quote = quote or {}
    quote_ts = parse_optional_datetime(quote.get("quote_ts") or quote.get("quote_ts_utc"))
    price = quote.get(price_field)
    status_payload = {
        "option_mid": quote.get("option_mid"),
        "option_bid": quote.get("option_bid"),
        "option_ask": quote.get("option_ask"),
        "tradability_bucket": quote.get("tradability_bucket"),
    }
    if quote.get("quote_age_ms") is not None:
        status_payload["quote_age_ms"] = quote.get("quote_age_ms")
    if quote.get("quote_ts") or quote.get("quote_ts_utc"):
        status_payload["quote_ts_utc"] = quote.get("quote_ts") or quote.get("quote_ts_utc")
    freshness = _event_freshness_status(status_payload, reference_time or datetime.now(timezone.utc), "option_mid")
    return {
        "order_type": "limit",
        "price_reference": "option_mid",
        "reference_price": float(price) if price not in (None, "") else None,
        "max_slippage_pct": EXECUTION_MAX_SLIPPAGE_PCT,
        "quote_freshness": freshness,
        "quote_valid_until": _quote_valid_until(quote_ts),
        "quote_age_ms": quote.get("quote_age_ms"),
        "option_bid": quote.get("option_bid"),
        "option_ask": quote.get("option_ask"),
        "option_mid": quote.get("option_mid"),
        "quote_ts": quote.get("quote_ts") or quote.get("quote_ts_utc"),
        "tradability_bucket": quote.get("tradability_bucket"),
    }


def _event_freshness_status(payload: dict, reference_time: datetime | None, feature: str) -> str:
    if feature == "underlying_mid":
        if _payload_bool(payload, "underlying_data_stale", "underlyingDataStale", "priceDataStale", "price_data_stale"):
            return "stale"
        if _payload_bool(payload, "underlying_warmup_complete", "underlyingWarmupComplete", "warmupComplete", "warmup_complete") is False:
            return "unknown_freshness"
        feature_time = _payload_datetime(payload, UNDERLYING_FRESHNESS_FIELDS)
        return _freshness_status(reference_time, feature_time, UNDERLYING_MAX_AGE_SECONDS, missing_is_stale=True)
    if feature == "option_mid":
        executable = _payload_bool(payload, "option_executable", "optionExecutable", "executable")
        tradable = _payload_bool(payload, "option_tradable", "optionTradable", "tradable")
        bucket = str(_payload_value(payload, "tradability_bucket", "tradabilityBucket") or "").strip().lower()
        if executable is False or tradable is False or bucket in {"avoid", "reject", "unknown"}:
            return "untradable"
        if _payload_bool(payload, "option_stale", "optionStale", "stale"):
            return "stale"
        age_seconds = _payload_age_seconds(payload, "quote_age_ms", "quoteAgeMs", "option_quote_age_ms", "optionQuoteAgeMs")
        if age_seconds is not None:
            return "available" if age_seconds <= OPTION_QUOTE_MAX_AGE_SECONDS else "stale"
        feature_time = _payload_datetime(payload, OPTION_FRESHNESS_FIELDS)
        return _freshness_status(reference_time, feature_time, OPTION_QUOTE_MAX_AGE_SECONDS, missing_is_stale=True)
    if feature in {"delta", "gamma"}:
        feature_time = _payload_datetime(payload, GREEK_FRESHNESS_FIELDS)
        if not feature_time:
            feature_time = _payload_datetime(payload, OPTION_FRESHNESS_FIELDS)
        return _freshness_status(reference_time, feature_time, GREEK_MAX_AGE_SECONDS, missing_is_stale=True)
    return "available"


def ny_session_date(dt_utc: datetime):
    return dt_utc.astimezone(NY).date()


def decision_slot(dt_utc: datetime) -> dict | None:
    t = dt_utc.astimezone(NY).time()
    for slot in DECISION_SLOTS:
        if slot["entry"] <= t < slot["end"]:
            return slot
    return None


def event_window_slot(dt_utc: datetime) -> dict | None:
    t = dt_utc.astimezone(NY).time()
    for slot in DECISION_SLOTS:
        if slot["window_start"] <= t < slot["window_end"]:
            return slot
    return None


def input_streams() -> dict[str, str]:
    if INPUT_STREAM:
        return {INPUT_STREAM: STREAM_START_ID}
    return {f"md:{symbol}:options:trades": STREAM_START_ID for symbol in sorted(SYMBOLS)}


async def read_input_streams(redis_client, streams: dict[str, str]):
    if REDIS_CLUSTER and len(streams) > 1:
        replies = []
        for stream_name, last_id in list(streams.items()):
            replies.extend(await redis_client.xread({stream_name: last_id}, count=10, block=250))
        return replies
    return await redis_client.xread(streams, count=10, block=1000)


def signal_key(session_date, symbol: str, strategy: str) -> str:
    if FIRST_TRIGGER_SCOPE == "strategy":
        return f"{session_date}:{symbol}:{strategy}"
    return f"{session_date}:{symbol}"


def symbol_lane_key(session_date, symbol: str) -> str:
    return f"{session_date}:{symbol}"


def group_lock_key(session_date, strategy: str) -> str:
    return f"{session_date}:group:{strategy}"


def redis_symbol_lock_key(session_date, symbol: str) -> str:
    return f"nexus:lock:{session_date}:{symbol}"


def redis_strategy_lock_key(session_date, symbol: str, strategy: str) -> str:
    return f"nexus:lock:{session_date}:{symbol}:{strategy}"


def redis_group_lock_key(session_date, strategy: str) -> str:
    return f"nexus:lock:{session_date}:group:{strategy}"


def redis_active_position_key(session_date, symbol: str) -> str:
    return f"nexus:active_position:{session_date}:{symbol}"


def redis_stream_offset_key(stream_name: str) -> str:
    return STREAM_OFFSET_KEY_TEMPLATE.format(stream=stream_name)


def window_eval_key(session_date, symbol: str, entry_label: str) -> str:
    return f"{session_date}:{symbol}:{entry_label}"


def _option_side_from_raw_symbol(raw_symbol: str | None) -> str | None:
    if not raw_symbol:
        return None
    compact = str(raw_symbol).replace(" ", "").upper()
    if len(compact) >= 9 and compact[-9] in {"C", "P"}:
        return compact[-9]
    return None


def _contract_details_from_raw_symbol(raw_symbol: str | None) -> dict[str, str | float | None]:
    if not raw_symbol:
        return {"expiry_date": None, "strike": None, "side": None}
    compact = str(raw_symbol).replace(" ", "").upper()
    if len(compact) < 15:
        return {"expiry_date": None, "strike": None, "side": _option_side_from_raw_symbol(raw_symbol)}
    try:
        expiry_raw = compact[-15:-9]
        strike_raw = compact[-8:]
        return {
            "expiry_date": f"20{expiry_raw[0:2]}-{expiry_raw[2:4]}-{expiry_raw[4:6]}",
            "strike": int(strike_raw) / 1000.0,
            "side": compact[-9],
        }
    except Exception:
        return {"expiry_date": None, "strike": None, "side": _option_side_from_raw_symbol(raw_symbol)}


def _raw_symbol_with_strike(raw_symbol: str | None, strike: float) -> str | None:
    if not raw_symbol:
        return None
    compact = str(raw_symbol).replace(" ", "").upper()
    if len(compact) < 15:
        return None
    try:
        strike_raw = f"{int(round(float(strike) * 1000)):08d}"
    except (TypeError, ValueError):
        return None
    return f"{compact[:-8]}{strike_raw}"


def _raw_symbol_key_variants(raw_symbol: str | None) -> list[str]:
    if not raw_symbol:
        return []
    raw = str(raw_symbol).strip().upper()
    compact = raw.replace(" ", "")
    variants = []
    for value in (raw, compact):
        if value and value not in variants:
            variants.append(value)
    if len(compact) >= 15:
        padded = f"{compact[:-15].ljust(6)}{compact[-15:]}"
        if padded not in variants:
            variants.append(padded)
    return variants


def _payload_has_any(payload: dict, *names: str) -> str | None:
    for name in names:
        if name in payload and payload[name] not in (None, ""):
            return name
    return None


def _payload_has_positive_number(payload: dict, *names: str) -> str | None:
    for name in names:
        try:
            if name in payload and float(payload[name]) > 0:
                return name
        except (TypeError, ValueError):
            continue
    return None


def _payload_value(payload: dict, *names: str):
    for name in names:
        if name in payload and payload[name] not in (None, ""):
            return payload[name]
    return None


def _payload_float(payload: dict, *names: str) -> float | None:
    value = _payload_value(payload, *names)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payload_bool(payload: dict, *names: str) -> bool | None:
    value = _payload_value(payload, *names)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _canonical_aggressor(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        code = int(value)
        return {1: "B", 2: "A", 3: "M"}.get(code, "")
    raw = str(value).strip().upper()
    if raw in {"A", "ASK", "BUY", "BOUGHT", "LIFT", "LIFTED"}:
        return "A"
    if raw in {"B", "BID", "SELL", "SOLD", "HIT"}:
        return "B"
    if raw in {"M", "MID", "NEUTRAL", "N"}:
        return "M"
    return "" if raw in {"UNKNOWN", "UNK", "U", "0"} else raw


def _derive_aggressor_from_quote(payload: dict, reference_time: datetime | None) -> str:
    price = _payload_float(payload, "price")
    bid = _payload_float(payload, "option_bid", "bid", "Bid")
    ask = _payload_float(payload, "option_ask", "ask", "Ask")
    if price is None or bid is None or ask is None or price <= 0 or bid <= 0 or ask <= 0 or ask < bid:
        return ""

    mid = _payload_float(payload, "option_mid", "optionMid", "mid", "Mid")
    mid = mid if mid and mid > 0 else (bid + ask) / 2.0
    if mid <= 0:
        return ""

    quote_status = _event_freshness_status(payload, reference_time, "option_mid")
    if quote_status not in FRESH_STATUSES:
        return ""

    width = ask - bid
    if width <= 0 or width / mid > AGGRESSOR_MAX_SPREAD_PCT:
        return ""

    if price <= bid + AGGRESSOR_EDGE_PCT * width:
        return "B"
    if price >= ask - AGGRESSOR_EDGE_PCT * width:
        return "A"

    previous_price = _payload_float(payload, "previous_trade_price", "previousTradePrice", "prev_trade_price", "prevTradePrice")
    if previous_price is not None:
        if price > previous_price:
            return "A"
        if price < previous_price:
            return "B"

    return "M"


def _derive_sweep_from_quote(payload: dict, aggressor: str) -> bool | None:
    if aggressor not in {"A", "B"}:
        return False if aggressor == "M" else None
    premium = _payload_float(payload, "premium")
    if premium is None:
        price = _payload_float(payload, "price")
        size = _payload_float(payload, "size", "contracts")
        premium = price * size * 100.0 if price is not None and size is not None else None
    if premium is None:
        return None
    return premium >= SWEEP_PREMIUM_USD


def _nested_payload(payload: dict, *names: str) -> dict:
    for name in names:
        nested = payload.get(name)
        if isinstance(nested, dict):
            return nested
    return {}


def normalize_raw_symbol(raw_symbol: str | None) -> str:
    return str(raw_symbol or "").strip().upper()


def build_signal_id(strategy: str, symbol: str, session_date, slot: dict | None, raw_symbol: str | None) -> str:
    entry_label = slot["entry_label"] if slot else "na"
    base = "|".join([
        str(session_date or ""),
        str(symbol or "").upper(),
        str(strategy or ""),
        entry_label,
        normalize_raw_symbol(raw_symbol),
    ])
    return f"sig_{hashlib.sha1(base.encode('utf-8')).hexdigest()[:16]}"


def new_message_id() -> str:
    return f"msg_{uuid4().hex}"


def _event_feature_status(payload: dict, raw_symbol: str | None) -> dict[str, str]:
    reference_time = parse_event_datetime(payload) if _payload_has_any(payload, "ts_utc", "timestamp", "ts_event_ns") else None
    status = {}
    status["ts_utc"] = "available" if _payload_has_any(payload, "ts_utc", "timestamp") else "derived" if _payload_has_any(payload, "ts_event_ns") else "missing"
    status["symbol"] = "available" if _payload_has_any(payload, "symbol", "underlying") else "missing"
    status["raw_symbol"] = "available" if _payload_has_any(payload, "raw_symbol", "rawSymbol") else "missing"
    status["side"] = "available" if _payload_has_any(payload, "side") else "derived" if _option_side_from_raw_symbol(raw_symbol) else "missing"
    status["premium"] = (
        "available"
        if _payload_has_positive_number(payload, "premium")
        else "derived"
        if _payload_has_positive_number(payload, "price") and _payload_has_positive_number(payload, "size", "contracts")
        else "missing"
    )
    status["is_sweep"] = (
        "derived"
        if payload.get("_derived_is_sweep")
        else "available"
        if _payload_has_any(payload, "is_sweep", "isSweep")
        else "missing"
    )
    status["aggressor"] = (
        "derived"
        if payload.get("_derived_aggressor")
        else "available"
        if _payload_has_any(payload, "aggressor", "trade_side", "tradeSide")
        else "missing"
    )
    status["delta"] = _event_freshness_status(payload, reference_time, "delta") if _payload_has_any(payload, "delta") else "missing"
    status["gamma"] = _event_freshness_status(payload, reference_time, "gamma") if _payload_has_any(payload, "gamma") else "missing"
    status["underlying_mid"] = (
        _event_freshness_status(payload, reference_time, "underlying_mid")
        if _payload_has_any(payload, "underlying_mid", "underlyingMid", "underlying_price", "underlyingPrice")
        else "missing"
    )
    status["option_mid"] = _event_freshness_status(payload, reference_time, "option_mid") if _payload_has_any(payload, "option_mid", "optionMid") else "missing"
    return status


def normalize_trade_payload(payload: dict) -> dict:
    raw_symbol = payload.get("raw_symbol") or payload.get("rawSymbol")
    symbol = payload.get("symbol") or payload.get("underlying")
    price = float(payload.get("price") or 0.0)
    size = float(payload.get("size") or payload.get("contracts") or 0.0)
    ts_utc = payload.get("ts_utc") or payload.get("timestamp")
    ts_event_ns = payload.get("ts_event_ns")
    if not ts_utc and ts_event_ns:
        ts_utc = datetime.fromtimestamp(int(ts_event_ns) / 1_000_000_000, tz=timezone.utc).isoformat()

    reference_time = parse_event_datetime(payload) if ts_utc or ts_event_ns else None
    previous_status = payload.get("_feature_status") if isinstance(payload.get("_feature_status"), dict) else {}
    raw_aggressor = None if previous_status.get("aggressor") in {"missing", "derived"} else _payload_value(payload, "aggressor", "trade_side", "tradeSide")
    aggressor = _canonical_aggressor(raw_aggressor)
    derived_aggressor = False
    if not aggressor:
        aggressor = _derive_aggressor_from_quote(payload, reference_time)
        derived_aggressor = bool(aggressor)

    raw_sweep_source = None if previous_status.get("is_sweep") in {"missing", "derived"} and "isSweep" not in payload else _payload_has_any(payload, "is_sweep", "isSweep")
    derived_sweep = False
    if raw_sweep_source:
        is_sweep = bool(_payload_bool(payload, "is_sweep", "isSweep"))
    else:
        sweep_value = _derive_sweep_from_quote(payload, aggressor)
        is_sweep = bool(sweep_value) if sweep_value is not None else False
        derived_sweep = sweep_value is not None

    normalized = {
        **payload,
        "symbol": str(symbol or "").strip().upper(),
        "raw_symbol": raw_symbol,
        "ts_utc": ts_utc,
        "side": str(payload.get("side") or _option_side_from_raw_symbol(raw_symbol) or "").strip().upper(),
        "premium": float(payload.get("premium") or price * size * 100.0),
        "is_sweep": is_sweep,
        "aggressor": aggressor,
        "delta": float(payload.get("delta") or 0.0),
        "gamma": float(payload.get("gamma") or 0.0),
    }
    for target, aliases in {
        "underlying_mid": ("underlying_mid", "underlyingMid", "underlying_price", "underlyingPrice"),
        "option_mid": ("option_mid", "optionMid"),
        "quote_age_ms": ("quote_age_ms", "quoteAgeMs", "option_quote_age_ms", "optionQuoteAgeMs"),
    }.items():
        value = _payload_value(payload, *aliases)
        if value is not None:
            normalized[target] = value
    status_payload = dict(payload)
    if derived_sweep:
        status_payload["is_sweep"] = is_sweep
        status_payload["_derived_is_sweep"] = True
    elif previous_status.get("is_sweep") == "missing" and "isSweep" not in status_payload:
        status_payload.pop("is_sweep", None)
    if derived_aggressor:
        status_payload["aggressor"] = aggressor
        status_payload["_derived_aggressor"] = True
    elif previous_status.get("aggressor") == "missing" and "trade_side" not in status_payload and "tradeSide" not in status_payload:
        status_payload.pop("aggressor", None)
    if previous_status.get("delta") == "missing" and not _payload_datetime(status_payload, GREEK_FRESHNESS_FIELDS):
        status_payload.pop("delta", None)
    if previous_status.get("gamma") == "missing" and not _payload_datetime(status_payload, GREEK_FRESHNESS_FIELDS):
        status_payload.pop("gamma", None)
    for target in ("underlying_mid", "option_mid", "quote_age_ms"):
        if target in normalized:
            status_payload[target] = normalized[target]
    normalized["_feature_status"] = _event_feature_status(status_payload, raw_symbol)
    return normalized


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


async def read_json_payload(client, key: str) -> dict:
    raw = await client.get(key)
    if not raw:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _set_enriched_value(payload: dict, field: str, value) -> None:
    if value in (None, ""):
        return
    status = (payload.get("_feature_status") or {}).get(field)
    if field not in payload or status not in FRESH_STATUSES:
        payload[field] = value


def _merge_underlying_context(payload: dict, context: dict) -> None:
    if not context:
        return
    price = _payload_float(context, "price", "lastTradePrice", "close")
    if price is not None and price > 0:
        _set_enriched_value(payload, "underlying_mid", price)
    ts = _payload_value(context, "lastPriceUtc", "last_price_utc", "lastTradeUtc", "last_trade_utc", "tsUtc", "ts_utc")
    if ts is not None:
        payload.setdefault("underlying_ts_utc", ts)
    warmup = _payload_bool(context, "warmupComplete", "warmup_complete")
    if warmup is not None:
        payload["underlying_warmup_complete"] = warmup
    stale = _payload_bool(context, "priceDataStale", "price_data_stale")
    if stale is not None:
        payload["underlying_data_stale"] = stale


def _merge_contract_payload(payload: dict, contract: dict) -> None:
    if not contract:
        return
    option = _nested_payload(contract, "option", "Option")
    greeks = _nested_payload(contract, "greeks", "Greeks")

    mid = _payload_float(contract, "option_mid", "optionMid", "mid", "Mid") or _payload_float(option, "mid", "Mid")
    if mid is not None and mid > 0:
        _set_enriched_value(payload, "option_mid", mid)

    for target, names in {
        "option_bid": ("bid", "Bid"),
        "option_ask": ("ask", "Ask"),
        "bid_size": ("bidSize", "bid_size", "BidSize"),
        "ask_size": ("askSize", "ask_size", "AskSize"),
        "spread_pct": ("spreadPct", "spread_pct", "SpreadPct"),
        "tradability_score": ("tradabilityScore", "tradability_score", "TradabilityScore"),
    }.items():
        value = _payload_float(contract, *names)
        if value is None:
            value = _payload_float(option, *names)
        if value is not None:
            payload.setdefault(target, value)

    for target, names in {
        "option_tradable": ("tradable", "Tradable"),
        "option_executable": ("executable", "Executable"),
        "option_stale": ("stale", "Stale"),
    }.items():
        value = _payload_bool(contract, *names)
        if value is not None:
            payload[target] = value

    bucket = _payload_value(contract, "tradabilityBucket", "tradability_bucket", "TradabilityBucket")
    if bucket is not None:
        payload["tradability_bucket"] = str(bucket)

    ts = _payload_value(contract, "asOfUtc", "AsOfUtc", "tsUtc", "ts_utc", "asOf", "as_of")
    if ts is not None:
        payload.setdefault("quote_ts_utc", ts)

    quote_age_ms = _payload_float(contract, "quoteAgeMs", "quote_age_ms", "QuoteAgeMs")
    if quote_age_ms is not None:
        payload.setdefault("quote_age_ms", quote_age_ms)

    for greek in ("delta", "gamma"):
        value = _payload_float(contract, greek, greek.capitalize())
        if value is None:
            value = _payload_float(greeks, greek, greek.capitalize())
        if value is not None:
            _set_enriched_value(payload, greek, value)
    greek_ts = _payload_value(contract, "greeksTsUtc", "greeks_ts_utc", "greekTsUtc", "greek_ts_utc")
    if greek_ts is None:
        greek_ts = _payload_value(greeks, "asOfUtc", "asOf", "tsUtc", "ts_utc")
    if greek_ts is None and ts is not None and (_payload_has_any(contract, "delta", "gamma") or _payload_has_any(greeks, "delta", "gamma")):
        greek_ts = ts
    if greek_ts is not None:
        payload.setdefault("greeks_ts_utc", greek_ts)


async def enrich_trade_payload_from_redis(payload: dict, client) -> dict:
    symbol = str(payload.get("symbol") or "").strip().upper()
    raw_symbol = normalize_raw_symbol(payload.get("raw_symbol") or payload.get("rawSymbol"))
    equity_key = EQUITY_CONTEXT_KEY_TEMPLATE.format(symbol=symbol) if symbol else None
    state_key = CONTRACT_STATE_KEY_TEMPLATE.format(symbol=symbol, raw_symbol=raw_symbol) if raw_symbol else None
    tradability_key = CONTRACT_TRADABILITY_KEY_TEMPLATE.format(symbol=symbol, raw_symbol=raw_symbol) if raw_symbol else None

    tasks = [
        read_json_payload(client, key) if key else asyncio.sleep(0, result={})
        for key in (equity_key, state_key, tradability_key)
    ]
    equity_context, contract_state, tradability = await asyncio.gather(*tasks)
    enriched = dict(payload)
    _merge_underlying_context(enriched, equity_context)
    _merge_contract_payload(enriched, contract_state)
    _merge_contract_payload(enriched, tradability)
    return normalize_trade_payload(enriched)

class SigmatiqNexus:
    def __init__(self):
        self.buffers = {}
        self.max_buffer = 5000
        self.active_positions = {} # Tracks {symbol: {'entry_price': float, 'is_guarded': bool, 'side': str, 'raw_symbol': str, 'signal_id': str, 'position_id': str}}

        print("Loading Triple-ETF Sniper (SPY, QQQ, IWM)...")
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
        self.feature_blocks_reported = set()
        self.window_views_reported = set()
        self.window_pricing_reported = set()
        self.option_market_context_reported = set()
        self.participant_flow_reported = set()
        self.evaluated_windows = set()
        self.late_window_impacts = {}
        self.redis = None

    def _log(self, event: str, **fields) -> None:
        payload = {
            "source": "sigmatiq_nexus",
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        print(json.dumps(payload, default=str, separators=(",", ":")))

    async def _publish(self, channel: str, payload: str) -> None:
        publisher = getattr(self.redis, "publish", None)
        if publisher:
            await publisher(channel, payload)
            return
        await self.redis.execute_command("PUBLISH", channel, payload)

    def _window_log_fields(self, df: pl.DataFrame, slot: dict | None = None) -> dict:
        fields = {"rows": int(df.height)}
        if slot:
            fields["entry_time"] = slot["entry_label"]
            fields["window_start"] = slot["window_start"].isoformat()
            fields["window_end"] = slot["window_end"].isoformat()
        if not df.is_empty():
            stats = window_stats(df)
            fields.update({
                "total_premium": round(stats["total_p"], 2),
                "call_premium": round(stats["call_p"], 2),
                "put_premium": round(stats["put_p"], 2),
                "sweep_ratio": round(stats["sweep"], 4),
            })
        return fields

    def _window_lead_contract(self, df: pl.DataFrame) -> dict[str, str | float | None]:
        if df.is_empty() or "raw_symbol" not in df.columns:
            return {"raw_symbol": None, "expiry_date": None, "strike": None, "side": None}
        lead = (
            df.group_by("raw_symbol")
            .agg(pl.col("premium").cast(pl.Float64, strict=False).fill_null(0).sum().alias("total_premium"))
            .sort("total_premium", descending=True)
            .head(1)
        )
        if lead.is_empty():
            return {"raw_symbol": None, "expiry_date": None, "strike": None, "side": None}
        raw_symbol = lead[0, "raw_symbol"]
        details = _contract_details_from_raw_symbol(raw_symbol)
        return {"raw_symbol": raw_symbol, **details}

    def _contract_pricing_profiles(self, df: pl.DataFrame) -> list[dict]:
        required = {"ts_utc", "raw_symbol", "underlying_mid", "delta"}
        if df.is_empty() or not required.issubset(set(df.columns)):
            return []
        price_col = "option_mid" if "option_mid" in df.columns else "price" if "price" in df.columns else None
        if price_col is None:
            return []
        profiles: list[dict] = []
        for raw_symbol in df.select("raw_symbol").drop_nulls().unique()["raw_symbol"].to_list():
            hist = (
                df.filter(pl.col("raw_symbol") == raw_symbol)
                .with_columns(pl.col("ts_utc").str.to_datetime(strict=False, time_zone="UTC").alias("_dt_utc"))
                .sort("_dt_utc")
            )
            if hist.height < 2:
                continue
            end = hist.tail(1)
            end_ts = end[0, "_dt_utc"]
            start = hist.filter(pl.col("_dt_utc") <= end_ts - timedelta(minutes=5)).tail(1)
            if start.is_empty():
                start = hist.head(1)
            p_start = float(start[0, price_col] or 0.0)
            p_now = float(end[0, price_col] or 0.0)
            s_start = float(start[0, "underlying_mid"] or 0.0)
            s_now = float(end[0, "underlying_mid"] or 0.0)
            delta = float(start[0, "delta"] or 0.0)
            if p_start <= 0:
                continue
            actual_change = p_now - p_start
            expected_change = delta * (s_now - s_start)
            pricing_lag = (actual_change - expected_change) / (p_start + 1e-9)
            details = _contract_details_from_raw_symbol(raw_symbol)
            premium = hist.select(pl.col("premium").cast(pl.Float64, strict=False).fill_null(0).sum()).item() if "premium" in hist.columns else 0.0
            cheapness_score = max(0.0, min(100.0, 50.0 + (-pricing_lag * 500.0)))
            profiles.append({
                "raw_symbol": raw_symbol,
                "pricing_lag": round(float(pricing_lag), 6),
                "cheapness_score": round(float(cheapness_score), 2),
                "premium": float(premium),
                "side": str(end[0, "side"] or details["side"] or ""),
                "expiry_date": details["expiry_date"],
                "strike": details["strike"],
            })
        return profiles

    def _window_pricing_summary(self, df: pl.DataFrame) -> dict:
        profiles = self._contract_pricing_profiles(df)
        if not profiles:
            return {
                "profiles": [],
                "evaluated_contract_count": 0,
                "cheap_contract": None,
                "costly_contract": None,
                "cheap_side": None,
                "cheap_side_avg_pricing_lag": None,
                "costly_side": None,
                "costly_side_avg_pricing_lag": None,
            }
        cheapest = min(profiles, key=lambda p: p["pricing_lag"])
        costliest = max(profiles, key=lambda p: p["pricing_lag"])
        side_buckets: dict[str, dict[str, float]] = {}
        for profile in profiles:
            side = profile["side"]
            if side not in {"C", "P"}:
                continue
            bucket = side_buckets.setdefault(side, {"weighted_lag": 0.0, "premium": 0.0})
            weight = max(profile["premium"], 1.0)
            bucket["weighted_lag"] += profile["pricing_lag"] * weight
            bucket["premium"] += weight
        side_avgs = {
            side: bucket["weighted_lag"] / bucket["premium"]
            for side, bucket in side_buckets.items()
            if bucket["premium"] > 0
        }
        cheap_side = min(side_avgs, key=side_avgs.get) if side_avgs else None
        costly_side = max(side_avgs, key=side_avgs.get) if side_avgs else None
        return {
            "profiles": profiles,
            "evaluated_contract_count": len(profiles),
            "cheap_contract": cheapest,
            "costly_contract": costliest,
            "cheap_side": cheap_side,
            "cheap_side_avg_pricing_lag": round(float(side_avgs[cheap_side]), 6) if cheap_side else None,
            "costly_side": costly_side,
            "costly_side_avg_pricing_lag": round(float(side_avgs[costly_side]), 6) if costly_side else None,
        }

    def _contract_contexts(self, df: pl.DataFrame, profiles: list[dict]) -> list[dict]:
        if df.is_empty() or "raw_symbol" not in df.columns:
            return []
        profile_by_raw = {p["raw_symbol"]: p for p in profiles}
        contexts = []
        for row in (
            df.group_by("raw_symbol")
            .agg([
                pl.col("premium").cast(pl.Float64, strict=False).fill_null(0).sum().alias("premium"),
                pl.len().alias("trade_count"),
                pl.col("side").cast(pl.Utf8).drop_nulls().last().alias("side"),
                pl.col("option_mid").cast(pl.Float64, strict=False).drop_nulls().last().alias("option_mid") if "option_mid" in df.columns else pl.lit(None).alias("option_mid"),
                pl.col("option_bid").cast(pl.Float64, strict=False).drop_nulls().last().alias("option_bid") if "option_bid" in df.columns else pl.lit(None).alias("option_bid"),
                pl.col("option_ask").cast(pl.Float64, strict=False).drop_nulls().last().alias("option_ask") if "option_ask" in df.columns else pl.lit(None).alias("option_ask"),
            ])
            .sort("premium", descending=True)
            .to_dicts()
        ):
            raw_symbol = row.get("raw_symbol")
            details = _contract_details_from_raw_symbol(raw_symbol)
            option_mid = row.get("option_mid")
            bid = row.get("option_bid")
            ask = row.get("option_ask")
            spread_pct = None
            if option_mid not in (None, 0) and bid is not None and ask is not None:
                spread_pct = round(float((ask - bid) / option_mid * 100.0), 4)
            profile = profile_by_raw.get(raw_symbol, {})
            contexts.append({
                "raw_symbol": raw_symbol,
                "expiry": details["expiry_date"],
                "strike": details["strike"],
                "side": str(row.get("side") or details["side"] or ""),
                "premium": float(row.get("premium") or 0.0),
                "trade_count": int(row.get("trade_count") or 0),
                "option_mid": float(option_mid) if option_mid not in (None, "") else None,
                "bid_ask_spread_pct": spread_pct,
                "pricing_lag": profile.get("pricing_lag"),
                "cheapness_score": profile.get("cheapness_score"),
            })
        return contexts

    def _option_market_context_payload(self, df: pl.DataFrame, symbol: str, slot: dict, session_date) -> dict:
        stats = window_stats(df)
        pricing_summary = self._window_pricing_summary(df)
        profiles = pricing_summary.get("profiles") or []
        contexts = self._contract_contexts(df, profiles)
        cheapest_raws = {p["raw_symbol"] for p in sorted(profiles, key=lambda p: p["pricing_lag"])[:5]}
        costliest_raws = {p["raw_symbol"] for p in sorted(profiles, key=lambda p: p["pricing_lag"], reverse=True)[:5]}
        most_traded = sorted(contexts, key=lambda c: (c["premium"], c["trade_count"]), reverse=True)[:5]
        cheapest = [c for c in contexts if c["raw_symbol"] in cheapest_raws][:5]
        costliest = [c for c in contexts if c["raw_symbol"] in costliest_raws][:5]
        spread_values = [c["bid_ask_spread_pct"] for c in contexts if c.get("bid_ask_spread_pct") is not None]
        avg_spread = sum(spread_values) / len(spread_values) if spread_values else None
        liquidity_quality = "unknown"
        if avg_spread is not None:
            liquidity_quality = "good" if avg_spread <= 5 else "fair" if avg_spread <= 15 else "poor"
        pricing_quality = "usable" if profiles else "unknown"
        if liquidity_quality == "poor":
            pricing_quality = "degraded"
        if df.is_empty():
            pricing_quality = "unknown"
        cheap_side = {"C": "calls", "P": "puts"}.get(pricing_summary.get("cheap_side"), "unknown")
        costly_side = {"C": "calls", "P": "puts"}.get(pricing_summary.get("costly_side"), "unknown")
        if cheap_side == "unknown" and costly_side == "unknown" and stats["total_p"] > 0:
            cheap_side = "balanced"
            costly_side = "balanced"
        late = self.late_window_impacts.get(window_eval_key(session_date, symbol, slot["entry_label"])) or {}
        payload = {
            "symbol": symbol,
            "window_id": slot["entry_label"],
            "window_start": slot["window_start"].isoformat(),
            "window_end": slot["window_end"].isoformat(),
            "as_of": datetime.now(timezone.utc).isoformat(),
            "is_partial": False,
            "premium": {
                "call_premium": round(float(stats["call_p"]), 2),
                "put_premium": round(float(stats["put_p"]), 2),
                "total_premium": round(float(stats["total_p"]), 2),
                "net_premium_bias": "call_heavy" if stats["call_p"] > stats["put_p"] * 1.25 else "put_heavy" if stats["put_p"] > stats["call_p"] * 1.25 else "balanced",
            },
            "activity": {
                "trade_count": int(df.height),
                "contract_count": len(contexts),
                "sweep_count": int(df.select(pl.col("is_sweep").cast(pl.Boolean, strict=False).fill_null(False).sum()).item()) if "is_sweep" in df.columns and not df.is_empty() else 0,
                "large_trade_count": int(df.filter(pl.col("premium").cast(pl.Float64, strict=False).fill_null(0) >= SWEEP_PREMIUM_USD).height) if "premium" in df.columns and not df.is_empty() else 0,
            },
            "most_traded_contracts": most_traded,
            "cheapest_contracts": cheapest,
            "costliest_contracts": costliest,
            "cheap_side": cheap_side,
            "costly_side": costly_side,
            "liquidity_quality": liquidity_quality,
            "pricing_quality": pricing_quality,
            "late_event_impact": {
                "late_event_count": int(late.get("late_event_count") or 0),
                "late_total_premium": round(float(late.get("late_total_premium") or 0.0), 2),
                "late_call_premium": round(float(late.get("late_call_premium") or 0.0), 2),
                "late_put_premium": round(float(late.get("late_put_premium") or 0.0), 2),
            },
            "source": "sigmatiq_nexus",
        }
        payload.update(narratives.build_option_market_context_narrative(payload))
        return payload

    async def connect(self):
        if REDIS_CLUSTER:
            self.redis = self._connect_cluster(REDIS_URL)
        else:
            self.redis = await redis.from_url(self._redis_url(REDIS_URL), decode_responses=False)
        self._log("redis_connected", cluster=REDIS_CLUSTER)
        await self.restore_active_positions()

    def _connect_cluster(self, value: str):
        # Azure Redis Cluster can redirect slots to node IPs while the TLS
        # certificate is issued for the managed hostname. Keep certificate-chain
        # validation enabled, but disable hostname matching for redirected IPs.
        tls_kwargs = {"ssl_cert_reqs": ssl.CERT_REQUIRED, "ssl_check_hostname": False}
        if value.startswith("redis://") or value.startswith("rediss://"):
            return RedisCluster.from_url(value, decode_responses=False, **tls_kwargs)
        if ",password=" in value:
            host, rest = value.split(",", 1)
            password = rest.split("password=", 1)[1].split(",", 1)[0]
            hostname, port = host.rsplit(":", 1)
            return RedisCluster(host=hostname, port=int(port), password=password, ssl=True, decode_responses=False, **tls_kwargs)
        parsed = urlparse(value)
        return RedisCluster(host=parsed.hostname, port=parsed.port or 6379, password=parsed.password, ssl=parsed.scheme == "rediss", decode_responses=False, **tls_kwargs)

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
        await self.restore_stream_offsets(streams)
        self._log(
            "worker_started",
            symbols=sorted(SYMBOLS),
            first_trigger_scope=FIRST_TRIGGER_SCOPE,
            streams=sorted(streams.keys()),
        )
        while True:
            try:
                replies = await read_input_streams(self.redis, streams)
                if replies:
                    self._log(
                        "stream_batch_received",
                        stream_count=len(replies),
                        message_count=sum(len(messages) for _, messages in replies),
                    )
                for stream, messages in replies:
                        stream_name = stream.decode("utf-8") if isinstance(stream, bytes) else stream
                        for msg_id, data in messages:
                            streams[stream_name] = msg_id
                            await self.process_message(data)
                            await self.persist_stream_offset(stream_name, msg_id)
                await self.evaluate_due_windows(datetime.now(timezone.utc))
            except Exception as e:
                self._log("main_loop_error", error=str(e))
                await asyncio.sleep(1)

    def reset_if_new_session(self, event_dt_utc: datetime):
        current_session_date = ny_session_date(event_dt_utc)
        if current_session_date > self.last_reset_session_date:
            self.signaled_today.clear()
            self.active_positions.clear()
            self.feature_blocks_reported.clear()
            self.window_views_reported.clear()
            self.window_pricing_reported.clear()
            self.option_market_context_reported.clear()
            self.participant_flow_reported.clear()
            self.evaluated_windows.clear()
            self.late_window_impacts.clear()
            self.last_reset_session_date = current_session_date

    async def restore_stream_offsets(self, streams: dict[str, str]) -> None:
        restored = 0
        for stream_name in list(streams):
            raw = await self.redis.get(redis_stream_offset_key(stream_name))
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            streams[stream_name] = str(raw)
            restored += 1
        if restored:
            self._log("stream_offsets_restored", count=restored, streams=streams)

    async def persist_stream_offset(self, stream_name: str, msg_id) -> None:
        if isinstance(msg_id, bytes):
            msg_id = msg_id.decode("utf-8")
        await self.redis.set(redis_stream_offset_key(stream_name), str(msg_id))

    async def restore_active_positions(self, session_date=None):
        session_date = session_date or self.last_reset_session_date
        restored = 0
        for symbol in sorted(SYMBOLS):
            raw = await self.redis.get(redis_active_position_key(session_date, symbol))
            if not raw:
                continue
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                position = json.loads(raw)
            except Exception as exc:
                self._log("active_position_restore_failed", symbol=symbol, session_date=str(session_date), error=str(exc))
                continue
            self.active_positions[symbol] = position
            restored += 1
        if restored:
            self._log("active_positions_restored", session_date=str(session_date), count=restored)

    async def _acquire_final_locks(self, session_date, symbol: str, strategy: str, signal_id: str) -> bool:
        lock_specs = [(redis_symbol_lock_key(session_date, symbol), symbol_lane_key(session_date, symbol))]
        if FIRST_TRIGGER_SCOPE == "strategy":
            lock_specs.append((redis_strategy_lock_key(session_date, symbol, strategy), signal_key(session_date, symbol, strategy)))
        if strategy in GROUP_LOCK_STRATEGIES:
            lock_specs.append((redis_group_lock_key(session_date, strategy), group_lock_key(session_date, strategy)))

        acquired: list[tuple[str, str]] = []
        for redis_key, memory_key in lock_specs:
            locked = await self.redis.set(redis_key, signal_id, nx=True, ex=LOCK_TTL_SECONDS)
            if not locked:
                for acquired_key, _ in acquired:
                    await self.redis.delete(acquired_key)
                self._log("strategy_final_blocked_by_lock", strategy=strategy, symbol=symbol, session_date=str(session_date), lock_key=redis_key)
                return False
            acquired.append((redis_key, memory_key))
        for _, memory_key in acquired:
            self.signaled_today.add(memory_key)
        return True

    async def _persist_active_position(self, session_date, symbol: str, position: dict):
        await self.redis.set(
            redis_active_position_key(session_date, symbol),
            json.dumps(position),
            ex=ACTIVE_POSITION_TTL_SECONDS,
        )

    async def _clear_active_position(self, session_date, symbol: str):
        await self.redis.delete(redis_active_position_key(session_date, symbol))

    async def process_message(self, data):
        try:
            payload = decode_stream_entry(data)
            symbol = str(payload["symbol"]).strip().upper()
            if symbol not in SYMBOLS:
                return

            payload = await enrich_trade_payload_from_redis(payload, self.redis)
            event_dt_utc = parse_event_datetime(payload)
            self.reset_if_new_session(event_dt_utc)

            # --- DYNAMIC RISK MANAGEMENT (EXIT MONITORING) ---
            if symbol in self.active_positions:
                pos = self.active_positions[symbol]
                quote = await self._active_position_quote(symbol, pos, payload)
                curr_price = float(quote.get("option_mid") or 0.0)
                if curr_price > 0:
                    ret = ((curr_price - pos['entry_price']) / pos['entry_price']) * 100
                    
                    # 1. Hard Stop
                    if ret <= STOP_LOSS_PCT:
                        await self._publish_liquidate(symbol, "STOP_LOSS", ret, quote)
                    # 2. Guard Activation
                    elif not pos['is_guarded'] and ret >= GUARD_ACTIVATE_PCT:
                        pos['is_guarded'] = True
                        print(f"🛡️ [GUARD] Breakeven guard activated for {symbol} at +{ret:.1f}%")
                    # 3. Guard Execution
                    elif pos['is_guarded'] and ret <= GUARD_FLOOR_PCT:
                        await self._publish_liquidate(symbol, "GUARD_EXIT", ret, quote)

            if symbol not in self.buffers:
                self.buffers[symbol] = deque(maxlen=self.max_buffer)
            self.buffers[symbol].append(payload)

            await self._record_late_window_event(symbol, payload, event_dt_utc)
            await self.evaluate_due_windows(event_dt_utc)
        except Exception as e:
            self._log("process_message_failed", error=str(e))

    async def _record_late_window_event(self, symbol: str, payload: dict, event_dt_utc: datetime) -> None:
        if not hasattr(self, "late_window_impacts"):
            self.late_window_impacts = {}
        slot = event_window_slot(event_dt_utc)
        if not slot:
            return
        session_date = ny_session_date(event_dt_utc)
        eval_key = window_eval_key(session_date, symbol, slot["entry_label"])
        if eval_key not in self.evaluated_windows:
            return

        premium = _payload_float(payload, "premium") or 0.0
        side = str(payload.get("side") or _option_side_from_raw_symbol(payload.get("raw_symbol")) or "").upper()
        impact = self.late_window_impacts.setdefault(
            eval_key,
            {
                "session_date": str(session_date),
                "symbol": symbol,
                "entry_time": slot["entry_label"],
                "window_start": slot["window_start"].isoformat(),
                "window_end": slot["window_end"].isoformat(),
                "late_event_count": 0,
                "late_total_premium": 0.0,
                "late_call_premium": 0.0,
                "late_put_premium": 0.0,
                "last_event_ts": None,
                "last_raw_symbol": None,
            },
        )
        impact["late_event_count"] += 1
        impact["late_total_premium"] += premium
        if side == "C":
            impact["late_call_premium"] += premium
        elif side == "P":
            impact["late_put_premium"] += premium
        impact["last_event_ts"] = event_dt_utc.isoformat()
        impact["last_raw_symbol"] = payload.get("raw_symbol")

        msg = {
            "message_id": new_message_id(),
            "decision": "WINDOW_LATE_EVENT",
            "symbol": symbol,
            "session_date": str(session_date),
            "entry_time": slot["entry_label"],
            "window_start": slot["window_start"].isoformat(),
            "window_end": slot["window_end"].isoformat(),
            "event_ts": event_dt_utc.isoformat(),
            "raw_symbol": payload.get("raw_symbol"),
            "side": side or None,
            "premium": premium,
            "late_event_count": impact["late_event_count"],
            "late_total_premium": round(float(impact["late_total_premium"]), 2),
            "late_call_premium": round(float(impact["late_call_premium"]), 2),
            "late_put_premium": round(float(impact["late_put_premium"]), 2),
            "source": "sigmatiq_nexus",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        msg.update(narratives.build_window_late_event_narrative(msg))
        redis_key = f"nexus_window_late_event:{symbol}:{slot['entry_label']}"
        await self.redis.set(redis_key, json.dumps(msg))
        await self._append_persistence_event_for_key(redis_key, msg)
        await self._publish("signal:window_late_event", json.dumps(msg))
        self._log(
            "window_late_event_detected",
            symbol=symbol,
            session_date=str(session_date),
            entry_time=slot["entry_label"],
            raw_symbol=payload.get("raw_symbol"),
            side=side or None,
            premium=round(float(premium), 2),
            late_event_count=impact["late_event_count"],
            late_total_premium=round(float(impact["late_total_premium"]), 2),
        )

    def _slot_due(self, reference_dt_utc: datetime, slot: dict) -> bool:
        reference_ny = reference_dt_utc.astimezone(NY)
        due_ny = datetime.combine(reference_ny.date(), slot["entry"], tzinfo=NY) + timedelta(seconds=WINDOW_EVALUATION_GRACE_SECONDS)
        return reference_ny >= due_ny

    async def evaluate_due_windows(self, reference_dt_utc: datetime) -> None:
        session_date = ny_session_date(reference_dt_utc)
        for symbol in sorted(self.buffers):
            if symbol not in SYMBOLS:
                continue
            for slot in MARKET_CONTEXT_WINDOWS:
                if not self._slot_due(reference_dt_utc, slot):
                    continue
                await self.publish_option_market_context_for_slot(symbol, slot, session_date)
                await self.publish_participant_flow_context_for_slot(symbol, slot, session_date)
            for slot in DECISION_SLOTS:
                if not self._slot_due(reference_dt_utc, slot):
                    continue
                key = window_eval_key(session_date, symbol, slot["entry_label"])
                if key in self.evaluated_windows:
                    continue
                self.evaluated_windows.add(key)
                self._log(
                    "window_due_for_evaluation",
                    symbol=symbol,
                    session_date=str(session_date),
                    entry_time=slot["entry_label"],
                    grace_seconds=WINDOW_EVALUATION_GRACE_SECONDS,
                    buffer_size=len(self.buffers.get(symbol, [])),
                )
                await self.evaluate_strategy(symbol, slot, reference_dt_utc)

    async def _publish_liquidate(self, symbol, reason, ret, quote: dict | None = None):
        active_position = self.active_positions.get(symbol, {})
        execution = _quote_execution_snapshot(quote, datetime.now(timezone.utc))
        msg = {
            "message_id": new_message_id(),
            "symbol": symbol,
            "decision": "LIQUIDATE",
            "reason": reason,
            "return_pct": float(ret),
            "signal_id": active_position.get("signal_id"),
            "position_id": active_position.get("position_id"),
            "raw_symbol": active_position.get("raw_symbol"),
            "entry_price": active_position.get("entry_price"),
            "exit_price": quote.get("option_mid") if quote else None,
            "option_bid": quote.get("option_bid") if quote else None,
            "option_ask": quote.get("option_ask") if quote else None,
            "quote_ts": quote.get("quote_ts") if quote else None,
            "quote_age_ms": quote.get("quote_age_ms") if quote else None,
            "quote_freshness": execution["quote_freshness"],
            "quote_valid_until": execution["quote_valid_until"],
            "tradability_bucket": quote.get("tradability_bucket") if quote else None,
            "execution": execution,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "sigmatiq_nexus",
        }
        msg.update(narratives.build_lifecycle_reason_summary(msg))
        if symbol in self.active_positions:
            del self.active_positions[symbol]
        position_session_date = active_position.get("session_date") or ny_session_date(datetime.now(timezone.utc))
        await self._clear_active_position(position_session_date, symbol)
        await self.redis.set(f"nexus_live_overlay:{symbol}", json.dumps(msg))
        await self._append_persistence_event(symbol, msg)
        await self._publish("nexus_live_overlay:updates", symbol)
        self._log("position_liquidated", symbol=symbol, reason=reason, return_pct=round(float(ret), 4))

    def _quote_from_payload(self, symbol: str, raw_symbol: str | None, payload: dict) -> dict:
        return {
            "symbol": symbol,
            "raw_symbol": raw_symbol or payload.get("raw_symbol") or payload.get("rawSymbol"),
            "option_mid": float(payload.get("option_mid") or 0.0),
            "option_bid": _payload_float(payload, "option_bid", "bid"),
            "option_ask": _payload_float(payload, "option_ask", "ask"),
            "quote_ts": _payload_value(payload, "quote_ts_utc", "option_mid_ts_utc", "option_quote_ts_utc", "ts_utc"),
            "quote_age_ms": _payload_float(payload, "quote_age_ms", "quoteAgeMs", "option_quote_age_ms", "optionQuoteAgeMs"),
            "tradability_bucket": _payload_value(payload, "tradability_bucket", "tradabilityBucket"),
        }

    async def _contract_quote_snapshot(self, symbol: str, raw_symbol: str | None) -> dict:
        raw_symbol_variants = _raw_symbol_key_variants(raw_symbol)
        if not raw_symbol_variants:
            return {}
        for tracked_raw_symbol in raw_symbol_variants:
            state_key = CONTRACT_STATE_KEY_TEMPLATE.format(symbol=symbol, raw_symbol=tracked_raw_symbol)
            tradability_key = CONTRACT_TRADABILITY_KEY_TEMPLATE.format(symbol=symbol, raw_symbol=tracked_raw_symbol)
            contract_state, tradability = await asyncio.gather(
                read_json_payload(self.redis, state_key),
                read_json_payload(self.redis, tradability_key),
            )
            if not contract_state and not tradability:
                continue
            exact_payload = {"symbol": symbol, "raw_symbol": tracked_raw_symbol}
            _merge_contract_payload(exact_payload, contract_state)
            _merge_contract_payload(exact_payload, tradability)
            return self._quote_from_payload(symbol, tracked_raw_symbol, exact_payload)
        return {}

    def _quote_is_available(self, quote: dict) -> bool:
        execution = _quote_execution_snapshot(quote, datetime.now(timezone.utc))
        return execution["quote_freshness"] in FRESH_STATUSES and execution["reference_price"] is not None

    async def _spread_candidate(self, df: pl.DataFrame, symbol: str, right: str) -> dict | None:
        if df.is_empty() or not {"raw_symbol", "side", "delta"}.issubset(set(df.columns)):
            return None
        side_df = df.filter(pl.col("side").cast(pl.Utf8).str.to_uppercase() == right)
        if side_df.is_empty():
            return None
        candidates = []
        for row in side_df.to_dicts():
            raw_symbol = str(row.get("raw_symbol") or "").replace(" ", "").upper()
            details = _contract_details_from_raw_symbol(raw_symbol)
            if details["strike"] is None or details["side"] != right:
                continue
            try:
                delta_distance = abs(abs(float(row.get("delta") or 0.0)) - SPREAD_TARGET_DELTA)
                premium = float(row.get("premium") or 0.0)
            except (TypeError, ValueError):
                continue
            candidates.append((delta_distance, -premium, raw_symbol, details))
        if not candidates:
            return None
        _, _, short_raw_symbol, short_details = sorted(candidates)[0]
        short_strike = float(short_details["strike"])
        long_strike = short_strike + SPREAD_STRIKE_WIDTH if right == "C" else short_strike - SPREAD_STRIKE_WIDTH
        long_raw_symbol = _raw_symbol_with_strike(short_raw_symbol, long_strike)
        if not long_raw_symbol:
            return None
        short_quote, long_quote = await asyncio.gather(
            self._contract_quote_snapshot(symbol, short_raw_symbol),
            self._contract_quote_snapshot(symbol, long_raw_symbol),
        )
        if not self._quote_is_available(short_quote) or not self._quote_is_available(long_quote):
            return None
        short_bid = short_quote.get("option_bid")
        long_ask = long_quote.get("option_ask")
        if short_bid is None or long_ask is None:
            return None
        net_credit = float(short_bid) - float(long_ask)
        if net_credit < SPREAD_MIN_ENTRY_CREDIT:
            return None
        max_loss = max(SPREAD_STRIKE_WIDTH - net_credit, 0.0)
        return {
            "structure": "credit_spread",
            "spread_type": "put_credit" if right == "P" else "call_credit",
            "right": right,
            "short_raw_symbol": short_raw_symbol,
            "long_raw_symbol": long_raw_symbol,
            "short_strike": short_strike,
            "long_strike": long_strike,
            "expiry_date": short_details["expiry_date"],
            "net_credit": round(net_credit, 4),
            "strike_width": SPREAD_STRIKE_WIDTH,
            "max_loss": round(max_loss, 4),
            "max_loss_assumption": "AT_EXPIRATION_NO_ASSIGNMENT",
            "legs": [
                {
                    "raw_symbol": short_raw_symbol,
                    "action": "SELL",
                    "ratio": -1,
                    "side": right,
                    "strike": short_strike,
                    "expiry_date": short_details["expiry_date"],
                    "quote": short_quote,
                },
                {
                    "raw_symbol": long_raw_symbol,
                    "action": "BUY",
                    "ratio": 1,
                    "side": right,
                    "strike": long_strike,
                    "expiry_date": short_details["expiry_date"],
                    "quote": long_quote,
                },
            ],
        }

    async def _active_position_quote(self, symbol: str, position: dict, payload: dict) -> dict:
        tracked_raw_symbol = normalize_raw_symbol(position.get("raw_symbol"))
        if not tracked_raw_symbol:
            return self._quote_from_payload(symbol, None, payload)

        payload_raw_symbol = normalize_raw_symbol(payload.get("raw_symbol") or payload.get("rawSymbol"))
        if payload_raw_symbol == tracked_raw_symbol:
            return self._quote_from_payload(symbol, tracked_raw_symbol, payload)

        return await self._contract_quote_snapshot(symbol, tracked_raw_symbol)

    async def evaluate_strategy(self, symbol, slot: dict, event_dt_utc: datetime):
        session_date = ny_session_date(event_dt_utc)
        trade_locked = self.already_signaled(session_date, symbol, "*")

        # --- GLOBAL QUALITY FILTERS ---
        iv_rank, atm_iv, net_gex = await self.get_context(symbol)
        if net_gex < -2e9: # Skip deep negative GEX (unstable)
            self._log("window_skipped", symbol=symbol, session_date=str(session_date), reason="net_gex_below_floor", net_gex=net_gex, entry_time=slot["entry_label"])
            return
        if iv_rank < 10: # Skip options that are too cheap (dead zone)
            self._log("window_skipped", symbol=symbol, session_date=str(session_date), reason="iv_rank_below_floor", iv_rank=iv_rank, entry_time=slot["entry_label"])
            return

        slot_df = window_df_for_slot(pl.DataFrame(list(self.buffers[symbol])), slot)
        if slot_df.height == 0:
            self._log("window_skipped", symbol=symbol, session_date=str(session_date), reason="empty_window", entry_time=slot["entry_label"])
            return
        self._log(
            "window_evaluation_started",
            symbol=symbol,
            session_date=str(session_date),
            iv_rank=round(iv_rank, 4),
            atm_iv=round(atm_iv, 6),
            net_gex=round(net_gex, 2),
            trade_locked=trade_locked,
            **self._window_log_fields(slot_df, slot),
        )
        await self.publish_window_pricing(slot_df, symbol, slot, session_date)
        await self.publish_window_assessments(slot_df, symbol, slot, session_date)
        if trade_locked:
            self._log("trade_evaluation_skipped", symbol=symbol, session_date=str(session_date), reason="already_signaled", entry_time=slot["entry_label"])
            return

        # Deterministic order follows the research log: confluence first, then
        # the specialist assigned to the completed window. First trigger wins.
        await self.evaluate_confluence_sniper(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*") and slot["entry_label"] == "10:00":
            await self.evaluate_put_credit_open30_spread(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*") and slot["entry_label"] == "10:00":
            await self.evaluate_call_credit_open30_spread(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*") and slot["entry_label"] == "10:00":
            await self.evaluate_open_specialist(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*"):
            await self.evaluate_low_sweep_core(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*") and slot["entry_label"] == "10:30":
            await self.evaluate_flow_specialist(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*") and slot["entry_label"] == "11:00":
            await self.evaluate_momentum_specialist(slot_df, symbol, slot, session_date)

    def already_signaled(self, session_date, symbol: str, strategy: str) -> bool:
        if symbol_lane_key(session_date, symbol) in self.signaled_today:
            return True
        if strategy in GROUP_LOCK_STRATEGIES and group_lock_key(session_date, strategy) in self.signaled_today:
            return True
        if FIRST_TRIGGER_SCOPE == "strategy" and signal_key(session_date, symbol, strategy) in self.signaled_today:
            return True
        return False

    async def get_context(self, symbol: str) -> tuple[float, float, float]:
        iv_rank, atm_iv, net_gex, _ = await self.get_context_with_quality(symbol)
        return iv_rank, atm_iv, net_gex

    async def get_context_with_quality(self, symbol: str, reference_time: datetime | None = None) -> tuple[float, float, float, dict[str, str]]:
        iv_rank_raw = await self.redis.get(IV_RANK_KEY_TEMPLATE.format(symbol=symbol))
        atm_iv_raw = await self.redis.get(ATM_IV_KEY_TEMPLATE.format(symbol=symbol))
        net_gex_raw = await self.redis.get(NET_GEX_KEY_TEMPLATE.format(symbol=symbol))
        context_status = {
            "iv_rank": "unknown_freshness" if iv_rank_raw and NEXUS_REQUIRE_CONTEXT_TIMESTAMPS else "available" if iv_rank_raw else "missing",
            "atm_iv": "unknown_freshness" if atm_iv_raw and NEXUS_REQUIRE_CONTEXT_TIMESTAMPS else "available" if atm_iv_raw else "missing",
            "net_gex": "unknown_freshness" if net_gex_raw and NEXUS_REQUIRE_CONTEXT_TIMESTAMPS else "available" if net_gex_raw else "missing",
        }
        iv_rank = float(iv_rank_raw or 50.0)
        atm_iv = float(atm_iv_raw or 0.15)
        net_gex = float(net_gex_raw or 0.0)
        if not atm_iv_raw:
            atm_iv, found, payload = await self._context_float_with_status(IV_SURFACE_KEY_TEMPLATE.format(symbol=symbol), "atmIv", atm_iv)
            if found:
                context_status["atm_iv"] = self._context_freshness_status(payload, reference_time, "atm_iv")
        if not net_gex_raw:
            net_gex, found, payload = await self._context_float_with_status(GEX_KEY_TEMPLATE.format(symbol=symbol), "netGex", net_gex)
            if found:
                context_status["net_gex"] = self._context_freshness_status(payload, reference_time, "net_gex")
        if not iv_rank_raw:
            iv_rank, found, payload = await self._iv_rank_from_vrp_with_status(symbol, iv_rank)
            if found:
                context_status["iv_rank"] = self._context_freshness_status(payload, reference_time, "iv_rank")
        return iv_rank, atm_iv, net_gex, context_status

    async def _context_float(self, key: str, field: str, default: float) -> float:
        value, _, _ = await self._context_float_with_status(key, field, default)
        return value

    async def _context_float_with_status(self, key: str, field: str, default: float) -> tuple[float, bool, dict]:
        raw = await self.redis.get(key)
        if not raw:
            return default, False, {}
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            value = payload.get(field)
            return (float(value), True, payload) if value is not None else (default, False, payload)
        except Exception:
            return default, False, {}

    async def _iv_rank_from_vrp(self, symbol: str, default: float) -> float:
        value, _, _ = await self._iv_rank_from_vrp_with_status(symbol, default)
        return value

    async def _iv_rank_from_vrp_with_status(self, symbol: str, default: float) -> tuple[float, bool, dict]:
        raw = await self.redis.get(VRP_KEY_TEMPLATE.format(symbol=symbol))
        if not raw:
            return default, False, {}
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if payload.get("ivRank") is not None:
                return float(payload["ivRank"]), True, payload
            regime = str(payload.get("vrpRegime") or "").lower()
            mapped = {"cheap": 20.0, "fair": 50.0, "moderate": 60.0, "rich": 80.0, "elevated": 90.0}.get(regime)
            return (mapped, True, payload) if mapped is not None else (default, False, payload)
        except Exception:
            return default, False, {}

    def _context_freshness_status(self, payload: dict, reference_time: datetime | None, feature: str) -> str:
        feature_time = _payload_datetime(payload, CONTEXT_TIMESTAMP_FIELDS)
        if not feature_time and NEXUS_REQUIRE_CONTEXT_TIMESTAMPS:
            return "unknown_freshness"
        max_age = FEATURE_MAX_AGE_SECONDS[feature]
        status = _freshness_status(reference_time, feature_time, max_age, missing_is_stale=NEXUS_REQUIRE_CONTEXT_TIMESTAMPS)
        return "fallback" if status == "available" else status

    async def _strategy_features_ready(self, strategy: str, symbol: str, df: pl.DataFrame, slot: dict, session_date) -> bool:
        failures = await self._strategy_feature_failures(strategy, symbol, df)
        if not failures:
            return True
        await self._publish_feature_block(strategy, symbol, slot, session_date, failures)
        return False

    async def _missing_strategy_features(self, strategy: str, symbol: str, df: pl.DataFrame) -> list[str]:
        return sorted((await self._strategy_feature_failures(strategy, symbol, df)).keys())

    async def _strategy_feature_failures(self, strategy: str, symbol: str, df: pl.DataFrame) -> dict[str, str]:
        required = STRATEGY_REQUIRED_FEATURES[strategy]
        failures = {}
        for feature in required:
            if feature in EVENT_FEATURES:
                status = self._window_event_feature_status(df, feature)
                if status not in FRESH_STATUSES:
                    failures[feature] = status
        context_required = [feature for feature in required if feature in CONTEXT_FEATURES]
        if context_required:
            _, _, _, context_status = await self.get_context_with_quality(symbol, self._window_reference_time(df))
            for feature in context_required:
                status = context_status.get(feature, "missing")
                if status not in FRESH_STATUSES:
                    failures[feature] = status
        return failures

    def _window_reference_time(self, df: pl.DataFrame) -> datetime | None:
        if df.is_empty() or "ts_utc" not in df.columns:
            return None
        times = [parse_optional_datetime(row.get("ts_utc")) for row in df.to_dicts()]
        times = [dt for dt in times if dt]
        return max(times) if times else None

    def _window_event_feature_status(self, df: pl.DataFrame, feature: str) -> str:
        if df.is_empty():
            return "missing"
        if "_feature_status" in df.columns:
            statuses = []
            for row in df.to_dicts():
                status_map = row.get("_feature_status") or {}
                if isinstance(status_map, dict) and feature in status_map:
                    statuses.append(status_map.get(feature) or "missing")
            if any(status in FRESH_STATUSES for status in statuses):
                return "available"
            if statuses:
                return statuses[0]
        if feature == "is_sweep":
            return "available" if "is_sweep" in df.columns else "missing"
        if feature not in df.columns:
            return "missing"
        return "available" if df.select(pl.col(feature).is_not_null().any()).item() else "missing"

    async def _publish_feature_block(self, strategy: str, symbol: str, slot: dict, session_date, failures: dict[str, str]):
        key = (str(session_date), symbol, strategy, slot["entry_label"])
        reported = getattr(self, "feature_blocks_reported", set())
        if key in reported:
            return
        reported.add(key)
        self.feature_blocks_reported = reported
        missing = sorted(failures.keys())
        msg = {
            "strategy": strategy,
            "symbol": symbol,
            "stage": 0,
            "decision": "BLOCKED",
            "block_reason": "live_feature_quality_gate_closed",
            "missing_features": missing,
            "feature_failures": failures,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_date": str(session_date),
            "entry_time": slot["entry_label"],
            "window_start": slot["window_start"].isoformat(),
            "window_end": slot["window_end"].isoformat(),
            "source": "sigmatiq_nexus",
        }
        msg.update(narratives.build_lifecycle_reason_summary(msg))
        self._log(
            "strategy_blocked",
            strategy=strategy,
            symbol=symbol,
            session_date=str(session_date),
            feature_failures=failures,
            **self._window_log_fields(pl.DataFrame(), slot),
        )
        redis_key = f"nexus_window_view:{symbol}:{strategy}:{slot['entry_label']}"
        await self.redis.set(redis_key, json.dumps(msg))
        await self._append_persistence_event_for_key(redis_key, msg)
        await self._publish(f"signal:window_view:{strategy}", json.dumps(msg))

    async def _publish_window_view(self, strategy: str, symbol: str, sentiment: str, reason: str, slot: dict, session_date) -> None:
        key = (str(session_date), symbol, strategy, slot["entry_label"])
        reported = getattr(self, "window_views_reported", set())
        if key in reported:
            return
        reported.add(key)
        self.window_views_reported = reported
        msg = {
            "strategy": strategy,
            "symbol": symbol,
            "stage": 0,
            "decision": "WINDOW_VIEW",
            "sentiment": sentiment,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_date": str(session_date),
            "entry_time": slot["entry_label"],
            "window_start": slot["window_start"].isoformat(),
            "window_end": slot["window_end"].isoformat(),
            "source": "sigmatiq_nexus",
        }
        lead_contract = self._window_lead_contract(getattr(self, "_current_window_df", pl.DataFrame()))
        pricing_summary = getattr(self, "_current_window_pricing_summary", {}) or {}
        profiles = pricing_summary.get("profiles") or []
        lead_pricing = next((p for p in profiles if p["raw_symbol"] == lead_contract["raw_symbol"]), None)
        msg["lead_contract_raw_symbol"] = lead_contract["raw_symbol"]
        msg["lead_contract_expiry_date"] = lead_contract["expiry_date"]
        msg["lead_contract_strike"] = lead_contract["strike"]
        msg["lead_contract_side"] = lead_contract["side"]
        msg["lead_contract_pricing_lag"] = lead_pricing["pricing_lag"] if lead_pricing else None
        msg["lead_contract_cheapness_score"] = lead_pricing["cheapness_score"] if lead_pricing else None
        msg.update(narratives.build_window_view_narrative(msg))
        redis_key = f"nexus_window_view:{symbol}:{strategy}:{slot['entry_label']}"
        await self.redis.set(redis_key, json.dumps(msg))
        await self._append_persistence_event_for_key(redis_key, msg)
        await self._publish(f"signal:window_view:{strategy}", json.dumps(msg))
        self._log("strategy_window_view_published", strategy=strategy, symbol=symbol, sentiment=sentiment, reason=reason, session_date=str(session_date), entry_time=slot["entry_label"])

    async def publish_window_pricing(self, df: pl.DataFrame, symbol: str, slot: dict, session_date) -> None:
        key = (str(session_date), symbol, slot["entry_label"])
        reported = getattr(self, "window_pricing_reported", set())
        if key in reported:
            return
        reported.add(key)
        self.window_pricing_reported = reported
        summary = self._window_pricing_summary(df)
        self._current_window_pricing_summary = summary
        cheap = summary["cheap_contract"]
        costly = summary["costly_contract"]
        msg = {
            "symbol": symbol,
            "stage": 0,
            "decision": "WINDOW_PRICING",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_date": str(session_date),
            "entry_time": slot["entry_label"],
            "window_start": slot["window_start"].isoformat(),
            "window_end": slot["window_end"].isoformat(),
            "evaluated_contract_count": summary["evaluated_contract_count"],
            "cheap_contract_raw_symbol": cheap["raw_symbol"] if cheap else None,
            "cheap_contract_expiry_date": cheap["expiry_date"] if cheap else None,
            "cheap_contract_strike": cheap["strike"] if cheap else None,
            "cheap_contract_side": cheap["side"] if cheap else None,
            "cheap_contract_pricing_lag": cheap["pricing_lag"] if cheap else None,
            "cheap_contract_cheapness_score": cheap["cheapness_score"] if cheap else None,
            "costly_contract_raw_symbol": costly["raw_symbol"] if costly else None,
            "costly_contract_expiry_date": costly["expiry_date"] if costly else None,
            "costly_contract_strike": costly["strike"] if costly else None,
            "costly_contract_side": costly["side"] if costly else None,
            "costly_contract_pricing_lag": costly["pricing_lag"] if costly else None,
            "costly_contract_cheapness_score": costly["cheapness_score"] if costly else None,
            "cheap_side": summary["cheap_side"],
            "cheap_side_avg_pricing_lag": summary["cheap_side_avg_pricing_lag"],
            "costly_side": summary["costly_side"],
            "costly_side_avg_pricing_lag": summary["costly_side_avg_pricing_lag"],
            "source": "sigmatiq_nexus",
        }
        msg.update(narratives.build_window_pricing_narrative(msg))
        redis_key = f"nexus_window_pricing:{symbol}:{slot['entry_label']}"
        await self.redis.set(redis_key, json.dumps(msg))
        await self._append_persistence_event_for_key(redis_key, msg)
        await self._publish("signal:window_pricing", json.dumps(msg))
        self._log("window_pricing_published", symbol=symbol, session_date=str(session_date), entry_time=slot["entry_label"], evaluated_contract_count=summary["evaluated_contract_count"])

    async def publish_option_market_context_for_slot(self, symbol: str, slot: dict, session_date) -> None:
        key = (str(session_date), symbol, slot["entry_label"])
        reported = getattr(self, "option_market_context_reported", set())
        if key in reported:
            return
        if symbol not in self.buffers:
            return
        df = window_df_for_slot(pl.DataFrame(list(self.buffers[symbol])), slot)
        if df.is_empty():
            return
        reported.add(key)
        self.option_market_context_reported = reported
        msg = self._option_market_context_payload(df, symbol, slot, session_date)
        redis_key = f"nexus_option_market_context:{symbol}:{slot['entry_label']}"
        await self.redis.set(redis_key, json.dumps(msg))
        await self.redis.set(f"nexus_option_market_context:{symbol}:latest", json.dumps(msg))
        await self._append_persistence_event_for_key(redis_key, msg)
        await self._publish("signal:option_market_context", json.dumps(msg))
        self._log(
            "option_market_context_published",
            symbol=symbol,
            session_date=str(session_date),
            window_id=slot["entry_label"],
            trade_count=msg["activity"]["trade_count"],
            contract_count=msg["activity"]["contract_count"],
            pricing_quality=msg["pricing_quality"],
        )

    async def publish_participant_flow_context_for_slot(self, symbol: str, slot: dict, session_date) -> None:
        key = (str(session_date), symbol, slot["entry_label"])
        reported = getattr(self, "participant_flow_reported", set())
        if key in reported:
            return
        if symbol not in self.buffers:
            return
        df = window_df_for_slot(pl.DataFrame(list(self.buffers[symbol])), slot)
        if df.is_empty():
            return
        msg = pf.build_participant_flow_payload(df, symbol, slot, session_date, pf.PARTICIPANT_FLOW_DEFAULT_CONFIG)
        redis_key = f"nexus_participant_flow_context:{symbol}:{slot['entry_label']}"
        await self.redis.set(redis_key, json.dumps(msg), ex=48 * 3600)
        await self.redis.set(f"nexus_participant_flow_context:{symbol}:latest", json.dumps(msg), ex=8 * 3600)
        await self._append_persistence_event_for_key(redis_key, msg)
        await self._publish("signal:participant_flow_context", json.dumps(msg))
        # Mark reported only after all writes succeed
        reported.add(key)
        self.participant_flow_reported = reported
        self._log(
            "participant_flow_context_published",
            symbol=symbol,
            session_date=str(session_date),
            window_key=slot["entry_label"],
            directional_read=msg.get("window_side_read", {}).get("directional_read"),
            data_quality=msg.get("data_quality", {}).get("status"),
        )

    async def publish_window_assessments(self, df: pl.DataFrame, symbol: str, slot: dict, session_date) -> None:
        self._current_window_df = df
        strategies = [
            ("etf_confluence_sniper", self.assess_confluence_window),
            ("etf_open_specialist", self.assess_open_specialist_window),
            ("etf_low_sweep_core", self.assess_low_sweep_window),
            ("etf_flow_specialist", self.assess_flow_window),
            ("etf_momentum_specialist", self.assess_momentum_window),
            ("etf_put_credit_open30_spread", self.assess_put_credit_open30_spread),
            ("etf_call_credit_open30_spread", self.assess_call_credit_open30_spread),
        ]
        for strategy, assessor in strategies:
            failures = await self._strategy_feature_failures(strategy, symbol, df)
            if failures:
                await self._publish_feature_block(strategy, symbol, slot, session_date, failures)
                continue
            sentiment, reason = await assessor(df, symbol, slot)
            await self._publish_window_view(strategy, symbol, sentiment, reason, slot, session_date)
        self._current_window_df = pl.DataFrame()
        self._current_window_pricing_summary = {}

    def _get_lead_contract_quote(self, df: pl.DataFrame, sentiment: str) -> tuple[str | None, float]:
        side = "C" if sentiment == "BULLISH" else "P"
        side_df = df.filter(pl.col("side").cast(pl.Utf8).str.to_uppercase() == side)
        if side_df.is_empty():
            return None, 0.0
        lead = side_df.group_by("raw_symbol").agg(pl.col("premium").cast(pl.Float64, strict=False).fill_null(0).sum().alias("tp")).sort("tp", descending=True).head(1)
        if lead.is_empty():
            return None, 0.0
        price_col = "option_mid" if "option_mid" in df.columns else "price"
        raw_symbol = lead[0, "raw_symbol"]
        price = float(side_df.filter(pl.col("raw_symbol") == raw_symbol).tail(1).select(pl.col(price_col)).item() or 0.0)
        return raw_symbol, price

    async def evaluate_confluence_sniper(self, df, symbol, slot: dict, session_date):
        strategy = "etf_confluence_sniper"
        if self.already_signaled(session_date, symbol, strategy):
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
            return
        sentiment, valid, p_feat = await self.check_momentum_heuristics(df, symbol)
        if not valid:
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="momentum_heuristic_not_met", **self._window_log_fields(df, slot))
            return
        pricing_lag = self.calculate_pricing_lag(df, sentiment)
        if pricing_lag is None or pricing_lag > -0.05:
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="pricing_lag_not_cheap_enough", pricing_lag=pricing_lag, sentiment=sentiment, **self._window_log_fields(df, slot))
            return
        lead_raw_symbol, price = self._get_lead_contract_quote(df, sentiment)
        await self._publish_intermediate(strategy, symbol, sentiment, slot, session_date, lead_raw_symbol)
        await self._publish_final(strategy, symbol, sentiment, 1.0, price, session_date, slot, lead_raw_symbol)

    async def assess_confluence_window(self, df, symbol, slot: dict):
        sentiment, valid, _ = await self.check_momentum_heuristics(df, symbol)
        if not valid or not sentiment:
            return "CHOP", "momentum_heuristic_not_met"
        pricing_lag = self.calculate_pricing_lag(df, sentiment)
        if pricing_lag is None or pricing_lag > -0.05:
            return "CHOP", "pricing_lag_not_cheap_enough"
        return sentiment, "confluence_alignment"

    async def evaluate_put_credit_open30_spread(self, df, symbol, slot: dict, session_date):
        strategy = "etf_put_credit_open30_spread"
        if self.already_signaled(session_date, symbol, strategy) or slot["entry_label"] != "10:00" or symbol not in {"SPY", "QQQ"}:
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
            return
        sentiment, valid = await self.check_put_credit_open30_spread(df, symbol, slot)
        if not valid:
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="put_credit_open30_heuristic_not_met", **self._window_log_fields(df, slot))
            return
        candidate = await self._spread_candidate(df, symbol, "P")
        if not candidate:
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="no_valid_put_credit_spread_candidate", **self._window_log_fields(df, slot))
            return
        await self._publish_intermediate(strategy, symbol, sentiment, slot, session_date, candidate["short_raw_symbol"])
        await self._publish_spread_final(strategy, symbol, sentiment, 1.0, session_date, slot, candidate)

    async def check_put_credit_open30_spread(self, df, symbol, slot: dict):
        if slot["entry_label"] != "10:00" or symbol not in {"SPY", "QQQ"}:
            return None, False
        stats = window_stats(df)
        if stats["total_p"] < MIN_WINDOW_PREMIUM:
            return None, False
        iv_rank, _, _ = await self.get_context(symbol)
        if iv_rank >= SPREAD_MAX_IV_RANK:
            return None, False
        if stats["call_p"] < stats["put_p"] * OPEN_CALL_DOMINANCE:
            return None, False
        return "BULLISH", True

    async def assess_put_credit_open30_spread(self, df, symbol, slot: dict):
        sentiment, valid = await self.check_put_credit_open30_spread(df, symbol, slot)
        return (sentiment, "open30_call_dominance_put_credit_context") if valid else ("CHOP", "put_credit_open30_filter_not_met")

    async def evaluate_call_credit_open30_spread(self, df, symbol, slot: dict, session_date):
        strategy = "etf_call_credit_open30_spread"
        if self.already_signaled(session_date, symbol, strategy) or slot["entry_label"] != "10:00" or symbol != "SPY":
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
            return
        sentiment, valid = await self.check_call_credit_open30_spread(df, symbol, slot)
        if not valid:
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="call_credit_open30_heuristic_not_met", **self._window_log_fields(df, slot))
            return
        candidate = await self._spread_candidate(df, symbol, "C")
        if not candidate:
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="no_valid_call_credit_spread_candidate", **self._window_log_fields(df, slot))
            return
        await self._publish_intermediate(strategy, symbol, sentiment, slot, session_date, candidate["short_raw_symbol"])
        await self._publish_spread_final(strategy, symbol, sentiment, 1.0, session_date, slot, candidate)

    async def check_call_credit_open30_spread(self, df, symbol, slot: dict):
        if slot["entry_label"] != "10:00" or symbol != "SPY":
            return None, False
        stats = window_stats(df)
        if stats["total_p"] < MIN_WINDOW_PREMIUM:
            return None, False
        iv_rank, _, _ = await self.get_context(symbol)
        if iv_rank >= SPREAD_MAX_IV_RANK:
            return None, False
        if stats["put_p"] < stats["call_p"] * OPEN_CALL_DOMINANCE:
            return None, False
        return "BEARISH", True

    async def assess_call_credit_open30_spread(self, df, symbol, slot: dict):
        sentiment, valid = await self.check_call_credit_open30_spread(df, symbol, slot)
        return (sentiment, "open30_put_dominance_call_credit_context") if valid else ("CHOP", "call_credit_open30_filter_not_met")

    def calculate_pricing_lag(self, df, sentiment: str) -> float | None:
        required = {"ts_utc", "raw_symbol", "underlying_mid", "delta"}
        if not required.issubset(set(df.columns)):
            return None
        price_col = "option_mid" if "option_mid" in df.columns else "price" if "price" in df.columns else None
        if price_col is None:
            return None
        side = "C" if sentiment == "BULLISH" else "P"
        side_df = df.filter(pl.col("side").cast(pl.Utf8).str.to_uppercase() == side)
        if side_df.is_empty():
            return None
        lead = (
            side_df.group_by("raw_symbol")
            .agg(pl.col("premium").cast(pl.Float64, strict=False).fill_null(0).sum().alias("total_premium"))
            .sort("total_premium", descending=True)
            .head(1)
        )
        if lead.is_empty():
            return None
        raw_symbol = lead[0, "raw_symbol"]
        hist = (
            side_df.filter(pl.col("raw_symbol") == raw_symbol)
            .with_columns(pl.col("ts_utc").str.to_datetime(strict=False, time_zone="UTC").alias("_dt_utc"))
            .sort("_dt_utc")
        )
        if hist.height < 2:
            return None
        end = hist.tail(1)
        end_ts = end[0, "_dt_utc"]
        start = hist.filter(pl.col("_dt_utc") <= end_ts - timedelta(minutes=5)).tail(1)
        if start.is_empty():
            return None
        p_start = float(start[0, price_col] or 0.0)
        p_now = float(end[0, price_col] or 0.0)
        s_start = float(start[0, "underlying_mid"] or 0.0)
        s_now = float(end[0, "underlying_mid"] or 0.0)
        delta = float(start[0, "delta"] or 0.0)
        if p_start <= 0:
            return None
        actual_change = p_now - p_start
        expected_change = delta * (s_now - s_start)
        return (actual_change - expected_change) / (p_start + 1e-9)

    async def evaluate_open_specialist(self, df, symbol, slot: dict, session_date):
        strategy = "etf_open_specialist"
        if self.already_signaled(session_date, symbol, strategy) or slot["entry_label"] != "10:00":
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
            return
        sentiment, valid = await self.check_open_specialist_heuristic(df, symbol, slot)
        if valid:
            lead_raw_symbol, price = self._get_lead_contract_quote(df, sentiment)
            await self._publish_intermediate(strategy, symbol, sentiment, slot, session_date, lead_raw_symbol)
            await self._publish_final(strategy, symbol, sentiment, 0.95, price, session_date, slot, lead_raw_symbol)
        else:
            iv_rank, _, _ = await self.get_context(symbol)
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="open_specialist_heuristic_not_met", iv_rank=round(iv_rank, 4), **self._window_log_fields(df, slot))

    async def check_open_specialist_heuristic(self, df, symbol, slot: dict):
        if slot["entry_label"] != "10:00":
            return None, False
        iv_rank, _, _ = await self.get_context(symbol)
        if iv_rank >= 30:
            return None, False
        stats = window_stats(df)
        if stats["call_p"] < MIN_WINDOW_PREMIUM:
            return None, False
        if stats["put_p"] > 0 and stats["call_p"] < stats["put_p"] * OPEN_CALL_DOMINANCE:
            return None, False
        return "BULLISH", True

    async def assess_open_specialist_window(self, df, symbol, slot: dict):
        iv_rank, _, _ = await self.get_context(symbol)
        stats = window_stats(df)
        if iv_rank >= 30 or stats["total_p"] < MIN_WINDOW_PREMIUM:
            return "CHOP", "cheap_vol_or_premium_filter_not_met"
        if stats["call_p"] > stats["put_p"] * OPEN_CALL_DOMINANCE:
            return "BULLISH", "call_dominance"
        if stats["put_p"] > stats["call_p"] * OPEN_CALL_DOMINANCE:
            return "BEARISH", "put_dominance"
        return "CHOP", "no_open_dominance"

    async def evaluate_low_sweep_core(self, df, symbol, slot: dict, session_date):
        strategy = "etf_low_sweep_core"
        if self.already_signaled(session_date, symbol, strategy):
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
            return
        sentiment, valid = await self.calculate_low_sweep_heuristic(df, slot)
        if valid:
            lead_raw_symbol, price = self._get_lead_contract_quote(df, sentiment)
            await self._publish_intermediate(strategy, symbol, sentiment, slot, session_date, lead_raw_symbol)
            await self._publish_final(strategy, symbol, sentiment, 1.0, price, session_date, slot, lead_raw_symbol)
        else:
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="low_sweep_heuristic_not_met", **self._window_log_fields(df, slot))

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

    async def assess_low_sweep_window(self, df, symbol, slot: dict):
        stats = window_stats(df)
        side = dominant_side(stats)
        if stats["total_p"] < MIN_WINDOW_PREMIUM:
            return "CHOP", "premium_below_threshold"
        if stats["sweep"] > 0.10:
            return "CHOP", "sweep_ratio_too_high"
        if side == "C":
            return "BULLISH", "low_sweep_call_dominance"
        if side == "P":
            return "BEARISH", "low_sweep_put_dominance"
        return "CHOP", "no_dominant_side"

    async def evaluate_flow_specialist(self, df, symbol, slot: dict, session_date):
        strategy = "etf_flow_specialist"
        if self.already_signaled(session_date, symbol, strategy):
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
            return
        sentiment, valid = await self.check_flow_heuristics(df, symbol, slot)
        if valid:
            await self._publish_intermediate(strategy, symbol, sentiment, slot, session_date)
            prob = await self.predict_v6(df, symbol)
            if prob > 0.45:
                lead_raw_symbol, price = self._get_lead_contract_quote(df, sentiment)
                await self._publish_final(strategy, symbol, sentiment, prob, price, session_date, slot, lead_raw_symbol)
            else:
                self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="v6_probability_below_threshold", probability=round(prob, 4), sentiment=sentiment, **self._window_log_fields(df, slot))
        else:
            iv_rank, atm_iv, net_gex = await self.get_context(symbol)
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="flow_heuristic_not_met", iv_rank=round(iv_rank, 4), atm_iv=round(atm_iv, 6), net_gex=round(net_gex, 2), **self._window_log_fields(df, slot))

    async def assess_flow_window(self, df, symbol, slot: dict):
        sentiment, valid = await self.check_flow_heuristics(df, symbol, slot)
        return (sentiment, "flow_alignment") if valid and sentiment else ("CHOP", "flow_heuristic_not_met")

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
        strategy = "etf_momentum_specialist"
        if self.already_signaled(session_date, symbol, strategy):
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
            return
        sentiment, valid, p_feat = await self.check_momentum_heuristics(df, symbol)
        if valid:
            await self._publish_intermediate(strategy, symbol, sentiment, slot, session_date)
            prob = await self.predict_v10(df, symbol, p_feat)
            if prob > 0.55:
                lead_raw_symbol, price = self._get_lead_contract_quote(df, sentiment)
                await self._publish_final(strategy, symbol, sentiment, prob, price, session_date, slot, lead_raw_symbol)
            else:
                self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="v10_probability_below_threshold", probability=round(prob, 4), sentiment=sentiment, price_features=p_feat, **self._window_log_fields(df, slot))
        else:
            iv_rank, _, _ = await self.get_context(symbol)
            self._log("strategy_no_signal", strategy=strategy, symbol=symbol, session_date=str(session_date), reason="momentum_heuristic_not_met", iv_rank=round(iv_rank, 4), **self._window_log_fields(df, slot))

    async def assess_momentum_window(self, df, symbol, slot: dict):
        sentiment, valid, _ = await self.check_momentum_heuristics(df, symbol)
        return (sentiment, "price_persistence_alignment") if valid and sentiment else ("CHOP", "momentum_heuristic_not_met")

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
            self._log("momentum_calc_error", symbol=symbol, error=str(e))
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

    async def _publish_intermediate(self, strategy, symbol, sentiment, slot: dict | None = None, session_date=None, raw_symbol: str | None = None):
        signal_id = build_signal_id(strategy, symbol, session_date, slot, raw_symbol)
        msg = {
            "message_id": new_message_id(),
            "signal_id": signal_id,
            "position_id": signal_id,
            "strategy": strategy,
            "symbol": symbol,
            "stage": 1,
            "decision": "INTERMEDIATE",
            "sentiment": sentiment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "sigmatiq_nexus",
        }
        if raw_symbol:
            msg["raw_symbol"] = raw_symbol
        if slot:
            msg.update({"entry_time": slot["entry_label"], "window_start": slot["window_start"].isoformat(), "window_end": slot["window_end"].isoformat()})
        if session_date:
            msg["session_date"] = str(session_date)
        msg.update(narratives.build_lifecycle_reason_summary(msg))
        entry_label = slot["entry_label"] if slot else "na"
        redis_key = f"nexus_intermediate:{symbol}:{strategy}:{entry_label}"
        await self.redis.set(redis_key, json.dumps(msg))
        await self._append_persistence_event_for_key(redis_key, msg)
        await self._publish("nexus_intermediate:updates", symbol)
        await self._publish(f"signal:intermediate:{strategy}", json.dumps(msg))
        self._log("strategy_intermediate_published", strategy=strategy, symbol=symbol, sentiment=sentiment, entry_time=slot["entry_label"] if slot else None)

    async def _publish_final(self, strategy: str, symbol: str, sentiment: str, confidence: float, entry_price: float = 0.0, session_date=None, slot: dict | None = None, raw_symbol: str | None = None):
        # --- TOURNAMENT WHITELIST CHECK (Best Practical Combo) ---
        # Exclude: SPY open calls and QQQ momentum puts
        # Use: QQQ open calls, QQQ flow calls/puts, QQQ momentum calls, SPY flow calls/puts, SPY momentum calls/puts
        is_allowed = True
        if strategy == "etf_open_specialist" and symbol == "SPY":
            is_allowed = False
        elif strategy == "etf_momentum_specialist" and symbol == "QQQ" and sentiment == "BEARISH":
            is_allowed = False
            
        if not is_allowed:
            self._log("strategy_final_blocked_by_whitelist", strategy=strategy, symbol=symbol, sentiment=sentiment)
            return

        if slot is None and isinstance(session_date, dict) and isinstance(entry_price, date):
            slot = session_date
            session_date = entry_price
            entry_price = 0.0
        signal_id = build_signal_id(strategy, symbol, session_date, slot, raw_symbol)
        quote = await self._contract_quote_snapshot(symbol, raw_symbol) if raw_symbol else {}
        execution = _quote_execution_snapshot(quote, datetime.now(timezone.utc))
        if execution["quote_freshness"] not in FRESH_STATUSES or execution["reference_price"] is None:
            self._log(
                "strategy_final_blocked_by_quote",
                strategy=strategy,
                symbol=symbol,
                raw_symbol=raw_symbol,
                quote_freshness=execution["quote_freshness"],
                entry_time=slot["entry_label"] if slot else None,
            )
            return
        entry_price = execution["reference_price"]
        key_date = session_date or ny_session_date(datetime.now(timezone.utc))
        if not await self._acquire_final_locks(key_date, symbol, strategy, signal_id):
            return
        msg = {
            "message_id": new_message_id(),
            "signal_id": signal_id,
            "position_id": signal_id,
            "strategy": strategy,
            "symbol": symbol,
            "stage": 2,
            "decision": "BET",
            "sentiment": sentiment,
            "confidence": float(confidence),
            "entry_price": entry_price,
            "quote_freshness": execution["quote_freshness"],
            "quote_valid_until": execution["quote_valid_until"],
            "entry_quote": {
                "option_mid": quote.get("option_mid"),
                "option_bid": quote.get("option_bid"),
                "option_ask": quote.get("option_ask"),
                "quote_ts": quote.get("quote_ts"),
                "quote_age_ms": quote.get("quote_age_ms"),
                "tradability_bucket": quote.get("tradability_bucket"),
            },
            "execution": execution,
            "risk": {
                "stop_loss_pct": STOP_LOSS_PCT,
                "guard_activate_pct": GUARD_ACTIVATE_PCT,
                "guard_floor_pct": GUARD_FLOOR_PCT,
                "policy": "stop_loss_plus_breakeven_guard",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "sigmatiq_nexus",
        }
        if session_date:
            msg["session_date"] = str(session_date)
        if slot:
            msg.update({"entry_time": slot["entry_label"], "window_start": slot["window_start"].isoformat(), "window_end": slot["window_end"].isoformat()})
        if raw_symbol:
            msg["raw_symbol"] = raw_symbol
            msg.update({k: v for k, v in {
                "expiry_date": _contract_details_from_raw_symbol(raw_symbol)["expiry_date"],
                "strike": _contract_details_from_raw_symbol(raw_symbol)["strike"],
                "option_side": _contract_details_from_raw_symbol(raw_symbol)["side"],
            }.items() if v is not None})
        msg.update(narratives.build_lifecycle_reason_summary(msg))
        # Track position for dynamic exit
        active_positions = getattr(self, "active_positions", None)
        if active_positions is None:
            active_positions = {}
            self.active_positions = active_positions
        if entry_price > 0:
            position = {
                'entry_price': entry_price,
                'is_guarded': False,
                'side': sentiment,
                'raw_symbol': raw_symbol,
                'signal_id': signal_id,
                'position_id': signal_id,
                'session_date': str(key_date),
            }
            active_positions[symbol] = position
            await self._persist_active_position(key_date, symbol, position)

        await self.redis.set(f"nexus_live_overlay:{symbol}", json.dumps(msg))
        await self._append_persistence_event(symbol, msg)
        await self._publish("nexus_live_overlay:updates", symbol)
        self._log("strategy_final_published", strategy=strategy, symbol=symbol, sentiment=sentiment, confidence=round(float(confidence), 4), entry_price=round(float(entry_price), 4), session_date=str(key_date), entry_time=slot["entry_label"] if slot else None)

    async def _publish_spread_final(self, strategy: str, symbol: str, sentiment: str, confidence: float, session_date, slot: dict, candidate: dict):
        raw_symbol = candidate["short_raw_symbol"]
        signal_id = build_signal_id(strategy, symbol, session_date, slot, raw_symbol)
        leg_quotes = [leg.get("quote") or {} for leg in candidate["legs"]]
        executions = [_quote_execution_snapshot(quote, datetime.now(timezone.utc)) for quote in leg_quotes]
        quote_freshness = (
            "available"
            if executions and all(execution["quote_freshness"] in FRESH_STATUSES for execution in executions)
            else "stale"
        )
        quote_valid_until = min(
            [execution["quote_valid_until"] for execution in executions if execution.get("quote_valid_until")],
            default=None,
        )
        legs = []
        for leg in candidate["legs"]:
            quote = leg.get("quote") or {}
            legs.append({
                "raw_symbol": leg["raw_symbol"],
                "action": leg["action"],
                "ratio": leg["ratio"],
                "side": leg["side"],
                "strike": leg["strike"],
                "expiry_date": leg["expiry_date"],
                "quote": {
                    "option_mid": quote.get("option_mid"),
                    "option_bid": quote.get("option_bid"),
                    "option_ask": quote.get("option_ask"),
                    "quote_ts": quote.get("quote_ts"),
                    "quote_age_ms": quote.get("quote_age_ms"),
                    "tradability_bucket": quote.get("tradability_bucket"),
                },
            })
        msg = {
            "message_id": new_message_id(),
            "signal_id": signal_id,
            "position_id": signal_id,
            "strategy": strategy,
            "symbol": symbol,
            "stage": 2,
            "decision": "BET",
            "sentiment": sentiment,
            "confidence": float(confidence),
            "instrument_type": "vertical_credit_spread",
            "paper_only": True,
            "entry_credit": candidate["net_credit"],
            "entry_price": candidate["net_credit"],
            "entry_price_reference": "net_credit",
            "quote_freshness": quote_freshness,
            "quote_valid_until": quote_valid_until,
            "spread": {
                "structure": candidate["structure"],
                "spread_type": candidate["spread_type"],
                "strike_width": candidate["strike_width"],
                "short_raw_symbol": candidate["short_raw_symbol"],
                "long_raw_symbol": candidate["long_raw_symbol"],
                "short_strike": candidate["short_strike"],
                "long_strike": candidate["long_strike"],
                "expiry_date": candidate["expiry_date"],
                "net_credit": candidate["net_credit"],
                "max_loss": candidate["max_loss"],
                "max_loss_assumption": candidate["max_loss_assumption"],
                "take_profit_pct": SPREAD_TAKE_PROFIT_PCT,
                "stop_loss_pct": SPREAD_STOP_LOSS_PCT,
                "hold_seconds": SPREAD_HOLD_SECONDS,
                "min_entry_credit": SPREAD_MIN_ENTRY_CREDIT,
                "target_delta": SPREAD_TARGET_DELTA,
            },
            "legs": legs,
            "execution": {
                "order_type": "limit",
                "price_reference": "net_credit",
                "reference_price": candidate["net_credit"],
                "max_slippage_pct": EXECUTION_MAX_SLIPPAGE_PCT,
                "quote_freshness": quote_freshness,
                "quote_valid_until": quote_valid_until,
                "fill_realism": "REALISTIC",
                "paper_only": True,
            },
            "risk": {
                "take_profit_pct": SPREAD_TAKE_PROFIT_PCT,
                "stop_loss_pct": SPREAD_STOP_LOSS_PCT,
                "max_hold_seconds": SPREAD_HOLD_SECONDS,
                "max_loss": candidate["max_loss"],
                "policy": "vertical_credit_spread_paper_only",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_date": str(session_date),
            "entry_time": slot["entry_label"],
            "window_start": slot["window_start"].isoformat(),
            "window_end": slot["window_end"].isoformat(),
            "source": "sigmatiq_nexus",
        }
        msg.update(narratives.build_lifecycle_reason_summary(msg))
        redis_key = f"nexus_spread_overlay:{symbol}:{strategy}:{slot['entry_label']}"
        await self.redis.set(redis_key, json.dumps(msg))
        await self._append_persistence_event_for_key(redis_key, msg)
        await self._publish("nexus_spread_overlay:updates", symbol)
        await self._publish(f"signal:spread:{strategy}", json.dumps(msg))
        self._log(
            "strategy_spread_final_published",
            strategy=strategy,
            symbol=symbol,
            sentiment=sentiment,
            confidence=round(float(confidence), 4),
            entry_credit=round(float(candidate["net_credit"]), 4),
            session_date=str(session_date),
            entry_time=slot["entry_label"],
        )

    async def _append_persistence_event(self, symbol, msg):
        await self._append_persistence_event_for_key(f"nexus_live_overlay:{symbol}", msg)

    async def _append_persistence_event_for_key(self, redis_key: str, msg):
        try:
            await self.redis.xadd(
                LIVE_PERSISTENCE_EVENT_STREAM,
                {"redis_key": redis_key, "payload_json": json.dumps(msg)},
                maxlen=10_000,
                approximate=True,
            )
        except Exception as exc:
            self._log("persistence_event_append_failed", redis_key=redis_key, error=str(exc))


def main() -> None:
    asyncio.run(SigmatiqNexus().run())


if __name__ == "__main__":
    main()
