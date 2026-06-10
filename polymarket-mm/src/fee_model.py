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

        Standard formula (sports=False):  size * fee_rate * price * (1 - price)
          Note: `exponent` is ignored when sports=False. All current Polymarket
          non-sports categories use the standard formula regardless of exponent.

        Sports formula (sports=True):  size * price * fee_rate * (price * (1 - price))^exponent
          With exponent=1, this equals size * fee_rate * price^2 * (1-price),
          which peaks at p=2/3, not p=0.5 like the standard formula.

        Args:
            size: number of contracts
            price: fill price in [0, 1]
            fee_rate: category fee rate (Crypto=0.07, Finance/Politics=0.04, Sports=0.03)
            exponent: only used when sports=True; 1 for all current Polymarket categories
            sports: if True, use sports variant p^2*(1-p)
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

        Note: always uses the standard (non-sports) fee formula for the flatten leg,
        regardless of what formula was used on the fill side.

        The `discriminant < 0` guard is defensive for out-of-range inputs; in practice
        with valid Polymarket prices the clamp `max(0.0, ...)` is what triggers for
        impossible cases (the lower quadratic root goes negative before the discriminant
        does).
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

    def min_flatten_price_for_sell(
        self,
        p_fill: float,
        fee_rate: float,
        rebate_fraction: float,
        min_edge_floor: float,
    ) -> float:
        """
        Minimum price at which SELLING the opposing side still yields net
        positive edge, given a passive sell fill at p_fill.

        This is the sell-side mirror of max_flatten_price and a different
        bound — reusing the buy ceiling as a sell floor counts loss-making
        bids as hedgeable (the gap between the two bounds is ~2*(fee+edge)).

        Breakeven condition (proceeds side):
            (p_fill + p_flatten - 1) + rebate - taker_fee(p_flatten) - min_edge_floor >= 0

        Substituting taker_fee = fee_rate * p * (1 - p):
            fee_rate * p^2 + (1 - fee_rate) * p + C >= 0
        where:
            rebate = rebate_fraction * fee_rate * p_fill * (1 - p_fill)
            C      = p_fill - 1 + rebate - min_edge_floor

        The parabola opens upward, so prices at or above the larger root are
        profitable. The result is intentionally NOT clamped to 1.0: a value
        above 1.0 means no valid book price can hedge profitably, and depth
        scans comparing `price >= threshold` then correctly find nothing.
        """
        rebate = rebate_fraction * fee_rate * p_fill * (1 - p_fill)
        c = p_fill - 1 + rebate - min_edge_floor

        if fee_rate <= 0:
            # Linear degenerate case: p + C >= 0
            return max(0.0, -c)

        a = fee_rate
        b = 1 - fee_rate

        discriminant = b ** 2 - 4 * a * c
        if discriminant < 0:
            # Quadratic never reaches zero from below — with a > 0 this means
            # always positive, i.e. any price hedges profitably.
            return 0.0

        p_min = (-b + math.sqrt(discriminant)) / (2 * a)
        return max(0.0, p_min)
