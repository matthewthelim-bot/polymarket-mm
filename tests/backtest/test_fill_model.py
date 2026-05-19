import pytest
from src.backtest.fill_model import FillModel, FillModelConfig, QueueModel, FillModelInput


def make_input(**kwargs) -> FillModelInput:
    defaults = dict(
        quote_price=0.46,
        quote_size=100.0,
        market_trade_price=0.46,
        market_trade_size=200.0,
        book_size_at_price=500.0,
    )
    defaults.update(kwargs)
    return FillModelInput(**defaults)


# --- FRONT model ---

def test_touch_fills_when_market_trades_at_price():
    model = FillModel(FillModelConfig(queue_model=QueueModel.FRONT))
    inp = make_input(quote_price=0.46, market_trade_price=0.46)
    result = model.simulate_fill(inp)
    assert result.filled_size == pytest.approx(100.0)


def test_touch_no_fill_when_price_not_touched():
    model = FillModel(FillModelConfig(queue_model=QueueModel.FRONT))
    inp = make_input(quote_price=0.46, market_trade_price=0.47)
    result = model.simulate_fill(inp)
    assert result.filled_size == pytest.approx(0.0)


def test_touch_partial_fill_when_trade_smaller_than_quote():
    model = FillModel(FillModelConfig(queue_model=QueueModel.FRONT))
    inp = make_input(quote_price=0.46, market_trade_price=0.46, market_trade_size=50.0)
    result = model.simulate_fill(inp)
    # FRONT: we're at front of queue, fill min(trade_size, quote_size)
    assert result.filled_size == pytest.approx(50.0)


# --- PRO_RATA model ---

def test_pro_rata_fill_proportion():
    model = FillModel(FillModelConfig(queue_model=QueueModel.PRO_RATA))
    inp = make_input(
        quote_price=0.46,
        market_trade_price=0.46,
        market_trade_size=100.0,
        book_size_at_price=500.0,
        quote_size=50.0,
    )
    result = model.simulate_fill(inp)
    # pro-rata share: (50/500) * 100 = 10
    assert result.filled_size == pytest.approx(10.0)


# --- BACK model ---

def test_back_fills_only_if_full_book_cleared():
    model = FillModel(FillModelConfig(queue_model=QueueModel.BACK))
    inp = make_input(
        quote_price=0.46,
        market_trade_price=0.46,
        market_trade_size=200.0,
        book_size_at_price=500.0,
        quote_size=100.0,
    )
    result = model.simulate_fill(inp)
    # trade_size (200) < book_size (500) → we're at back, no fill
    assert result.filled_size == pytest.approx(0.0)


def test_back_fills_when_book_cleared():
    model = FillModel(FillModelConfig(queue_model=QueueModel.BACK))
    inp = make_input(
        quote_price=0.46,
        market_trade_price=0.46,
        market_trade_size=600.0,   # exceeds book
        book_size_at_price=500.0,
        quote_size=100.0,
    )
    result = model.simulate_fill(inp)
    assert result.filled_size == pytest.approx(100.0)


# --- Latency ---

def test_latency_delays_fill():
    model = FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=100))
    inp = make_input()
    result = model.simulate_fill(inp)
    assert result.latency_ms == 100
