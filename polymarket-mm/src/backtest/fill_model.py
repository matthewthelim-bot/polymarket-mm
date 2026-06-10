"""
Fill models for backtesting.

QueueModel.FRONT      — optimistic: we're at front of queue, fill up to trade size
QueueModel.PRO_RATA   — our fill = (our_size / book_size_at_price) * trade_size
QueueModel.BACK       — pessimistic: only fill if book at our price is fully cleared
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class QueueModel(Enum):
    FRONT = "FRONT"
    PRO_RATA = "PRO_RATA"
    BACK = "BACK"


@dataclass
class FillModelConfig:
    queue_model: QueueModel = QueueModel.FRONT
    latency_ms: int = 50


@dataclass
class FillModelInput:
    quote_price: float
    quote_size: float
    market_trade_price: float
    market_trade_size: float
    book_size_at_price: float   # total book depth at our quote price

    def __post_init__(self):
        if self.quote_size < 0:
            raise ValueError(f"quote_size must be >= 0, got {self.quote_size}")
        if self.market_trade_size < 0:
            raise ValueError(f"market_trade_size must be >= 0, got {self.market_trade_size}")
        if self.book_size_at_price < 0:
            raise ValueError(f"book_size_at_price must be >= 0, got {self.book_size_at_price}")


@dataclass
class FillModelResult:
    filled_size: float
    fill_price: float
    latency_ms: int


class FillModel:

    def __init__(self, config: FillModelConfig):
        self.config = config

    def simulate_fill(self, inp: FillModelInput) -> FillModelResult:
        """
        Given a market trade event, compute how much of our resting BID gets filled.

        A passive bid at price B is filled when a market sell arrives at price P ≤ B —
        i.e. the market came down to our level or below.  Exact-price matching is wrong
        here because the market maker posts *below* the current mid and waits.

        Returns filled_size=0 if the trade price is above our bid.
        """
        # Fill only when the market trades at or below our bid
        if inp.market_trade_price > inp.quote_price + 1e-9:
            return FillModelResult(filled_size=0.0, fill_price=inp.quote_price,
                                   latency_ms=self.config.latency_ms)

        filled = self._compute_fill(inp)
        return FillModelResult(
            filled_size=min(filled, inp.quote_size),
            fill_price=inp.quote_price,
            latency_ms=self.config.latency_ms,
        )

    def _compute_fill(self, inp: FillModelInput) -> float:
        model = self.config.queue_model

        if model == QueueModel.FRONT:
            return min(inp.market_trade_size, inp.quote_size)

        elif model == QueueModel.PRO_RATA:
            # book_size_at_price is the RECORDED depth at our price and cannot
            # include our own simulated order — our quote must join the
            # denominator or our share is overstated (and exceeds 1 whenever
            # our size >= displayed book). Correct: ours / (book + ours).
            total_at_price = inp.book_size_at_price + inp.quote_size
            if total_at_price <= 0:
                return 0.0
            share = inp.quote_size / total_at_price
            return share * inp.market_trade_size

        elif model == QueueModel.BACK:
            # Our simulated order rests BEHIND the recorded book: the trade
            # must clear the displayed depth before any contracts reach us.
            if inp.market_trade_size >= inp.book_size_at_price:
                return min(inp.quote_size,
                           inp.market_trade_size - inp.book_size_at_price)
            return 0.0

        raise ValueError(f"Unknown QueueModel: {model}")
