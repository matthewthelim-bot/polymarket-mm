import pytest
from src.fee_model import FeeModel
from src.pnl import PnLEngine, CompletedCycle


def make_engine():
    return PnLEngine(fee_model=FeeModel(), fee_rate=0.04, rebate_fraction=0.20)


# --- Spread PnL ---

def test_spread_pnl_risk_free_cycle():
    engine = make_engine()
    # Buy Yes at 0.44, buy No at 0.52 → combined = 0.96 < 1.0
    # Risk-free payout = 1 - 0.44 - 0.52 = 0.04 per contract * 100 = 4.00
    # Taker fee on flatten: 100 * 0.04 * 0.52 * 0.48 = 0.9984
    # Maker rebate on entry: 100 * 0.20 * 0.04 * 0.44 * 0.56 = 0.19712
    cycle = CompletedCycle(
        market_id="m1",
        entry_price=0.44,
        entry_size=100.0,
        flatten_price=0.52,
        flatten_size=100.0,
        is_skew=False,
    )
    result = engine.compute_cycle(cycle)
    gross = (1 - 0.44 - 0.52) * 100
    flatten_fee = 100 * 0.04 * 0.52 * 0.48
    maker_rebate = 100 * 0.20 * 0.04 * 0.44 * 0.56
    expected_net = gross - flatten_fee + maker_rebate
    assert result.spread_pnl == pytest.approx(expected_net, rel=1e-4)
    assert result.skew_pnl == pytest.approx(0.0)


def test_skew_pnl_reported_separately():
    engine = make_engine()
    cycle = CompletedCycle(
        market_id="m1",
        entry_price=0.44,
        entry_size=100.0,
        flatten_price=0.52,
        flatten_size=100.0,
        is_skew=True,
    )
    result = engine.compute_cycle(cycle)
    assert result.spread_pnl == pytest.approx(0.0)
    assert result.skew_pnl != 0.0


def test_loss_when_flatten_too_expensive():
    engine = make_engine()
    # Buy Yes at 0.44, forced to flatten No at 0.60 → combined = 1.04 > 1.0
    cycle = CompletedCycle(
        market_id="m1",
        entry_price=0.44,
        entry_size=100.0,
        flatten_price=0.60,
        flatten_size=100.0,
        is_skew=False,
    )
    result = engine.compute_cycle(cycle)
    assert result.spread_pnl < 0


def test_total_pnl_is_sum_of_buckets():
    engine = make_engine()
    cycle = CompletedCycle("m1", 0.44, 100, 0.52, 100, is_skew=False)
    result = engine.compute_cycle(cycle)
    assert result.total_pnl() == pytest.approx(result.spread_pnl + result.skew_pnl)


def test_settlement_pnl_yes_resolves():
    engine = make_engine()
    result = engine.compute_settlement(
        avg_fill_price=0.46, contracts=100.0, resolution=1.0, is_skew=False
    )
    # pnl = (1.0 - 0.46) * 100 = 54.0
    assert result.spread_pnl == pytest.approx(54.0)


def test_settlement_pnl_no_resolves():
    engine = make_engine()
    result = engine.compute_settlement(
        avg_fill_price=0.46, contracts=100.0, resolution=0.0, is_skew=False
    )
    # pnl = (0.0 - 0.46) * 100 = -46.0
    assert result.spread_pnl == pytest.approx(-46.0)


def test_fees_present_in_result():
    engine = make_engine()
    cycle = CompletedCycle("m1", 0.44, 100, 0.52, 100, is_skew=False)
    result = engine.compute_cycle(cycle)
    assert result.taker_fee_paid > 0
    assert result.maker_rebate_received > 0
