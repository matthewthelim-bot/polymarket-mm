"""
InventoryManager — two-bucket inventory tracking.

Bucket 1: hedgeable_contracts — positions with opposing depth available at fill time
Bucket 2: skew_contracts      — positions accepted without hedge (operator-allowed skew)

Capital charges:
  hedgeable: price * size * daily_rate * 1x
  skew:      price * size * daily_rate * skew_multiplier (default 3x)
"""

from __future__ import annotations
from src.data.schemas import Fill, InventoryState


class InventoryManager:
    """
    Mutable per-market inventory tracker.

    All fills are in "Yes contracts" for simplicity.
    Flatten fills reduce inventory starting from the hedgeable bucket.
    """

    def __init__(self, market_id: str, daily_capital_charge_rate: float = 0.0003):
        self.market_id = market_id
        self.daily_capital_charge_rate = daily_capital_charge_rate
        self._hedgeable: float = 0.0
        self._skew: float = 0.0
        self._total_notional: float = 0.0     # for avg price tracking
        self._total_contracts_held: float = 0.0  # current open contracts denominator

    def add_fill(self, fill: Fill, is_skew: bool) -> None:
        """Record a passive fill into the appropriate bucket."""
        if is_skew:
            self._skew += fill.size
        else:
            self._hedgeable += fill.size
        self._total_notional += fill.price * fill.size
        self._total_contracts_held += fill.size

    def add_flatten(self, size: float, price: float) -> None:
        """Record a flatten (taker) fill. Reduces hedgeable first, then skew."""
        remaining = size

        hedge_reduction = min(remaining, self._hedgeable)
        self._hedgeable -= hedge_reduction
        remaining -= hedge_reduction

        skew_reduction = min(remaining, self._skew)
        self._skew -= skew_reduction
        remaining -= skew_reduction

        # Reduce avg-price denominator by contracts actually closed
        contracts_closed = size - remaining
        if self._total_contracts_held > 0 and contracts_closed > 0:
            # Remove notional proportional to fraction closed
            fraction_closed = contracts_closed / self._total_contracts_held
            self._total_notional -= self._total_notional * fraction_closed
            self._total_contracts_held -= contracts_closed

    def state(self) -> InventoryState:
        avg_price = (
            self._total_notional / self._total_contracts_held
            if self._total_contracts_held > 0
            else 0.0
        )
        return InventoryState(
            market_id=self.market_id,
            hedgeable_contracts=self._hedgeable,
            skew_contracts=self._skew,
            avg_fill_price=avg_price,
        )

    def daily_capital_charge(self, skew_multiplier: float = 3.0) -> float:
        """Total daily capital charge across both buckets."""
        state = self.state()
        hedge_charge = (
            state.hedgeable_contracts
            * state.avg_fill_price
            * self.daily_capital_charge_rate
        )
        skew_charge = (
            state.skew_contracts
            * state.avg_fill_price
            * self.daily_capital_charge_rate
            * skew_multiplier
        )
        return hedge_charge + skew_charge
