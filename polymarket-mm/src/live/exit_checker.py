"""
Exit viability checker — assesses real exit liquidity before quoting.

Before placing any bid we must verify that we can exit the position:
  - YES exit: sell YES contracts back into the YES bid side.
    We need bid depth at prices >= entry_price * (1 - max_loss_fraction).
  - NO exit (hedge): buy NO contracts at a price that keeps the trade profitable.
    We need ask depth at prices <= max_flatten_price (computed by FeeModel).

max_quotable_size = min(yes_exit_size, no_exit_size)

A trade is only viable when max_quotable_size >= min_viable_size.
"""

from __future__ import annotations
from dataclasses import dataclass

from src.data.schemas import OrderBook
from src.fee_model import FeeModel


@dataclass
class ExitViability:
    """
    Result of an exit liquidity check.

    Attributes:
        yes_exit_size: contracts we can sell back into the YES bid at acceptable loss.
        no_exit_size: contracts we can hedge by buying NO at a profitable flatten price.
        max_quotable_size: min(yes_exit_size, no_exit_size) — safe quote size.
        is_viable: True when max_quotable_size >= min_viable_size.
        yes_best_bid: current best YES bid price (0 if book is empty).
        no_best_ask: current best NO ask price (1 if book is empty).
        max_flatten_price: computed profitable flatten threshold for the NO side.
    """
    yes_exit_size: float
    no_exit_size: float
    max_quotable_size: float
    is_viable: bool
    yes_best_bid: float
    no_best_ask: float
    max_flatten_price: float


class ExitChecker:
    """
    Checks real exit liquidity using live L2 order books.

    Args:
        fee_model: Shared FeeModel instance.
        fee_rate: Taker fee rate (e.g. 0.07 for 7 bps).
        rebate_fraction: Maker rebate fraction (e.g. 0.5 = 50% rebate).
        min_edge_floor: Minimum edge required for a profitable flatten.
        max_loss_fraction: Maximum tolerable loss fraction for a YES exit
            (e.g. 0.10 = accept up to 10% loss to exit quickly).
        min_viable_size: Minimum contracts we need to be able to exit to
            consider the opportunity viable. Defaults to 1.0.
    """

    def __init__(
        self,
        fee_model: FeeModel,
        fee_rate: float,
        rebate_fraction: float,
        min_edge_floor: float = 0.005,
        max_loss_fraction: float = 0.10,
        min_viable_size: float = 1.0,
    ):
        self._fm = fee_model
        self._fee_rate = fee_rate
        self._rebate_fraction = rebate_fraction
        self._min_edge_floor = min_edge_floor
        self._max_loss_fraction = max_loss_fraction
        self._min_viable_size = min_viable_size

    def check(
        self,
        yes_book: OrderBook,
        no_book: OrderBook,
        entry_price: float,
        quote_size: float,
        own_yes_bid_sizes: dict[float, float] | None = None,
        own_no_ask_sizes: dict[float, float] | None = None,
    ) -> ExitViability:
        """
        Assess whether we can safely enter and exit a position of `quote_size`.

        Args:
            yes_book: Current live L2 book for the YES token.
            no_book: Current live L2 book for the NO token.
            entry_price: The bid price we intend to post (the fill price if hit).
            quote_size: The number of contracts we want to quote.
            own_yes_bid_sizes: Our own resting YES-bid size per price level
                (price rounded to 6 dp -> size). MUST be passed when we are
                actively quoting this market — our own bids are not exit
                liquidity, and a market whose only "exit depth" is our own
                order must fail this check. Scanners running before any
                orders exist may omit.
            own_no_ask_sizes: Same for our resting NO asks.

        Returns:
            ExitViability with sizes we can actually exit and whether it's viable.
        """
        own_yes = own_yes_bid_sizes or {}
        own_no = own_no_ask_sizes or {}

        # --- YES exit: sell back into YES bid side ---
        # We accept bids at prices >= entry_price * (1 - max_loss_fraction)
        yes_min_price = entry_price * (1.0 - self._max_loss_fraction)
        yes_exit_size = sum(
            max(0.0, lvl.size - own_yes.get(round(lvl.price, 6), 0.0))
            for lvl in yes_book.bids
            if lvl.price >= yes_min_price
        )
        yes_exit_size = min(yes_exit_size, quote_size)
        yes_best_bid = yes_book.bids[0].price if yes_book.bids else 0.0

        # --- NO exit (hedge): buy NO ask side at profitable flatten price ---
        # max_flatten_price = the highest NO price we can pay and still profit.
        # Equivalent to: the max ask price where spread_pnl > 0 after fees.
        max_flatten_price = self._fm.max_flatten_price(
            p_fill=entry_price,
            fee_rate=self._fee_rate,
            rebate_fraction=self._rebate_fraction,
            min_edge_floor=self._min_edge_floor,
        )
        no_exit_size = sum(
            max(0.0, lvl.size - own_no.get(round(lvl.price, 6), 0.0))
            for lvl in no_book.asks
            if lvl.price <= max_flatten_price
        )
        no_exit_size = min(no_exit_size, quote_size)
        no_best_ask = no_book.asks[0].price if no_book.asks else 1.0

        max_quotable = min(yes_exit_size, no_exit_size)
        is_viable = max_quotable >= self._min_viable_size

        return ExitViability(
            yes_exit_size=yes_exit_size,
            no_exit_size=no_exit_size,
            max_quotable_size=max_quotable,
            is_viable=is_viable,
            yes_best_bid=yes_best_bid,
            no_best_ask=no_best_ask,
            max_flatten_price=max_flatten_price,
        )

    def check_depth_summary(
        self,
        yes_book: OrderBook,
        no_book: OrderBook,
        entry_price: float,
        quote_size: float,
    ) -> str:
        """
        Human-readable summary of exit liquidity for diagnostics.
        """
        v = self.check(yes_book, no_book, entry_price, quote_size)
        viable_str = "VIABLE" if v.is_viable else "NOT VIABLE"
        return (
            f"{viable_str} | "
            f"YES exit: {v.yes_exit_size:.0f} (best bid {v.yes_best_bid:.3f}) | "
            f"NO exit:  {v.no_exit_size:.0f} (best ask {v.no_best_ask:.3f}, "
            f"max flatten {v.max_flatten_price:.3f}) | "
            f"max quotable: {v.max_quotable_size:.0f}"
        )
