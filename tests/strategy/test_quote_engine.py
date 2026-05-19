import pytest
from src.fee_model import FeeModel
from src.data.schemas import Regime, QuoteDecision
from src.strategy.quote_engine import QuoteEngine, QuoteInput
from src.strategy.hedgeability import HedgeabilityResult


def make_result(hedgeable=100.0, unhedgeable=0.0, skew_accepted=0.0, p_max=0.527) -> HedgeabilityResult:
    return HedgeabilityResult(
        hedgeable_size=hedgeable,
        unhedgeable_size=unhedgeable,
        skew_accepted=skew_accepted,
        skew_rejected=unhedgeable - skew_accepted,
        max_flatten_price=p_max,
    )


def make_engine(half_spread_base=0.015, min_edge_floor=0.005) -> QuoteEngine:
    return QuoteEngine(
        fee_model=FeeModel(),
        fee_rate=0.04,
        rebate_fraction=0.20,
        half_spread_base=half_spread_base,
        min_edge_floor=min_edge_floor,
    )


def make_input(**kwargs) -> QuoteInput:
    defaults = dict(
        fv=0.50,
        regime=Regime.QUOTE_ACTIVE,
        hedgeability=make_result(),
        adverse_selection=0.005,
        quote_size=100.0,
    )
    defaults.update(kwargs)
    return QuoteInput(**defaults)


# --- Basic spread construction ---

def test_bid_below_fv_ask_above_fv():
    engine = make_engine()
    inp = make_input(fv=0.50)
    decision = engine.compute(inp)
    assert decision.bid_price < 0.50
    assert decision.ask_price > 0.50


def test_spread_covers_fee_flatten_expected():
    engine = make_engine()
    fv = 0.50
    inp = make_input(fv=fv)
    decision = engine.compute(inp)
    fee_cost = FeeModel().fee_flatten_expected(fv=fv, fee_rate=0.04)
    half_spread = (decision.ask_price - decision.bid_price) / 2
    assert half_spread >= fee_cost - 1e-9


def test_spread_at_midmarket_is_wider_than_at_extreme():
    engine = make_engine()
    d_mid = engine.compute(make_input(fv=0.50))
    d_low = engine.compute(make_input(fv=0.30))
    assert d_mid.spread() >= d_low.spread() - 1e-6


# --- Regime adjustments ---

def test_suspended_returns_suspend_flag():
    engine = make_engine()
    inp = make_input(regime=Regime.SUSPENDED)
    decision = engine.compute(inp)
    assert decision.suspend is True


def test_settled_returns_suspend_flag():
    engine = make_engine()
    inp = make_input(regime=Regime.SETTLED)
    decision = engine.compute(inp)
    assert decision.suspend is True


def test_warehouse_widens_spread():
    engine = make_engine()
    d_active = engine.compute(make_input(regime=Regime.QUOTE_ACTIVE))
    d_warehouse = engine.compute(make_input(regime=Regime.INVENTORY_WAREHOUSE))
    assert d_warehouse.spread() > d_active.spread()


def test_one_side_filled_quotes_only_hedge_leg():
    engine = make_engine()
    inp = make_input(regime=Regime.ONE_SIDE_FILLED)
    decision = engine.compute(inp)
    # Don't add more inventory; only quote ask side (flatten leg)
    assert decision.bid_size == 0.0
    assert decision.ask_size > 0.0


# --- Skew edge premium ---

def test_skew_widens_bid_when_accepted():
    engine = make_engine()
    d_no_skew = engine.compute(make_input(hedgeability=make_result(hedgeable=100, unhedgeable=0, skew_accepted=0)))
    d_with_skew = engine.compute(make_input(hedgeability=make_result(hedgeable=50, unhedgeable=50, skew_accepted=50)))
    assert d_with_skew.bid_price <= d_no_skew.bid_price


# --- Size constraints ---

def test_bid_size_zero_when_no_hedgeable_depth_and_no_skew():
    engine = make_engine()
    inp = make_input(hedgeability=make_result(hedgeable=0, unhedgeable=100, skew_accepted=0))
    decision = engine.compute(inp)
    assert decision.bid_size == 0.0
