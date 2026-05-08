"""Deterministic narrative builders for Nexus messages.

Generates trader-readable summaries from reason codes, data-quality flags,
and numeric fields. No LLM, no persuasive language, no identity claims.

All functions are pure — no Redis, no async, no side effects.
"""

from __future__ import annotations

NARRATIVE_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Banned phrases — must never appear in generated narrative text
# ---------------------------------------------------------------------------

BANNED_PHRASES = [
    "buy this",
    "sell this",
    "enter now",
    "take this trade",
    "short this",
    "guaranteed",
    "will move",
    "retail is buying",
    "institutions are selling",
    "dealers are betting",
]


def check_banned_phrases(text: str) -> list[str]:
    """Return any banned phrases found in text (case-insensitive)."""
    lower = text.lower()
    return [p for p in BANNED_PHRASES if p in lower]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_premium(value: float) -> str:
    """Format dollar premium in compact form."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def _fmt_ratio(a: float, b: float) -> str:
    """Format a/b as ratio with one decimal."""
    if b <= 0:
        return "n/a"
    return f"{a / b:.1f}x"


def _quality_prefix(status: str) -> str:
    """Return the quality-driven prefix for summaries."""
    return {
        "thin": "Thin window:",
        "degraded": "Degraded read:",
        "stale": "Stale read:",
        "unknown": "Unknown read:",
    }.get(status, "")


# ---------------------------------------------------------------------------
# PARTICIPANT_FLOW_CONTEXT narrative
# ---------------------------------------------------------------------------


def build_participant_flow_context_narrative(payload: dict) -> dict:
    """Build narrative fields for a PARTICIPANT_FLOW_CONTEXT message.

    Returns dict with narrative_version, summary, and narrative (headline,
    what_happened, what_it_means, caveats, reason_codes).
    """
    wsr = payload.get("window_side_read") or {}
    retail = payload.get("retail_like_flow") or {}
    institutional = payload.get("institutional_like_flow") or {}
    dominant = payload.get("dominant_strategy_shape") or {}
    top_contracts = payload.get("top_contracts") or []
    dq = payload.get("data_quality") or {}
    dealer = payload.get("dealer_inferred_pressure") or {}

    dq_status = dq.get("status", "unknown")
    prefix = _quality_prefix(dq_status)

    # --- what_happened ---
    what_happened = []

    call_p = float(wsr.get("call_premium") or 0)
    put_p = float(wsr.get("put_premium") or 0)
    if call_p > 0 or put_p > 0:
        total = call_p + put_p
        if call_p > put_p and put_p > 0:
            what_happened.append(f"Call premium was {_fmt_ratio(call_p, put_p)} put premium ({_fmt_premium(call_p)} vs {_fmt_premium(put_p)}).")
        elif put_p > call_p and call_p > 0:
            what_happened.append(f"Put premium was {_fmt_ratio(put_p, call_p)} call premium ({_fmt_premium(put_p)} vs {_fmt_premium(call_p)}).")
        else:
            what_happened.append(f"Total premium was {_fmt_premium(total)}.")

    if top_contracts:
        top = top_contracts[0]
        rs = top.get("raw_symbol", "unknown")
        side_word = "call" if top.get("side") == "C" else "put" if top.get("side") == "P" else "option"
        what_happened.append(f"Top contract was {rs} ({side_word}, {_fmt_premium(float(top.get('premium') or 0))}).")

    aggressor_bias = wsr.get("aggressor_bias", "balanced")
    if aggressor_bias == "ask_side_call_heavy":
        what_happened.append("Ask-side call flow dominated aggressive prints.")
    elif aggressor_bias == "ask_side_put_heavy":
        what_happened.append("Ask-side put flow dominated aggressive prints.")

    retail_count = int(retail.get("trade_count") or 0)
    if retail_count > 0:
        retail_shape = retail.get("dominant_shape", "unclear")
        what_happened.append(f"Small-lot-like flow: {retail_count} trades, dominant shape {retail_shape}.")

    inst_count = int(institutional.get("trade_count") or 0)
    if inst_count > 0:
        inst_shape = institutional.get("dominant_shape", "unclear")
        what_happened.append(f"Block-like activity: {inst_count} trades, dominant shape {inst_shape}.")

    # --- what_it_means ---
    what_it_means = []
    directional_read = wsr.get("directional_read", "unknown")
    confidence = wsr.get("confidence", "low")

    if dq_status == "thin":
        what_it_means.append("Not enough trades for a strong read in this completed window.")
    elif dq_status == "stale":
        what_it_means.append("This read should not be treated as current market state.")
    elif directional_read == "bullish":
        what_it_means.append(f"The completed window leans bullish on ask-side flow ({confidence} confidence).")
    elif directional_read == "bearish":
        what_it_means.append(f"The completed window leans bearish on ask-side flow ({confidence} confidence).")
    elif directional_read == "conflicted":
        what_it_means.append("Premium and aggressor signals conflict — the read is ambiguous.")
    elif directional_read == "neutral":
        what_it_means.append("No directional edge appears in this completed window.")
    else:
        what_it_means.append("Directional read is unavailable for this completed window.")

    # --- caveats ---
    caveats = []
    degraded = dq.get("degraded") or []

    if "opening_or_closing_unknown" in degraded:
        caveats.append("Opening/closing status is unavailable.")
    if "low_confidence_labels" in degraded:
        caveats.append("Most trade labels have low confidence due to bid-side or wide-spread ambiguity.")

    caveats.append("Participant labels are inferred from trade shape, not true account identity.")

    dealer_dir = dealer.get("underlying_hedge_direction", "unknown")
    if dealer_dir == "unknown":
        caveats.append("Dealer pressure is unknown because dealer context is unavailable.")

    caveats.append("This is not a trade recommendation.")

    # --- reason_codes ---
    all_codes = list(wsr.get("reason_codes") or [])

    # --- headline ---
    if dq_status in ("thin", "stale", "unknown"):
        headline = f"{prefix} limited data"
    elif directional_read == "bullish":
        headline = f"Appears bullish, {confidence} confidence"
    elif directional_read == "bearish":
        headline = f"Appears bearish, {confidence} confidence"
    elif directional_read == "conflicted":
        headline = "Conflicted flow — no clear direction"
    elif directional_read == "neutral":
        headline = "Neutral — balanced flow"
    else:
        headline = "Directional read unavailable"

    # --- summary ---
    summary_parts = []
    premium_bias = wsr.get("premium_bias", "balanced")
    if premium_bias == "call_heavy":
        summary_parts.append("Call premium dominated")
    elif premium_bias == "put_heavy":
        summary_parts.append("Put premium dominated")
    else:
        summary_parts.append("Premium was balanced")

    if confidence == "low":
        summary_parts.append("but confidence is low")
    elif aggressor_bias == "balanced":
        summary_parts.append("with balanced aggressor activity")

    summary_raw = ", ".join(summary_parts) + "."
    if prefix:
        summary = f"{prefix} {summary_raw[0].lower()}{summary_raw[1:]}"
    else:
        summary = summary_raw

    result = {
        "narrative_version": NARRATIVE_VERSION,
        "summary": summary,
        "narrative": {
            "headline": headline,
            "what_happened": what_happened,
            "what_it_means": what_it_means,
            "caveats": caveats,
            "reason_codes": all_codes,
        },
    }

    # Validate no banned phrases leaked in
    all_text = summary + " " + headline + " " + " ".join(what_happened) + " " + " ".join(what_it_means) + " " + " ".join(caveats)
    violations = check_banned_phrases(all_text)
    if violations:
        raise ValueError(f"Narrative contains banned phrases: {violations}")

    return result


# ---------------------------------------------------------------------------
# OPTION_MARKET_CONTEXT narrative (placeholder for step 3)
# ---------------------------------------------------------------------------


def build_option_market_context_narrative(payload: dict) -> dict:
    """Build narrative fields for an OPTION_MARKET_CONTEXT message."""
    premium = payload.get("premium") or {}
    activity = payload.get("activity") or {}
    cheap_side = payload.get("cheap_side", "unknown")
    costly_side = payload.get("costly_side", "unknown")
    liquidity_quality = payload.get("liquidity_quality", "unknown")
    pricing_quality = payload.get("pricing_quality", "unknown")
    cheapest = payload.get("cheapest_contracts") or []
    most_traded = payload.get("most_traded_contracts") or []

    call_p = float(premium.get("call_premium") or 0)
    put_p = float(premium.get("put_premium") or 0)
    total_p = float(premium.get("total_premium") or 0)
    bias = premium.get("net_premium_bias", "balanced")
    trade_count = int(activity.get("trade_count") or 0)

    # --- what_happened ---
    what_happened = []

    if total_p > 0:
        what_happened.append(f"Total premium was {_fmt_premium(total_p)} across {trade_count} trades.")
    if bias == "call_heavy" and put_p > 0:
        what_happened.append(f"Call premium was {_fmt_ratio(call_p, put_p)} put premium.")
    elif bias == "put_heavy" and call_p > 0:
        what_happened.append(f"Put premium was {_fmt_ratio(put_p, call_p)} call premium.")

    if most_traded:
        top = most_traded[0]
        what_happened.append(f"Most traded contract was {top.get('raw_symbol', 'unknown')}.")

    if cheap_side not in ("unknown", "balanced"):
        what_happened.append(f"Cheap side was {cheap_side}.")
    if costly_side not in ("unknown", "balanced"):
        what_happened.append(f"Costly side was {costly_side}.")

    # --- what_it_means ---
    what_it_means = []
    if pricing_quality == "usable" and liquidity_quality in ("good", "fair"):
        what_it_means.append("Pricing quality appears usable for this completed window.")
    elif pricing_quality == "degraded":
        what_it_means.append("Pricing quality is degraded — spreads may distort contract value reads.")
    elif pricing_quality == "unknown":
        what_it_means.append("Pricing quality is unknown — insufficient data for a reliable read.")

    if cheap_side not in ("unknown", "balanced") and cheapest:
        top_cheap = cheapest[0]
        lag = top_cheap.get("pricing_lag")
        if lag is not None:
            what_it_means.append(f"Cheapest contract shows {float(lag):.1f}% pricing lag.")

    # --- caveats ---
    caveats = []
    if liquidity_quality == "poor":
        caveats.append("Liquidity quality is poor — wide spreads may affect pricing accuracy.")
    caveats.append("This is not a trade recommendation.")

    # --- headline ---
    if trade_count == 0:
        headline = "No trading activity in this window"
    elif bias == "call_heavy":
        headline = "Call-heavy premium with " + liquidity_quality + " liquidity"
    elif bias == "put_heavy":
        headline = "Put-heavy premium with " + liquidity_quality + " liquidity"
    else:
        headline = "Balanced premium with " + liquidity_quality + " liquidity"

    # --- summary ---
    if trade_count == 0:
        summary = "No trades in this completed window."
    elif bias == "call_heavy":
        summary = f"Call premium dominated ({_fmt_premium(call_p)} vs {_fmt_premium(put_p)}), {cheap_side} side appears cheap."
    elif bias == "put_heavy":
        summary = f"Put premium dominated ({_fmt_premium(put_p)} vs {_fmt_premium(call_p)}), {cheap_side} side appears cheap."
    else:
        summary = f"Premium was balanced ({_fmt_premium(total_p)} total), {cheap_side} side appears cheap."

    result = {
        "narrative_version": NARRATIVE_VERSION,
        "summary": summary,
        "narrative": {
            "headline": headline,
            "what_happened": what_happened,
            "what_it_means": what_it_means,
            "caveats": caveats,
            "reason_codes": [],
        },
    }

    all_text = summary + " " + headline + " " + " ".join(what_happened) + " " + " ".join(what_it_means) + " " + " ".join(caveats)
    violations = check_banned_phrases(all_text)
    if violations:
        raise ValueError(f"Narrative contains banned phrases: {violations}")

    return result


# ---------------------------------------------------------------------------
# Lifecycle message narratives (WINDOW_VIEW, INTERMEDIATE, BET, BLOCKED, LIQUIDATE)
# ---------------------------------------------------------------------------


def build_window_view_narrative(payload: dict) -> dict:
    """Build narrative fields for a WINDOW_VIEW message."""
    sentiment = payload.get("sentiment", "unknown")
    reason = payload.get("reason", "")
    strategy = payload.get("strategy", "unknown")

    sentiment_word = sentiment.lower()
    if sentiment_word == "chop":
        summary = "Window classified as CHOP."
        reason_summary = f"This strategy reads the completed window as CHOP because {_humanize_reason(reason)}."
    elif sentiment_word in ("bullish", "bearish"):
        summary = f"Window leans {sentiment_word}."
        reason_summary = f"This strategy reads the completed window as {sentiment_word} because {_humanize_reason(reason)}."
    else:
        summary = "Window read unavailable."
        reason_summary = f"Strategy {strategy} could not form a window read."

    return {
        "narrative_version": NARRATIVE_VERSION,
        "summary": summary,
        "reason_summary": reason_summary,
    }


def build_lifecycle_reason_summary(payload: dict) -> dict:
    """Build narrative fields for INTERMEDIATE, BET, BLOCKED, or LIQUIDATE."""
    decision = payload.get("decision", "")

    if decision == "INTERMEDIATE":
        strategy = payload.get("strategy", "unknown")
        sentiment = payload.get("sentiment", "unknown").lower()
        entry_time = payload.get("entry_time", "unknown")
        reason_summary = f"Candidate identified from {sentiment} flow in the completed {entry_time} window by {strategy}."

    elif decision == "BET":
        reason_summary = "Final paper signal emitted because the strategy rule passed and required quote checks were fresh."

    elif decision == "BLOCKED":
        missing = payload.get("missing_features") or []
        failures = payload.get("feature_failures") or {}
        if missing:
            reason_summary = f"Blocked because required fields were missing or stale: {', '.join(missing)}."
        elif failures:
            details = ", ".join(f"{k} ({v})" for k, v in failures.items())
            reason_summary = f"Blocked because feature checks failed: {details}."
        else:
            block_reason = payload.get("block_reason", "unknown reason")
            reason_summary = f"Blocked: {block_reason}."

    elif decision == "LIQUIDATE":
        liq_reason = payload.get("reason", "unknown")
        ret = payload.get("return_pct")
        if ret is not None:
            reason_summary = f"Liquidation context emitted: {liq_reason} at {float(ret):.1f}% return."
        else:
            reason_summary = f"Liquidation context emitted: {liq_reason}."

    else:
        reason_summary = f"Lifecycle event: {decision}."

    return {
        "narrative_version": NARRATIVE_VERSION,
        "reason_summary": reason_summary,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_REASON_HUMANIZE = {
    "call_dominance": "call premium dominates",
    "put_dominance": "put premium dominates",
    "no_open_dominance": "neither side shows clear dominance at the open",
    "cheap_vol_or_premium_filter_not_met": "volatility or premium filters were not met",
    "flow_alignment": "option flow aligned directionally",
    "confluence_alignment": "flow, pricing lag, and momentum aligned",
    "pricing_lag_not_cheap_enough": "pricing lag was not cheap enough to qualify",
    "momentum_heuristic_not_met": "the momentum heuristic did not qualify",
}


def _humanize_reason(reason: str) -> str:
    """Convert a snake_case reason code into readable prose."""
    if reason in _REASON_HUMANIZE:
        return _REASON_HUMANIZE[reason]
    return reason.replace("_", " ")
