"""
QuoteEngine — computes bid/ask prices and sizes.

Half-spread = max(half_spread_base, fee_flatten_expected(FV) + min_edge_floor) + AS_buffer
Spread widens with regime severity and skew acceptance.
"""

from __future__ import annotations
from dataclasses import dataclass
from src.fee_model import FeeModel
from src.data.schemas import Regime, QuoteDecision
from src.strategy.hedgeability import HedgeabilityResult

# Regime spread multipliers (SUSPENDED/SETTLED return suspend=True, no quote)
_REGIME_MULTIPLIERS = {
    Regime.QUOTE_ACTIVE: 1.0,
    Regime.ONE_SIDE_FILLED: 1.0,
    Regime.INVENTORY_REDUCED: 1.5,
    Regime.INVENTORY_WAREHOUSE: 2.5,
    Regime.HEDGE_PENDING: 3.0,
    Regime.SUSPENDED: 0.0,
    Regime.SETTLED: 0.0,
}

_SKEW_EDGE_PREMIUM = 0.005   # additional half-spread when accepting skew


@dataclass
class QuoteInput:
    fv: float
    regime: Regime
    hedgeability: HedgeabilityResult
    adverse_selection: float
    quote_size: float


class QuoteEngine:
    """
    Args:
        fee_model: shared FeeModel instance
        fee_rate: market fee_rate
        rebate_fraction: market rebate_fraction
        half_spread_base: minimum half-spread from config
        min_edge_floor: minimum net edge floor (same value as in FeeModel calls)
    """

    def __init__(
        self,
        fee_model: FeeModel,
        fee_rate: float,
        rebate_fraction: float,
        half_spread_base: float = 0.015,
        min_edge_floor: float = 0.005,
    ):
        self.fee_model = fee_model
        self.fee_rate = fee_rate
        self.rebate_fraction = rebate_fraction
        self.half_spread_base = half_spread_base
        self.min_edge_floor = min_edge_floor

    def compute(self, inp: QuoteInput) -> QuoteDecision:
        multiplier = _REGIME_MULTIPLIERS.get(inp.regime, 1.0)

        if multiplier == 0.0:
            return QuoteDecision(
                bid_price=0.0, ask_price=1.0,
                bid_size=0.0, ask_size=0.0,
                regime=inp.regime, suspend=True,
                reason=f"regime={inp.regime.value}",
            )

        # Minimum half-spread to cover flatten fee + edge floor
        fee_cost = self.fee_model.fee_flatten_expected(
            fv=inp.fv, fee_rate=self.fee_rate
        )
        half_spread = max(self.half_spread_base, fee_cost + self.min_edge_floor)
        half_spread += inp.adverse_selection * 0.5   # buffer for AS
        half_spread *= multiplier

        # Extra premium when accepting skew
        skew_premium = _SKEW_EDGE_PREMIUM if inp.hedgeability.skew_accepted > 0 else 0.0

        bid_price = inp.fv - half_spread - skew_premium
        ask_price = inp.fv + half_spread

        # Clamp to valid range and round to cent
        bid_price = max(0.01, round(bid_price, 2))
        ask_price = min(0.99, round(ask_price, 2))

        # Size logic by regime
        if inp.regime == Regime.ONE_SIDE_FILLED:
            bid_size = 0.0           # don't add inventory; only quote flatten leg
            ask_size = inp.quote_size
        elif inp.hedgeability.hedgeable_size == 0 and inp.hedgeability.skew_accepted == 0:
            bid_size = 0.0           # no hedge available and skew not accepted
            ask_size = inp.quote_size
        else:
            bid_size = min(
                inp.quote_size,
                inp.hedgeability.hedgeable_size + inp.hedgeability.skew_accepted
            )
            ask_size = inp.quote_size

        return QuoteDecision(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
            regime=inp.regime,
            suspend=False,
        )
