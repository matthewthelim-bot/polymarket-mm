import pytest
from src.data.schemas import Side, Fill
from src.strategy.inventory import InventoryManager
from datetime import datetime, timezone


def ts():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_fill(price: float, size: float, side: Side = Side.BUY, is_maker: bool = True) -> Fill:
    return Fill(
        fill_id="f1", market_id="m1",
        side=side, price=price, size=size,
        timestamp=ts(), is_maker=is_maker,
    )


# --- Initial state ---

def test_initial_inventory_is_zero():
    mgr = InventoryManager(market_id="m1")
    state = mgr.state()
    assert state.hedgeable_contracts == 0.0
    assert state.skew_contracts == 0.0
    assert state.total_contracts() == 0.0


# --- Adding fills ---

def test_add_hedgeable_fill():
    mgr = InventoryManager(market_id="m1")
    mgr.add_fill(make_fill(0.46, 100.0), is_skew=False)
    state = mgr.state()
    assert state.hedgeable_contracts == pytest.approx(100.0)
    assert state.skew_contracts == 0.0


def test_add_skew_fill():
    mgr = InventoryManager(market_id="m1")
    mgr.add_fill(make_fill(0.46, 50.0), is_skew=True)
    state = mgr.state()
    assert state.skew_contracts == pytest.approx(50.0)
    assert state.hedgeable_contracts == 0.0


def test_avg_fill_price_weighted():
    mgr = InventoryManager(market_id="m1")
    mgr.add_fill(make_fill(0.40, 100.0), is_skew=False)
    mgr.add_fill(make_fill(0.50, 100.0), is_skew=False)
    state = mgr.state()
    assert state.avg_fill_price == pytest.approx(0.45)


# --- Flatten fills reduce inventory ---

def test_flatten_reduces_hedgeable_first():
    mgr = InventoryManager(market_id="m1")
    mgr.add_fill(make_fill(0.46, 100.0), is_skew=False)
    mgr.add_fill(make_fill(0.50, 60.0), is_skew=True)
    # Flatten 80: reduce hedgeable first
    mgr.add_flatten(size=80.0, price=0.52)
    state = mgr.state()
    assert state.hedgeable_contracts == pytest.approx(20.0)
    assert state.skew_contracts == pytest.approx(60.0)


def test_flatten_bleeds_into_skew():
    mgr = InventoryManager(market_id="m1")
    mgr.add_fill(make_fill(0.46, 50.0), is_skew=False)
    mgr.add_fill(make_fill(0.46, 50.0), is_skew=True)
    # Flatten 80: exhaust hedgeable (50), then take 30 from skew
    mgr.add_flatten(size=80.0, price=0.52)
    state = mgr.state()
    assert state.hedgeable_contracts == pytest.approx(0.0)
    assert state.skew_contracts == pytest.approx(20.0)


def test_flatten_does_not_go_negative():
    mgr = InventoryManager(market_id="m1")
    mgr.add_fill(make_fill(0.46, 30.0), is_skew=False)
    mgr.add_flatten(size=50.0, price=0.52)  # more than we have
    state = mgr.state()
    assert state.hedgeable_contracts == pytest.approx(0.0)
    assert state.total_contracts() == pytest.approx(0.0)


# --- Capital charge ---

def test_capital_charge_hedgeable():
    mgr = InventoryManager(market_id="m1", daily_capital_charge_rate=0.0003)
    mgr.add_fill(make_fill(0.46, 100.0), is_skew=False)
    charge = mgr.daily_capital_charge(skew_multiplier=3.0)
    # hedgeable: 100 * 0.46 * 0.0003 = 0.0138
    assert charge == pytest.approx(100 * 0.46 * 0.0003)


def test_capital_charge_skew_multiplied():
    mgr = InventoryManager(market_id="m1", daily_capital_charge_rate=0.0003)
    mgr.add_fill(make_fill(0.46, 100.0), is_skew=True)
    charge = mgr.daily_capital_charge(skew_multiplier=3.0)
    # skew: 100 * 0.46 * 0.0003 * 3.0 = 0.0414
    assert charge == pytest.approx(100 * 0.46 * 0.0003 * 3.0)


def test_capital_charge_combined():
    mgr = InventoryManager(market_id="m1", daily_capital_charge_rate=0.0003)
    mgr.add_fill(make_fill(0.46, 100.0), is_skew=False)
    mgr.add_fill(make_fill(0.46, 50.0), is_skew=True)
    charge = mgr.daily_capital_charge(skew_multiplier=3.0)
    expected = (100 * 0.46 * 0.0003) + (50 * 0.46 * 0.0003 * 3.0)
    assert charge == pytest.approx(expected)


def test_avg_fill_price_stable_after_partial_flatten():
    # avg_fill_price should be unchanged after a partial flatten.
    # We bought 100 @ 0.46. Flatten 50 (half). Avg price stays 0.46.
    mgr = InventoryManager(market_id="m1")
    mgr.add_fill(make_fill(0.46, 100.0), is_skew=False)
    mgr.add_flatten(size=50.0, price=0.52)
    state = mgr.state()
    assert state.hedgeable_contracts == pytest.approx(50.0)
    assert state.avg_fill_price == pytest.approx(0.46)
