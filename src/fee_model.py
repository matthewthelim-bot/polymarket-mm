"""
FeeModel — single source of truth for all Polymarket fee and rebate calculations.

All other components (HedgeabilityAssessor, QuoteEngine, PnLEngine, Simulator)
import this module. No fee logic lives anywhere else.

Polymarket fee formulas (as of 2026-05):
  Standard:  fee = size * fee_rate * p * (1 - p)
  Sports:    fee = size * fee_rate * p^2 * (1 - p)   [peaks at p=2/3]
  Rebate:    rebate = rebate_fraction * fee_rate * p * (1 - p) * size
"""

import math


class FeeModel:
    """Stateless fee calculator. Instantiate once per market with its fee_rate."""

    def taker_fee(
        self,
        size: float,
        price: float,
        fee_rate: float,
        exponent: int = 1,
        sports: bool = False,
    ) -> float:
        """
        Taker fee for a fill of `size` contracts at `price`.

        Standard formula:  size * fee_rate * price * (1 - price)
        Sports formula:    size * fee_rate * price^2 * (1 - price)
            equivalently:  size * price * fee_rate * (price * (1 - price))^exponent
            with exponent=1, which peaks at p=2/3 not p=0.5.
        """
        if sports:
            return size * price * fee_rate * (price * (1 - price)) ** exponent
        return size * fee_rate * price * (1 - price)

    def maker_rebate(
        self,
        size: float,
        price: float,
        fee_rate: float,
        rebate_fraction: float,
    ) -> float:
        """
        Maker rebate for a passive fill of `size` contracts at `price`.

        rebate = rebate_fraction * fee_rate * price * (1 - price) * size
        """
        fee_equiv = size * fee_rate * price * (1 - price)
        return rebate_fraction * fee_equiv

    def fee_flatten_expected(
        self,
        fv: float,
        fee_rate: float,
        exponent: int = 1,
        sports: bool = False,
    ) -> float:
        """
        Expected taker fee per contract when flattening at fair value.
        Used by QuoteEngine to compute minimum half-spread. Returns fee per contract (size=1).
        """
        return self.taker_fee(
            size=1, price=fv, fee_rate=fee_rate, exponent=exponent, sports=sports
        )

    def max_flatten_price(
        self,
        p_fill: float,
        fee_rate: float,
        rebate_fraction: float,
        min_edge_floor: float,
    ) -> float:
        """
        Maximum price at which flattening the opposing side still yields
        net positive edge (after fees and rebate), given a passive fill at p_fill.

        Breakeven condition:
            (1 - p_fill - p_flatten) + rebate - taker_fee(p_flatten) - min_edge_floor >= 0

        Substituting taker_fee = fee_rate * p * (1 - p):
            fee_rate * p^2 - (1 + fee_rate) * p + LHS = 0
        where:
            rebate = rebate_fraction * fee_rate * p_fill * (1 - p_fill)
            LHS    = 1 - p_fill + rebate - min_edge_floor

        Returns 0.0 if discriminant < 0 (no valid price exists).
        """
        rebate = rebate_fraction * fee_rate * p_fill * (1 - p_fill)
        lhs = 1 - p_fill + rebate - min_edge_floor

        a = fee_rate
        b = -(1 + fee_rate)
        c = lhs

        discriminant = b ** 2 - 4 * a * c
        if discriminant < 0:
            return 0.0

        p_max = (-b - math.sqrt(discriminant)) / (2 * a)
        return max(0.0, min(1.0, p_max))
