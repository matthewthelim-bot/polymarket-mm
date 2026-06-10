import pytest
from datetime import datetime, timezone
from src.fee_model import FeeModel
from src.data.schemas import OrderBook, PriceLevel, Side
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig, HedgeabilityResult


def ts():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_book(asks: list[tuple[float, float]], bids: list[tuple[float, float]] = None) -> OrderBook:
    return OrderBook(
        market_id="m1",
        timestamp=ts(),
        bids=[PriceLevel(p, s) for p, s in (bids or [])],
        asks=[PriceLevel(p, s) for p, s in asks],
    )


NO_SKEW = SkewConfig(
    skew_tolerance=0.0,
    skew_edge_premium=0.005,
    skew_hard_limit=0,
    skew_capital_charge_multiplier=3.0,
    max_skew_notional=0.0,
    current_skew_notional=0.0,
)

SKEW_ALLOWED = SkewConfig(
    skew_tolerance=100.0,
    skew_edge_premium=0.005,
    skew_hard_limit=200,
    skew_capital_charge_multiplier=3.0,
    max_skew_notional=500.0,
    current_skew_notional=0.0,
)


def make_assessor(min_edge_floor: float = 0.005) -> HedgeabilityAssessor:
    return HedgeabilityAssessor(
        fee_model=FeeModel(),
        fee_rate=0.04,
        rebate_fraction=0.20,
        min_edge_floor=min_edge_floor,
    )


# --- Basic hedgeability ---

def test_full_depth_available():
    assessor = make_assessor()
    # Bought Yes at 0.46. Opposing No asks at 0.50.
    # max_flatten_price at p_fill=0.46, fee_rate=0.04 ≈ 0.527
    # 0.50 < 0.527, so all depth is hedgeable.
    book = make_book(asks=[(0.50, 200.0)])
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=100.0,
        book=book,
        own_order_ids=set(),
        skew_config=NO_SKEW,
    )
    assert result.hedgeable_size == pytest.approx(100.0)
    assert result.unhedgeable_size == pytest.approx(0.0)


def test_partial_depth():
    assessor = make_assessor()
    book = make_book(asks=[(0.50, 40.0)])  # only 40 contracts available
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=100.0,
        book=book,
        own_order_ids=set(),
        skew_config=NO_SKEW,
    )
    assert result.hedgeable_size == pytest.approx(40.0)
    assert result.unhedgeable_size == pytest.approx(60.0)


def test_price_above_max_flatten_is_excluded():
    assessor = make_assessor()
    # max_flatten_price at 0.46 ≈ 0.527. Ask at 0.60 > 0.527 → excluded.
    book = make_book(asks=[(0.60, 200.0)])
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=100.0,
        book=book,
        own_order_ids=set(),
        skew_config=NO_SKEW,
    )
    assert result.hedgeable_size == pytest.approx(0.0)
    assert result.unhedgeable_size == pytest.approx(100.0)


# --- Own order stripping ---

def test_own_orders_stripped_from_depth():
    assessor = make_assessor()
    # Book shows 200 at 0.50 but 150 are our own orders.
    book = make_book(asks=[(0.50, 200.0)])
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=100.0,
        book=book,
        own_order_ids={"ord-1"},
        skew_config=NO_SKEW,
        own_order_sizes={0.50: 150.0},  # 150 of our own at price 0.50
    )
    # Net depth = 200 - 150 = 50
    assert result.hedgeable_size == pytest.approx(50.0)
    assert result.unhedgeable_size == pytest.approx(50.0)


def test_own_orders_only_strip_at_correct_level():
    assessor = make_assessor()
    # Two ask levels: 0.50 (200), 0.52 (100). Own order of 150 at 0.50.
    # max_flatten_price at 0.46 ≈ 0.527, so both levels are below ceiling.
    # Net depth: (200-150) + 100 = 150
    book = make_book(asks=[(0.50, 200.0), (0.52, 100.0)])
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=200.0,
        book=book,
        own_order_ids={"ord-1"},
        skew_config=NO_SKEW,
        own_order_sizes={0.50: 150.0},  # only at 0.50, not at 0.52
    )
    # Net depth = (200-150) + 100 = 150; min(200, 150) = 150 hedgeable
    assert result.hedgeable_size == pytest.approx(150.0)
    assert result.unhedgeable_size == pytest.approx(50.0)


# --- Skew accept/reject ---

def test_skew_rejected_when_tolerance_zero():
    assessor = make_assessor()
    book = make_book(asks=[])  # no opposing depth
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=100.0,
        book=book,
        own_order_ids=set(),
        skew_config=NO_SKEW,
    )
    assert result.hedgeable_size == pytest.approx(0.0)
    assert result.unhedgeable_size == pytest.approx(100.0)
    assert result.skew_accepted == pytest.approx(0.0)


def test_skew_accepted_within_tolerance():
    assessor = make_assessor()
    book = make_book(asks=[])  # no opposing depth
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=50.0,
        book=book,
        own_order_ids=set(),
        skew_config=SKEW_ALLOWED,
    )
    # skew_tolerance=100, quote_size=50 → all 50 accepted as skew
    assert result.skew_accepted == pytest.approx(50.0)
    assert result.skew_rejected == pytest.approx(0.0)


def test_skew_hard_limit_notional_still_enforced():
    assessor = make_assessor()
    book = make_book(asks=[])
    config = SkewConfig(
        skew_tolerance=100.0,
        skew_edge_premium=0.005,
        skew_hard_limit=200,
        skew_capital_charge_multiplier=3.0,
        max_skew_notional=500.0,
        current_skew_notional=180.0,  # already near notional limit
    )
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=100.0,
        book=book,
        own_order_ids=set(),
        skew_config=config,
    )
    # max_skew_notional=500, current=180, remaining = 320 notional
    # at price 0.46, max new skew contracts = 320/0.46 ≈ 695
    # but quote_size=100, so all 100 accepted (notional room is sufficient)
    assert result.skew_accepted * 0.46 + 180.0 <= 500.0 + 1e-6


def test_skew_hard_limit_blocks_when_contracts_at_limit():
    assessor = make_assessor()
    book = make_book(asks=[])
    config = SkewConfig(
        skew_tolerance=100.0,
        skew_edge_premium=0.005,
        skew_hard_limit=200,
        skew_capital_charge_multiplier=3.0,
        max_skew_notional=500.0,
        current_skew_notional=0.0,
        current_skew_contracts=200.0,  # already AT the hard limit
    )
    result = assessor.assess(
        quote_side=Side.BUY,
        quote_price=0.46,
        quote_size=100.0,
        book=book,
        own_order_ids=set(),
        skew_config=config,
    )
    # Hard limit hit — no new skew accepted
    assert result.skew_accepted == pytest.approx(0.0)
    assert result.skew_rejected == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Sell-side hedge threshold (min_flatten_price_for_sell)
# ---------------------------------------------------------------------------
# Selling the opposing side is profitable only when
#   p_fill + p_flatten - 1 + rebate - taker_fee(p_flatten) - edge >= 0
# i.e. p_flatten must sit ABOVE a floor (~1 - p_fill + fees + edge), not below
# the buy-side ceiling (~1 - p_fill - fees - edge). The gap between the two
# bounds is ~2*(fee + edge) of loss-making prices.

def test_min_flatten_price_for_sell_above_buy_ceiling():
    fm = FeeModel()
    kw = dict(p_fill=0.5, fee_rate=0.07, rebate_fraction=0.5, min_edge_floor=0.005)
    floor = fm.min_flatten_price_for_sell(**kw)
    ceiling = fm.max_flatten_price(**kw)
    # The sell floor must sit strictly above the buy ceiling (fee+edge gap)
    assert floor > ceiling + 0.02


def test_min_flatten_price_for_sell_breakeven_exact():
    fm = FeeModel()
    p_fill, fee_rate, rebate_frac, edge = 0.5, 0.07, 0.5, 0.005
    floor = fm.min_flatten_price_for_sell(
        p_fill=p_fill, fee_rate=fee_rate,
        rebate_fraction=rebate_frac, min_edge_floor=edge,
    )
    # Verify the root: net edge at the floor is exactly zero
    rebate = rebate_frac * fee_rate * p_fill * (1 - p_fill)
    taker_fee = fee_rate * floor * (1 - floor)
    net = (p_fill + floor - 1) + rebate - taker_fee - edge
    assert net == pytest.approx(0.0, abs=1e-9)


def test_min_flatten_price_for_sell_zero_fee_linear():
    fm = FeeModel()
    floor = fm.min_flatten_price_for_sell(
        p_fill=0.6, fee_rate=0.0, rebate_fraction=0.5, min_edge_floor=0.01,
    )
    # No fees, no rebate: p >= 1 - 0.6 + 0.01
    assert floor == pytest.approx(0.41)


def test_sell_assess_excludes_bids_in_loss_gap():
    """Bids between the buy ceiling and the sell floor must NOT count."""
    assessor = make_assessor()
    fm = FeeModel()
    # Parameters must match make_assessor (fee_rate=0.04, rebate_fraction=0.20)
    floor = fm.min_flatten_price_for_sell(
        p_fill=0.5, fee_rate=0.04, rebate_fraction=0.20, min_edge_floor=0.005,
    )
    # One bid just below the floor (loss-making), one just above (profitable)
    book = make_book(asks=[], bids=[(floor + 0.01, 60.0), (floor - 0.01, 40.0)])
    result = assessor.assess(
        quote_side=Side.SELL,
        quote_price=0.5,
        quote_size=100.0,
        book=book,
        own_order_ids=set(),
        skew_config=NO_SKEW,
    )
    # Only the 60 contracts above the floor are hedgeable
    assert result.hedgeable_size == pytest.approx(60.0)
    assert result.unhedgeable_size == pytest.approx(40.0)
    assert result.max_flatten_price == pytest.approx(floor)


def test_sell_assess_old_bound_would_have_passed():
    """Regression guard: a bid above the (wrong) buy ceiling but below the
    (correct) sell floor is unhedgeable."""
    assessor = make_assessor()
    fm = FeeModel()
    kw = dict(p_fill=0.5, fee_rate=0.04, rebate_fraction=0.20, min_edge_floor=0.005)
    ceiling = fm.max_flatten_price(**kw)
    floor = fm.min_flatten_price_for_sell(**kw)
    mid_gap = (ceiling + floor) / 2  # inside the loss-making gap
    book = make_book(asks=[], bids=[(mid_gap, 100.0)])
    result = assessor.assess(
        quote_side=Side.SELL,
        quote_price=0.5,
        quote_size=100.0,
        book=book,
        own_order_ids=set(),
        skew_config=NO_SKEW,
    )
    assert result.hedgeable_size == pytest.approx(0.0)
    assert result.unhedgeable_size == pytest.approx(100.0)
