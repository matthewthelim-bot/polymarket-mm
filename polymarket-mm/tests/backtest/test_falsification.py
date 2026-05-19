"""
Falsification tests for the core trading hypothesis.

Central hypothesis: A passive fill at price p_entry followed by a taker flatten
at p_flatten where p_entry + p_flatten < 1 generates positive net PnL after
taker fees and maker rebates, with no basis risk.

These tests run the full simulator on controlled synthetic event streams
and assert that the predicted economic outcomes occur. A failure here means
the code does not implement the spec correctly, or the hypothesis is wrong.

NOTE: The QuoteEngine with FV=0.50 and half_spread_base=0.015 computes a
bid price of 0.48 (rounded from 0.485). The fill model requires exact price
match, so all H1/H2/H5/H6 scenarios use trade prices of 0.48 (entry) and
0.50 (flatten). max_flatten_price(0.48, 0.04, 0.20, 0.005) ≈ 0.507, so
0.50 is well within the profitable flatten window and 0.62 is outside it.
"""

import json
import pytest
from pathlib import Path
from src.backtest.runner import BacktestRunner, RunConfig


def make_run_config(data_dir: str, market_id: str, **kwargs) -> RunConfig:
    defaults = dict(
        market_id=market_id,
        data_dir=data_dir,
        fee_rate=0.04,
        fee_exponent=1,
        rebate_fraction=0.20,
        sports=False,
        start_capital=50000.0,
        quote_size=100.0,
        queue_model="FRONT",
        latency_ms=0,
        twap_window_seconds=300,
        min_edge_floor=0.005,
        half_spread_base=0.015,
        time_to_resolution_hours=48.0,
        skew_tolerance=0.0,
        skew_hard_limit=0,
        max_skew_notional=0.0,
    )
    defaults.update(kwargs)
    return RunConfig(**defaults)


def write_events(path: Path, events: list[dict]):
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


# ===========================================================================
# H1: Risk-free cycle produces positive PnL
# p_entry + p_flatten < 1, fees covered → net PnL > 0
# ===========================================================================

def test_H1_risk_free_cycle_positive_pnl(tmp_path):
    """
    A clean cycle: passive fill at 0.48 (QuoteEngine bid for FV=0.50), flatten at 0.50.
    Combined = 0.98 < 1.0. Gross = 0.02 per contract * 100 = 2.00
    Taker fee at 0.50: 100 * 0.04 * 0.50 * 0.50 = 1.00
    Maker rebate at 0.48: 100 * 0.20 * 0.04 * 0.48 * 0.52 = 0.19968
    Net = 2.00 - 1.00 + 0.19968 = 1.19968 > 0
    """
    market = "h1-risk-free"
    events = [
        # Seed FV at 0.50
        {"event_type": "trade", "market_id": market, "fill_id": "seed", "timestamp": "2026-01-01T12:00:00Z",
         "side": "buy", "price": 0.50, "size": 500, "is_maker": False},
        # Book: asks at 0.50 (within max_flatten_price=0.507, so hedgeable), bids at 0.48
        {"event_type": "book", "market_id": market, "timestamp": "2026-01-01T12:00:01Z",
         "bids": [{"price": 0.48, "size": 500}], "asks": [{"price": 0.50, "size": 500}]},
        # Market sells at 0.48 → exact match with QuoteEngine bid → passive fill
        {"event_type": "trade", "market_id": market, "fill_id": "entry", "timestamp": "2026-01-01T12:00:02Z",
         "side": "sell", "price": 0.48, "size": 100, "is_maker": False},
        # Book still showing 0.50 ask
        {"event_type": "book", "market_id": market, "timestamp": "2026-01-01T12:00:03Z",
         "bids": [{"price": 0.48, "size": 400}], "asks": [{"price": 0.50, "size": 500}]},
        # Market trades at 0.50 → simulator attempts flatten (0.50 <= p_max=0.507)
        {"event_type": "trade", "market_id": market, "fill_id": "flatten", "timestamp": "2026-01-01T12:00:04Z",
         "side": "buy", "price": 0.50, "size": 200, "is_maker": False},
    ]
    write_events(tmp_path / f"{market}.jsonl", events)
    result = BacktestRunner(make_run_config(str(tmp_path), market)).run()
    assert result.total_spread_pnl > 0, (
        f"H1 FAIL: Expected positive spread PnL from risk-free cycle, got {result.total_spread_pnl:.4f}"
    )
    assert result.total_skew_pnl == pytest.approx(0.0), "No skew in this scenario"


# ===========================================================================
# H2: Loss when flatten price exceeds breakeven
# p_entry + p_flatten > 1 → simulator should NOT flatten (max_flatten_price gate)
# ===========================================================================

def test_H2_loss_when_flatten_above_breakeven(tmp_path):
    """
    Passive fill at 0.48, flatten would require 0.62.
    max_flatten_price(0.48, 0.04, 0.20, 0.005) ≈ 0.507.
    0.62 > 0.507 → the simulator's max_flatten_price gate should prevent this.
    PnL stays at 0 (inventory held, not flattened at a loss).
    """
    market = "h2-loss"
    events = [
        {"event_type": "trade", "market_id": market, "fill_id": "seed", "timestamp": "2026-01-01T12:00:00Z",
         "side": "buy", "price": 0.50, "size": 500, "is_maker": False},
        # Book: asks at 0.62 (above max_flatten_price=0.507, so NOT hedgeable)
        # No hedgeable depth → bid_size=0 from QuoteEngine (hedgeable_size=0, skew_accepted=0)
        # BUT: asks must exist for fill to potentially occur. With 0 bid_size, no fill happens.
        # We include bids at 0.48 to show the book structure.
        {"event_type": "book", "market_id": market, "timestamp": "2026-01-01T12:00:01Z",
         "bids": [{"price": 0.48, "size": 500}], "asks": [{"price": 0.62, "size": 500}]},
        {"event_type": "trade", "market_id": market, "fill_id": "entry", "timestamp": "2026-01-01T12:00:02Z",
         "side": "sell", "price": 0.48, "size": 100, "is_maker": False},
        {"event_type": "book", "market_id": market, "timestamp": "2026-01-01T12:00:03Z",
         "bids": [{"price": 0.48, "size": 400}], "asks": [{"price": 0.62, "size": 500}]},
        {"event_type": "trade", "market_id": market, "fill_id": "flatten", "timestamp": "2026-01-01T12:00:04Z",
         "side": "buy", "price": 0.62, "size": 200, "is_maker": False},
    ]
    write_events(tmp_path / f"{market}.jsonl", events)
    result = BacktestRunner(make_run_config(str(tmp_path), market)).run()
    # With asks at 0.62 (above max_flatten_price ≈ 0.507), the hedgeability
    # gate returns hedgeable_size=0, causing QuoteEngine to set bid_size=0.
    # No fill should occur and no cycle should complete.
    assert result.num_fills == 0, (
        f"H2 FAIL: Hedgeability gate should suppress bid when only asks at 0.62. "
        f"Fills={result.num_fills}"
    )
    assert result.num_cycles_completed == 0, (
        f"H2 FAIL: No cycle should complete when bid is suppressed. "
        f"Cycles={result.num_cycles_completed}"
    )
    assert result.total_spread_pnl == pytest.approx(0.0), (
        f"H2 FAIL: PnL should be zero with no fills. PnL={result.total_spread_pnl:.4f}"
    )


# ===========================================================================
# H3: Fees peak at midmarket (p=0.50) for Finance/Politics
# ===========================================================================

def test_H3_fees_peak_at_midmarket():
    from src.fee_model import FeeModel
    fm = FeeModel()
    fee_mid = fm.taker_fee(100, 0.50, 0.04)
    fee_low = fm.taker_fee(100, 0.30, 0.04)
    fee_high = fm.taker_fee(100, 0.70, 0.04)
    assert fee_mid > fee_low, "H3 FAIL: Fee at midmarket should exceed fee at p=0.30"
    assert fee_mid > fee_high, "H3 FAIL: Fee at midmarket should exceed fee at p=0.70"
    # Symmetry: fee at 0.30 == fee at 0.70
    assert fee_low == pytest.approx(fee_high, rel=1e-6)


# ===========================================================================
# H4: Sports formula peaks at p=2/3, not p=0.5
# ===========================================================================

def test_H4_sports_fee_peaks_at_two_thirds():
    from src.fee_model import FeeModel
    fm = FeeModel()
    fee_half = fm.taker_fee(100, 0.50, 0.03, sports=True)
    fee_two_thirds = fm.taker_fee(100, 2/3, 0.03, sports=True)
    fee_low = fm.taker_fee(100, 0.30, 0.03, sports=True)
    assert fee_two_thirds > fee_half, (
        f"H4 FAIL: Sports fee at 2/3 ({fee_two_thirds:.6f}) should exceed fee at 0.5 ({fee_half:.6f})"
    )
    assert fee_two_thirds > fee_low


# ===========================================================================
# H5: Hedgeability gating prevents fills when book is empty
# ===========================================================================

def test_H5_no_fill_when_no_opposing_depth(tmp_path):
    """
    When the opposing book has no depth (asks=[]),
    the hedgeability assessor sets hedgeable_size=0 and skew_accepted=0,
    causing QuoteEngine to set bid_size=0. No fill occurs.
    """
    market = "h5-no-depth"
    events = [
        {"event_type": "trade", "market_id": market, "fill_id": "seed", "timestamp": "2026-01-01T12:00:00Z",
         "side": "buy", "price": 0.50, "size": 500, "is_maker": False},
        # Book: ask side is EMPTY (no opposing depth)
        {"event_type": "book", "market_id": market, "timestamp": "2026-01-01T12:00:01Z",
         "bids": [{"price": 0.48, "size": 500}], "asks": []},
        {"event_type": "trade", "market_id": market, "fill_id": "t1", "timestamp": "2026-01-01T12:00:02Z",
         "side": "sell", "price": 0.48, "size": 100, "is_maker": False},
    ]
    write_events(tmp_path / f"{market}.jsonl", events)
    result = BacktestRunner(make_run_config(str(tmp_path), market)).run()
    assert result.num_fills == 0, (
        f"H5 FAIL: Should not fill when opposing book is empty. Fills={result.num_fills}"
    )


# ===========================================================================
# H6: FeeModel is the same code path in backtest as in direct calculation
# ===========================================================================

def test_H6_backtest_fees_match_direct_calculation(tmp_path):
    """
    The fees recorded in the backtest result must match a direct FeeModel calculation
    for the same fill size and price. This confirms no separate fee approximation exists.
    Fill at 0.48 (QuoteEngine bid for FV=0.50), flatten at 0.50.
    """
    from src.fee_model import FeeModel
    fm = FeeModel()
    fee_rate = 0.04
    rebate_fraction = 0.20
    fill_price = 0.48
    fill_size = 100.0
    flatten_price = 0.50
    flatten_size = 100.0

    expected_fee = fm.taker_fee(flatten_size, flatten_price, fee_rate)
    expected_rebate = fm.maker_rebate(fill_size, fill_price, fee_rate, rebate_fraction)

    market = "h6-fee-check"
    events = [
        {"event_type": "trade", "market_id": market, "fill_id": "seed", "timestamp": "2026-01-01T12:00:00Z",
         "side": "buy", "price": 0.50, "size": 500, "is_maker": False},
        {"event_type": "book", "market_id": market, "timestamp": "2026-01-01T12:00:01Z",
         "bids": [{"price": 0.48, "size": 500}], "asks": [{"price": 0.50, "size": 500}]},
        {"event_type": "trade", "market_id": market, "fill_id": "entry", "timestamp": "2026-01-01T12:00:02Z",
         "side": "sell", "price": 0.48, "size": 100, "is_maker": False},
        {"event_type": "book", "market_id": market, "timestamp": "2026-01-01T12:00:03Z",
         "bids": [{"price": 0.48, "size": 400}], "asks": [{"price": 0.50, "size": 500}]},
        {"event_type": "trade", "market_id": market, "fill_id": "flatten", "timestamp": "2026-01-01T12:00:04Z",
         "side": "buy", "price": 0.50, "size": 200, "is_maker": False},
    ]
    write_events(tmp_path / f"{market}.jsonl", events)
    result = BacktestRunner(
        make_run_config(str(tmp_path), market, fee_rate=fee_rate, rebate_fraction=rebate_fraction)
    ).run()

    assert result.num_cycles_completed > 0, (
        "H6 FAIL: No cycle completed — backtest must complete a cycle for fee verification"
    )
    assert result.total_fees_paid == pytest.approx(expected_fee, rel=1e-6), (
        f"H6 FAIL: Backtest fee {result.total_fees_paid:.8f} != direct calc {expected_fee:.8f}"
    )
