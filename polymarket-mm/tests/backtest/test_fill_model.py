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
    # Our quote joins the denominator: share = 50/(500+50), fill = share * 100
    assert result.filled_size == pytest.approx(100.0 * 50.0 / 550.0)


def test_pro_rata_own_quote_in_denominator():
    """Our size >= displayed book must NOT yield share > 1 (the old bug)."""
    model = FillModel(FillModelConfig(queue_model=QueueModel.PRO_RATA))
    inp = make_input(
        quote_price=0.46,
        market_trade_price=0.46,
        market_trade_size=60.0,
        book_size_at_price=50.0,
        quote_size=100.0,
    )
    result = model.simulate_fill(inp)
    # share = 100/150, fill = 60 * 100/150 = 40 — never the full trade
    assert result.filled_size == pytest.approx(40.0)


def test_pro_rata_zero_book_we_are_whole_queue():
    """Zero displayed depth means our order IS the queue → full pro-rata fill."""
    model = FillModel(FillModelConfig(queue_model=QueueModel.PRO_RATA))
    inp = make_input(quote_price=0.46, market_trade_price=0.46,
                     market_trade_size=200.0, book_size_at_price=0.0,
                     quote_size=100.0)
    result = model.simulate_fill(inp)
    assert result.filled_size == pytest.approx(100.0)


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
    # 600 clears the 500 book; 100 contracts remain for us → full fill
    assert result.filled_size == pytest.approx(100.0)


def test_back_partial_fill_from_overflow():
    """Only the trade volume beyond the displayed book reaches us."""
    model = FillModel(FillModelConfig(queue_model=QueueModel.BACK))
    inp = make_input(
        quote_price=0.46,
        market_trade_price=0.46,
        market_trade_size=530.0,   # 30 contracts beyond the book
        book_size_at_price=500.0,
        quote_size=100.0,
    )
    result = model.simulate_fill(inp)
    assert result.filled_size == pytest.approx(30.0)


def test_back_exact_book_exhaustion_no_fill():
    """trade_size exactly equals book_size → nothing left for us at the back."""
    model = FillModel(FillModelConfig(queue_model=QueueModel.BACK))
    inp = make_input(
        quote_price=0.46,
        market_trade_price=0.46,
        market_trade_size=500.0,  # exactly equals book_size
        book_size_at_price=500.0,
        quote_size=100.0,
    )
    result = model.simulate_fill(inp)
    assert result.filled_size == pytest.approx(0.0)


# --- Latency ---

def test_latency_delays_fill():
    model = FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=100))
    inp = make_input()
    result = model.simulate_fill(inp)
    assert result.latency_ms == 100


# --- Input validation ---

def test_negative_quote_size_raises():
    with pytest.raises(ValueError, match="quote_size"):
        make_input(quote_size=-10.0)


def test_negative_trade_size_raises():
    with pytest.raises(ValueError, match="market_trade_size"):
        make_input(market_trade_size=-5.0)
