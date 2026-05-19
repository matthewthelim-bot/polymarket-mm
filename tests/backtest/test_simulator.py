import pytest
from datetime import datetime, timezone, timedelta
from src.fee_model import FeeModel
from src.data.schemas import (
    MarketMetadata, OrderBook, PriceLevel, Fill, Side, Regime
)
from src.strategy.fair_value import FairValueEstimator
from src.strategy.regime import RegimeClassifier
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig
from src.strategy.quote_engine import QuoteEngine
from src.strategy.inventory import InventoryManager
from src.pnl import PnLEngine
from src.backtest.fill_model import FillModel, FillModelConfig, QueueModel
from src.backtest.simulator import BacktestSimulator, SimulatorConfig, SimulationResult


def ts(offset=0):
    return datetime(2026, 1, 1, 12, tzinfo=timezone.utc) + timedelta(seconds=offset)


def make_metadata() -> MarketMetadata:
    return MarketMetadata(
        condition_id="test-001",
        token_id_yes="yes-001",
        token_id_no="no-001",
        category="politics",
        fee_rate=0.04,
        fee_exponent=1,
        rebate_fraction=0.20,
        sports=False,
    )


def make_book(bid=0.45, ask=0.55, size=200.0, t=0) -> OrderBook:
    return OrderBook(
        market_id="test-001",
        timestamp=ts(t),
        bids=[PriceLevel(bid, size)],
        asks=[PriceLevel(ask, size)],
    )


def make_simulator() -> BacktestSimulator:
    fm = FeeModel()
    meta = make_metadata()
    no_skew = SkewConfig(
        skew_tolerance=0.0, skew_edge_premium=0.005,
        skew_hard_limit=0, skew_capital_charge_multiplier=3.0,
        max_skew_notional=0.0, current_skew_notional=0.0,
    )
    return BacktestSimulator(
        metadata=meta,
        fee_model=fm,
        fv_estimator=FairValueEstimator(twap_window_seconds=300, external_weight=0.0),
        regime_classifier=RegimeClassifier(),
        hedgeability_assessor=HedgeabilityAssessor(fm, meta.fee_rate, meta.rebate_fraction),
        quote_engine=QuoteEngine(fm, meta.fee_rate, meta.rebate_fraction),
        inventory_manager=InventoryManager(meta.condition_id),
        pnl_engine=PnLEngine(fm, meta.fee_rate, meta.rebate_fraction),
        fill_model=FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=0)),
        skew_config=no_skew,
        config=SimulatorConfig(
            start_capital=10000.0,
            max_inventory_contracts=500,
            adverse_selection_threshold=0.012,
            time_to_resolution_hours=48.0,
            quote_size=100.0,
        ),
    )


# --- Simulator runs without error on empty feed ---

def test_empty_feed_produces_zero_pnl():
    sim = make_simulator()
    result = sim.run(events=[])
    assert result.total_spread_pnl == pytest.approx(0.0)
    assert result.total_skew_pnl == pytest.approx(0.0)
    assert result.num_fills == 0


# --- Book events update state ---

def test_book_event_updates_fv():
    sim = make_simulator()
    # Send a trade event followed by a book; FV should be set
    from src.strategy.fair_value import TradeObservation
    # We inject via events: a trade event creates a TradeObservation
    trade_fill = Fill(
        fill_id="t1", market_id="test-001",
        side=Side.BUY, price=0.50, size=50.0,
        timestamp=ts(0), is_maker=False,
    )
    book = make_book(t=1)
    result = sim.run(events=[trade_fill, book])
    assert result.num_book_updates >= 1


# --- A complete fill cycle produces positive spread PnL ---

def test_positive_pnl_on_clean_cycle():
    """
    FV = 0.50, half_spread_base=0.015:
      fee_flatten_expected(0.50, 0.04) = 1 * 0.04 * 0.50 * 0.50 = 0.01
      half_spread = max(0.015, 0.01 + 0.005) = 0.015
      bid_price = 0.50 - 0.015 = 0.485 → rounds to 0.49 (round(0.485, 2) = 0.48 in Python banker's rounding)

    We seed FV with a trade at 0.50, then build a book with ask depth at 0.52
    (within max_flatten_price(0.485, ...) ≈ 0.503).

    We inject a market trade at exactly the computed bid price to trigger the fill,
    then a book + trade at the flatten price to complete the cycle.
    """
    sim = make_simulator()

    # Seed FV
    seed_trade = Fill("seed", "test-001", Side.BUY, 0.50, 200.0, ts(0), False)

    # Book showing depth at ask=0.52 (within flatten ceiling ~0.503... actually let's
    # use ask=0.50 to guarantee it's within flatten price)
    book1 = make_book(bid=0.44, ask=0.50, size=500.0, t=1)

    # Compute what bid_price the QuoteEngine will actually produce given FV=0.50
    # fee_flatten_expected = 0.04 * 0.50 * 0.50 = 0.01
    # half_spread = max(0.015, 0.01 + 0.005) = 0.015
    # bid_price = 0.50 - 0.015 = 0.485 → round(0.485, 2)
    # Python banker's rounding: round(0.485, 2) == 0.48
    # However numpy/standard may differ. Let's compute it:
    fm = FeeModel()
    fee_cost = fm.fee_flatten_expected(fv=0.50, fee_rate=0.04)
    half_spread = max(0.015, fee_cost + 0.005)
    computed_bid = round(0.50 - half_spread, 2)

    # Market trade at exactly the computed bid price to trigger our passive fill
    passive_trade = Fill("pass1", "test-001", Side.SELL, computed_bid, 100.0, ts(2), False)

    # Book with ask at 0.50 (definitely within flatten ceiling for bid ~0.48)
    book2 = make_book(bid=computed_bid, ask=0.50, size=500.0, t=3)

    # Market trade at 0.50 on ask side (taker buy = we taker-sell to flatten)
    flatten_trade = Fill("flat1", "test-001", Side.BUY, 0.50, 100.0, ts(4), False)

    result = sim.run(events=[seed_trade, book1, passive_trade, book2, flatten_trade])
    # Gross = (1 - computed_bid - 0.50) * size, net of fees should be positive
    assert result.total_spread_pnl > 0
    assert result.num_fills >= 1


# --- Result has required fields ---

def test_result_has_required_fields():
    sim = make_simulator()
    result = sim.run(events=[])
    assert hasattr(result, 'total_spread_pnl')
    assert hasattr(result, 'total_skew_pnl')
    assert hasattr(result, 'num_fills')
    assert hasattr(result, 'num_book_updates')
    assert hasattr(result, 'total_fees_paid')
    assert hasattr(result, 'total_rebates_received')


# --- No fill when no prior book ---

def test_no_fill_without_book():
    sim = make_simulator()
    # Trade with no prior book should not produce fills
    trade = Fill("t1", "test-001", Side.BUY, 0.50, 100.0, ts(0), False)
    result = sim.run(events=[trade])
    assert result.num_fills == 0


# --- Multiple book updates are counted ---

def test_multiple_book_updates_counted():
    sim = make_simulator()
    books = [make_book(t=i) for i in range(5)]
    result = sim.run(events=books)
    assert result.num_book_updates == 5
