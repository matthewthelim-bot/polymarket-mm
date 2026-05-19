"""
AdverseSelectionTracker — measures post-fill price movement.

After each fill (Yes buy), watches for the first trade that arrives
after `window_seconds`. If price fell by more than `adverse_threshold`,
the fill is classified as adverse.

Output of `estimate()` is the rolling average adverse magnitude in
price units (e.g. 0.02 = 2 cents), directly comparable to
`RegimeClassifier.adverse_selection_threshold` (default 0.012).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class _ASEvent:
    fill_price: float
    fill_timestamp: datetime
    observed_price: Optional[float] = None
    is_adverse: bool = False


class AdverseSelectionTracker:
    """
    Tracks adverse selection magnitude for Yes-buy fills.

    Args:
        window_seconds: seconds to wait before measuring post-fill drift
        adverse_threshold: minimum drop to count as adverse (noise filter)
        rolling_n: number of recent fills to include in estimate
    """

    def __init__(
        self,
        window_seconds: float = 300.0,
        adverse_threshold: float = 0.005,
        rolling_n: int = 20,
    ):
        self.window_seconds = window_seconds
        self.adverse_threshold = adverse_threshold
        self.rolling_n = rolling_n
        self._pending: list[_ASEvent] = []
        self._completed: list[_ASEvent] = []

    def on_fill(self, price: float, timestamp: datetime) -> None:
        """Record a Yes buy fill at `price`."""
        self._pending.append(_ASEvent(fill_price=price, fill_timestamp=timestamp))

    def on_trade(self, price: float, timestamp: datetime) -> None:
        """
        Advance pending fills. Any fill whose window has elapsed is
        measured against `price` and moved to completed.
        """
        now_ts = timestamp.timestamp()
        still_pending: list[_ASEvent] = []
        for ev in self._pending:
            elapsed = now_ts - ev.fill_timestamp.timestamp()
            if elapsed >= self.window_seconds:
                drop = ev.fill_price - price        # positive = adverse
                ev.observed_price = price
                ev.is_adverse = drop > self.adverse_threshold
                self._completed.append(ev)
            else:
                still_pending.append(ev)
        self._pending = still_pending

    def estimate(self) -> float:
        """
        Rolling average adverse magnitude over the last `rolling_n` measured fills.
        Returns 0.0 when no adverse fills are in the window.
        """
        recent = self._completed[-self.rolling_n:]
        adverse = [ev for ev in recent if ev.is_adverse]
        if not adverse:
            return 0.0
        return sum(ev.fill_price - ev.observed_price for ev in adverse) / len(adverse)

    def stats(self) -> dict:
        """Summary statistics for reporting."""
        recent = self._completed[-self.rolling_n:]
        adverse = [ev for ev in recent if ev.is_adverse]
        avg_mag = (
            sum(ev.fill_price - ev.observed_price for ev in adverse) / len(adverse)
            if adverse else 0.0
        )
        return {
            "num_measured": len(self._completed),
            "num_adverse": len([ev for ev in self._completed if ev.is_adverse]),
            "as_rate": len(adverse) / len(recent) if recent else 0.0,
            "avg_magnitude": avg_mag,
        }
