"""Participant flow context — pure functions for labeling and aggregating option trades.

Labels each trade by participant type (retail-like, institutional-like, etc.) and
strategy shape (directional call buying, lottery calls, tail hedge, etc.), then
aggregates per window for a completed-window context payload.

No Redis, no async, no imports from nexus_worker.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import polars as pl

from sigmatiq_nexus import narratives

NY = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Configuration — all thresholds configurable via env vars
# ---------------------------------------------------------------------------

PARTICIPANT_FLOW_DEFAULT_CONFIG = {
    "large_premium_threshold": float(os.environ.get("NEXUS_PF_LARGE_PREMIUM_THRESHOLD", "100000")),
    "small_premium_threshold": float(os.environ.get("NEXUS_PF_SMALL_PREMIUM_THRESHOLD", "5000")),
    "cheap_option_mid_threshold": float(os.environ.get("NEXUS_PF_CHEAP_OPTION_MID_THRESHOLD", "0.25")),
    "far_otm_delta_threshold": float(os.environ.get("NEXUS_PF_FAR_OTM_DELTA_THRESHOLD", "0.15")),
    "repeat_cluster_min_count": int(os.environ.get("NEXUS_PF_REPEAT_CLUSTER_MIN_COUNT", "3")),
    "repeat_cluster_min_aggregate_premium": float(os.environ.get("NEXUS_PF_REPEAT_CLUSTER_MIN_AGGREGATE_PREMIUM", "100000")),
    "max_spread_pct": float(os.environ.get("NEXUS_PF_MAX_SPREAD_PCT", "0.20")),
    "premium_shock_concentration_pct": float(os.environ.get("NEXUS_PF_PREMIUM_SHOCK_CONCENTRATION_PCT", "0.50")),
    "side_dominance_ratio": float(os.environ.get("NEXUS_PF_SIDE_DOMINANCE_RATIO", "1.5")),
    "top_contracts_limit": int(os.environ.get("NEXUS_PF_TOP_CONTRACTS_LIMIT", "5")),
    "thin_trade_count": int(os.environ.get("NEXUS_PF_THIN_TRADE_COUNT", "10")),
    "usable_label_pct": float(os.environ.get("NEXUS_PF_USABLE_LABEL_PCT", "0.80")),
    "degraded_label_pct": float(os.environ.get("NEXUS_PF_DEGRADED_LABEL_PCT", "0.50")),
}

# ---------------------------------------------------------------------------
# Trade labeler
# ---------------------------------------------------------------------------


def label_trade_participant_shape(
    row: dict,
    window_context: dict,
    config: dict,
) -> dict:
    """Label a single normalized trade with participant type and strategy shape.

    Args:
        row: single normalized trade payload dict.
        window_context: pre-computed window stats — contract_counts, contract_premiums, total_premium.
        config: threshold config dict.

    Returns:
        dict with participant_label, strategy_shape, direction_bias, confidence, reason_codes, why.
    """
    premium = float(row.get("premium") or 0)
    side = str(row.get("side") or "").upper()
    aggressor = str(row.get("aggressor") or "")
    is_sweep = bool(row.get("is_sweep"))
    option_mid = float(row.get("option_mid") or 0)
    delta = float(row.get("delta") or 0)
    raw_symbol = str(row.get("raw_symbol") or "")
    option_bid = row.get("option_bid")
    option_ask = row.get("option_ask")
    total_premium = float(window_context.get("total_premium") or 1)

    reason_codes: list[str] = []
    why: list[dict] = []
    confidence = "medium"

    # --- Data quality check ---
    has_aggressor = aggressor in ("A", "B", "M")
    has_quotes = option_bid is not None and option_ask is not None
    if not has_aggressor and not has_quotes:
        return {
            "participant_label": "unclear",
            "strategy_shape": "unclear",
            "direction_bias": "unknown",
            "confidence": "low",
            "reason_codes": ["MISSING_FRESH_CONTRACT_QUOTE"],
            "why": [{"code": "MISSING_FRESH_CONTRACT_QUOTE", "text": "Missing aggressor and quote data"}],
        }

    # --- Confidence degradation ---
    if aggressor == "B":
        confidence = "low"
        reason_codes.append("BID_SIDE_AMBIGUOUS")
        why.append({"code": "BID_SIDE_AMBIGUOUS", "text": "Bid-side flow is ambiguous without open/close"})
    elif aggressor == "M":
        confidence = "low"

    if has_quotes:
        bid = float(option_bid or 0)
        ask = float(option_ask or 0)
        mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
        max_spread = config.get("max_spread_pct", 0.20)
        if mid > 0 and (ask - bid) / mid > max_spread:
            if confidence != "low":
                confidence = "low"
            reason_codes.append("WIDE_SPREAD_LOW_CONFIDENCE")
            why.append({"code": "WIDE_SPREAD_LOW_CONFIDENCE", "text": "Spread was too wide for confident classification"})

    # --- Repeat cluster context ---
    contract_counts = window_context.get("contract_counts", {})
    contract_premiums = window_context.get("contract_premiums", {})
    is_repeat = contract_counts.get(raw_symbol, 0) >= config["repeat_cluster_min_count"]
    repeat_agg_premium = contract_premiums.get(raw_symbol, 0)

    # --- Participant label ---
    far_otm = abs(delta) <= config["far_otm_delta_threshold"] and abs(delta) > 0
    cheap_option = option_mid > 0 and option_mid <= config["cheap_option_mid_threshold"]

    participant_label = "unclear"

    if side == "P" and premium >= config["large_premium_threshold"] and far_otm:
        participant_label = "positioning_or_hedge_like"
        reason_codes.append("LARGE_FAR_OTM_PUT_PREMIUM")
        why.append({"code": "LARGE_FAR_OTM_PUT_PREMIUM", "text": "Large premium far-OTM put — positioning or hedge"})
    elif premium >= config["large_premium_threshold"] and aggressor == "A":
        participant_label = "institutional_like"
        reason_codes.append("LARGE_ASK_SIDE_PREMIUM")
        why.append({"code": "LARGE_ASK_SIDE_PREMIUM", "text": "Large premium ask-side trade"})
    elif premium >= config["large_premium_threshold"] and is_sweep:
        participant_label = "institutional_like"
        reason_codes.append("LARGE_SWEEP_PREMIUM")
        why.append({"code": "LARGE_SWEEP_PREMIUM", "text": "Large premium sweep execution"})
    elif is_repeat and repeat_agg_premium >= config["repeat_cluster_min_aggregate_premium"]:
        participant_label = "institutional_like"
        reason_codes.append("HIGH_PREMIUM_CONTRACT_CLUSTER")
        why.append({"code": "HIGH_PREMIUM_CONTRACT_CLUSTER", "text": "Repeated contract with high aggregate premium"})
    elif premium <= config["small_premium_threshold"] and (cheap_option or far_otm):
        participant_label = "retail_like"
        reason_codes.append("SMALL_LOT_SPECULATIVE")
        why.append({"code": "SMALL_LOT_SPECULATIVE", "text": "Small premium speculative trade"})
    elif is_repeat and repeat_agg_premium < config["repeat_cluster_min_aggregate_premium"]:
        participant_label = "coordinated_or_clustered_like"
        reason_codes.append("REPEAT_CLUSTER_BELOW_INSTITUTIONAL_THRESHOLD")
        why.append({"code": "REPEAT_CLUSTER_BELOW_INSTITUTIONAL_THRESHOLD", "text": "Repeated contract but aggregate premium below institutional threshold"})

    # --- Strategy shape ---
    strategy_shape = "unclear"

    if premium > config["premium_shock_concentration_pct"] * total_premium and total_premium > 0:
        strategy_shape = "premium_shock"
    elif participant_label == "positioning_or_hedge_like" and side == "P":
        strategy_shape = "tail_hedge_puts"
    elif side == "C" and (cheap_option or far_otm) and premium <= config["small_premium_threshold"]:
        strategy_shape = "lottery_calls"
    elif side == "P" and (cheap_option or far_otm) and premium <= config["small_premium_threshold"]:
        strategy_shape = "lottery_puts"
    elif side == "C" and aggressor == "A" and premium > config["small_premium_threshold"]:
        strategy_shape = "directional_call_buying"
    elif side == "P" and aggressor == "A" and premium > config["small_premium_threshold"]:
        strategy_shape = "directional_put_buying"
    elif is_repeat:
        strategy_shape = "repeat_cluster"
    elif aggressor in ("M", "B", ""):
        strategy_shape = "chop_or_income_like"

    # --- Direction bias ---
    if side == "C" and aggressor == "A":
        direction_bias = "bullish"
    elif side == "P" and aggressor == "A":
        direction_bias = "bearish"
    elif side == "C":
        direction_bias = "bullish"
    elif side == "P":
        direction_bias = "bearish"
    else:
        direction_bias = "unknown"

    # Degrade confidence for large bid-side
    if premium >= config["large_premium_threshold"] and aggressor == "B":
        confidence = "low"

    return {
        "participant_label": participant_label,
        "strategy_shape": strategy_shape,
        "direction_bias": direction_bias,
        "confidence": confidence,
        "reason_codes": reason_codes,
        "why": why,
    }


# ---------------------------------------------------------------------------
# Window aggregator
# ---------------------------------------------------------------------------


def _build_window_context(rows: list[dict]) -> dict:
    """Pre-compute window-level stats for the trade labeler."""
    contract_counts: dict[str, int] = Counter()
    contract_premiums: dict[str, float] = Counter()
    total_premium = 0.0
    for r in rows:
        rs = str(r.get("raw_symbol") or "")
        p = float(r.get("premium") or 0)
        contract_counts[rs] += 1
        contract_premiums[rs] += p
        total_premium += p
    return {
        "contract_counts": dict(contract_counts),
        "contract_premiums": dict(contract_premiums),
        "total_premium": total_premium,
    }


def _aggregate_participant_group(labeled: list[dict], group: str) -> dict:
    """Aggregate trades for a specific participant_label group."""
    trades = [t for t in labeled if t["label"]["participant_label"] == group]
    if not trades:
        return {
            "bias": "unknown",
            "confidence": "low",
            "premium": 0,
            "trade_count": 0,
            "dominant_side": "unknown",
            "dominant_shape": "unclear",
            "reason_codes": [],
            "why": [],
        }
    total_premium = sum(float(t["row"].get("premium") or 0) for t in trades)
    # Only ask-side premium carries directional intent; bid-side is ambiguous
    ask_call_premium = sum(float(t["row"].get("premium") or 0) for t in trades
                          if str(t["row"].get("side") or "").upper() == "C" and str(t["row"].get("aggressor") or "") == "A")
    ask_put_premium = sum(float(t["row"].get("premium") or 0) for t in trades
                         if str(t["row"].get("side") or "").upper() == "P" and str(t["row"].get("aggressor") or "") == "A")
    ask_total = ask_call_premium + ask_put_premium
    bid_premium = sum(float(t["row"].get("premium") or 0) for t in trades if str(t["row"].get("aggressor") or "") == "B")
    bid_dominant = bid_premium > ask_total

    if bid_dominant or ask_total == 0:
        dominant_side = "unknown"
        bias = "unknown"
    else:
        dominant_side = "calls" if ask_call_premium >= ask_put_premium else "puts"
        bias = "bullish" if ask_call_premium > ask_put_premium else "bearish" if ask_put_premium > ask_call_premium else "neutral"

    shapes = Counter(t["label"]["strategy_shape"] for t in trades)
    dominant_shape = shapes.most_common(1)[0][0] if shapes else "unclear"

    all_codes = []
    all_why = []
    for t in trades:
        all_codes.extend(t["label"]["reason_codes"])
        all_why.extend(t["label"]["why"])

    low_confidence_count = sum(1 for t in trades if t["label"]["confidence"] == "low")
    mostly_low = low_confidence_count > len(trades) * 0.5

    return {
        "bias": bias,
        "confidence": "low" if mostly_low or bid_dominant else ("medium" if len(trades) >= 3 else "low"),
        "premium": total_premium,
        "trade_count": len(trades),
        "dominant_side": dominant_side,
        "dominant_shape": dominant_shape,
        "reason_codes": list(dict.fromkeys(all_codes)),
        "why": list({c["code"]: c for c in all_why}.values()),
    }


def aggregate_participant_flow_window(
    df: pl.DataFrame,
    config: dict,
) -> dict:
    """Aggregate labeled trades into window-level participant flow context sections."""
    if df.is_empty():
        return _empty_aggregation()

    rows = df.to_dicts()
    window_context = _build_window_context(rows)

    labeled = []
    for row in rows:
        label = label_trade_participant_shape(row, window_context, config)
        labeled.append({"row": row, "label": label})

    # --- window_side_read ---
    call_premium = sum(float(t["row"].get("premium") or 0) for t in labeled if str(t["row"].get("side") or "").upper() == "C")
    put_premium = sum(float(t["row"].get("premium") or 0) for t in labeled if str(t["row"].get("side") or "").upper() == "P")
    ratio = config["side_dominance_ratio"]

    if call_premium > put_premium * ratio:
        premium_bias = "call_heavy"
    elif put_premium > call_premium * ratio:
        premium_bias = "put_heavy"
    else:
        premium_bias = "balanced"

    ask_call_premium = sum(float(t["row"].get("premium") or 0) for t in labeled
                          if str(t["row"].get("side") or "").upper() == "C" and str(t["row"].get("aggressor") or "") == "A")
    ask_put_premium = sum(float(t["row"].get("premium") or 0) for t in labeled
                         if str(t["row"].get("side") or "").upper() == "P" and str(t["row"].get("aggressor") or "") == "A")

    if ask_call_premium > ask_put_premium * ratio:
        aggressor_bias = "ask_side_call_heavy"
    elif ask_put_premium > ask_call_premium * ratio:
        aggressor_bias = "ask_side_put_heavy"
    else:
        aggressor_bias = "balanced"

    has_aggressor_data = sum(1 for t in labeled if str(t["row"].get("aggressor") or "") in ("A", "B", "M"))
    aggressor_coverage = has_aggressor_data / len(labeled) if labeled else 0

    # Bid-side premium is ambiguous — only ask-side confirmed flow drives direction
    bid_premium_total = sum(float(t["row"].get("premium") or 0) for t in labeled if str(t["row"].get("aggressor") or "") == "B")
    ask_premium_total = ask_call_premium + ask_put_premium
    bid_dominant_window = bid_premium_total > ask_premium_total

    if aggressor_coverage < 0.5:
        directional_read = "unknown"
    elif bid_dominant_window:
        directional_read = "unknown"
    elif aggressor_bias == "ask_side_call_heavy":
        directional_read = "bullish"
    elif aggressor_bias == "ask_side_put_heavy":
        directional_read = "bearish"
    elif aggressor_bias == "balanced" and premium_bias == "balanced":
        directional_read = "neutral"
    elif aggressor_bias == "balanced" and premium_bias in ("call_heavy", "put_heavy"):
        directional_read = "conflicted"
    else:
        directional_read = "conflicted"

    # Confidence degrades when bid-side is significant or low-confidence labels dominate
    low_conf_count = sum(1 for t in labeled if t["label"]["confidence"] == "low")
    mostly_low_conf = low_conf_count > len(labeled) * 0.5

    if mostly_low_conf or bid_dominant_window:
        read_confidence = "low"
    elif aggressor_coverage > 0.8 and directional_read not in ("conflicted", "unknown"):
        read_confidence = "high"
    elif aggressor_coverage > 0.5:
        read_confidence = "medium"
    else:
        read_confidence = "low"

    wsr_codes: list[str] = []
    wsr_why: list[dict] = []
    if premium_bias == "call_heavy":
        wsr_codes.append("CALL_PREMIUM_DOMINANCE")
        wsr_why.append({"code": "CALL_PREMIUM_DOMINANCE", "text": f"Call premium was {call_premium / max(put_premium, 1):.1f}x put premium"})
    elif premium_bias == "put_heavy":
        wsr_codes.append("PUT_PREMIUM_DOMINANCE")
        wsr_why.append({"code": "PUT_PREMIUM_DOMINANCE", "text": f"Put premium was {put_premium / max(call_premium, 1):.1f}x call premium"})
    if aggressor_bias == "ask_side_call_heavy":
        wsr_codes.append("ASK_SIDE_CALL_LARGE_PRINTS")
        wsr_why.append({"code": "ASK_SIDE_CALL_LARGE_PRINTS", "text": "Ask-side call flow dominated aggressive prints"})
    elif aggressor_bias == "ask_side_put_heavy":
        wsr_codes.append("ASK_SIDE_PUT_LARGE_PRINTS")
        wsr_why.append({"code": "ASK_SIDE_PUT_LARGE_PRINTS", "text": "Ask-side put flow dominated aggressive prints"})

    window_side_read = {
        "premium_bias": premium_bias,
        "aggressor_bias": aggressor_bias,
        "directional_read": directional_read,
        "confidence": read_confidence,
        "call_premium": call_premium,
        "put_premium": put_premium,
        "reason_codes": wsr_codes,
        "why": wsr_why,
    }

    # --- participant groups ---
    retail_like_flow = _aggregate_participant_group(labeled, "retail_like")
    institutional_like_flow = _aggregate_participant_group(labeled, "institutional_like")

    # --- dominant_strategy_shape ---
    shape_premium: dict[str, float] = Counter()
    for t in labeled:
        shape = t["label"]["strategy_shape"]
        shape_premium[shape] += float(t["row"].get("premium") or 0)
    if shape_premium:
        dominant = max(shape_premium, key=shape_premium.get)
    else:
        dominant = "unclear"

    bullish_shapes = {"directional_call_buying", "lottery_calls"}
    bearish_shapes = {"directional_put_buying", "lottery_puts", "tail_hedge_puts"}
    if dominant in bullish_shapes:
        supporting = [s for s in shape_premium if s in bullish_shapes and s != dominant]
        conflicting = [s for s in shape_premium if s in bearish_shapes]
    elif dominant in bearish_shapes:
        supporting = [s for s in shape_premium if s in bearish_shapes and s != dominant]
        conflicting = [s for s in shape_premium if s in bullish_shapes]
    else:
        supporting = []
        conflicting = []

    dominant_strategy_shape = {
        "shape": dominant,
        "confidence": "medium" if shape_premium.get(dominant, 0) > window_context["total_premium"] * 0.3 else "low",
        "supporting_shapes": supporting,
        "conflicting_shapes": conflicting,
        "reason_codes": ["CALL_AGGRESSOR_DOMINANCE"] if dominant in bullish_shapes else
                        ["PUT_AGGRESSOR_DOMINANCE"] if dominant in bearish_shapes else [],
    }

    # --- top_contracts ---
    contract_agg: dict[str, dict] = {}
    for t in labeled:
        rs = str(t["row"].get("raw_symbol") or "")
        if not rs:
            continue
        if rs not in contract_agg:
            contract_agg[rs] = {
                "raw_symbol": rs,
                "expiry": _parse_expiry(rs),
                "strike": _parse_strike(rs),
                "side": str(t["row"].get("side") or "").upper(),
                "premium": 0.0,
                "trade_count": 0,
                "participant_labels": [],
                "strategy_shapes": [],
            }
        contract_agg[rs]["premium"] += float(t["row"].get("premium") or 0)
        contract_agg[rs]["trade_count"] += 1
        contract_agg[rs]["participant_labels"].append(t["label"]["participant_label"])
        contract_agg[rs]["strategy_shapes"].append(t["label"]["strategy_shape"])

    top_contracts = []
    for c in sorted(contract_agg.values(), key=lambda x: x["premium"], reverse=True)[:config["top_contracts_limit"]]:
        plabels = Counter(c["participant_labels"])
        slabels = Counter(c["strategy_shapes"])
        top_contracts.append({
            "raw_symbol": c["raw_symbol"],
            "expiry": c["expiry"],
            "strike": c["strike"],
            "side": c["side"],
            "premium": c["premium"],
            "trade_count": c["trade_count"],
            "participant_label": plabels.most_common(1)[0][0] if plabels else "unclear",
            "strategy_shape": slabels.most_common(1)[0][0] if slabels else "unclear",
            "reason_codes": ["LARGE_PREMIUM_CONTRACT"] if c["premium"] >= config["large_premium_threshold"] else [],
        })

    # --- data_quality ---
    # Both unclear labels AND low-confidence labels indicate degraded quality
    non_unclear = sum(1 for t in labeled if t["label"]["participant_label"] != "unclear")
    high_or_medium_conf = sum(1 for t in labeled if t["label"]["confidence"] in ("high", "medium"))
    label_pct = non_unclear / len(labeled) if labeled else 0
    quality_pct = high_or_medium_conf / len(labeled) if labeled else 0
    effective_pct = min(label_pct, quality_pct)

    if len(labeled) < config["thin_trade_count"]:
        dq_status = "thin"
    elif effective_pct >= config["usable_label_pct"]:
        dq_status = "usable"
    elif effective_pct >= config["degraded_label_pct"]:
        dq_status = "degraded"
    else:
        dq_status = "degraded"

    missing = []
    degraded_list = ["opening_or_closing_unknown"]
    if aggressor_coverage < 0.5:
        missing.append("aggressor")
    if quality_pct < label_pct:
        degraded_list.append("low_confidence_labels")

    data_quality = {
        "status": dq_status,
        "missing": missing,
        "degraded": degraded_list,
        "reason_codes": ["OPEN_CLOSE_UNAVAILABLE"],
    }

    return {
        "window_side_read": window_side_read,
        "retail_like_flow": retail_like_flow,
        "institutional_like_flow": institutional_like_flow,
        "dominant_strategy_shape": dominant_strategy_shape,
        "top_contracts": top_contracts,
        "data_quality": data_quality,
    }


def _empty_aggregation() -> dict:
    return {
        "window_side_read": {
            "premium_bias": "balanced", "aggressor_bias": "balanced",
            "directional_read": "unknown", "confidence": "low",
            "call_premium": 0, "put_premium": 0, "reason_codes": [], "why": [],
        },
        "retail_like_flow": {
            "bias": "unknown", "confidence": "low", "premium": 0, "trade_count": 0,
            "dominant_side": "unknown", "dominant_shape": "unclear", "reason_codes": [], "why": [],
        },
        "institutional_like_flow": {
            "bias": "unknown", "confidence": "low", "premium": 0, "trade_count": 0,
            "dominant_side": "unknown", "dominant_shape": "unclear", "reason_codes": [], "why": [],
        },
        "dominant_strategy_shape": {
            "shape": "unclear", "confidence": "low", "supporting_shapes": [],
            "conflicting_shapes": [], "reason_codes": [],
        },
        "top_contracts": [],
        "data_quality": {
            "status": "unknown", "missing": [], "degraded": ["opening_or_closing_unknown"],
            "reason_codes": ["OPEN_CLOSE_UNAVAILABLE"],
        },
    }


# ---------------------------------------------------------------------------
# Dealer inference (v1 stub)
# ---------------------------------------------------------------------------


def infer_dealer_pressure(window_context: dict | None = None) -> dict:
    """v1: always returns unknown. P1 will wire dealer context."""
    return {
        "underlying_hedge_direction": "unknown",
        "impact_state": "unknown",
        "confidence": "low",
        "source": "unavailable",
        "reason_codes": ["DEALER_CONTEXT_STALE_OR_MISSING"],
        "why": [{"code": "DEALER_CONTEXT_STALE_OR_MISSING", "text": "Dealer inference not yet implemented in v1"}],
    }


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def build_participant_flow_payload(
    df: pl.DataFrame,
    symbol: str,
    slot: dict,
    session_date,
    config: dict,
) -> dict:
    """Build the complete participant flow context payload for a completed window."""
    aggregated = aggregate_participant_flow_window(df, config)
    dealer = infer_dealer_pressure()

    window_key = slot["entry_label"]
    now = datetime.now(timezone.utc)
    session_str = str(session_date)

    # Build window_start/window_end as ET timestamps
    ws = slot["window_start"]
    we = slot["window_end"]
    window_start_et = datetime.combine(session_date, ws, tzinfo=NY).isoformat()
    window_end_et = datetime.combine(session_date, we, tzinfo=NY).isoformat()
    window_label = f"{ws.strftime('%H:%M')}-{we.strftime('%H:%M')}"

    payload = {
        "schema_version": 1,
        "symbol": symbol,
        "window_key": window_key,
        "window_id": window_end_et,
        "window_label": window_label,
        "window_tz": "America/New_York",
        "window_start": window_start_et,
        "window_end": window_end_et,
        "window_status": "completed",
        "is_partial": False,
        "as_of": now.isoformat(),
        "session_date": session_str,
        "redis_key": f"nexus_participant_flow_context:{symbol}:{window_key}",
        "window_side_read": aggregated["window_side_read"],
        "retail_like_flow": aggregated["retail_like_flow"],
        "institutional_like_flow": aggregated["institutional_like_flow"],
        "dealer_inferred_pressure": dealer,
        "dominant_strategy_shape": aggregated["dominant_strategy_shape"],
        "top_contracts": aggregated["top_contracts"],
        "data_quality": aggregated["data_quality"],
        "source": "sigmatiq_nexus",
    }

    # Add deterministic narrative fields
    narrative_fields = narratives.build_participant_flow_context_narrative(payload)
    payload.update(narrative_fields)

    return payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_expiry(raw_symbol: str) -> str | None:
    """Extract expiry from OCC-style raw_symbol like SPY   260508C00520000."""
    stripped = raw_symbol.replace(" ", "")
    if len(stripped) < 15:
        return None
    try:
        alpha_end = 0
        for i, ch in enumerate(stripped):
            if ch.isdigit():
                alpha_end = i
                break
        date_part = stripped[alpha_end:alpha_end + 6]
        if len(date_part) == 6:
            return f"20{date_part[:2]}-{date_part[2:4]}-{date_part[4:6]}"
    except (ValueError, IndexError):
        pass
    return None


def _parse_strike(raw_symbol: str) -> float | None:
    """Extract strike from OCC-style raw_symbol."""
    stripped = raw_symbol.replace(" ", "")
    if len(stripped) < 15:
        return None
    try:
        strike_str = stripped[-8:]
        return int(strike_str) / 1000.0
    except (ValueError, IndexError):
        return None
