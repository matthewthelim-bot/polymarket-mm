from dataclasses import asdict
from datetime import datetime, timezone
from src.data.schemas import (
    MarketMetadata,
    PriceLevel,
    OrderBook,
    Fill,
    InventoryState,
    QuoteDecision,
    Side,
    Regime,
)
import pytest


def test_market_metadata_defaults():
    m = MarketMetadata(
        condition_id="abc",
        token_id_yes="0xyes",
        token_id_no="0xno",
        category="crypto",
        fee_rate=0.07,
        fee_exponent=1,
        rebate_fraction=0.20,
        sports=False,
    )
    assert m.fee_rate == 0.07
    assert m.sports is False


def test_order_book_mid():
    book = OrderBook(
        market_id="abc",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bids=[PriceLevel(price=0.45, size=100.0)],
        asks=[PriceLevel(price=0.55, size=100.0)],
    )
    assert book.mid() == 0.50


def test_order_book_mid_empty_returns_none():
    book = OrderBook(
        market_id="abc",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bids=[],
        asks=[],
    )
    assert book.mid() is None


def test_order_book_best_bid_ask():
    book = OrderBook(
        market_id="abc",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bids=[PriceLevel(0.44, 50), PriceLevel(0.43, 100)],
        asks=[PriceLevel(0.56, 50), PriceLevel(0.57, 100)],
    )
    assert book.best_bid() == 0.44
    assert book.best_ask() == 0.56


def test_fill_dataclass():
    f = Fill(
        fill_id="f1",
        market_id="m1",
        side=Side.BUY,
        price=0.46,
        size=100.0,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_maker=True,
    )
    assert f.notional() == pytest.approx(46.0)


def test_inventory_state_total_exposure():
    inv = InventoryState(
        market_id="m1",
        hedgeable_contracts=200.0,
        skew_contracts=50.0,
        avg_fill_price=0.46,
    )
    assert inv.total_contracts() == 250.0


def test_regime_enum_values():
    assert Regime.QUOTE_ACTIVE.value == "quote_active"
    assert Regime.SETTLED.value == "settled"


def test_side_enum():
    assert Side.BUY.value == "buy"
    assert Side.SELL.value == "sell"


def test_quote_decision_dataclass():
    qd = QuoteDecision(
        bid_price=0.44,
        ask_price=0.56,
        bid_size=100.0,
        ask_size=100.0,
        regime=Regime.QUOTE_ACTIVE,
        suspend=False,
    )
    assert qd.spread() == pytest.approx(0.12)
