"""
HedgeabilityAssessor — evaluates whether a passive fill can be profitably hedged.

For a Yes buy at p_fill, the hedge is a No buy (taker) at p_flatten.
The fill is risk-free if p_fill + p_flatten < 1 (net of fees).
max_flatten_price is the maximum acceptable No ask price, computed by FeeModel.

Own orders are stripped from opposing book depth before assessment.
"""

from __future__ import annotations
from dataclasses import dataclass
from src.fee_model import FeeModel
from src.data.schemas import OrderBook, Side


@dataclass
class SkewConfig:
    skew_tolerance: float              # max unhedgeable contracts to accept
    skew_edge_premium: float           # extra edge required on top of min_edge_floor
    skew_hard_limit: int               # absolute max skew contracts (circuit breaker)
    skew_capital_charge_multiplier: float  # 3.0x capital charge vs hedgeable
    max_skew_notional: float           # USDC notional cap on skew bucket
    current_skew_notional: float       # current skew notional already held


@dataclass
class HedgeabilityResult:
    hedgeable_size: float      # contracts that can be hedged within max_flatten_price
    unhedgeable_size: float    # contracts with no opposing depth / price too high
    skew_accepted: float       # unhedgeable contracts accepted as skew
    skew_rejected: float       # unhedgeable contracts that would be rejected
    max_flatten_price: float   # computed ceiling for flatten leg price


class HedgeabilityAssessor:
    """
    Args:
        fee_model: shared FeeModel instance
        fee_rate: market's fee_rate from MarketMetadata
        rebate_fraction: market's rebate_fraction from MarketMetadata
        min_edge_floor: minimum net edge required (from config)
    """

    def __init__(
        self,
        fee_model: FeeModel,
        fee_rate: float,
        rebate_fraction: float,
        min_edge_floor: float = 0.005,
    ):
        self.fee_model = fee_model
        self.fee_rate = fee_rate
        self.rebate_fraction = rebate_fraction
        self.min_edge_floor = min_edge_floor

    def assess(
        self,
        quote_side: Side,
        quote_price: float,
        quote_size: float,
        book: OrderBook,
        own_order_ids: set[str],
        skew_config: SkewConfig,
        own_order_sizes: dict[str, float] | None = None,
    ) -> HedgeabilityResult:
        """
        Assess hedgeability of a passive fill at quote_price for quote_size contracts.

        quote_side=BUY  → we bought Yes; hedge by buying No (check ask side)
        quote_side=SELL → we sold Yes; hedge by selling No (check bid side)
        """
        p_max = self.fee_model.max_flatten_price(
            p_fill=quote_price,
            fee_rate=self.fee_rate,
            rebate_fraction=self.rebate_fraction,
            min_edge_floor=self.min_edge_floor,
        )

        net_depth = self._net_opposing_depth(
            book=book,
            own_order_ids=own_order_ids,
            own_order_sizes=own_order_sizes or {},
            max_price=p_max,
            side=quote_side,
        )

        hedgeable = min(quote_size, net_depth)
        unhedgeable = quote_size - hedgeable

        skew_accepted, skew_rejected = self._evaluate_skew(
            unhedgeable_size=unhedgeable,
            quote_price=quote_price,
            skew_config=skew_config,
        )

        return HedgeabilityResult(
            hedgeable_size=hedgeable,
            unhedgeable_size=unhedgeable,
            skew_accepted=skew_accepted,
            skew_rejected=skew_rejected,
            max_flatten_price=p_max,
        )

    def _net_opposing_depth(
        self,
        book: OrderBook,
        own_order_ids: set[str],
        own_order_sizes: dict[str, float],
        max_price: float,
        side: Side,
    ) -> float:
        """Sum opposing-side depth at prices <= max_price, stripping own orders."""
        # For a BUY fill, we look at asks (we'll taker-buy the opposing side)
        levels = book.asks if side == Side.BUY else book.bids
        total = 0.0
        for level in levels:
            if side == Side.BUY and level.price > max_price:
                break  # asks sorted ascending; stop when too expensive
            if side == Side.SELL and level.price < max_price:
                break  # bids sorted descending; stop when too cheap
            own_at_level = sum(
                own_order_sizes.get(oid, 0.0) for oid in own_order_ids
            )
            net = max(0.0, level.size - own_at_level)
            total += net
        return total

    def _evaluate_skew(
        self,
        unhedgeable_size: float,
        quote_price: float,
        skew_config: SkewConfig,
    ) -> tuple[float, float]:
        if unhedgeable_size <= 0:
            return 0.0, 0.0

        if skew_config.skew_tolerance <= 0:
            return 0.0, unhedgeable_size

        # Notional room remaining
        notional_room = skew_config.max_skew_notional - skew_config.current_skew_notional
        if notional_room <= 0:
            return 0.0, unhedgeable_size

        max_by_notional = notional_room / quote_price if quote_price > 0 else 0.0
        max_by_tolerance = skew_config.skew_tolerance
        max_acceptable = min(max_by_notional, max_by_tolerance)

        accepted = min(unhedgeable_size, max_acceptable)
        rejected = unhedgeable_size - accepted
        return accepted, rejected
