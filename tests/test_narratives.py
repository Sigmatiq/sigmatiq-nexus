"""Unit tests for narratives — deterministic template builders."""

from __future__ import annotations

import pytest

from sigmatiq_nexus import narratives


# ---------------------------------------------------------------------------
# Banned phrase tests
# ---------------------------------------------------------------------------


class TestBannedPhrases:

    def test_catches_banned_phrase(self):
        assert narratives.check_banned_phrases("you should buy this now") == ["buy this"]

    def test_catches_multiple(self):
        result = narratives.check_banned_phrases("buy this and sell this")
        assert "buy this" in result
        assert "sell this" in result

    def test_clean_text_passes(self):
        assert narratives.check_banned_phrases("Call premium leans bullish.") == []

    def test_valid_phrases_not_banned(self):
        """Phrases like 'short-dated options' or 'sell-side quote' must not trigger."""
        assert narratives.check_banned_phrases("short-dated options") == []
        assert narratives.check_banned_phrases("sell-side quote") == []
        assert narratives.check_banned_phrases("buy/sell spread") == []


# ---------------------------------------------------------------------------
# Participant flow context narrative
# ---------------------------------------------------------------------------


def _pf_payload(**overrides):
    base = {
        "window_side_read": {
            "premium_bias": "call_heavy",
            "aggressor_bias": "ask_side_call_heavy",
            "directional_read": "bullish",
            "confidence": "medium",
            "call_premium": 1_200_000,
            "put_premium": 650_000,
            "reason_codes": ["CALL_PREMIUM_DOMINANCE", "ASK_SIDE_CALL_LARGE_PRINTS"],
        },
        "retail_like_flow": {
            "bias": "bullish",
            "confidence": "low",
            "premium": 180_000,
            "trade_count": 42,
            "dominant_side": "calls",
            "dominant_shape": "lottery_calls",
        },
        "institutional_like_flow": {
            "bias": "bearish",
            "confidence": "medium",
            "premium": 850_000,
            "trade_count": 5,
            "dominant_side": "puts",
            "dominant_shape": "directional_put_buying",
        },
        "dealer_inferred_pressure": {
            "underlying_hedge_direction": "unknown",
            "impact_state": "unknown",
            "confidence": "low",
            "source": "unavailable",
        },
        "dominant_strategy_shape": {
            "shape": "directional_call_buying",
            "confidence": "medium",
        },
        "top_contracts": [
            {
                "raw_symbol": "SPY260508C00520000",
                "side": "C",
                "premium": 450_000,
            }
        ],
        "data_quality": {
            "status": "usable",
            "missing": [],
            "degraded": ["opening_or_closing_unknown"],
        },
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


class TestParticipantFlowNarrative:

    def test_bullish_produces_cautious_summary(self):
        result = narratives.build_participant_flow_context_narrative(_pf_payload())
        assert result["narrative_version"] == "1.0"
        assert "Call premium dominated" in result["summary"]
        assert result["narrative"]["headline"] == "Appears bullish, medium confidence"

    def test_bearish_headline(self):
        payload = _pf_payload(window_side_read={
            "premium_bias": "put_heavy",
            "aggressor_bias": "ask_side_put_heavy",
            "directional_read": "bearish",
            "confidence": "high",
            "call_premium": 200_000,
            "put_premium": 800_000,
            "reason_codes": ["PUT_PREMIUM_DOMINANCE"],
        })
        result = narratives.build_participant_flow_context_narrative(payload)
        assert "bearish" in result["narrative"]["headline"].lower()
        assert "Put premium dominated" in result["summary"]

    def test_low_confidence_appears_in_summary(self):
        payload = _pf_payload(window_side_read={
            "premium_bias": "call_heavy",
            "aggressor_bias": "balanced",
            "directional_read": "bullish",
            "confidence": "low",
            "call_premium": 500_000,
            "put_premium": 200_000,
            "reason_codes": [],
        })
        result = narratives.build_participant_flow_context_narrative(payload)
        assert "confidence is low" in result["summary"]

    def test_bid_side_ambiguity_in_caveats(self):
        payload = _pf_payload(data_quality={
            "status": "degraded",
            "missing": [],
            "degraded": ["opening_or_closing_unknown", "low_confidence_labels"],
        })
        result = narratives.build_participant_flow_context_narrative(payload)
        assert any("low confidence" in c.lower() for c in result["narrative"]["caveats"])

    def test_dealer_unknown_caveat(self):
        result = narratives.build_participant_flow_context_narrative(_pf_payload())
        assert any("dealer" in c.lower() for c in result["narrative"]["caveats"])

    def test_not_a_trade_recommendation_caveat(self):
        result = narratives.build_participant_flow_context_narrative(_pf_payload())
        assert any("not a trade recommendation" in c.lower() for c in result["narrative"]["caveats"])

    def test_opening_closing_unavailable_caveat(self):
        result = narratives.build_participant_flow_context_narrative(_pf_payload())
        assert any("opening/closing" in c.lower() for c in result["narrative"]["caveats"])

    def test_thin_quality_changes_summary(self):
        payload = _pf_payload(
            data_quality={"status": "thin", "missing": [], "degraded": ["opening_or_closing_unknown"]},
            window_side_read={
                "premium_bias": "balanced", "aggressor_bias": "balanced",
                "directional_read": "unknown", "confidence": "low",
                "call_premium": 10_000, "put_premium": 10_000, "reason_codes": [],
            },
        )
        result = narratives.build_participant_flow_context_narrative(payload)
        assert result["summary"].startswith("Thin window:")

    def test_degraded_quality_changes_summary(self):
        payload = _pf_payload(
            data_quality={"status": "degraded", "missing": ["aggressor"], "degraded": ["opening_or_closing_unknown"]},
        )
        result = narratives.build_participant_flow_context_narrative(payload)
        assert result["summary"].startswith("Degraded read:")

    def test_stale_quality_changes_summary(self):
        payload = _pf_payload(
            data_quality={"status": "stale", "missing": [], "degraded": ["opening_or_closing_unknown"]},
        )
        result = narratives.build_participant_flow_context_narrative(payload)
        assert result["summary"].startswith("Stale read:")
        assert any("not be treated as current" in m for m in result["narrative"]["what_it_means"])

    def test_unknown_quality_changes_summary(self):
        payload = _pf_payload(
            data_quality={"status": "unknown", "missing": [], "degraded": ["opening_or_closing_unknown"]},
        )
        result = narratives.build_participant_flow_context_narrative(payload)
        assert result["summary"].startswith("Unknown read:")

    def test_no_banned_phrases_in_output(self):
        result = narratives.build_participant_flow_context_narrative(_pf_payload())
        all_text = result["summary"] + " " + result["narrative"]["headline"]
        all_text += " " + " ".join(result["narrative"]["what_happened"])
        all_text += " " + " ".join(result["narrative"]["what_it_means"])
        all_text += " " + " ".join(result["narrative"]["caveats"])
        assert narratives.check_banned_phrases(all_text) == []

    def test_deterministic_output(self):
        """Same input must produce identical output."""
        payload = _pf_payload()
        r1 = narratives.build_participant_flow_context_narrative(payload)
        r2 = narratives.build_participant_flow_context_narrative(payload)
        assert r1 == r2

    def test_required_fields_present(self):
        result = narratives.build_participant_flow_context_narrative(_pf_payload())
        assert "narrative_version" in result
        assert "summary" in result
        assert "narrative" in result
        assert "headline" in result["narrative"]
        assert "what_happened" in result["narrative"]
        assert "what_it_means" in result["narrative"]
        assert "caveats" in result["narrative"]
        assert "reason_codes" in result["narrative"]

    def test_retail_flow_appears_in_what_happened(self):
        result = narratives.build_participant_flow_context_narrative(_pf_payload())
        what = " ".join(result["narrative"]["what_happened"])
        assert "small-lot-like" in what.lower()

    def test_institutional_flow_appears_in_what_happened(self):
        result = narratives.build_participant_flow_context_narrative(_pf_payload())
        what = " ".join(result["narrative"]["what_happened"])
        assert "block-like" in what.lower()


# ---------------------------------------------------------------------------
# Window view narrative
# ---------------------------------------------------------------------------


class TestWindowViewNarrative:

    def test_chop_summary(self):
        result = narratives.build_window_view_narrative({"sentiment": "CHOP", "reason": "no_open_dominance", "strategy": "etf_open_specialist"})
        assert "CHOP" in result["summary"]
        assert "neither side" in result["reason_summary"]

    def test_bullish_summary(self):
        result = narratives.build_window_view_narrative({"sentiment": "BULLISH", "reason": "call_dominance"})
        assert "bullish" in result["summary"]
        assert "call premium dominates" in result["reason_summary"]


# ---------------------------------------------------------------------------
# Lifecycle reason summaries
# ---------------------------------------------------------------------------


class TestLifecycleNarrative:

    def test_intermediate(self):
        result = narratives.build_lifecycle_reason_summary({"decision": "INTERMEDIATE", "strategy": "etf_flow_specialist", "sentiment": "BEARISH", "entry_time": "10:30"})
        assert "bearish" in result["reason_summary"]
        assert "10:30" in result["reason_summary"]

    def test_bet(self):
        result = narratives.build_lifecycle_reason_summary({"decision": "BET"})
        assert "paper signal" in result["reason_summary"].lower()

    def test_blocked_with_missing_features(self):
        result = narratives.build_lifecycle_reason_summary({"decision": "BLOCKED", "missing_features": ["net_gex", "atm_iv"]})
        assert "net_gex" in result["reason_summary"]
        assert "atm_iv" in result["reason_summary"]

    def test_liquidate_with_return(self):
        result = narratives.build_lifecycle_reason_summary({"decision": "LIQUIDATE", "reason": "STOP_LOSS", "return_pct": -50.2})
        assert "STOP_LOSS" in result["reason_summary"]
        assert "-50.2%" in result["reason_summary"]

    def test_all_lifecycle_include_narrative_version(self):
        for decision in ["INTERMEDIATE", "BET", "BLOCKED", "LIQUIDATE"]:
            result = narratives.build_lifecycle_reason_summary({"decision": decision, "strategy": "test", "sentiment": "BULLISH", "entry_time": "10:00"})
            assert result["narrative_version"] == "1.0"
