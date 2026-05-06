from __future__ import annotations

import asyncio
import json
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
    assert audit["strategies"]["spy_low_sweep_core"]["status"] == "blocked"
    assert "is_sweep" in audit["strategies"]["spy_low_sweep_core"]["missing"]
    assert "delta" in audit["strategies"]["spy_flow_specialist"]["missing"]
    assert "underlying_mid" in audit["strategies"]["spy_momentum_specialist"]["missing"]


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

    confluence = audit["strategies"]["spy_confluence_sniper"]
    assert confluence["status"] == "blocked"
    assert confluence["missing"] == ["option_mid"]


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
    assert "NEXUS_SYMBOLS=SPY" in text

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


def test_publish_final_appends_live_persistence_event():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis()

    asyncio.run(worker._publish_final("spy_low_sweep_core", "SPY", "BULLISH", 1.0))

    assert len(worker.redis.sets) == 1
    assert len(worker.redis.xadds) == 1
    stream, fields, maxlen, approximate = worker.redis.xadds[0]
    assert stream == "live:persistence:events"
    assert fields["redis_key"] == "nexus_live_overlay:SPY"
    payload = json.loads(fields["payload_json"])
    assert payload["strategy"] == "spy_low_sweep_core"
    assert payload["stage"] == 2
    assert payload["decision"] == "BET"
    assert maxlen == 10000
    assert approximate is True


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

    assert worker.redis.sets == []
    assert len(worker.redis.xadds) == 1
    blocked = json.loads(worker.redis.xadds[0][1]["payload_json"])
    assert blocked["decision"] == "BLOCKED"
    assert blocked["block_reason"] == "live_feature_quality_gate_closed"
    assert blocked["missing_features"] == ["is_sweep"]
    assert blocked["feature_failures"] == {"is_sweep": "missing"}


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

    assert worker.redis.sets == []
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

    assert worker.redis.sets == []
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

    assert asyncio.run(worker._missing_strategy_features("spy_flow_specialist", "SPY", df)) == []


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

    assert asyncio.run(worker._missing_strategy_features("spy_confluence_sniper", "SPY", pl.DataFrame([enriched]))) == []


def test_runtime_gate_allows_enriched_low_sweep_signal():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
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

    assert len(worker.redis.sets) == 1
    assert len(worker.redis.xadds) == 2
    final = json.loads(worker.redis.sets[0][1])
    assert final["strategy"] == "spy_low_sweep_core"
    assert final["decision"] == "BET"


def test_default_first_trigger_scope_prevents_second_strategy_final_publish():
    worker = nw.SigmatiqNexus.__new__(nw.SigmatiqNexus)
    worker.signaled_today = set()
    worker.redis = FakeRedis()
    worker.buffers = {
        "SPY": [
            row("2026-05-05T13:35:00Z", "C", 250_000, sweep=False),
            row("2026-05-05T14:05:00Z", "P", 500_000, sweep=True),
        ]
    }
    calls = []

    async def confluence(df, symbol, slot, session_date):
        calls.append("confluence")

    async def low(df, symbol, slot, session_date):
        calls.append("low")
        await worker._publish_final("spy_low_sweep_core", symbol, "BULLISH", 1.0, session_date, slot)

    async def hybrid(df, symbol, slot, session_date):
        calls.append("hybrid")

    worker.evaluate_confluence_sniper = confluence
    worker.evaluate_low_sweep_core = low
    worker.evaluate_flow_specialist = hybrid

    asyncio.run(worker.evaluate_strategy("SPY", nw.DECISION_SLOTS[0], datetime(2026, 5, 5, 14, 5, tzinfo=timezone.utc)))

    assert calls == ["confluence", "low"]
    assert len(worker.redis.sets) == 1


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
