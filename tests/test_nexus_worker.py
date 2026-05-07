from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone

import msgpack
import polars as pl

from sigmatiq_nexus import feature_audit as fa
from sigmatiq_nexus import nexus_worker as nw


def row(ts: str, side: str, premium: float, sweep: bool = False) -> dict:
    return {
        "ts_utc": ts,
        "symbol": "SPY",
        "side": side,
        "premium": premium,
        "is_sweep": sweep,
        "delta": 0.5,
        "gamma": 0.01,
        "aggressor": "A",
    }


def test_decision_slot_uses_event_time_in_new_york():
    slot = nw.decision_slot(datetime(2026, 5, 5, 14, 5, tzinfo=timezone.utc))

    assert slot is not None
    assert slot["entry_label"] == "10:00"
    assert slot["window_start"].isoformat() == "09:30:00"
    assert slot["window_end"].isoformat() == "10:00:00"


def test_decision_slot_includes_1130_completed_window():
    slot = nw.decision_slot(datetime(2026, 5, 5, 15, 35, tzinfo=timezone.utc))

    assert slot is not None
    assert slot["entry_label"] == "11:30"
    assert slot["window_start"].isoformat() == "11:00:00"
    assert slot["window_end"].isoformat() == "11:30:00"


def test_window_df_for_slot_uses_completed_window_not_current_tick_window():
    df = pl.DataFrame([
        row("2026-05-05T13:35:00Z", "C", 150_000),  # 09:35 ET, included for 10:00 entry
        row("2026-05-05T13:59:59Z", "C", 75_000),
        row("2026-05-05T14:05:00Z", "P", 500_000),  # 10:05 ET, excluded
    ])

    filtered = nw.window_df_for_slot(df, nw.DECISION_SLOTS[0])

    assert filtered.height == 2
    assert filtered["premium"].sum() == 225_000


def test_window_stats_normalizes_option_side_case():
    df = pl.DataFrame([
        row("2026-05-05T13:35:00Z", "c", 300_000),
        row("2026-05-05T13:36:00Z", "P", 100_000, sweep=True),
    ])

    stats = nw.window_stats(df)

    assert stats["total_p"] == 400_000
    assert stats["call_p"] == 300_000
    assert stats["put_p"] == 100_000
    assert stats["sweep"] == 0.5
    assert nw.dominant_side(stats) == "C"


def test_decode_msgpack_stream_entry_derives_live_trade_fields():
    payload = {
        "underlying": "SPY",
        "raw_symbol": "SPY   260505P00719000",
        "price": 1.25,
        "size": 4,
        "ts_event_ns": 1_778_012_099_996_787_889,
    }

    decoded = nw.decode_stream_entry({b"data": msgpack.packb(payload, use_bin_type=True)})

    assert decoded["symbol"] == "SPY"
    assert decoded["side"] == "P"
    assert decoded["premium"] == 500.0
    assert decoded["is_sweep"] is False
    assert decoded["ts_utc"].startswith("2026-")


def test_contract_details_from_raw_symbol_parses_expiry_strike_and_side():
    details = nw._contract_details_from_raw_symbol("SPY   260505P00719000")

    assert details == {
        "expiry_date": "2026-05-05",
        "strike": 719.0,
        "side": "P",
    }


def test_feature_audit_blocks_raw_trade_payload_missing_strategy_fields():
    payload = {
        "underlying": "SPY",
        "raw_symbol": "SPY   260505P00719000",
        "price": 1.25,
        "size": 4,
        "ts_event_ns": 1_778_012_099_996_787_889,
    }

    audit = fa.audit_payload(payload, {})

    assert audit["features"]["premium"]["status"] == "derived"
    assert audit["features"]["side"]["status"] == "derived"
    assert audit["features"]["is_sweep"]["status"] == "missing"
    assert audit["strategies"]["etf_low_sweep_core"]["status"] == "blocked"
    assert "is_sweep" in audit["strategies"]["etf_low_sweep_core"]["missing"]
    assert "iv_rank" in audit["strategies"]["etf_open_specialist"]["missing"]
    assert "delta" in audit["strategies"]["etf_flow_specialist"]["missing"]
    assert "underlying_mid" in audit["strategies"]["etf_momentum_specialist"]["missing"]


def test_feature_audit_marks_enriched_payload_ready_for_all_strategies():
    payload = {
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00719000",
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 1_250.0,
        "is_sweep": False,
        "aggressor": "A",
        "delta": 0.52,
        "gamma": 0.018,
        "greeks_ts_utc": "2026-05-05T14:00:00Z",
        "underlying_mid": 700.25,
        "underlying_ts_utc": "2026-05-05T14:00:00Z",
        "option_mid": 1.24,
        "quote_ts_utc": "2026-05-05T14:00:00Z",
    }

    audit = fa.audit_payload(payload, {"iv_rank": 24.0, "atm_iv": 0.18, "net_gex": 1_000_000, "asOf": "2026-05-05T14:00:00Z"})

    assert {result["status"] for result in audit["strategies"].values()} == {"ready"}


def test_feature_audit_blocks_confluence_when_only_trade_price_exists():
    payload = {
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00719000",
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 1_250.0,
        "is_sweep": False,
        "aggressor": "A",
        "delta": 0.52,
        "gamma": 0.018,
        "greeks_ts_utc": "2026-05-05T14:00:00Z",
        "underlying_mid": 700.25,
        "underlying_ts_utc": "2026-05-05T14:00:00Z",
    }

    audit = fa.audit_payload(payload, {"iv_rank": 24.0, "atm_iv": 0.18, "net_gex": 1_000_000, "asOf": "2026-05-05T14:00:00Z"})

    confluence = audit["strategies"]["etf_confluence_sniper"]
    assert confluence["status"] == "blocked"
    assert confluence["missing"] == ["option_mid"]


def test_open_specialist_uses_cheap_call_dominance_for_1000_entry():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.redis = FakeRedis({"options:live:vrp:SPY": json.dumps({"ivRank": 24.0, "asOf": "2026-05-05T14:00:00Z"})})
    df = pl.DataFrame([
        row("2026-05-05T13:35:00Z", "C", 210_000, sweep=True),
        row("2026-05-05T13:50:00Z", "P", 100_000, sweep=True),
    ])

    assert asyncio.run(worker.check_open_specialist_heuristic(df, "SPY", nw.DECISION_SLOTS[0])) == ("BULLISH", True)
    assert asyncio.run(worker.check_open_specialist_heuristic(df, "SPY", nw.DECISION_SLOTS[1])) == (None, False)


def test_low_sweep_core_allows_only_research_windows_and_sides():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    call_df = pl.DataFrame([row("2026-05-05T13:35:00Z", "C", 250_000, sweep=False)])
    put_df = pl.DataFrame([row("2026-05-05T13:35:00Z", "P", 250_000, sweep=False)])

    assert asyncio.run(worker.calculate_low_sweep_heuristic(call_df, nw.DECISION_SLOTS[0])) == ("BULLISH", True)
    assert asyncio.run(worker.calculate_low_sweep_heuristic(put_df, nw.DECISION_SLOTS[0])) == (None, False)
    assert asyncio.run(worker.calculate_low_sweep_heuristic(call_df, nw.DECISION_SLOTS[1])) == ("BULLISH", True)
    assert asyncio.run(worker.calculate_low_sweep_heuristic(put_df, nw.DECISION_SLOTS[1])) == ("BEARISH", True)
    assert asyncio.run(worker.calculate_low_sweep_heuristic(call_df, nw.DECISION_SLOTS[2])) == (None, False)


def test_low_sweep_core_rejects_high_sweep_windows():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    df = pl.DataFrame([row("2026-05-05T13:35:00Z", "C", 250_000, sweep=True)])

    assert asyncio.run(worker.calculate_low_sweep_heuristic(df, nw.DECISION_SLOTS[0])) == (None, False)


def test_confluence_pricing_lag_detects_cheap_option_after_underlying_move():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    df = pl.DataFrame([
        {
            **row("2026-05-05T14:00:00Z", "C", 125_000),
            "raw_symbol": "SPY   260505C00700000",
            "option_mid": 1.00,
            "underlying_mid": 700.0,
            "delta": 0.50,
        },
        {
            **row("2026-05-05T14:06:00Z", "C", 125_000),
            "raw_symbol": "SPY   260505C00700000",
            "option_mid": 1.10,
            "underlying_mid": 701.0,
            "delta": 0.50,
        },
    ])

    lag = worker.calculate_pricing_lag(df, "BULLISH")

    assert lag is not None
    assert lag < -0.05


def test_workflow_uses_configured_redis_host_variable():
    text = open(".github/workflows/deploy-nexus-prod.yml", encoding="utf-8").read()

    assert "CORE_REDIS_HOST" not in text
    assert "rg-sigmatiq-prod" in text
    assert "secrets.NEXUS_REDIS_URL" in text
    assert "NEXUS_REDIS_CLUSTER=true" in text
    assert "NEXUS_SYMBOLS=SPY,QQQ" in text
    assert "NEXUS_FIRST_TRIGGER_SCOPE=symbol" in text
    assert "NEXUS_GROUP_LOCK_STRATEGIES=etf_confluence_sniper" in text


def test_default_symbols_and_scope_cover_combined_etf_sniper():
    assert {"SPY", "QQQ"}.issubset(nw.SYMBOLS)
    assert nw.FIRST_TRIGGER_SCOPE == "symbol"
    assert "etf_confluence_sniper" in nw.GROUP_LOCK_STRATEGIES

class FakeRedis:
    def __init__(self, values=None):
        self.values = values or {}
        self.sets = []
        self.publishes = []
        self.xadds = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.sets.append((key, value))

    async def publish(self, channel, value):
        self.publishes.append((channel, value))

    async def xadd(self, name, fields, maxlen=None, approximate=True):
        self.xadds.append((name, fields, maxlen, approximate))
        return "1-0"


class FakeXReadRedis:
    def __init__(self):
        self.calls = []

    async def xread(self, streams, count=None, block=None):
        self.calls.append((streams, count, block))
        stream_name = next(iter(streams))
        return [(stream_name, [(f"{len(self.calls)}-0", {b"data": b"{}"})])]


def test_cluster_mode_reads_each_input_stream_separately(monkeypatch):
    monkeypatch.setattr(nw, "REDIS_CLUSTER", True)
    redis_client = FakeXReadRedis()
    streams = {
        "md:QQQ:options:trades": "$",
        "md:SPY:options:trades": "$",
    }

    replies = asyncio.run(nw.read_input_streams(redis_client, streams))

    assert len(redis_client.calls) == 2
    assert [call[0] for call in redis_client.calls] == [
        {"md:QQQ:options:trades": "$"},
        {"md:SPY:options:trades": "$"},
    ]
    assert all(call[1:] == (10, 250) for call in redis_client.calls)
    assert [reply[0] for reply in replies] == ["md:QQQ:options:trades", "md:SPY:options:trades"]


def test_non_cluster_mode_uses_single_multi_stream_xread(monkeypatch):
    monkeypatch.setattr(nw, "REDIS_CLUSTER", False)
    redis_client = FakeXReadRedis()
    streams = {
        "md:QQQ:options:trades": "$",
        "md:SPY:options:trades": "$",
    }

    asyncio.run(nw.read_input_streams(redis_client, streams))

    assert redis_client.calls == [(streams, 10, 1000)]


def test_publish_final_appends_live_persistence_event():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis({
        "options:live:contract_state:SPY   260505C00720000": json.dumps({
            "optionMid": 1.24,
            "bid": 1.20,
            "ask": 1.28,
            "asOfUtc": "2026-05-05T14:00:00Z",
            "tradable": True,
        }),
        "options:live:tradability:SPY   260505C00720000": json.dumps({
            "quoteAgeMs": 700,
            "tradabilityBucket": "tradable",
        }),
    })

    asyncio.run(worker._publish_final("etf_low_sweep_core", "SPY", "BULLISH", 1.0, 1.24, datetime(2026, 5, 5).date(), nw.DECISION_SLOTS[0], "SPY   260505C00720000"))

    assert len(worker.redis.sets) == 1
    assert len(worker.redis.xadds) == 1
    stream, fields, maxlen, approximate = worker.redis.xadds[0]
    assert stream == "live:persistence:events"
    assert fields["redis_key"] == "nexus_live_overlay:SPY"
    payload = json.loads(fields["payload_json"])
    assert payload["strategy"] == "etf_low_sweep_core"
    assert payload["stage"] == 2
    assert payload["decision"] == "BET"
    assert payload["signal_id"].startswith("sig_")
    assert payload["position_id"] == payload["signal_id"]
    assert payload["raw_symbol"] == "SPY   260505C00720000"
    assert payload["expiry_date"] == "2026-05-05"
    assert payload["strike"] == 720.0
    assert payload["option_side"] == "C"
    assert payload["risk"]["stop_loss_pct"] == nw.STOP_LOSS_PCT
    assert payload["risk"]["guard_activate_pct"] == nw.GUARD_ACTIVATE_PCT
    assert payload["risk"]["guard_floor_pct"] == nw.GUARD_FLOOR_PCT
    assert payload["quote_freshness"] == "available"
    assert payload["quote_valid_until"] == "2026-05-05T14:00:05+00:00"
    assert payload["entry_quote"]["option_mid"] == 1.24
    assert payload["entry_quote"]["option_bid"] == 1.2
    assert payload["entry_quote"]["option_ask"] == 1.28
    assert payload["entry_quote"]["tradability_bucket"] == "tradable"
    assert payload["execution"]["order_type"] == "limit"
    assert payload["execution"]["price_reference"] == "option_mid"
    assert payload["execution"]["reference_price"] == 1.24
    assert payload["execution"]["max_slippage_pct"] == nw.EXECUTION_MAX_SLIPPAGE_PCT
    assert payload["execution"]["quote_freshness"] == "available"
    assert maxlen == 10000
    assert approximate is True


def test_publish_intermediate_sets_key_and_appends_persistence_event():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.redis = FakeRedis()

    asyncio.run(worker._publish_intermediate("etf_low_sweep_core", "SPY", "BULLISH", nw.DECISION_SLOTS[0], datetime(2026, 5, 5).date(), "SPY   260505C00720000"))

    assert worker.redis.sets[0][0] == "nexus_intermediate:SPY:etf_low_sweep_core:10:00"
    payload = json.loads(worker.redis.sets[0][1])
    assert payload["strategy"] == "etf_low_sweep_core"
    assert payload["stage"] == 1
    assert payload["decision"] == "INTERMEDIATE"
    assert payload["sentiment"] == "BULLISH"
    assert payload["signal_id"].startswith("sig_")
    assert payload["position_id"] == payload["signal_id"]
    assert payload["raw_symbol"] == "SPY   260505C00720000"
    assert worker.redis.xadds[0][1]["redis_key"] == "nexus_intermediate:SPY:etf_low_sweep_core:10:00"
    assert worker.redis.publishes[0] == ("nexus_intermediate:updates", "SPY")
    assert worker.redis.publishes[1][0] == "signal:intermediate:etf_low_sweep_core"


def test_publish_window_view_sets_key_and_appends_persistence_event():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.redis = FakeRedis()
    worker.window_views_reported = set()
    worker._current_window_df = pl.DataFrame([
        nw.normalize_trade_payload({
            "symbol": "SPY",
            "raw_symbol": "SPY   260505C00720000",
            "ts_utc": "2026-05-05T13:35:00Z",
            "side": "C",
            "price": 12.5,
            "size": 300,
            "premium": 375_000,
            "is_sweep": False,
            "aggressor": "A",
            "delta": 0.5,
            "gamma": 0.01,
            "underlying_mid": 720.0,
            "option_mid": 12.5,
        }),
        nw.normalize_trade_payload({
            "symbol": "SPY",
            "raw_symbol": "SPY   260505P00700000",
            "ts_utc": "2026-05-05T13:36:00Z",
            "side": "P",
            "price": 5.0,
            "size": 100,
            "premium": 50_000,
            "is_sweep": False,
            "aggressor": "A",
            "delta": -0.4,
            "gamma": 0.01,
            "underlying_mid": 719.5,
            "option_mid": 5.0,
        }),
    ])
    worker._current_window_pricing_summary = worker._window_pricing_summary(worker._current_window_df)

    asyncio.run(worker._publish_window_view(
        "etf_low_sweep_core",
        "SPY",
        "BULLISH",
        "low_sweep_call_dominance",
        nw.DECISION_SLOTS[0],
        datetime(2026, 5, 5).date(),
    ))

    assert worker.redis.sets[0][0] == "nexus_window_view:SPY:etf_low_sweep_core:10:00"
    payload = json.loads(worker.redis.sets[0][1])
    assert payload["decision"] == "WINDOW_VIEW"
    assert payload["sentiment"] == "BULLISH"
    assert payload["reason"] == "low_sweep_call_dominance"
    assert payload["lead_contract_raw_symbol"] == "SPY   260505C00720000"
    assert payload["lead_contract_expiry_date"] == "2026-05-05"
    assert payload["lead_contract_strike"] == 720.0
    assert payload["lead_contract_side"] == "C"
    assert "lead_contract_pricing_lag" in payload
    assert "lead_contract_cheapness_score" in payload
    assert worker.redis.xadds[0][1]["redis_key"] == "nexus_window_view:SPY:etf_low_sweep_core:10:00"
    assert worker.redis.publishes[0][0] == "signal:window_view:etf_low_sweep_core"


def test_publish_window_pricing_sets_key_and_side_summary():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.redis = FakeRedis()
    worker.window_pricing_reported = set()
    df = pl.DataFrame([
        nw.normalize_trade_payload({
            "symbol": "SPY",
            "raw_symbol": "SPY   260505C00720000",
            "ts_utc": "2026-05-05T13:35:00Z",
            "side": "C",
            "price": 10.0,
            "size": 200,
            "premium": 200_000,
            "is_sweep": False,
            "aggressor": "A",
            "delta": 0.50,
            "gamma": 0.01,
            "underlying_mid": 720.0,
            "option_mid": 10.0,
        }),
        nw.normalize_trade_payload({
            "symbol": "SPY",
            "raw_symbol": "SPY   260505C00720000",
            "ts_utc": "2026-05-05T13:41:00Z",
            "side": "C",
            "price": 10.4,
            "size": 200,
            "premium": 208_000,
            "is_sweep": False,
            "aggressor": "A",
            "delta": 0.50,
            "gamma": 0.01,
            "underlying_mid": 721.5,
            "option_mid": 10.4,
        }),
        nw.normalize_trade_payload({
            "symbol": "SPY",
            "raw_symbol": "SPY   260505P00700000",
            "ts_utc": "2026-05-05T13:35:00Z",
            "side": "P",
            "price": 8.0,
            "size": 150,
            "premium": 120_000,
            "is_sweep": False,
            "aggressor": "A",
            "delta": -0.45,
            "gamma": 0.01,
            "underlying_mid": 720.0,
            "option_mid": 8.0,
        }),
        nw.normalize_trade_payload({
            "symbol": "SPY",
            "raw_symbol": "SPY   260505P00700000",
            "ts_utc": "2026-05-05T13:41:00Z",
            "side": "P",
            "price": 7.4,
            "size": 150,
            "premium": 111_000,
            "is_sweep": False,
            "aggressor": "A",
            "delta": -0.45,
            "gamma": 0.01,
            "underlying_mid": 721.5,
            "option_mid": 7.4,
        }),
    ])

    asyncio.run(worker.publish_window_pricing(df, "SPY", nw.DECISION_SLOTS[0], datetime(2026, 5, 5).date()))

    payload = json.loads(worker.redis.sets[0][1])
    assert worker.redis.sets[0][0] == "nexus_window_pricing:SPY:10:00"
    assert payload["decision"] == "WINDOW_PRICING"
    assert payload["cheap_contract_raw_symbol"] is not None
    assert payload["costly_contract_raw_symbol"] is not None
    assert payload["cheap_side"] in {"C", "P"}
    assert payload["costly_side"] in {"C", "P"}
    assert worker.redis.publishes[0][0] == "signal:window_pricing"


def test_enrich_trade_payload_from_redis_merges_underlying_and_contract_state():
    payload = nw.normalize_trade_payload({
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00700000",
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 1250.0,
    })
    redis_client = FakeRedis({
        "equity:live:context:SPY": json.dumps({"price": 700.25, "lastPriceUtc": "2026-05-05T14:00:00Z"}),
        "options:live:contract_state:SPY   260505C00700000": json.dumps({
            "mid": 1.24,
            "quoteAgeMs": 250,
            "delta": 0.52,
            "gamma": 0.018,
            "asOfUtc": "2026-05-05T14:00:00Z",
        }),
    })

    enriched = asyncio.run(nw.enrich_trade_payload_from_redis(payload, redis_client))

    assert enriched["underlying_mid"] == 700.25
    assert enriched["option_mid"] == 1.24
    assert enriched["delta"] == 0.52
    assert enriched["gamma"] == 0.018
    assert enriched["_feature_status"]["underlying_mid"] == "available"
    assert enriched["_feature_status"]["option_mid"] == "available"


def test_runtime_gate_blocks_low_sweep_when_sweep_classifier_is_missing():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis()
    payload = {
        "underlying": "SPY",
        "raw_symbol": "SPY   260505C00700000",
        "price": 12.5,
        "size": 200,
        "ts_event_ns": 1_778_012_099_996_787_889,
    }
    df = pl.DataFrame([nw.decode_stream_entry({b"data": msgpack.packb(payload, use_bin_type=True)})])

    asyncio.run(worker.evaluate_low_sweep_core(df, "SPY", nw.DECISION_SLOTS[0], datetime(2026, 5, 5).date()))

    assert worker.redis.sets[0][0] == "nexus_window_view:SPY:etf_low_sweep_core:10:00"
    assert len(worker.redis.xadds) == 1
    blocked = json.loads(worker.redis.xadds[0][1]["payload_json"])
    assert blocked["decision"] == "BLOCKED"
    assert blocked["block_reason"] == "live_feature_quality_gate_closed"
    assert blocked["missing_features"] == ["is_sweep"]
    assert blocked["feature_failures"] == {"is_sweep": "missing"}
    assert json.loads(worker.redis.sets[0][1]) == blocked
    assert worker.redis.publishes[0][0] == "signal:window_view:etf_low_sweep_core"


def test_runtime_gate_blocks_flow_when_live_context_is_missing():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis()
    df = pl.DataFrame([
        {
            **row("2026-05-05T14:00:00Z", "C", 250_000, sweep=True),
            "raw_symbol": "SPY   260505C00700000",
        }
    ])

    asyncio.run(worker.evaluate_flow_specialist(df, "SPY", nw.DECISION_SLOTS[1], datetime(2026, 5, 5).date()))

    assert worker.redis.sets[0][0] == "nexus_window_view:SPY:etf_flow_specialist:10:30"
    blocked = json.loads(worker.redis.xadds[0][1]["payload_json"])
    assert blocked["decision"] == "BLOCKED"
    assert blocked["missing_features"] == ["atm_iv", "iv_rank", "net_gex"]


def test_runtime_gate_blocks_confluence_without_option_mid():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis({"options:live:vrp:SPY": json.dumps({"ivRank": 20, "asOf": "2026-05-05T14:00:00Z"})})
    df = pl.DataFrame([
        {
            **row("2026-05-05T14:00:00Z", "C", 250_000, sweep=True),
            "raw_symbol": "SPY   260505C00700000",
            "price": 1.25,
            "underlying_mid": 700.0,
        }
    ])

    asyncio.run(worker.evaluate_confluence_sniper(df, "SPY", nw.DECISION_SLOTS[1], datetime(2026, 5, 5).date()))

    assert worker.redis.sets[0][0] == "nexus_window_view:SPY:etf_confluence_sniper:10:30"
    blocked = json.loads(worker.redis.xadds[0][1]["payload_json"])
    assert blocked["decision"] == "BLOCKED"
    assert blocked["missing_features"] == ["option_mid"]
    assert blocked["feature_failures"] == {"option_mid": "missing"}


def test_runtime_gate_blocks_stale_option_mid_for_confluence():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis({"options:live:vrp:SPY": json.dumps({"ivRank": 20, "asOf": "2026-05-05T14:00:00Z"})})
    payload = {
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00700000",
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 250_000,
        "is_sweep": True,
        "aggressor": "A",
        "delta": 0.52,
        "gamma": 0.018,
        "greeks_ts_utc": "2026-05-05T14:00:00Z",
        "underlying_mid": 700.25,
        "underlying_ts_utc": "2026-05-05T14:00:00Z",
        "option_mid": 1.24,
        "quote_age_ms": 10_000,
    }
    df = pl.DataFrame([nw.normalize_trade_payload(payload)])

    asyncio.run(worker.evaluate_confluence_sniper(df, "SPY", nw.DECISION_SLOTS[1], datetime(2026, 5, 5).date()))

    blocked = json.loads(worker.redis.xadds[0][1]["payload_json"])
    assert blocked["decision"] == "BLOCKED"
    assert blocked["feature_failures"] == {"option_mid": "stale"}


def test_runtime_gate_blocks_stale_live_context_for_flow():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis({
        "options:live:iv_surface:SPY": json.dumps({"atmIv": 0.22, "asOf": "2026-05-05T13:55:00Z"}),
        "options:live:gex:SPY": json.dumps({"netGex": -1_500_000_000, "asOf": "2026-05-05T13:55:00Z"}),
        "options:live:vrp:SPY": json.dumps({"ivRank": 20, "asOf": "2026-05-05T13:55:00Z"}),
    })
    payload = {
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00700000",
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 250_000,
        "is_sweep": True,
        "aggressor": "A",
        "delta": 0.52,
        "gamma": 0.018,
        "greeks_ts_utc": "2026-05-05T14:00:00Z",
    }
    df = pl.DataFrame([nw.normalize_trade_payload(payload)])

    asyncio.run(worker.evaluate_flow_specialist(df, "SPY", nw.DECISION_SLOTS[1], datetime(2026, 5, 5).date()))

    blocked = json.loads(worker.redis.xadds[0][1]["payload_json"])
    assert blocked["decision"] == "BLOCKED"
    assert blocked["feature_failures"] == {"atm_iv": "stale", "iv_rank": "stale", "net_gex": "stale"}


def test_runtime_gate_accepts_fresh_live_context_for_flow():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.redis = FakeRedis({
        "options:live:iv_surface:SPY": json.dumps({"atmIv": 0.22, "asOf": "2026-05-05T14:00:00Z"}),
        "options:live:gex:SPY": json.dumps({"netGex": -1_500_000_000, "asOf": "2026-05-05T14:00:00Z"}),
        "options:live:vrp:SPY": json.dumps({"ivRank": 20, "asOf": "2026-05-05T14:00:00Z"}),
    })
    payload = {
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00700000",
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 250_000,
        "is_sweep": True,
        "aggressor": "A",
        "delta": 0.52,
        "gamma": 0.018,
        "greeks_ts_utc": "2026-05-05T14:00:00Z",
    }
    df = pl.DataFrame([nw.normalize_trade_payload(payload)])

    assert asyncio.run(worker._missing_strategy_features("etf_flow_specialist", "SPY", df)) == []


def test_enrich_trade_payload_uses_equity_context_and_contract_tradability():
    raw_symbol = "SPY   260505C00700000"
    redis = FakeRedis({
        "equity:live:context:SPY": json.dumps({
            "symbol": "SPY",
            "price": 700.25,
            "lastPriceUtc": "2026-05-05T14:00:00Z",
            "warmupComplete": True,
            "priceDataStale": False,
        }),
        f"options:live:tradability:{raw_symbol}": json.dumps({
            "symbol": "SPY",
            "rawSymbol": raw_symbol,
            "asOfUtc": "2026-05-05T14:00:00Z",
            "available": True,
            "stale": False,
            "tradable": True,
            "executable": True,
            "tradabilityScore": 0.91,
            "tradabilityBucket": "tradable",
            "option": {
                "bid": 1.20,
                "ask": 1.28,
                "mid": 1.24,
                "bidSize": 25,
                "askSize": 31,
                "spreadPct": 0.064516,
            },
        }),
    })
    payload = nw.normalize_trade_payload({
        "symbol": "SPY",
        "raw_symbol": raw_symbol,
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 1_250.0,
        "is_sweep": True,
        "aggressor": "A",
    })

    enriched = asyncio.run(nw.enrich_trade_payload_from_redis(payload, redis))

    assert enriched["underlying_mid"] == 700.25
    assert enriched["underlying_ts_utc"] == "2026-05-05T14:00:00Z"
    assert enriched["option_mid"] == 1.24
    assert enriched["quote_ts_utc"] == "2026-05-05T14:00:00Z"
    assert enriched["tradability_bucket"] == "tradable"
    assert enriched["_feature_status"]["underlying_mid"] == "available"
    assert enriched["_feature_status"]["option_mid"] == "available"
    assert enriched["_feature_status"]["delta"] == "missing"


def test_normalize_trade_payload_derives_aggressor_and_sweep_from_fresh_quote():
    payload = {
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00700000",
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.28,
        "size": 250,
        "option_bid": 1.20,
        "option_ask": 1.28,
        "option_mid": 1.24,
        "quote_ts_utc": "2026-05-05T14:00:00Z",
        "option_tradable": True,
        "option_executable": True,
        "tradability_bucket": "tradable",
    }

    normalized = nw.normalize_trade_payload(payload)

    assert normalized["aggressor"] == "A"
    assert normalized["is_sweep"] is True
    assert normalized["_feature_status"]["aggressor"] == "derived"
    assert normalized["_feature_status"]["is_sweep"] == "derived"


def test_raw_prod_shape_enriches_aggressor_sweep_from_contract_state():
    raw_symbol = "SPY   260505C00700000"
    redis = FakeRedis({
        "equity:live:context:SPY": json.dumps({
            "price": 700.25,
            "lastPriceUtc": "2026-05-05T14:00:00Z",
            "warmupComplete": True,
            "priceDataStale": False,
        }),
        f"options:live:contract_state:{raw_symbol}": json.dumps({
            "symbol": "SPY",
            "rawSymbol": raw_symbol,
            "asOfUtc": "2026-05-05T14:00:00Z",
            "available": True,
            "stale": False,
            "tradable": True,
            "executable": True,
            "bid": 1.20,
            "ask": 1.28,
            "optionMid": 1.24,
            "tradabilityBucket": "tradable",
            "underlyingMid": 700.25,
            "delta": 0.52,
            "gamma": 0.018,
            "greeksTsUtc": "2026-05-05T14:00:00Z",
        }),
    })
    raw_payload = {
        "underlying": "SPY",
        "raw_symbol": raw_symbol,
        "price": 1.28,
        "size": 250,
        "ts_event_ns": int(datetime(2026, 5, 5, 14, 0, tzinfo=timezone.utc).timestamp() * 1_000_000_000),
    }

    decoded = nw.decode_stream_entry({b"data": msgpack.packb(raw_payload, use_bin_type=True)})
    enriched = asyncio.run(nw.enrich_trade_payload_from_redis(decoded, redis))

    assert enriched["aggressor"] == "A"
    assert enriched["is_sweep"] is True
    assert enriched["_feature_status"]["aggressor"] == "derived"
    assert enriched["_feature_status"]["is_sweep"] == "derived"
    assert enriched["_feature_status"]["delta"] == "available"
    assert enriched["_feature_status"]["gamma"] == "available"


def test_feature_audit_marks_quote_derived_aggressor_and_sweep_ready():
    payload = nw.normalize_trade_payload({
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00700000",
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.28,
        "size": 250,
        "option_bid": 1.20,
        "option_ask": 1.28,
        "option_mid": 1.24,
        "quote_ts_utc": "2026-05-05T14:00:00Z",
        "option_tradable": True,
        "option_executable": True,
        "tradability_bucket": "tradable",
        "delta": 0.52,
        "gamma": 0.018,
        "greeks_ts_utc": "2026-05-05T14:00:00Z",
        "underlying_mid": 700.25,
        "underlying_ts_utc": "2026-05-05T14:00:00Z",
    })

    audit = fa.audit_payload(payload, {"iv_rank": 24.0, "atm_iv": 0.18, "net_gex": 1_000_000, "asOf": "2026-05-05T14:00:00Z"})

    assert audit["features"]["aggressor"]["status"] == "derived"
    assert audit["features"]["is_sweep"]["status"] == "derived"
    assert {result["status"] for result in audit["strategies"].values()} == {"ready"}


def test_enrich_trade_payload_blocks_untradable_contract_mid():
    raw_symbol = "SPY   260505C00700000"
    redis = FakeRedis({
        f"options:live:tradability:{raw_symbol}": json.dumps({
            "symbol": "SPY",
            "rawSymbol": raw_symbol,
            "asOfUtc": "2026-05-05T14:00:00Z",
            "available": True,
            "stale": False,
            "tradable": False,
            "executable": False,
            "tradabilityBucket": "reject",
            "option": {"mid": 1.24, "bid": 1.00, "ask": 1.48},
        }),
    })
    payload = nw.normalize_trade_payload({
        "symbol": "SPY",
        "raw_symbol": raw_symbol,
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 1_250.0,
        "is_sweep": True,
        "aggressor": "A",
    })

    enriched = asyncio.run(nw.enrich_trade_payload_from_redis(payload, redis))

    assert enriched["option_mid"] == 1.24
    assert enriched["_feature_status"]["option_mid"] == "untradable"


def test_contract_state_can_satisfy_confluence_required_features():
    raw_symbol = "SPY   260505C00700000"
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.redis = FakeRedis({
        "options:live:vrp:SPY": json.dumps({"ivRank": 20, "asOf": "2026-05-05T14:00:00Z"}),
    })
    redis = FakeRedis({
        "equity:live:context:SPY": json.dumps({
            "price": 700.25,
            "lastPriceUtc": "2026-05-05T14:00:00Z",
            "warmupComplete": True,
            "priceDataStale": False,
        }),
        f"options:live:contract_state:{raw_symbol}": json.dumps({
            "symbol": "SPY",
            "rawSymbol": raw_symbol,
            "asOf": "2026-05-05T14:00:00Z",
            "optionMid": 1.24,
            "tradable": True,
            "executable": True,
            "tradabilityBucket": "tradable",
            "delta": 0.52,
            "gamma": 0.018,
            "greeksTsUtc": "2026-05-05T14:00:00Z",
        }),
    })
    payload = nw.normalize_trade_payload({
        "symbol": "SPY",
        "raw_symbol": raw_symbol,
        "ts_utc": "2026-05-05T14:00:00Z",
        "side": "C",
        "price": 1.25,
        "size": 10,
        "premium": 1_250.0,
        "is_sweep": True,
        "aggressor": "A",
    })
    enriched = asyncio.run(nw.enrich_trade_payload_from_redis(payload, redis))

    assert asyncio.run(worker._missing_strategy_features("etf_confluence_sniper", "SPY", pl.DataFrame([enriched]))) == []


def test_runtime_gate_allows_enriched_low_sweep_signal():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.active_positions = {}
    worker.redis = FakeRedis()
    payload = {
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00700000",
        "ts_utc": "2026-05-05T13:35:00Z",
        "side": "C",
        "price": 12.5,
        "size": 200,
        "premium": 250_000,
        "is_sweep": False,
        "aggressor": "A",
        "delta": 0.50,
        "gamma": 0.01,
    }
    df = pl.DataFrame([nw.normalize_trade_payload(payload)])

    asyncio.run(worker.evaluate_low_sweep_core(df, "SPY", nw.DECISION_SLOTS[0], datetime(2026, 5, 5).date()))

    assert len(worker.redis.sets) == 2
    assert len(worker.redis.xadds) == 2
    assert worker.redis.sets[0][0] == "nexus_intermediate:SPY:etf_low_sweep_core:10:00"
    assert worker.redis.sets[1][0] == "nexus_live_overlay:SPY"
    final = json.loads(worker.redis.sets[1][1])
    assert final["strategy"] == "etf_low_sweep_core"
    assert final["decision"] == "BET"
    assert final["raw_symbol"] == "SPY   260505C00700000"


def test_active_position_mid_uses_tracked_contract_not_unrelated_symbol_trade():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.active_positions = {
        "SPY": {
            "entry_price": 10.0,
            "is_guarded": False,
            "side": "BULLISH",
            "raw_symbol": "SPY   260505C00700000",
            "signal_id": "sig_test_position",
            "position_id": "sig_test_position",
        }
    }
    worker.redis = FakeRedis({
        "options:live:contract_state:SPY   260505C00700000": json.dumps({
            "optionMid": 4.9,
            "asOfUtc": "2026-05-05T14:06:00Z",
            "tradable": True,
        }),
    })
    worker.last_reset_session_date = datetime(2026, 5, 5).date()
    worker.buffers = {"SPY": deque(maxlen=10)}
    worker.feature_blocks_reported = set()
    worker.window_views_reported = set()
    worker.window_pricing_reported = set()

    unrelated_payload = {
        "symbol": "SPY",
        "raw_symbol": "SPY   260505C00710000",
        "ts_utc": "2026-05-05T14:06:00Z",
        "side": "C",
        "price": 2.0,
        "size": 10,
        "premium": 2_000.0,
        "is_sweep": False,
        "aggressor": "A",
        "delta": 0.50,
        "gamma": 0.01,
        "option_mid": 20.0,
    }

    asyncio.run(worker.process_message({"payload": json.dumps(unrelated_payload)}))

    assert "SPY" not in worker.active_positions
    liquidate = next(json.loads(value) for _, value in worker.redis.sets if json.loads(value).get("decision") == "LIQUIDATE")
    assert liquidate["decision"] == "LIQUIDATE"
    assert liquidate["reason"] == "STOP_LOSS"
    assert liquidate["signal_id"] == "sig_test_position"
    assert liquidate["position_id"] == "sig_test_position"
    assert liquidate["raw_symbol"] == "SPY   260505C00700000"
    assert liquidate["exit_price"] == 4.9
    assert liquidate["quote_freshness"] == "stale"
    assert liquidate["quote_valid_until"] == "2026-05-05T14:06:05+00:00"
    assert liquidate["execution"]["order_type"] == "limit"
    assert liquidate["execution"]["reference_price"] == 4.9
    assert liquidate["execution"]["quote_freshness"] == "stale"


def test_evaluate_strategy_publishes_window_views_even_when_trade_locked():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = {nw.signal_key(datetime(2026, 5, 5).date(), "SPY", "*")}
    worker.window_views_reported = set()
    worker.feature_blocks_reported = set()
    worker.active_positions = {}
    worker.redis = FakeRedis({
        "options:live:vrp:SPY": json.dumps({"ivRank": 20, "asOf": "2026-05-05T14:05:00Z"}),
        "options:live:iv_surface:SPY": json.dumps({"atmIv": 0.22, "asOf": "2026-05-05T14:05:00Z"}),
        "options:live:gex:SPY": json.dumps({"netGex": 1_000_000, "asOf": "2026-05-05T14:05:00Z"}),
    })
    worker.buffers = {
        "SPY": [
            nw.normalize_trade_payload({
                "symbol": "SPY",
                "raw_symbol": "SPY   260505C00700000",
                "ts_utc": "2026-05-05T13:35:00Z",
                "side": "C",
                "price": 12.5,
                "size": 200,
                "premium": 250_000,
                "is_sweep": False,
                "aggressor": "A",
                "delta": 0.50,
                "gamma": 0.01,
                "greeks_ts_utc": "2026-05-05T13:35:00Z",
                "underlying_mid": 700.25,
                "underlying_ts_utc": "2026-05-05T13:35:00Z",
                "option_mid": 12.4,
                "quote_age_ms": 100,
            })
        ]
    }

    asyncio.run(worker.evaluate_strategy("SPY", nw.DECISION_SLOTS[0], datetime(2026, 5, 5, 14, 5, tzinfo=timezone.utc)))

    decisions = [json.loads(value)["decision"] for _, value in worker.redis.sets]
    assert "WINDOW_VIEW" in decisions
    assert "BET" not in decisions


def test_default_first_trigger_scope_prevents_second_strategy_final_publish():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis()
    worker.window_views_reported = set()
    worker.feature_blocks_reported = set()
    worker.active_positions = {}
    worker.buffers = {
        "QQQ": [
            nw.normalize_trade_payload({
                "symbol": "QQQ",
                "raw_symbol": "QQQ   260505C00500000",
                "ts_utc": "2026-05-05T13:35:00Z",
                "side": "C",
                "price": 12.5,
                "size": 200,
                "premium": 250_000,
                "is_sweep": False,
                "aggressor": "A",
                "delta": 0.50,
                "gamma": 0.01,
                "greeks_ts_utc": "2026-05-05T13:35:00Z",
                "underlying_mid": 500.25,
                "underlying_ts_utc": "2026-05-05T13:35:00Z",
                "option_mid": 12.4,
                "quote_age_ms": 100,
            }),
        ]
    }
    calls = []

    async def confluence(df, symbol, slot, session_date):
        calls.append("confluence")

    async def open_specialist(df, symbol, slot, session_date):
        calls.append("open")
        await worker._publish_final("etf_open_specialist", symbol, "BULLISH", 0.95, session_date, slot)

    async def hybrid(df, symbol, slot, session_date):
        calls.append("hybrid")

    worker.evaluate_confluence_sniper = confluence
    worker.evaluate_open_specialist = open_specialist
    worker.evaluate_low_sweep_core = hybrid
    worker.evaluate_flow_specialist = hybrid

    asyncio.run(worker.evaluate_strategy("QQQ", nw.DECISION_SLOTS[0], datetime(2026, 5, 5, 14, 5, tzinfo=timezone.utc)))

    assert calls == ["confluence", "open"]
    bet_messages = [json.loads(value) for _, value in worker.redis.sets if json.loads(value).get("decision") == "BET"]
    assert len(bet_messages) == 1


def test_symbol_lane_does_not_lock_other_symbol():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.active_positions = {}
    worker.redis = FakeRedis()
    session_date = datetime(2026, 5, 5).date()

    asyncio.run(worker._publish_final("etf_open_specialist", "QQQ", "BULLISH", 0.95, session_date, nw.DECISION_SLOTS[0]))

    assert not worker.already_signaled(session_date, "SPY", "etf_open_specialist")
    assert worker.already_signaled(session_date, "QQQ", "etf_open_specialist")


def test_confluence_group_lock_blocks_other_symbol_confluence_only():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.active_positions = {}
    worker.redis = FakeRedis()
    session_date = datetime(2026, 5, 5).date()

    asyncio.run(worker._publish_final("etf_confluence_sniper", "QQQ", "BULLISH", 0.95, session_date, nw.DECISION_SLOTS[0]))

    assert worker.already_signaled(session_date, "SPY", "etf_confluence_sniper")
    assert not worker.already_signaled(session_date, "SPY", "etf_open_specialist")


def test_context_falls_back_to_live_option_keys_when_stats_keys_are_absent():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.redis = FakeRedis({
        "options:live:iv_surface:SPY": json.dumps({"atmIv": 0.22}),
        "options:live:gex:SPY": json.dumps({"netGex": -1_500_000_000}),
        "options:live:vrp:SPY": json.dumps({"vrpRegime": "cheap"}),
    })

    assert asyncio.run(worker.get_context("SPY")) == (20.0, 0.22, -1_500_000_000.0)


def test_momentum_specialist_requires_underlying_mid_and_uses_iv_gate():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.redis = FakeRedis({"options:live:vrp:SPY": json.dumps({"vrpRegime": "cheap"})})
    rows = []
    for minute in range(10):
        rows.append({
            **row(f"2026-05-05T13:{30 + minute:02d}:00Z", "C", 25_000),
            "underlying_mid": 700.0 + minute,
        })
        rows.append({
            **row(f"2026-05-05T13:{30 + minute:02d}:30Z", "C", 25_000),
            "underlying_mid": 700.5 + minute,
        })

    sentiment, valid, p_feat = asyncio.run(worker.check_momentum_heuristics(pl.DataFrame(rows), "SPY"))

    assert (sentiment, valid) == ("BULLISH", True)
    assert p_feat[:2] == [10.0, 0.0]
