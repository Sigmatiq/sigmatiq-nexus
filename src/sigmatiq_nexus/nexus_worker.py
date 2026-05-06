from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, time, timedelta, timezone
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
LIVE_PERSISTENCE_EVENT_STREAM = os.environ.get("LIVE_PERSISTENCE_EVENT_STREAM", "live:persistence:events")

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
    "spy_low_sweep_core": ("ts_utc", "symbol", "raw_symbol", "side", "premium", "is_sweep"),
    "spy_flow_specialist": (
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
    "spy_momentum_specialist": ("ts_utc", "symbol", "side", "premium", "underlying_mid", "iv_rank"),
    "spy_confluence_sniper": (
        "ts_utc",
        "raw_symbol",
        "side",
        "premium",
        "underlying_mid",
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
        self.feature_blocks_reported = set()
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

            payload = await enrich_trade_payload_from_redis(payload, self.redis)
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

        # Deterministic order follows the research log: confluence first, then
        # low-sweep core, v6 flow, and v10 momentum. First trigger wins.
        await self.evaluate_confluence_sniper(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*"):
            await self.evaluate_low_sweep_core(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*"):
            await self.evaluate_flow_specialist(slot_df, symbol, slot, session_date)
        if not self.already_signaled(session_date, symbol, "*"):
            await self.evaluate_momentum_specialist(slot_df, symbol, slot, session_date)

    def already_signaled(self, session_date, symbol: str, strategy: str) -> bool:
        return signal_key(session_date, symbol, strategy) in self.signaled_today or signal_key(session_date, symbol, "*") in self.signaled_today

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

    def _window_has_event_feature(self, df: pl.DataFrame, feature: str) -> bool:
        return self._window_event_feature_status(df, feature) in FRESH_STATUSES

    def _window_event_feature_status(self, df: pl.DataFrame, feature: str) -> str:
        if df.is_empty():
            return "missing"
        if "_feature_status" in df.columns:
            for row in df.to_dicts():
                status = row.get("_feature_status") or {}
                if isinstance(status, dict) and status.get(feature) not in FRESH_STATUSES:
                    return status.get(feature, "missing")
        if feature == "option_mid":
            return "available" if "option_mid" in df.columns and df.select(pl.col("option_mid").is_not_null().any()).item() else "missing"
        if feature not in df.columns:
            return "missing"
        if feature == "is_sweep":
            return "available"
        if feature in {"delta", "gamma"}:
            return "available" if df.select(pl.col(feature).is_not_null().any()).item() else "missing"
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
        print(f"[BLOCKED] {strategy} for {symbol}: feature gate closed {failures}")
        await self._append_persistence_event(symbol, msg)

    async def evaluate_confluence_sniper(self, df, symbol, slot: dict, session_date):
        strategy = "spy_confluence_sniper"
        if self.already_signaled(session_date, symbol, strategy):
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
            return
        sentiment, valid, p_feat = await self.check_momentum_heuristics(df, symbol)
        if not valid:
            return
        pricing_lag = self.calculate_pricing_lag(df, sentiment)
        if pricing_lag is None or pricing_lag > -0.05:
            return
        await self._publish_intermediate(strategy, symbol, sentiment, slot)
        await self._publish_final(strategy, symbol, sentiment, 1.0, session_date, slot)

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

    async def evaluate_low_sweep_core(self, df, symbol, slot: dict, session_date):
        strategy = "spy_low_sweep_core"
        if self.already_signaled(session_date, symbol, strategy):
            return
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
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
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
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
        if not await self._strategy_features_ready(strategy, symbol, df, slot, session_date):
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
        msg = {"strategy": strategy, "symbol": symbol, "stage": 1, "sentiment": sentiment, "timestamp": datetime.now(timezone.utc).isoformat(), "source": "sigmatiq_nexus"}
        if slot:
            msg.update({"entry_time": slot["entry_label"], "window_start": slot["window_start"].isoformat(), "window_end": slot["window_end"].isoformat()})
        await self._append_persistence_event(symbol, msg)
        await self.redis.publish(f"signal:intermediate:{strategy}", json.dumps(msg))

    async def _publish_final(self, strategy, symbol, sentiment, confidence, session_date=None, slot: dict | None = None):
        msg = {"strategy": strategy, "symbol": symbol, "stage": 2, "decision": "BET", "sentiment": sentiment, "confidence": float(confidence), "timestamp": datetime.now(timezone.utc).isoformat(), "source": "sigmatiq_nexus"}
        if session_date:
            msg["session_date"] = str(session_date)
        if slot:
            msg.update({"entry_time": slot["entry_label"], "window_start": slot["window_start"].isoformat(), "window_end": slot["window_end"].isoformat()})
        key_date = session_date or ny_session_date(datetime.now(timezone.utc))
        self.signaled_today.add(signal_key(key_date, symbol, strategy))
        if FIRST_TRIGGER_SCOPE == "symbol":
            self.signaled_today.add(signal_key(key_date, symbol, "*"))
        await self.redis.set(f"nexus_live_overlay:{symbol}", json.dumps(msg))
        await self._append_persistence_event(symbol, msg)
        await self.redis.publish("nexus_live_overlay:updates", symbol)
        print(f"[BET] {strategy} for {symbol} (Conf: {confidence:.4f})")

    async def _append_persistence_event(self, symbol, msg):
        try:
            await self.redis.xadd(
                LIVE_PERSISTENCE_EVENT_STREAM,
                {"redis_key": f"nexus_live_overlay:{symbol}", "payload_json": json.dumps(msg)},
                maxlen=10_000,
                approximate=True,
            )
        except Exception as exc:
            print(f"Nexus persistence event append failed for {symbol}: {exc}")


def main():
    nexus = SigmatiqNexus()
    asyncio.run(nexus.run())


if __name__ == "__main__":
    main()
