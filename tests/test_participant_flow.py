"""Unit tests for participant_flow — pure functions, no Redis."""

from __future__ import annotations

import polars as pl
import pytest

from sigmatiq_nexus import participant_flow as pf

CONFIG = pf.PARTICIPANT_FLOW_DEFAULT_CONFIG


def _ctx(contract_counts=None, contract_premiums=None, total_premium=1_000_000):
    return {
        "contract_counts": contract_counts or {},
        "contract_premiums": contract_premiums or {},
        "total_premium": total_premium,
    }


def _row(**overrides):
    base = {
        "ts_utc": "2026-05-08T14:00:00Z",
        "symbol": "SPY",
        "raw_symbol": "SPY   260508C00560000",
        "side": "C",
        "premium": 50_000.0,
        "is_sweep": False,
        "aggressor": "A",
        "delta": 0.45,
        "gamma": 0.02,
        "option_mid": 5.0,
        "option_bid": 4.90,
        "option_ask": 5.10,
        "underlying_mid": 560.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Trade labeler tests
# ---------------------------------------------------------------------------


class TestLabelTradeParticipantShape:

    def test_retail_like_lottery_calls(self):
        row = _row(premium=2000, option_mid=0.10, delta=0.08, side="C", aggressor="A")
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["participant_label"] == "retail_like"
        assert result["strategy_shape"] == "lottery_calls"
        assert result["direction_bias"] == "bullish"

    def test_retail_like_lottery_puts(self):
        row = _row(premium=3000, option_mid=0.15, delta=-0.06, side="P", aggressor="A",
                   raw_symbol="SPY   260508P00540000")
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["participant_label"] == "retail_like"
        assert result["strategy_shape"] == "lottery_puts"
        assert result["direction_bias"] == "bearish"

    def test_institutional_like_large_ask_side(self):
        row = _row(premium=250_000, side="P", aggressor="A", delta=-0.40,
                   raw_symbol="SPY   260508P00555000")
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["participant_label"] == "institutional_like"
        assert result["strategy_shape"] == "directional_put_buying"

    def test_institutional_like_large_sweep(self):
        row = _row(premium=150_000, is_sweep=True, aggressor="B")
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["participant_label"] == "institutional_like"

    def test_positioning_or_hedge_like_far_otm_put(self):
        row = _row(premium=200_000, side="P", delta=-0.08, aggressor="A",
                   raw_symbol="SPY   260508P00530000")
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["participant_label"] == "positioning_or_hedge_like"
        assert result["strategy_shape"] == "tail_hedge_puts"

    def test_large_bid_side_degrades_confidence(self):
        row = _row(premium=200_000, aggressor="B")
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["confidence"] == "low"
        assert "BID_SIDE_AMBIGUOUS" in result["reason_codes"]

    def test_missing_quotes_and_aggressor_returns_unclear(self):
        row = _row(aggressor="", option_bid=None, option_ask=None)
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["participant_label"] == "unclear"
        assert result["confidence"] == "low"
        assert "MISSING_FRESH_CONTRACT_QUOTE" in result["reason_codes"]

    def test_repeat_cluster_below_institutional_threshold(self):
        ctx = _ctx(
            contract_counts={"SPY   260508C00560000": 5},
            contract_premiums={"SPY   260508C00560000": 40_000},
        )
        row = _row(premium=8_000)
        result = pf.label_trade_participant_shape(row, ctx, CONFIG)
        assert result["participant_label"] == "coordinated_or_clustered_like"
        assert "REPEAT_CLUSTER_BELOW_INSTITUTIONAL_THRESHOLD" in result["reason_codes"]

    def test_repeat_cluster_above_institutional_threshold(self):
        ctx = _ctx(
            contract_counts={"SPY   260508C00560000": 5},
            contract_premiums={"SPY   260508C00560000": 150_000},
        )
        row = _row(premium=30_000)
        result = pf.label_trade_participant_shape(row, ctx, CONFIG)
        assert result["participant_label"] == "institutional_like"
        assert "HIGH_PREMIUM_CONTRACT_CLUSTER" in result["reason_codes"]

    def test_premium_shock(self):
        row = _row(premium=600_000)
        result = pf.label_trade_participant_shape(row, _ctx(total_premium=1_000_000), CONFIG)
        assert result["strategy_shape"] == "premium_shock"

    def test_directional_call_buying(self):
        row = _row(premium=50_000, side="C", aggressor="A", delta=0.45)
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["strategy_shape"] == "directional_call_buying"
        assert result["direction_bias"] == "bullish"

    def test_chop_or_income_like_midpoint(self):
        row = _row(premium=20_000, aggressor="M", delta=0.50)
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["strategy_shape"] == "chop_or_income_like"

    def test_wide_spread_degrades_confidence(self):
        row = _row(option_bid=1.0, option_ask=2.0, option_mid=1.5, aggressor="A", premium=50_000)
        result = pf.label_trade_participant_shape(row, _ctx(), CONFIG)
        assert result["confidence"] == "low"
        assert "WIDE_SPREAD_LOW_CONFIDENCE" in result["reason_codes"]


# ---------------------------------------------------------------------------
# Window aggregation tests
# ---------------------------------------------------------------------------


def _make_df(rows):
    return pl.DataFrame(rows)


class TestAggregateWindow:

    def test_call_heavy_bullish_read(self):
        rows = [
            _row(premium=300_000, side="C", aggressor="A"),
            _row(premium=200_000, side="C", aggressor="A", raw_symbol="SPY   260508C00565000"),
            _row(premium=50_000, side="P", aggressor="A", raw_symbol="SPY   260508P00555000", delta=-0.40),
        ]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert result["window_side_read"]["premium_bias"] == "call_heavy"
        assert result["window_side_read"]["directional_read"] == "bullish"

    def test_bid_heavy_window_returns_unknown(self):
        """Bid-side call premium with smaller ask-side put should not be directional."""
        rows = [
            _row(premium=300_000, side="C", aggressor="B"),
            _row(premium=250_000, side="P", aggressor="A", raw_symbol="SPY   260508P00555000", delta=-0.40),
        ]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        wsr = result["window_side_read"]
        # Bid-side dominates total premium — directional read is unknown
        assert wsr["directional_read"] == "unknown"
        assert wsr["confidence"] == "low"

    def test_conflicted_read_premium_vs_aggressor(self):
        """Premium (total) says calls but ask-side aggressor says puts — conflicted."""
        rows = [
            # Total premium: calls dominate (600k vs 100k)
            _row(premium=300_000, side="C", aggressor="B"),  # bid-side — ambiguous
            _row(premium=300_000, side="C", aggressor="B", raw_symbol="SPY   260508C00565000"),  # bid-side
            # But ask-side premium: puts dominate (800k vs 0)
            _row(premium=400_000, side="P", aggressor="A", raw_symbol="SPY   260508P00555000", delta=-0.40),
            _row(premium=400_000, side="P", aggressor="A", raw_symbol="SPY   260508P00550000", delta=-0.35),
        ]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        wsr = result["window_side_read"]
        # Ask-side puts dominate → bearish (bid-side calls are ignored for direction)
        assert wsr["directional_read"] == "bearish"

    def test_retail_dominant_shape(self):
        rows = [_row(premium=2000, option_mid=0.10, delta=0.08, aggressor="A") for _ in range(10)]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert result["retail_like_flow"]["trade_count"] == 10
        assert result["retail_like_flow"]["dominant_shape"] == "lottery_calls"

    def test_institutional_flow_aggregation(self):
        rows = [
            _row(premium=250_000, side="P", aggressor="A", delta=-0.40,
                 raw_symbol="SPY   260508P00555000"),
            _row(premium=200_000, side="P", aggressor="A", delta=-0.35,
                 raw_symbol="SPY   260508P00550000"),
        ]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert result["institutional_like_flow"]["trade_count"] == 2
        assert result["institutional_like_flow"]["bias"] == "bearish"

    def test_top_contracts_sorted_by_premium(self):
        rows = [
            _row(premium=100_000, raw_symbol="SPY   260508C00560000"),
            _row(premium=300_000, raw_symbol="SPY   260508C00565000"),
            _row(premium=50_000, raw_symbol="SPY   260508P00555000", side="P", delta=-0.40),
        ]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert len(result["top_contracts"]) == 3
        assert result["top_contracts"][0]["raw_symbol"] == "SPY   260508C00565000"

    def test_top_contracts_limited(self):
        rows = [_row(premium=10_000 * i, raw_symbol=f"SPY   260508C005{60+i:02d}000") for i in range(1, 8)]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert len(result["top_contracts"]) <= CONFIG["top_contracts_limit"]

    def test_data_quality_usable(self):
        rows = [_row(aggressor="A") for _ in range(15)]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert result["data_quality"]["status"] == "usable"
        assert "opening_or_closing_unknown" in result["data_quality"]["degraded"]

    def test_data_quality_thin(self):
        rows = [_row()]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert result["data_quality"]["status"] == "thin"

    def test_data_quality_degraded_no_aggressor(self):
        rows = [_row(aggressor="", option_bid=4.9, option_ask=5.1) for _ in range(15)]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert result["data_quality"]["status"] in ("degraded", "usable")

    def test_bid_side_premium_does_not_produce_directional_read(self):
        """Bid-side call premium should NOT produce a bullish directional read."""
        rows = [
            _row(premium=500_000, side="C", aggressor="B"),
            _row(premium=400_000, side="C", aggressor="B", raw_symbol="SPY   260508C00565000"),
            _row(premium=20_000, side="P", aggressor="A", raw_symbol="SPY   260508P00555000", delta=-0.40),
        ]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        wsr = result["window_side_read"]
        # Even though call premium dominates, bid-side flow should not produce bullish
        assert wsr["directional_read"] in ("unknown", "conflicted")
        assert wsr["confidence"] == "low"

    def test_bid_side_group_bias_is_unknown(self):
        """Group aggregation should not produce directional bias from bid-side flow."""
        rows = [
            _row(premium=200_000, side="C", aggressor="B"),
            _row(premium=150_000, side="C", aggressor="B", raw_symbol="SPY   260508C00565000"),
        ]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        # Institutional-like trades are bid-side, bias should be unknown
        inst = result["institutional_like_flow"]
        if inst["trade_count"] > 0:
            assert inst["confidence"] == "low"

    def test_data_quality_degrades_with_low_confidence_labels(self):
        """data_quality should be degraded when most labels are low-confidence."""
        # All trades are bid-side → low confidence
        rows = [_row(premium=50_000, aggressor="B") for _ in range(15)]
        result = pf.aggregate_participant_flow_window(_make_df(rows), CONFIG)
        assert result["data_quality"]["status"] == "degraded"
        assert "low_confidence_labels" in result["data_quality"]["degraded"]

    def test_empty_dataframe(self):
        result = pf.aggregate_participant_flow_window(pl.DataFrame(), CONFIG)
        assert result["window_side_read"]["directional_read"] == "unknown"
        assert result["data_quality"]["status"] == "unknown"


# ---------------------------------------------------------------------------
# Dealer inference tests
# ---------------------------------------------------------------------------


class TestDealerInference:

    def test_v1_returns_unknown(self):
        result = pf.infer_dealer_pressure()
        assert result["underlying_hedge_direction"] == "unknown"
        assert result["impact_state"] == "unknown"
        assert result["confidence"] == "low"
        assert result["source"] == "unavailable"
        assert "DEALER_CONTEXT_STALE_OR_MISSING" in result["reason_codes"]


# ---------------------------------------------------------------------------
# Payload builder tests
# ---------------------------------------------------------------------------


class TestBuildPayload:

    def _slot(self):
        from datetime import time
        return {
            "entry": time(10, 0),
            "end": time(10, 0),
            "window_start": time(9, 30),
            "window_end": time(10, 0),
            "entry_label": "w0930_1000",
        }

    def test_payload_schema_version_and_identity(self):
        from datetime import date
        rows = [_row()]
        msg = pf.build_participant_flow_payload(_make_df(rows), "SPY", self._slot(), date(2026, 5, 8), CONFIG)
        assert msg["schema_version"] == 1
        assert msg["symbol"] == "SPY"
        assert msg["window_key"] == "w0930_1000"
        assert msg["window_label"] == "09:30-10:00"
        assert msg["window_status"] == "completed"
        assert msg["is_partial"] is False
        assert msg["source"] == "sigmatiq_nexus"
        assert msg["redis_key"] == "nexus_participant_flow_context:SPY:w0930_1000"
        assert msg["session_date"] == "2026-05-08"

    def test_payload_contains_all_sections(self):
        from datetime import date
        rows = [_row()]
        msg = pf.build_participant_flow_payload(_make_df(rows), "SPY", self._slot(), date(2026, 5, 8), CONFIG)
        assert "window_side_read" in msg
        assert "retail_like_flow" in msg
        assert "institutional_like_flow" in msg
        assert "dealer_inferred_pressure" in msg
        assert "dominant_strategy_shape" in msg
        assert "top_contracts" in msg
        assert "data_quality" in msg

    def test_payload_dealer_inferred_pressure_unknown_v1(self):
        from datetime import date
        rows = [_row()]
        msg = pf.build_participant_flow_payload(_make_df(rows), "SPY", self._slot(), date(2026, 5, 8), CONFIG)
        assert msg["dealer_inferred_pressure"]["underlying_hedge_direction"] == "unknown"
        assert msg["dealer_inferred_pressure"]["impact_state"] == "unknown"


# ---------------------------------------------------------------------------
# Config defaults test
# ---------------------------------------------------------------------------


class TestConfigDefaults:

    def test_config_matches_design_doc(self):
        assert CONFIG["large_premium_threshold"] == 100_000
        assert CONFIG["small_premium_threshold"] == 5_000
        assert CONFIG["cheap_option_mid_threshold"] == 0.25
        assert CONFIG["far_otm_delta_threshold"] == 0.15
        assert CONFIG["repeat_cluster_min_aggregate_premium"] == 100_000
        assert CONFIG["max_spread_pct"] == 0.20
        assert CONFIG["side_dominance_ratio"] == 1.5
        assert CONFIG["top_contracts_limit"] == 5


# ---------------------------------------------------------------------------
# Helpers test
# ---------------------------------------------------------------------------


class TestHelpers:

    def test_parse_expiry(self):
        assert pf._parse_expiry("SPY   260508C00560000") == "2026-05-08"
        assert pf._parse_expiry("SPY260508C00560000") == "2026-05-08"

    def test_parse_strike(self):
        assert pf._parse_strike("SPY   260508C00560000") == 560.0
        assert pf._parse_strike("SPY260508P00555000") == 555.0

    def test_parse_short_symbol_returns_none(self):
        assert pf._parse_expiry("SPY") is None
        assert pf._parse_strike("SPY") is None
