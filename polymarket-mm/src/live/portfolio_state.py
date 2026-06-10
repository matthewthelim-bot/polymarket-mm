"""PortfolioConstraints — shared thread-safe portfolio-level risk caps.

Passed to all QuoteLoops and BacktestSimulators so cross-market caps are
enforced consistently across all active positions.

Three constraints (each independently disableable via 0):

  1. Long-term cap: at most `max_long_term_fraction` of `total_capital` may be
     locked in positions whose market resolves more than `long_term_threshold_days`
     days from now.  Example: 80 % of $10,000 = $8,000 max in >30-day positions.

  2. Per-event cap: at most `max_event_notional` USDC notional may be accumulated
     across all sub-markets that share the same `event_key` (the Gamma event ID).
     Set to 0 to disable — useful when per-market cap is sufficient.

  3. Per-market cap: at most `max_market_notional` USDC notional per individual
     market.  Prevents over-concentration in any single binary question.
     Set to 0 to disable.

Thread-safe: all state mutations are protected by an internal RLock.
Both QuoteLoop (multithreaded) and BacktestSimulator (single-threaded) use the
same object — the lock is cheap when uncontested.

Usage:
    portfolio = PortfolioConstraints(total_capital=10_000.0,
                                     max_market_notional=2_000.0)

    notional = (yes_price + no_price) * size  # both legs

    if portfolio.can_open(event_key="23784", market_id="0xabc...",
                          notional=notional, days_to_resolution=65):
        portfolio.open_position("23784", "0xabc...", notional, 65)
        ...
        portfolio.close_position("23784", "0xabc...", notional, 65)
"""

from __future__ import annotations
import threading
from dataclasses import dataclass, field


@dataclass
class PortfolioConstraints:
    """Shared cross-market portfolio-level position constraints."""

    total_capital: float = 10_000.0
    # Fraction of total_capital that may be in positions resolving beyond
    # long_term_threshold_days.  This is a liquidity guard: capital locked in
    # long-dated positions can't be recycled into fast-resolving markets,
    # which carry more volume/volatility and recycle in hours-to-days.
    # 0.30 = 30 % = $3,000 on a $10 k account.
    max_long_term_fraction: float = 0.30
    # Absolute USDC cap per Gamma event group.  0 = disabled.
    max_event_notional: float = 0.0
    # Absolute USDC cap per individual market.  0 = disabled.
    max_market_notional: float = 2_000.0
    # Positions resolving further than this many days out count as "long-term".
    long_term_threshold_days: int = 30

    # --- internal mutable state (lock-protected) ---
    _lock: threading.RLock = field(
        default_factory=threading.RLock, compare=False, repr=False
    )
    _long_term_notional: float = field(default=0.0, compare=False)
    _event_notional: dict = field(default_factory=dict, compare=False)
    _market_notional: dict = field(default_factory=dict, compare=False)

    # ------------------------------------------------------------------ #
    #  Read-only properties                                                #
    # ------------------------------------------------------------------ #

    @property
    def max_long_term_notional(self) -> float:
        """Absolute USDC limit for long-term positions."""
        return self.total_capital * self.max_long_term_fraction

    # ------------------------------------------------------------------ #
    #  Constraint checks                                                   #
    # ------------------------------------------------------------------ #

    def can_open(
        self,
        event_key: str,
        market_id: str,
        notional: float,
        days_to_resolution: int,
    ) -> bool:
        """Return True iff all portfolio caps allow opening this position.

        Call BEFORE committing to open a position.  If False, skip the open.
        Does NOT modify state — call open_position() separately if you proceed.
        """
        with self._lock:
            # 1. Long-term exposure cap
            if days_to_resolution > self.long_term_threshold_days:
                if self._long_term_notional + notional > self.max_long_term_notional:
                    return False
            # 2. Per-event concentration cap (optional)
            if event_key and self.max_event_notional > 0:
                current = self._event_notional.get(event_key, 0.0)
                if current + notional > self.max_event_notional:
                    return False
            # 3. Per-market concentration cap (optional)
            if market_id and self.max_market_notional > 0:
                current = self._market_notional.get(market_id, 0.0)
                if current + notional > self.max_market_notional:
                    return False
            return True

    def try_open(
        self,
        event_key: str,
        market_id: str,
        notional: float,
        days_to_resolution: int,
    ) -> bool:
        """Atomically check caps and, if allowed, record the open.

        Unlike can_open() + open_position(), no other thread can sneak an
        open between the check and the commit. Returns True if the position
        was recorded, False if a cap blocked it (state unchanged).
        """
        with self._lock:
            if not self.can_open(event_key, market_id, notional, days_to_resolution):
                return False
            self.open_position(event_key, market_id, notional, days_to_resolution)
            return True

    # ------------------------------------------------------------------ #
    #  State mutations                                                     #
    # ------------------------------------------------------------------ #

    def open_position(
        self,
        event_key: str,
        market_id: str,
        notional: float,
        days_to_resolution: int,
    ) -> None:
        """Record a newly opened position against the caps.

        Call immediately after deciding to open, before the order is placed.
        """
        with self._lock:
            if days_to_resolution > self.long_term_threshold_days:
                self._long_term_notional += notional
            if event_key:
                self._event_notional[event_key] = (
                    self._event_notional.get(event_key, 0.0) + notional
                )
            if market_id:
                self._market_notional[market_id] = (
                    self._market_notional.get(market_id, 0.0) + notional
                )

    def close_position(
        self,
        event_key: str,
        market_id: str,
        notional: float,
        days_to_resolution: int,
    ) -> None:
        """Release notional when a position is fully or partially closed."""
        with self._lock:
            if days_to_resolution > self.long_term_threshold_days:
                self._long_term_notional = max(
                    0.0, self._long_term_notional - notional
                )
            if event_key:
                self._event_notional[event_key] = max(
                    0.0, self._event_notional.get(event_key, 0.0) - notional
                )
            if market_id:
                self._market_notional[market_id] = max(
                    0.0, self._market_notional.get(market_id, 0.0) - notional
                )

    # ------------------------------------------------------------------ #
    #  Observability                                                       #
    # ------------------------------------------------------------------ #

    def status(self) -> dict:
        """Read-only snapshot of current constraint utilization."""
        with self._lock:
            lt_pct = (
                self._long_term_notional / self.max_long_term_notional * 100
                if self.max_long_term_notional > 0
                else 0.0
            )
            return {
                "long_term_notional": round(self._long_term_notional, 2),
                "max_long_term_notional": round(self.max_long_term_notional, 2),
                "long_term_pct": round(lt_pct, 1),
                "event_notional": {
                    k: round(v, 2) for k, v in self._event_notional.items()
                },
                "market_notional": {
                    k: round(v, 2) for k, v in self._market_notional.items()
                },
            }
