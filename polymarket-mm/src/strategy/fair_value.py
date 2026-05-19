"""
FairValueEstimator — estimates the true probability of a binary market resolving Yes.

Design constraints:
- Never anchors to quoted mid or best bid/ask.
- Blends volume-weighted trade TWAP with optional external signals.
- Returns None when insufficient data exists (forces strategy to widen/suspend).
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TradeObservation:
    price: float
    size: float
    timestamp: datetime


@dataclass
class ExternalSignal:
    source: str        # e.g. "metaculus", "manifold", "base_rate"
    probability: float
    timestamp: datetime


class FairValueEstimator:
    """
    Estimates fair value as a weighted blend of:
      - Volume-weighted TWAP over a rolling window of trades
      - Simple average of external signals (Metaculus, Manifold, base rates)

    Args:
        twap_window_seconds: rolling window for trade TWAP
        external_weight: weight on external signals [0, 1]; remainder goes to TWAP
    """

    def __init__(self, twap_window_seconds: int = 300, external_weight: float = 0.0):
        self.twap_window_seconds = twap_window_seconds
        self.external_weight = external_weight
        self._trades: list[TradeObservation] = []
        self._signals: list[ExternalSignal] = []

    def on_trade(self, trade: TradeObservation) -> None:
        self._trades.append(trade)

    def on_external_signal(self, signal: ExternalSignal) -> None:
        self._signals.append(signal)

    def estimate(self, as_of: datetime) -> Optional[float]:
        """
        Returns fair value estimate in [0, 1], or None if insufficient data.

        Never reads from the order book. The caller must not pass book/mid.
        """
        twap = self._compute_twap(as_of)
        if twap is None:
            return None

        if self.external_weight == 0.0 or not self._signals:
            return twap

        external_avg = sum(s.probability for s in self._signals) / len(self._signals)
        return (1 - self.external_weight) * twap + self.external_weight * external_avg

    def _compute_twap(self, as_of: datetime) -> Optional[float]:
        cutoff = as_of.timestamp() - self.twap_window_seconds
        recent = [t for t in self._trades if t.timestamp.timestamp() >= cutoff]
        if not recent:
            return None
        total_size = sum(t.size for t in recent)
        if total_size == 0:
            return None
        return sum(t.price * t.size for t in recent) / total_size
