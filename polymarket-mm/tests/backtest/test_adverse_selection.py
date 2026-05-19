"""Tests for AdverseSelectionTracker."""
from datetime import datetime, timezone, timedelta
import pytest
from src.backtest.adverse_selection import AdverseSelectionTracker


def dt(offset_seconds: float) -> datetime:
    return datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


class TestAdverseSelectionTracker:

    def test_no_fills_returns_zero(self):
        t = AdverseSelectionTracker()
        t.on_trade(0.50, dt(10))
        assert t.estimate() == 0.0

    def test_fill_with_no_subsequent_trade_returns_zero(self):
        t = AdverseSelectionTracker(window_seconds=300)
        t.on_fill(0.50, dt(0))
        assert t.estimate() == 0.0

    def test_non_adverse_fill_returns_zero(self):
        """Price goes UP after fill — not adverse for a long."""
        t = AdverseSelectionTracker(window_seconds=60, adverse_threshold=0.005)
        t.on_fill(0.50, dt(0))
        t.on_trade(0.55, dt(90))   # price rose: good for us
        assert t.estimate() == 0.0

    def test_adverse_fill_detected(self):
        """Price drops after fill — adverse for our long Yes position."""
        t = AdverseSelectionTracker(window_seconds=60, adverse_threshold=0.005)
        t.on_fill(0.50, dt(0))
        t.on_trade(0.47, dt(90))   # price dropped 3 cents: adverse
        est = t.estimate()
        assert est > 0.0
        assert abs(est - 0.03) < 1e-9  # magnitude = 0.50 - 0.47 = 0.03

    def test_below_threshold_not_adverse(self):
        """Small price move below adverse_threshold — not counted."""
        t = AdverseSelectionTracker(window_seconds=60, adverse_threshold=0.01)
        t.on_fill(0.50, dt(0))
        t.on_trade(0.496, dt(90))  # 0.004 drop — below threshold
        assert t.estimate() == 0.0

    def test_rolling_window_uses_last_20(self):
        """estimate() reflects average of last 20 measured fills."""
        t = AdverseSelectionTracker(window_seconds=10, adverse_threshold=0.005)
        # 25 adverse fills of magnitude 0.02
        for i in range(25):
            t.on_fill(0.50, dt(i * 20))
            t.on_trade(0.48, dt(i * 20 + 15))  # adverse: 0.02 drop
        est = t.estimate()
        assert abs(est - 0.02) < 1e-9

    def test_stats_counts(self):
        t = AdverseSelectionTracker(window_seconds=60, adverse_threshold=0.005)
        t.on_fill(0.50, dt(0))
        t.on_trade(0.45, dt(90))  # adverse
        t.on_fill(0.50, dt(200))
        t.on_trade(0.55, dt(290))  # not adverse
        stats = t.stats()
        assert stats["num_measured"] == 2
        assert stats["num_adverse"] == 1
        assert abs(stats["avg_magnitude"] - 0.05) < 1e-9

    def test_pending_fill_not_yet_measured(self):
        """Fill within window should stay pending, not counted yet."""
        t = AdverseSelectionTracker(window_seconds=300, adverse_threshold=0.005)
        t.on_fill(0.50, dt(0))
        t.on_trade(0.45, dt(60))  # only 60s elapsed — still in window
        assert t.estimate() == 0.0  # not measured yet
