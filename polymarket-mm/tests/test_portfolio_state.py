"""Tests for PortfolioConstraints — cross-market portfolio risk caps."""
import threading

import pytest

from src.live.portfolio_state import PortfolioConstraints


def make_pc(**kw):
    defaults = dict(
        total_capital=10_000.0,
        max_long_term_fraction=0.80,
        max_event_notional=0.0,
        max_market_notional=0.0,
    )
    defaults.update(kw)
    return PortfolioConstraints(**defaults)


class TestLongTermCap:
    def test_default_fraction_is_liquidity_guarded(self):
        # Default deliberately low: long-dated positions lock capital that
        # short-duration markets could recycle. Changing this default changes
        # live risk posture — update intentionally.
        assert PortfolioConstraints().max_long_term_fraction == 0.30

    def test_max_long_term_notional_derived(self):
        pc = make_pc()
        assert pc.max_long_term_notional == 8_000.0

    def test_short_term_position_not_counted(self):
        pc = make_pc()
        # 29 days < 30-day threshold: never blocked by long-term cap
        assert pc.can_open("e", "m", 50_000.0, days_to_resolution=29)

    def test_long_term_position_blocked_over_cap(self):
        pc = make_pc()
        assert not pc.can_open("e", "m", 8_001.0, days_to_resolution=60)

    def test_long_term_position_allowed_at_cap(self):
        pc = make_pc()
        assert pc.can_open("e", "m", 8_000.0, days_to_resolution=60)

    def test_accumulation_blocks_at_cap(self):
        pc = make_pc()
        pc.open_position("e", "m1", 5_000.0, days_to_resolution=60)
        assert pc.can_open("e", "m2", 3_000.0, days_to_resolution=60)
        assert not pc.can_open("e", "m2", 3_001.0, days_to_resolution=60)

    def test_close_releases_long_term_notional(self):
        pc = make_pc()
        pc.open_position("e", "m", 8_000.0, days_to_resolution=60)
        assert not pc.can_open("e", "m2", 1.0, days_to_resolution=60)
        pc.close_position("e", "m", 8_000.0, days_to_resolution=60)
        assert pc.can_open("e", "m2", 8_000.0, days_to_resolution=60)

    def test_close_never_goes_negative(self):
        pc = make_pc()
        pc.close_position("e", "m", 5_000.0, days_to_resolution=60)
        assert pc.status()["long_term_notional"] == 0.0

    def test_threshold_boundary_exactly_30_days_is_short_term(self):
        pc = make_pc()
        # days > threshold counts as long-term; exactly 30 does not
        assert pc.can_open("e", "m", 50_000.0, days_to_resolution=30)
        assert not pc.can_open("e", "m", 50_000.0, days_to_resolution=31)


class TestEventCap:
    def test_disabled_by_default_zero(self):
        pc = make_pc(max_event_notional=0.0)
        assert pc.can_open("event-a", "m", 1e9, days_to_resolution=1)

    def test_blocks_over_event_cap(self):
        pc = make_pc(max_event_notional=3_000.0)
        pc.open_position("event-a", "m1", 2_000.0, days_to_resolution=1)
        assert pc.can_open("event-a", "m2", 1_000.0, days_to_resolution=1)
        assert not pc.can_open("event-a", "m2", 1_001.0, days_to_resolution=1)

    def test_different_events_independent(self):
        pc = make_pc(max_event_notional=3_000.0)
        pc.open_position("event-a", "m1", 3_000.0, days_to_resolution=1)
        assert pc.can_open("event-b", "m2", 3_000.0, days_to_resolution=1)

    def test_empty_event_key_skips_check(self):
        pc = make_pc(max_event_notional=3_000.0)
        assert pc.can_open("", "m", 1e9, days_to_resolution=1)


class TestMarketCap:
    def test_blocks_over_market_cap(self):
        pc = make_pc(max_market_notional=2_000.0)
        pc.open_position("e", "m1", 1_500.0, days_to_resolution=1)
        assert pc.can_open("e", "m1", 500.0, days_to_resolution=1)
        assert not pc.can_open("e", "m1", 501.0, days_to_resolution=1)

    def test_different_markets_independent(self):
        pc = make_pc(max_market_notional=2_000.0)
        pc.open_position("e", "m1", 2_000.0, days_to_resolution=1)
        assert pc.can_open("e", "m2", 2_000.0, days_to_resolution=1)

    def test_close_releases_market_notional(self):
        pc = make_pc(max_market_notional=2_000.0)
        pc.open_position("e", "m1", 2_000.0, days_to_resolution=1)
        pc.close_position("e", "m1", 1_000.0, days_to_resolution=1)
        assert pc.can_open("e", "m1", 1_000.0, days_to_resolution=1)


class TestStatus:
    def test_status_snapshot(self):
        pc = make_pc(max_event_notional=3_000.0, max_market_notional=2_000.0)
        pc.open_position("event-a", "m1", 1_000.0, days_to_resolution=60)
        s = pc.status()
        assert s["long_term_notional"] == 1_000.0
        assert s["max_long_term_notional"] == 8_000.0
        assert s["long_term_pct"] == 12.5
        assert s["event_notional"]["event-a"] == 1_000.0
        assert s["market_notional"]["m1"] == 1_000.0


class TestThreadSafety:
    def test_concurrent_open_close_consistent(self):
        pc = make_pc()
        n, notional = 200, 10.0

        def worker():
            for _ in range(n):
                pc.open_position("e", "m", notional, days_to_resolution=60)
                pc.close_position("e", "m", notional, days_to_resolution=60)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert pc.status()["long_term_notional"] == pytest.approx(0.0)
