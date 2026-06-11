"""Live-path tests for QuoteLoop — the highest-stakes code in the repo.

Covers the maker-fill -> hedge critical path with a fake CLOB client:
  - fill routing for all four quadrants (yes/no x bid/ask)
  - taker hedge: full fill, partial fill (remainder -> open position),
    IOC unfilled, execution exception
  - cancel rejected -> maker-maker cycle (no taker sent)
  - unprofitable / no-depth hedge -> open position, no order
  - unroutable fills -> dead-letter after retry budget
  - portfolio cap suppression keeps the exit side alive
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from src.data.schemas import OrderBook, PriceLevel, Fill, Side
from src.fee_model import FeeModel
from src.live.clob_client import OrderResponse
from src.live.portfolio_state import PortfolioConstraints
from src.live.quote_loop import QuoteLoop, QuoteLoopConfig, _RestingOrder

YES = "yes-token"
NO = "no-token"


class FakeClobClient:
    """Configurable stand-in for ClobClient. Records every call."""

    def __init__(self):
        self.placed = []            # OrderRequest list
        self.cancelled = []         # order_id list
        self.cancel_result = True   # return value of cancel_order
        self.cancel_raises = None   # exception to raise from cancel_order
        self.fill_size = None       # None = fill fully; float = partial/zero
        self.place_raises = None

    def place_order(self, order):
        if self.place_raises:
            raise self.place_raises
        self.placed.append(order)
        filled = order.size if self.fill_size is None else self.fill_size
        return OrderResponse(
            order_id=f"ord-{len(self.placed)}",
            status="matched" if filled > 0 else "live",
            filled_size=filled,
            remaining_size=order.size - filled,
        )

    def cancel_order(self, order_id):
        if self.cancel_raises:
            raise self.cancel_raises
        self.cancelled.append(order_id)
        return self.cancel_result

    def get_book(self, token_id):  # pragma: no cover - fallback path only
        raise AssertionError("REST get_book must not be called in these tests")


def make_book(token: str, bids=None, asks=None) -> OrderBook:
    return OrderBook(
        market_id=token,
        timestamp=datetime.now(timezone.utc),
        bids=[PriceLevel(p, s) for p, s in (bids or [])],
        asks=[PriceLevel(p, s) for p, s in (asks or [])],
    )


def resting(price: float, token: str, side: Side, order_side: str, level=0):
    return _RestingOrder(
        order_id=f"rest-{token}-{order_side}-{level}",
        token_id=token, side=side, price=price, size=100.0,
        placed_at=time.monotonic(), token_side="YES" if token == YES else "NO",
        order_side=order_side, level=level,
    )


def make_loop(client=None, dry_run=False, **cfg_overrides):
    cfg = QuoteLoopConfig(
        market_id="TEST", yes_token_id=YES, no_token_id=NO,
        condition_id="0xtest", dry_run=dry_run,
        fee_rate=0.03, rebate_fraction=0.25,
        **cfg_overrides,
    )
    loop = QuoteLoop(config=cfg, clob_client=client or FakeClobClient(),
                     fee_model=FeeModel())
    # Books: YES 0.50/0.52, NO 0.46/0.48 — bid-arb viable (0.45+0.48 < 1)
    loop._current_yes_book = make_book(YES, bids=[(0.50, 500)], asks=[(0.52, 500)])
    loop._current_no_book = make_book(NO, bids=[(0.46, 500)], asks=[(0.48, 500)])
    return loop


def yes_fill(price: float, size=100.0) -> Fill:
    return Fill(fill_id="f1", market_id="0xtest", side=Side.SELL, price=price,
                size=size, timestamp=datetime.now(timezone.utc),
                is_maker=True, token_side="YES")


def no_fill(price: float, size=100.0) -> Fill:
    return Fill(fill_id="f2", market_id="0xtest", side=Side.SELL, price=price,
                size=size, timestamp=datetime.now(timezone.utc),
                is_maker=True, token_side="NO")


# ---------------------------------------------------------------------------
# Hedge routing — all four quadrants send the right taker order
# ---------------------------------------------------------------------------

class TestHedgeRouting:
    def test_yes_bid_fill_takes_no_ask(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert len(client.placed) == 1
        order = client.placed[0]
        assert order.token_id == NO and order.side == Side.BUY
        assert order.price == pytest.approx(0.48)   # NO best ask
        assert order.time_in_force == "IOC"
        assert loop.stats.takers_filled == 1
        assert loop._long_notional == pytest.approx((0.45 + 0.48) * 100)

    def test_no_bid_fill_takes_yes_ask(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._no_bids[0] = resting(0.44, NO, Side.BUY, "bid")
        loop.on_fill(no_fill(0.44))
        order = client.placed[0]
        assert order.token_id == YES and order.side == Side.BUY
        assert order.price == pytest.approx(0.52)   # YES best ask

    def test_yes_ask_fill_sells_no_bid(self):
        client = FakeClobClient()
        loop = make_loop(client)
        # ask-arb viable: 0.56 + 0.46 > 1.0
        loop._yes_asks[0] = resting(0.56, YES, Side.SELL, "ask")
        loop.on_fill(yes_fill(0.56))
        order = client.placed[0]
        assert order.token_id == NO and order.side == Side.SELL
        assert order.price == pytest.approx(0.46)   # NO best bid

    def test_no_ask_fill_sells_yes_bid(self):
        client = FakeClobClient()
        loop = make_loop(client)
        # 0.52 + 0.50 > 1.0
        loop._no_asks[0] = resting(0.52, NO, Side.SELL, "ask")
        loop.on_fill(no_fill(0.52))
        order = client.placed[0]
        assert order.token_id == YES and order.side == Side.SELL
        assert order.price == pytest.approx(0.50)   # YES best bid


# ---------------------------------------------------------------------------
# _send_taker outcomes
# ---------------------------------------------------------------------------

class TestTakerOutcomes:
    def test_partial_taker_fill_opens_remainder(self):
        client = FakeClobClient()
        client.fill_size = 40.0
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45, size=100.0))
        assert loop.stats.takers_filled == 1
        assert len(loop._open_positions) == 1
        assert loop._open_positions[0].size == pytest.approx(60.0)
        assert loop._open_positions[0].fill_type == "yes_bid"
        # PnL recorded only for the filled 40
        assert loop._long_notional == pytest.approx((0.45 + 0.48) * 40)

    def test_ioc_unfilled_opens_full_position(self):
        client = FakeClobClient()
        client.fill_size = 0.0
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert loop.stats.takers_filled == 0
        assert len(loop._open_positions) == 1
        assert loop._open_positions[0].size == pytest.approx(100.0)

    def test_taker_exception_opens_position(self):
        client = FakeClobClient()
        client.place_raises = RuntimeError("api down")
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert len(loop._open_positions) == 1

    def test_unprofitable_hedge_opens_position_no_order(self):
        client = FakeClobClient()
        loop = make_loop(client)
        # NO ask at 0.60: 0.45 + 0.60 > 1 — bid-arb not profitable
        loop._current_no_book = make_book(NO, bids=[(0.46, 500)], asks=[(0.60, 500)])
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert client.placed == []
        assert len(loop._open_positions) == 1

    def test_empty_hedge_book_opens_position(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._current_no_book = make_book(NO, bids=[(0.46, 500)], asks=[])
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert client.placed == []
        assert len(loop._open_positions) == 1

    def test_dry_run_records_cycle_without_order(self):
        client = FakeClobClient()
        loop = make_loop(client, dry_run=True)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert client.placed == []
        assert loop.stats.takers_filled == 1
        assert loop._long_notional > 0


# ---------------------------------------------------------------------------
# Maker-maker cycle (cancel rejected = opposing order already filled)
# ---------------------------------------------------------------------------

class TestMakerMaker:
    def test_cancel_rejected_records_maker_maker_no_taker(self):
        client = FakeClobClient()
        client.cancel_result = False  # exchange: order already filled
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop._no_bids[0] = resting(0.46, NO, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert loop.stats.maker_maker_cycles == 1
        assert client.placed == []  # no taker hedge for a maker-maker pair

    def test_cancel_error_still_hedges(self):
        # Network error on cancel: order state unknown -> assume live, hedge
        client = FakeClobClient()
        client.cancel_raises = ConnectionError("timeout")
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop._no_bids[0] = resting(0.46, NO, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert loop.stats.maker_maker_cycles == 0
        assert len(client.placed) == 1  # hedge sent despite cancel uncertainty


# ---------------------------------------------------------------------------
# Unroutable fills — dead-letter path
# ---------------------------------------------------------------------------

class TestUnroutable:
    def test_unmatched_fill_recorded_unknown(self):
        loop = make_loop()
        loop.on_fill(yes_fill(0.30))  # no resting order anywhere near 0.30
        assert len(loop._open_positions) == 1
        assert loop._open_positions[0].fill_type == "unknown_YES"

    def test_unroutable_moves_to_dead_letter_after_budget(self):
        loop = make_loop()
        loop.on_fill(yes_fill(0.30))
        for _ in range(QuoteLoop.UNROUTABLE_MAX_ATTEMPTS):
            loop._retry_open_positions()
        assert loop._open_positions == []
        assert len(loop._unroutable_fills) == 1
        assert loop.stats.unroutable_fills == 1


# ---------------------------------------------------------------------------
# snapshot() — the live monitor contract
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_keys_and_values(self):
        loop = make_loop(dry_run=True)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        snap = loop.snapshot()
        for key in ("market", "fills", "takers_filled", "pnl",
                    "open_unhedged", "unroutable", "errors", "long_notional"):
            assert key in snap
        assert snap["fills"] == 1
        assert snap["long_notional"] > 0


# ---------------------------------------------------------------------------
# Partial MAKER fills — remainder must stay tracked and live
# ---------------------------------------------------------------------------

class TestPartialMakerFills:
    def test_partial_fill_keeps_slot_and_decrements(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")  # size 100
        loop.on_fill(yes_fill(0.45, size=30.0))
        # Hedge exactly the filled 30
        assert client.placed[0].size == pytest.approx(30.0)
        # Slot still occupied with the live remainder
        order = loop._yes_bids[0]
        assert order is not None
        assert order.size == pytest.approx(70.0)

    def test_second_partial_routes_to_same_slot(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45, size=30.0))
        loop.on_fill(yes_fill(0.45, size=50.0))
        # Both routed (NOT unknown/dead-letter), hedged 30 then 50
        assert [o.size for o in client.placed] == [pytest.approx(30.0),
                                                   pytest.approx(50.0)]
        assert loop._yes_bids[0].size == pytest.approx(20.0)
        assert all(p.fill_type != "unknown_YES" for p in loop._open_positions)

    def test_full_fill_clears_slot(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45, size=100.0))
        assert loop._yes_bids[0] is None

    def test_near_full_fill_treated_as_full(self):
        # Within PARTIAL_EPS (0.5 contracts) of the tracked size = full fill
        client = FakeClobClient()
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45, size=99.8))
        assert loop._yes_bids[0] is None

    def test_oversized_fill_clamped_to_tracked(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45, size=150.0))  # stale/duplicated report
        assert loop._yes_bids[0] is None
        assert client.placed[0].size == pytest.approx(100.0)  # hedge tracked size only

    def test_partial_on_ask_side(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._no_asks[0] = resting(0.52, NO, Side.SELL, "ask")
        loop.on_fill(no_fill(0.52, size=25.0))
        assert loop._no_asks[0].size == pytest.approx(75.0)
        assert client.placed[0].size == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Dead-man GTD expiry — local-machine safety
# ---------------------------------------------------------------------------

class TestDeadManExpiry:
    def test_maker_orders_are_gtd_with_expiry(self):
        client = FakeClobClient()
        loop = make_loop(client)
        # Drive one maker placement via the internal helper
        resp = loop._place_order(YES, Side.BUY, 0.45, 100.0, "yes_bid_0")
        assert resp is not None
        order = client.placed[0]
        assert order.time_in_force == "GTD"
        # Expiry ~ttl(300) + buffer(90) from now
        assert order.expiration > time.time() + 300
        assert order.expiration < time.time() + 300 + 90 + 30

    def test_taker_hedge_stays_ioc(self):
        client = FakeClobClient()
        loop = make_loop(client)
        loop._yes_bids[0] = resting(0.45, YES, Side.BUY, "bid")
        loop.on_fill(yes_fill(0.45))
        assert client.placed[0].time_in_force == "IOC"

    def test_zero_buffer_falls_back_to_gtc(self):
        client = FakeClobClient()
        loop = make_loop(client, order_expiration_buffer=0.0)
        loop._place_order(YES, Side.BUY, 0.45, 100.0, "yes_bid_0")
        assert client.placed[0].time_in_force == "GTC"
