import pytest
from datetime import datetime, timezone, timedelta
from src.data.schemas import Regime, InventoryState
from src.strategy.regime import RegimeClassifier, RegimeInput


def ts(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)


def empty_inventory(market_id="m1") -> InventoryState:
    return InventoryState(
        market_id=market_id,
        hedgeable_contracts=0.0,
        skew_contracts=0.0,
        avg_fill_price=0.0,
    )


def make_input(**kwargs) -> RegimeInput:
    defaults = dict(
        timestamp=ts(0),
        inventory=empty_inventory(),
        adverse_selection=0.005,
        adverse_selection_threshold=0.012,
        time_to_resolution_hours=48.0,
        pre_resolution_hours=4.0,
        max_inventory_contracts=500.0,
        warehouse_threshold_fraction=0.80,
        fv=0.50,
        best_bid=0.47,
        best_ask=0.53,
    )
    defaults.update(kwargs)
    return RegimeInput(**defaults)


def test_initial_regime_is_quote_active():
    clf = RegimeClassifier()
    inp = make_input()
    assert clf.classify(inp) == Regime.QUOTE_ACTIVE


def test_high_adverse_selection_suspends():
    clf = RegimeClassifier()
    inp = make_input(adverse_selection=0.015)
    assert clf.classify(inp) == Regime.SUSPENDED


def test_low_adverse_selection_stays_active():
    clf = RegimeClassifier()
    inp = make_input(adverse_selection=0.008)
    assert clf.classify(inp) == Regime.QUOTE_ACTIVE


def test_one_side_filled_when_inventory_nonzero():
    clf = RegimeClassifier()
    inv = InventoryState("m1", hedgeable_contracts=50.0, skew_contracts=0.0, avg_fill_price=0.46)
    inp = make_input(inventory=inv)
    assert clf.classify(inp) == Regime.ONE_SIDE_FILLED


def test_inventory_warehouse_near_limit():
    clf = RegimeClassifier()
    inv = InventoryState("m1", hedgeable_contracts=420.0, skew_contracts=0.0, avg_fill_price=0.46)
    # 420 / 500 = 0.84 > warehouse_threshold_fraction=0.80
    inp = make_input(inventory=inv)
    assert clf.classify(inp) == Regime.INVENTORY_WAREHOUSE


def test_inventory_reduced_mid_range():
    clf = RegimeClassifier()
    inv = InventoryState("m1", hedgeable_contracts=200.0, skew_contracts=0.0, avg_fill_price=0.46)
    # 200 / 500 = 0.40, between one_side_filled and warehouse
    inp = make_input(inventory=inv)
    assert clf.classify(inp) == Regime.INVENTORY_REDUCED


def test_pre_resolution_triggers_hedge_pending():
    clf = RegimeClassifier()
    inv = InventoryState("m1", hedgeable_contracts=50.0, skew_contracts=0.0, avg_fill_price=0.46)
    inp = make_input(inventory=inv, time_to_resolution_hours=2.0)  # < 4h
    assert clf.classify(inp) == Regime.HEDGE_PENDING


def test_settled_when_resolution_passed():
    clf = RegimeClassifier()
    inp = make_input(time_to_resolution_hours=0.0)
    assert clf.classify(inp) == Regime.SETTLED


def test_adverse_selection_overrides_inventory():
    clf = RegimeClassifier()
    inv = InventoryState("m1", hedgeable_contracts=420.0, skew_contracts=0.0, avg_fill_price=0.46)
    inp = make_input(inventory=inv, adverse_selection=0.020)
    assert clf.classify(inp) == Regime.SUSPENDED


def test_settled_overrides_one_side_filled():
    clf = RegimeClassifier()
    inv = InventoryState("m1", hedgeable_contracts=50.0, skew_contracts=0.0, avg_fill_price=0.46)
    inp = make_input(inventory=inv, time_to_resolution_hours=0.0)
    assert clf.classify(inp) == Regime.SETTLED


def test_settled_overrides_suspended():
    # When both conditions are true (time=0 AND high adverse selection),
    # SETTLED takes precedence. Once resolved, AS detection is moot.
    clf = RegimeClassifier()
    inp = make_input(time_to_resolution_hours=0.0, adverse_selection=0.020)
    assert clf.classify(inp) == Regime.SETTLED
