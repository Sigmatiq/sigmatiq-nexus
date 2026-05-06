from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import polars as pl

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


def test_workflow_uses_configured_redis_host_variable():
    text = open(".github/workflows/deploy-nexus-prod.yml", encoding="utf-8").read()

    assert "CORE_REDIS_HOST" not in text
    assert "${REDIS_HOST_CORE}:6380" in text
    assert "rediss://:" in text

class FakeRedis:
    def __init__(self):
        self.sets = []
        self.publishes = []

    async def set(self, key, value):
        self.sets.append((key, value))

    async def publish(self, channel, value):
        self.publishes.append((channel, value))


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

    async def low(df, symbol, slot, session_date):
        calls.append("low")
        await worker._publish_final("spy_low_sweep_core", symbol, "BULLISH", 1.0, session_date, slot)

    async def hybrid(df, symbol, slot, session_date):
        calls.append("hybrid")

    worker.evaluate_low_sweep_core = low
    worker.evaluate_hybrid_alpha = hybrid

    asyncio.run(worker.evaluate_strategy("SPY", nw.DECISION_SLOTS[0], datetime(2026, 5, 5, 14, 5, tzinfo=timezone.utc)))

    assert calls == ["low"]
    assert len(worker.redis.sets) == 1
