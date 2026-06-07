"""
BacktestSimulator — event-driven replay engine.

Maker-Taker arb model (correct strategy):
  Rests 4 orders simultaneously: YES bid, YES ask, NO bid, NO ask.
  When any maker order fills, immediately hedge with a taker order on the
  opposing token to lock in the combined spread.

  Bid-side arb (underprice: buys both legs):
    YES bid fills → taker buy NO at best NO ask
    Profitable when: YES_bid + NO_ask < 1.0
    PnL = (1 - YES_bid - NO_ask) * size + YES_maker_rebate - NO_taker_fee

    NO bid fills → taker buy YES at best YES ask
    Profitable when: NO_bid + YES_ask < 1.0
    PnL = (1 - NO_bid - YES_ask) * size + NO_maker_rebate - YES_taker_fee

  Ask-side arb (overprice: sells both legs):
    YES ask fills → taker sell NO at best NO bid
    Profitable when: YES_ask + NO_bid > 1.0
    PnL = (YES_ask + NO_bid - 1) * size + YES_maker_rebate - NO_taker_fee

    NO ask fills → taker sell YES at best YES bid
    Profitable when: NO_ask + YES_bid > 1.0
    PnL = (NO_ask + YES_bid - 1) * size + NO_maker_rebate - YES_taker_fee

  Hedge execution: only executes a cycle when the opposing book has depth.
  If the opposing book is empty at the moment of the maker fill, the fill is
  skipped (conservative: models a smart MM who only quotes when hedge is viable).
  Hedge size is capped by the depth available at the opposing book's best level.

Legacy single-book mode (data/raw without token_side tags):
  Falls back to the original single-book flatten logic for backward
  compatibility with data/raw synthetic data.

Uses the same FeeModel instance as all strategy components.
No separate fee approximations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Union

from src.fee_model import FeeModel
from src.data.schemas import (
    MarketMetadata, OrderBook, Fill, Side,
)
# Optional import — avoids hard dependency if portfolio_state is not installed.
try:
    from src.live.portfolio_state import PortfolioConstraints as _PortfolioConstraints
except ImportError:
    _PortfolioConstraints = None  # type: ignore
from src.strategy.fair_value import FairValueEstimator, TradeObservation
from src.strategy.regime import RegimeClassifier, RegimeInput
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig
from src.strategy.quote_engine import QuoteEngine, QuoteInput
from src.strategy.inventory import InventoryManager
from src.pnl import PnLEngine, CompletedCycle
from src.backtest.fill_model import FillModel, FillModelInput
from src.backtest.adverse_selection import AdverseSelectionTracker


Event = Union[OrderBook, Fill]


@dataclass
class SimulatorConfig:
    start_capital: float = 50000.0
    max_inventory_contracts: float = 500.0
    adverse_selection_threshold: float = 0.012
    time_to_resolution_hours: float = 48.0
    quote_size: float = 100.0
    pre_resolution_hours: float = 4.0
    warehouse_threshold_fraction: float = 0.80
    daily_capital_charge_rate: float = 0.0003
    resolution_time: Optional[datetime] = None  # if set, compute time_to_resolution dynamically
    adverse_selection_window_seconds: float = 300.0
    adverse_selection_adverse_threshold: float = 0.005
    quote_staleness_threshold: float = 0.0  # 0 = disabled; e.g. 0.01 = 1 cent
    max_concurrent_positions: int = 1       # unused in maker-taker mode; kept for API compat

    # Ladder quoting — best-bid anchored
    # L0 sits `ladder_offset_from_best` below the current best bid (above best ask for asks).
    # Each successive level steps `ladder_tick_spacing` further from the market.
    # Sizes scale by `ladder_size_ratios` (smallest near the market, largest deep).
    ladder_levels: int = 1                                      # 1 = single order (backward-compat default)
    ladder_offset_from_best: float = 0.030                     # L0 offset from best bid/ask
    ladder_tick_spacing: float = 0.010                         # additional offset per level
    ladder_size_ratios: list = field(default_factory=lambda: [1.0])  # multiplied by quote_size

    # Order management — mirrors live QuoteLoopConfig so the backtest accurately
    # models that orders do NOT reprice on every tiny tick.
    # `price_tolerance` is the minimum best-bid/ask movement required to move the
    # anchor from which ladder prices are computed.  Matches the live default of 1 tick.
    price_tolerance: float = 0.010  # min drift before repricing the ladder anchor

    # Iceberg order simulation.
    # When > 0, each ladder level is split into chunks of this size.  A single
    # large market trade can sweep through multiple iceberg chunks at the same
    # price level, generating multiple arb cycles and hiding our total capacity.
    # 0 = disabled (full level_size is shown as one order — current behaviour).
    # Typical value: 50–100 contracts (show a small slice, re-fill from reserve).
    iceberg_display_size: float = 0.0

    # Notional exposure cap per direction per market.
    # When cumulative long notional (sum of entry_yes+entry_no * size across all open
    # longs) reaches this limit, bid-arb fill checks are skipped — we only quote asks
    # to close existing longs.  Same logic applies to shorts / ask-arb.
    # Set to 0 to disable (no cap).
    max_open_notional: float = 2000.0

    # Portfolio-level context — used by the shared PortfolioConstraints object.
    # days_to_resolution: how many days until market resolution (from today).
    # event_key: Gamma event ID — groups sub-markets of the same parent event.
    # market_id: condition_id of this specific market — used for per-market cap.
    # These feed into cross-market long-term, per-event, and per-market caps.
    days_to_resolution: int = 9999
    event_key: str = ""
    market_id: str = ""


@dataclass
class SimulationResult:
    total_spread_pnl: float = 0.0
    total_skew_pnl: float = 0.0
    total_fees_paid: float = 0.0
    total_rebates_received: float = 0.0
    num_fills: int = 0
    num_book_updates: int = 0
    num_cycles_completed: int = 0
    num_open_positions: int = 0
    # Extended analytics (all default to zero/empty for backward compatibility)
    num_profitable_cycles: int = 0          # cycles with net_pnl > 0
    hedge_accessible_count: int = 0         # cycles where hedge depth was available
    hedge_checks_total: int = 0             # total fill check attempts (FV available + book present)
    per_cycle_pnl: list = field(default_factory=list)  # net PnL per completed cycle
    as_events_measured: int = 0             # fills with a completed AS measurement
    as_rate: float = 0.0                    # fraction classified as adverse
    num_stale_quote_skips: int = 0          # fill checks skipped due to FV jump
    num_fv_none_skips: int = 0             # fill checks skipped because FV estimator had no data
    num_no_hedge_depth: int = 0            # fill checks skipped: opposing book had no depth
    num_bid_arb_cycles: int = 0            # completed bid-side arb cycles
    num_ask_arb_cycles: int = 0            # completed ask-side arb cycles
    num_portfolio_blocked: int = 0         # arb opens skipped due to portfolio caps

    # Round-trip position tracking
    num_longs_opened: int = 0              # bid-arb entries
    num_shorts_opened: int = 0             # ask-arb entries
    num_round_trips: int = 0              # positions closed by opposite direction
    num_held_to_resolution: int = 0        # positions never closed (held to $1)
    round_trip_pnl: float = 0.0           # PnL from matched open+close pairs
    resolution_pnl: float = 0.0           # PnL from unmatched positions (held to $1)
    per_roundtrip_pnl: list = field(default_factory=list)   # PnL per round trip
    holding_times_seconds: list = field(default_factory=list)  # seconds held per round trip
    max_concurrent_open: int = 0           # peak number of open positions simultaneously
    total_capital_consumed: float = 0.0    # sum of all entry notionals (capital deployed)

    def total_pnl(self) -> float:
        return self.total_spread_pnl + self.total_skew_pnl

    def win_rate(self) -> float:
        """Fraction of completed cycles that were profitable."""
        if self.num_cycles_completed == 0:
            return 0.0
        return self.num_profitable_cycles / self.num_cycles_completed

    def hedge_accessibility(self) -> float:
        """Fraction of fill checks that found opposing book depth."""
        if self.hedge_checks_total == 0:
            return 0.0
        return self.hedge_accessible_count / self.hedge_checks_total


@dataclass
class _PendingEntry:
    """Legacy: tracks a passive fill awaiting a match on the opposing token side."""
    fill: Fill
    is_skew: bool


@dataclass
class _OpenPosition:
    """
    An open arb position waiting for the opposite direction to recycle capital.

    direction = "long"  → opened via bid-arb (bought YES+NO at combined cost < 1).
                          Closed when ask-arb condition is met (combined proceeds > 1).
    direction = "short" → opened via ask-arb (sold YES+NO at combined proceeds > 1).
                          Closed when bid-arb condition is met (combined cost < 1).

    entry_yes / entry_no : prices at which the two legs were executed on entry.
    entry_fees_net       : net fees already paid on entry (rebate - taker_fee).
    """
    direction: str          # "long" or "short"
    entry_yes: float
    entry_no: float
    size: float
    entry_fees_net: float   # maker_rebate - taker_fee already paid on entry
    opened_at: object       # datetime of entry trade


class BacktestSimulator:

    def __init__(
        self,
        metadata: MarketMetadata,
        fee_model: FeeModel,
        fv_estimator: FairValueEstimator,
        regime_classifier: RegimeClassifier,
        hedgeability_assessor: HedgeabilityAssessor,
        quote_engine: QuoteEngine,
        inventory_manager: InventoryManager,
        pnl_engine: PnLEngine,
        fill_model: FillModel,
        skew_config: SkewConfig,
        config: SimulatorConfig,
        portfolio: "Optional[_PortfolioConstraints]" = None,
    ):
        self.meta = metadata
        self.fee_model = fee_model
        self.fv_estimator = fv_estimator
        self.regime_classifier = regime_classifier
        self.hedgeability_assessor = hedgeability_assessor
        self.quote_engine = quote_engine
        self.inventory_manager = inventory_manager
        self.pnl_engine = pnl_engine
        self.fill_model = fill_model
        self.skew_config = skew_config
        self.config = config
        self._portfolio = portfolio  # shared cross-market constraints (may be None)

        self._current_book: OrderBook | None = None  # YES book (or legacy single book)
        self._no_book: OrderBook | None = None       # NO book (dual-book data only)
        # Legacy single-book mode pending queue
        self._pending_yes: list[_PendingEntry] = []
        self._pending_no: list[_PendingEntry] = []   # unused in legacy, kept for compat
        self._ever_seen_tagged_book: bool = False    # True once any tagged YES/NO book seen
        # Round-trip position tracking (dual-book mode)
        self._open_longs: list[_OpenPosition] = []   # waiting to be closed by ask-arb
        self._open_shorts: list[_OpenPosition] = []  # waiting to be closed by bid-arb
        self._as_estimate: float = 0.0
        self._last_fv: float | None = None
        # Price-tolerance anchoring — models that live orders don't reprice on every
        # tiny tick.  Each anchor stores the best_bid/ask at the time orders were last
        # "posted".  We only move the anchor when the market has drifted more than
        # `config.price_tolerance` from the stored anchor.
        self._yes_bid_anchor: float | None = None
        self._yes_ask_anchor: float | None = None
        self._no_bid_anchor: float | None = None
        self._no_ask_anchor: float | None = None

        # Notional exposure tracking per direction.
        # Long notional  = sum of (entry_yes + entry_no) * size for all open longs.
        # Short notional = same for open shorts.
        # When a direction hits max_open_notional, fill checks for that direction are
        # skipped; the opposite direction stays active to close existing positions.
        self._long_notional: float = 0.0
        self._short_notional: float = 0.0
        self._as_tracker = AdverseSelectionTracker(
            window_seconds=config.adverse_selection_window_seconds,
            adverse_threshold=config.adverse_selection_adverse_threshold,
        )
        self._result: SimulationResult = SimulationResult()

    def _update_anchor(
        self, anchor: float | None, current: float, tolerance: float
    ) -> float:
        """Return updated anchor: moves to `current` only when drift > tolerance."""
        if anchor is None or abs(current - anchor) > tolerance:
            return current
        return anchor

    # ------------------------------------------------------------------
    # Backward-compat alias used by legacy flatten paths
    # ------------------------------------------------------------------
    @property
    def _pending_entries(self) -> list[_PendingEntry]:
        return self._pending_yes

    def run(self, events: list[Event]) -> SimulationResult:
        self._result = SimulationResult()
        self._current_book = None
        self._no_book = None
        self._pending_yes = []
        self._pending_no = []
        self._open_longs = []
        self._open_shorts = []
        self._as_estimate = 0.0
        self._last_fv = None
        self._yes_bid_anchor = None
        self._yes_ask_anchor = None
        self._no_bid_anchor = None
        self._no_ask_anchor = None
        self._long_notional = 0.0
        self._short_notional = 0.0
        self._as_tracker = AdverseSelectionTracker(
            window_seconds=self.config.adverse_selection_window_seconds,
            adverse_threshold=self.config.adverse_selection_adverse_threshold,
        )
        # Pre-scan: if ANY event in the stream has a YES or NO tag, this is a
        # dual-book market.  All legacy single-book paths must be disabled from
        # the very first event — even before the first tagged book arrives.
        self._ever_seen_tagged_book = any(
            isinstance(e, (OrderBook, Fill)) and e.token_side in ("YES", "NO")
            for e in events
        )
        for event in events:
            if isinstance(event, OrderBook):
                self._on_book(event)
            elif isinstance(event, Fill):
                self._on_trade(event)

        # In maker-taker mode, no pending positions exist (each fill is immediately hedged).
        # In legacy mode, count stranded fills.
        self._result.num_open_positions = (
            len(self._pending_yes) + len(self._pending_no)
            + len(self._open_longs) + len(self._open_shorts)
        )

        # Settle unclosed positions at $1.00 (resolution)
        for pos in self._open_longs:
            # Bought YES+NO at entry_yes+entry_no; resolves to $1.00
            gross = (1.0 - pos.entry_yes - pos.entry_no) * pos.size
            net = gross + pos.entry_fees_net
            self._result.resolution_pnl += net
            self._result.total_spread_pnl += net
            self._result.num_held_to_resolution += 1
            self._result.num_cycles_completed += 1
            self._result.per_cycle_pnl.append(net)
            if net > 0:
                self._result.num_profitable_cycles += 1
        for pos in self._open_shorts:
            # Sold YES+NO at entry_yes+entry_no; resolves paying out $1.00
            gross = (pos.entry_yes + pos.entry_no - 1.0) * pos.size
            net = gross + pos.entry_fees_net
            self._result.resolution_pnl += net
            self._result.total_spread_pnl += net
            self._result.num_held_to_resolution += 1
            self._result.num_cycles_completed += 1
            self._result.per_cycle_pnl.append(net)
            if net > 0:
                self._result.num_profitable_cycles += 1

        # Finalize adverse-selection stats
        stats = self._as_tracker.stats()
        self._result.as_events_measured = stats["num_measured"]
        self._result.as_rate = stats["as_rate"]

        return self._result

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_book(self, book: OrderBook) -> None:
        side = book.token_side  # "YES", "NO", or "" (legacy)

        if side == "NO":
            self._no_book = book
            self._ever_seen_tagged_book = True
            return

        if side == "YES":
            self._ever_seen_tagged_book = True
        elif self._ever_seen_tagged_book:
            # Untagged book in a market we know has dual-book data — ignore it.
            return

        # YES book or legacy single-book
        self._current_book = book
        self._result.num_book_updates += 1

        # Legacy single-book flatten (only in pure legacy mode)
        if self._no_book is None and not self._ever_seen_tagged_book:
            for entry_obj in list(self._pending_yes):
                self._attempt_flatten(book, entry_obj)

    def _on_trade(self, trade: Fill) -> None:
        """Process a market trade event.

        Dual-book mode (maker-taker model):
          YES trades: check YES bid fill (buy arb) and YES ask fill (sell arb).
          NO trades:  check NO bid fill (buy arb) and NO ask fill (sell arb).
          FV updated after fill checks to avoid look-ahead bias.

        Legacy single-book mode:
          Unchanged flatten logic for backward compatibility.
        """
        if trade.token_side == "NO":
            # Dual-book mode: handle NO trades
            if self._no_book is not None and self._current_book is not None:
                fv = self.fv_estimator.estimate(as_of=trade.timestamp)
                if fv is None:
                    if self._last_fv is not None:
                        fv = self._last_fv
                    else:
                        self._result.num_fv_none_skips += 1
                if fv is not None:
                    self._check_no_bid_fill(trade, fv)
                    self._check_no_ask_fill(trade, fv)
            return

        # --- YES trade (or legacy untagged trade) ---

        # Untagged trades in a dual-book market: update FV/AS only, can't route.
        if trade.token_side == "" and self._ever_seen_tagged_book:
            self.fv_estimator.on_trade(
                TradeObservation(price=trade.price, size=trade.size, timestamp=trade.timestamp)
            )
            self._as_tracker.on_trade(trade.price, trade.timestamp)
            self._as_estimate = self._as_tracker.estimate()
            return

        # Legacy single-book flatten via incoming trade
        if self._no_book is None and self._current_book is not None and not self._ever_seen_tagged_book:
            for entry_obj in list(self._pending_yes):
                self._attempt_flatten_via_trade(trade, entry_obj)

        # In dual-book mode, wait until NO book is available before taking fills.
        if self._ever_seen_tagged_book and self._no_book is None:
            self.fv_estimator.on_trade(
                TradeObservation(price=trade.price, size=trade.size, timestamp=trade.timestamp)
            )
            self._as_tracker.on_trade(trade.price, trade.timestamp)
            self._as_estimate = self._as_tracker.estimate()
            return

        # Dual-book YES trade: check all YES bid/ask fill scenarios
        if self._current_book is not None and self._ever_seen_tagged_book:
            fv = self.fv_estimator.estimate(as_of=trade.timestamp)
            if fv is None:
                if self._last_fv is not None:
                    fv = self._last_fv
                else:
                    self._result.num_fv_none_skips += 1
            if fv is not None:
                threshold = self.config.quote_staleness_threshold
                stale = (
                    threshold > 0
                    and self._last_fv is not None
                    and abs(fv - self._last_fv) > threshold
                )
                if stale:
                    self._result.num_stale_quote_skips += 1
                    self._last_fv = None
                else:
                    self._check_yes_bid_fill(trade, fv)
                    self._check_yes_ask_fill(trade, fv)
                    self._last_fv = fv

        # Legacy single-book YES bid check (no_book is None and no tagged books ever seen)
        elif self._current_book is not None and not self._ever_seen_tagged_book:
            fv = self.fv_estimator.estimate(as_of=trade.timestamp)
            if fv is not None:
                threshold = self.config.quote_staleness_threshold
                stale = (
                    threshold > 0
                    and self._last_fv is not None
                    and abs(fv - self._last_fv) > threshold
                )
                if not stale:
                    self._check_fill_legacy(trade, fv)
                    self._last_fv = fv
                else:
                    self._result.num_stale_quote_skips += 1
                    self._last_fv = None
            else:
                self._result.num_fv_none_skips += 1

        # Update FV AFTER fill check (avoid look-ahead)
        self.fv_estimator.on_trade(
            TradeObservation(price=trade.price, size=trade.size, timestamp=trade.timestamp)
        )
        self._as_tracker.on_trade(trade.price, trade.timestamp)
        self._as_estimate = self._as_tracker.estimate()

    # ------------------------------------------------------------------
    # Dual-book maker-taker fill checks
    # ------------------------------------------------------------------

    def _check_yes_bid_fill(self, trade: Fill, fv: float) -> None:
        """YES bid ladder fill → immediately take NO at best NO ask (taker).

        Ladder is anchored to the current best YES bid:
          L0 = best_bid - ladder_offset_from_best
          Ln = best_bid - ladder_offset_from_best - n * ladder_tick_spacing
        Each level has an independent size (quote_size * ladder_size_ratios[n]).
        All levels are checked; a single trade may fill multiple levels if deep enough.
        """
        # Notional cap: if long exposure is at/above limit, skip new bid-arb fills.
        # Ask-arb (which closes longs) is still checked via _check_yes_ask_fill.
        cap = self.config.max_open_notional
        if cap > 0 and self._long_notional >= cap:
            return

        decision = self._compute_quote(fv, trade.timestamp)
        self._result.hedge_checks_total += 1
        if decision is None or decision.suspend or decision.bid_size == 0:
            return

        if not self._current_book or not self._current_book.bids:
            return
        best_bid = self._current_book.bids[0].price
        # Price-tolerance anchor: only reprice when best bid drifts > tolerance
        self._yes_bid_anchor = self._update_anchor(
            self._yes_bid_anchor, best_bid, self.config.price_tolerance
        )
        anchor_bid = self._yes_bid_anchor

        # Taker hedge book check — shared across all levels
        if not self._no_book or not self._no_book.asks:
            self._result.num_no_hedge_depth += 1
            return
        no_ask = self._no_book.asks[0].price

        n = self.config.ladder_levels
        ratios = list(self.config.ladder_size_ratios)
        while len(ratios) < n:
            ratios.append(ratios[-1])

        for level in range(n):
            offset = self.config.ladder_offset_from_best + level * self.config.ladder_tick_spacing
            yes_bid = round(max(0.01, min(0.99, anchor_bid - offset)), 3)
            level_size = self.config.quote_size * ratios[level]

            # Direction check: market SELL must reach this level
            if trade.price > yes_bid + 1e-9:
                continue

            # Profitability guard
            if yes_bid + no_ask >= 1.0 - 1e-9:
                continue

            # Iceberg: loop through display-size chunks drawn from the full level.
            # Without iceberg (display_size=0) this executes exactly once.
            display = self.config.iceberg_display_size if self.config.iceberg_display_size > 0 else level_size
            remaining_hidden = level_size
            remaining_trade  = trade.size

            while remaining_hidden > 0.5 and remaining_trade > 0.5:
                chunk = min(display, remaining_hidden)
                fill_inp = FillModelInput(
                    quote_price=yes_bid,
                    quote_size=chunk,
                    market_trade_price=trade.price,
                    market_trade_size=remaining_trade,
                    book_size_at_price=0.0,
                )
                maker_filled = self.fill_model.simulate_fill(fill_inp).filled_size
                if maker_filled <= 0:
                    break

                hedge_available = self._no_book.asks[0].size
                cycle_size = min(maker_filled, hedge_available)
                if cycle_size <= 0:
                    break

                self._result.hedge_accessible_count += 1
                self._result.num_fills += 1
                self._record_bid_arb_cycle(
                    maker_price=yes_bid,
                    taker_price=no_ask,
                    size=cycle_size,
                    timestamp=trade.timestamp,
                    maker_token="YES",
                )
                self._as_tracker.on_fill(yes_bid, trade.timestamp)
                remaining_hidden -= maker_filled
                remaining_trade  -= maker_filled

    def _check_yes_ask_fill(self, trade: Fill, fv: float) -> None:
        """YES ask ladder fill → immediately take NO bid (taker sell NO).

        Ladder anchored to current best YES ask:
          L0 = best_ask + ladder_offset_from_best
          Ln = best_ask + ladder_offset_from_best + n * ladder_tick_spacing
        """
        # Notional cap: if short exposure is at/above limit, skip new ask-arb fills.
        # Bid-arb (which closes shorts) is still checked via _check_yes_bid_fill.
        cap = self.config.max_open_notional
        if cap > 0 and self._short_notional >= cap:
            return

        decision = self._compute_quote(fv, trade.timestamp)
        if decision is None or decision.suspend:
            return

        if not self._current_book or not self._current_book.asks:
            return
        best_ask = self._current_book.asks[0].price
        # Price-tolerance anchor: only reprice when best ask drifts > tolerance
        self._yes_ask_anchor = self._update_anchor(
            self._yes_ask_anchor, best_ask, self.config.price_tolerance
        )
        anchor_ask = self._yes_ask_anchor

        if not self._no_book or not self._no_book.bids:
            self._result.num_no_hedge_depth += 1
            return
        no_bid = self._no_book.bids[0].price

        n = self.config.ladder_levels
        ratios = list(self.config.ladder_size_ratios)
        while len(ratios) < n:
            ratios.append(ratios[-1])

        for level in range(n):
            offset = self.config.ladder_offset_from_best + level * self.config.ladder_tick_spacing
            yes_ask = round(max(0.01, min(0.99, anchor_ask + offset)), 3)
            level_size = self.config.quote_size * ratios[level]

            # Direction check: market BUY must reach this level
            if trade.price < yes_ask - 1e-9:
                continue

            # Profitability guard
            if yes_ask + no_bid <= 1.0 + 1e-9:
                continue

            # Iceberg: loop through chunks
            display = self.config.iceberg_display_size if self.config.iceberg_display_size > 0 else level_size
            remaining_hidden = level_size
            remaining_trade  = trade.size

            while remaining_hidden > 0.5 and remaining_trade > 0.5:
                chunk = min(display, remaining_hidden)
                maker_filled = min(remaining_trade, chunk)
                if maker_filled <= 0:
                    break

                hedge_available = self._no_book.bids[0].size
                cycle_size = min(maker_filled, hedge_available)
                if cycle_size <= 0:
                    break

                self._result.num_fills += 1
                self._record_ask_arb_cycle(
                    maker_price=yes_ask,
                    taker_price=no_bid,
                    size=cycle_size,
                    timestamp=trade.timestamp,
                    maker_token="YES",
                )
                self._as_tracker.on_fill(yes_ask, trade.timestamp)
                remaining_hidden -= maker_filled
                remaining_trade  -= maker_filled

    def _check_no_bid_fill(self, trade: Fill, fv: float) -> None:
        """NO bid ladder fill → immediately take YES at best YES ask (taker).

        Ladder anchored to current best NO bid:
          L0 = best_no_bid - ladder_offset_from_best
          Ln = best_no_bid - ladder_offset_from_best - n * ladder_tick_spacing
        """
        # Notional cap: NO bid fills also open longs — same cap as YES bid fills.
        cap = self.config.max_open_notional
        if cap > 0 and self._long_notional >= cap:
            return

        self._result.hedge_checks_total += 1

        decision = self._compute_quote(fv, trade.timestamp)
        if decision is None or decision.suspend:
            return

        if not self._no_book or not self._no_book.bids:
            return
        best_no_bid = self._no_book.bids[0].price
        # Price-tolerance anchor: only reprice when best NO bid drifts > tolerance
        self._no_bid_anchor = self._update_anchor(
            self._no_bid_anchor, best_no_bid, self.config.price_tolerance
        )
        anchor_no_bid = self._no_bid_anchor

        # Taker hedge book check — shared across all levels
        if not self._current_book or not self._current_book.asks:
            self._result.num_no_hedge_depth += 1
            return
        yes_ask = self._current_book.asks[0].price

        n = self.config.ladder_levels
        ratios = list(self.config.ladder_size_ratios)
        while len(ratios) < n:
            ratios.append(ratios[-1])

        for level in range(n):
            offset = self.config.ladder_offset_from_best + level * self.config.ladder_tick_spacing
            no_bid = round(max(0.01, min(0.99, anchor_no_bid - offset)), 3)
            level_size = self.config.quote_size * ratios[level]

            if trade.price > no_bid + 1e-9:
                continue

            if no_bid + yes_ask >= 1.0 - 1e-9:
                continue

            # Iceberg: loop through chunks
            display = self.config.iceberg_display_size if self.config.iceberg_display_size > 0 else level_size
            remaining_hidden = level_size
            remaining_trade  = trade.size

            while remaining_hidden > 0.5 and remaining_trade > 0.5:
                chunk = min(display, remaining_hidden)
                fill_inp = FillModelInput(
                    quote_price=no_bid,
                    quote_size=chunk,
                    market_trade_price=trade.price,
                    market_trade_size=remaining_trade,
                    book_size_at_price=0.0,
                )
                maker_filled = self.fill_model.simulate_fill(fill_inp).filled_size
                if maker_filled <= 0:
                    break

                hedge_available = self._current_book.asks[0].size
                cycle_size = min(maker_filled, hedge_available)
                if cycle_size <= 0:
                    break

                self._result.hedge_accessible_count += 1
                self._result.num_fills += 1
                self._record_bid_arb_cycle(
                    maker_price=no_bid,
                    taker_price=yes_ask,
                    size=cycle_size,
                    timestamp=trade.timestamp,
                    maker_token="NO",
                )
                self._as_tracker.on_fill(no_bid, trade.timestamp)
                remaining_hidden -= maker_filled
                remaining_trade  -= maker_filled

    def _check_no_ask_fill(self, trade: Fill, fv: float) -> None:
        """NO ask fill → immediately take YES bid (taker sell YES).

        Arb condition (user-specified): NO_ask + YES_bid > 1.0
        PnL = (NO_ask + YES_bid - 1) * size + NO_maker_rebate - YES_taker_fee

        Only executes when combined proceeds exceed $1 (profitable before fees).
        """
        # Notional cap: NO ask fills also open shorts — same cap as YES ask fills.
        cap = self.config.max_open_notional
        if cap > 0 and self._short_notional >= cap:
            return

        decision = self._compute_quote(fv, trade.timestamp)
        if decision is None or decision.suspend:
            return

        if not self._no_book or not self._no_book.asks:
            return
        best_no_ask = self._no_book.asks[0].price
        # Price-tolerance anchor: only reprice when best NO ask drifts > tolerance
        self._no_ask_anchor = self._update_anchor(
            self._no_ask_anchor, best_no_ask, self.config.price_tolerance
        )
        anchor_no_ask = self._no_ask_anchor

        if not self._current_book or not self._current_book.bids:
            self._result.num_no_hedge_depth += 1
            return
        yes_bid = self._current_book.bids[0].price

        n = self.config.ladder_levels
        ratios = list(self.config.ladder_size_ratios)
        while len(ratios) < n:
            ratios.append(ratios[-1])

        for level in range(n):
            offset = self.config.ladder_offset_from_best + level * self.config.ladder_tick_spacing
            no_ask = round(max(0.01, min(0.99, anchor_no_ask + offset)), 3)
            level_size = self.config.quote_size * ratios[level]

            if trade.price < no_ask - 1e-9:
                continue

            if no_ask + yes_bid <= 1.0 + 1e-9:
                continue

            # Iceberg: loop through chunks
            display = self.config.iceberg_display_size if self.config.iceberg_display_size > 0 else level_size
            remaining_hidden = level_size
            remaining_trade  = trade.size

            while remaining_hidden > 0.5 and remaining_trade > 0.5:
                chunk = min(display, remaining_hidden)
                maker_filled = min(remaining_trade, chunk)
                if maker_filled <= 0:
                    break

                hedge_available = self._current_book.bids[0].size
                cycle_size = min(maker_filled, hedge_available)
                if cycle_size <= 0:
                    break

                self._result.num_fills += 1
                self._record_ask_arb_cycle(
                    maker_price=no_ask,
                    taker_price=yes_bid,
                    size=cycle_size,
                    timestamp=trade.timestamp,
                    maker_token="NO",
                )
                self._as_tracker.on_fill(no_ask, trade.timestamp)
                remaining_hidden -= maker_filled
                remaining_trade  -= maker_filled

    # ------------------------------------------------------------------
    # Cycle recording (dual-book maker-taker)
    # ------------------------------------------------------------------

    def _record_bid_arb_cycle(
        self,
        maker_price: float,
        taker_price: float,
        size: float,
        timestamp,
        maker_token: str,
    ) -> None:
        """Bid-arb event: combined cost (maker_price + taker_price) < 1.0.

        Two cases:
          A) Open shorts exist → close the oldest short (round-trip completed).
          B) No open shorts → open a new long position.

        Entry fees are recorded immediately; round-trip PnL is only finalised on close.
        Positions not closed during the simulation are settled at $1.00 in run().
        """
        maker_rebate = self.fee_model.maker_rebate(
            size=size, price=maker_price,
            fee_rate=self.meta.fee_rate,
            rebate_fraction=self.meta.rebate_fraction,
        )
        taker_fee = self.fee_model.taker_fee(
            size=size, price=taker_price,
            fee_rate=self.meta.fee_rate,
        )
        entry_fees_net = maker_rebate - taker_fee
        self._result.total_rebates_received += maker_rebate
        self._result.total_fees_paid += taker_fee
        self._result.num_bid_arb_cycles += 1

        if self._open_shorts:
            # Close the oldest short position (FIFO)
            short = self._open_shorts.pop(0)
            close_size = min(size, short.size)

            # Round-trip PnL: opened short at (short.entry_yes + short.entry_no) > 1,
            # closing now by buying back at (maker_price + taker_price) < 1.
            gross = (short.entry_yes + short.entry_no - maker_price - taker_price) * close_size
            net = gross + short.entry_fees_net + entry_fees_net
            self._result.total_spread_pnl += net
            self._result.round_trip_pnl += net
            self._result.num_round_trips += 1
            self._result.num_cycles_completed += 1
            self._result.per_cycle_pnl.append(net)
            self._result.per_roundtrip_pnl.append(net)
            if net > 0:
                self._result.num_profitable_cycles += 1
            try:
                held_s = (timestamp - short.opened_at).total_seconds()
                self._result.holding_times_seconds.append(held_s)
            except Exception:
                pass

            # Release short notional (proportional if partial close)
            close_notional = (short.entry_yes + short.entry_no) * close_size
            self._short_notional -= close_notional
            self._short_notional = max(0.0, self._short_notional)
            if self._portfolio is not None:
                self._portfolio.close_position(
                    self.config.event_key, self.config.market_id,
                    close_notional, self.config.days_to_resolution
                )

            # If short was larger, put remainder back
            if short.size > close_size:
                short.size -= close_size
                self._open_shorts.insert(0, short)
        else:
            # Open a new long — check portfolio caps first
            yes_price = maker_price if maker_token == "YES" else taker_price
            no_price  = taker_price if maker_token == "YES" else maker_price
            open_notional = (yes_price + no_price) * size
            if self._portfolio is not None and not self._portfolio.can_open(
                self.config.event_key, self.config.market_id,
                open_notional, self.config.days_to_resolution
            ):
                # Portfolio cap hit — undo the cycle counter and skip
                self._result.num_bid_arb_cycles -= 1
                self._result.num_portfolio_blocked += 1
                return
            pos = _OpenPosition(
                direction="long",
                entry_yes=yes_price,
                entry_no=no_price,
                size=size,
                entry_fees_net=entry_fees_net,
                opened_at=timestamp,
            )
            self._open_longs.append(pos)
            self._long_notional += open_notional
            self._result.num_longs_opened += 1
            self._result.total_capital_consumed += open_notional
            self._result.max_concurrent_open = max(
                self._result.max_concurrent_open,
                len(self._open_longs) + len(self._open_shorts),
            )
            if self._portfolio is not None:
                self._portfolio.open_position(
                    self.config.event_key, self.config.market_id,
                    open_notional, self.config.days_to_resolution
                )

        self.inventory_manager.add_flatten(size, taker_price)

    def _record_ask_arb_cycle(
        self,
        maker_price: float,
        taker_price: float,
        size: float,
        timestamp,
        maker_token: str,
    ) -> None:
        """Ask-arb event: combined proceeds (maker_price + taker_price) > 1.0.

        Two cases:
          A) Open longs exist → close the oldest long (round-trip completed).
          B) No open longs → open a new short position.
        """
        maker_rebate = self.fee_model.maker_rebate(
            size=size, price=maker_price,
            fee_rate=self.meta.fee_rate,
            rebate_fraction=self.meta.rebate_fraction,
        )
        taker_fee = self.fee_model.taker_fee(
            size=size, price=taker_price,
            fee_rate=self.meta.fee_rate,
        )
        entry_fees_net = maker_rebate - taker_fee
        self._result.total_rebates_received += maker_rebate
        self._result.total_fees_paid += taker_fee
        self._result.num_ask_arb_cycles += 1

        if self._open_longs:
            # Close the oldest long position (FIFO)
            long = self._open_longs.pop(0)
            close_size = min(size, long.size)

            # Round-trip PnL: opened long at (long.entry_yes + long.entry_no) < 1,
            # closing now by selling at (maker_price + taker_price) > 1.
            gross = (maker_price + taker_price - long.entry_yes - long.entry_no) * close_size
            net = gross + long.entry_fees_net + entry_fees_net
            self._result.total_spread_pnl += net
            self._result.round_trip_pnl += net
            self._result.num_round_trips += 1
            self._result.num_cycles_completed += 1
            self._result.per_cycle_pnl.append(net)
            self._result.per_roundtrip_pnl.append(net)
            if net > 0:
                self._result.num_profitable_cycles += 1
            try:
                held_s = (timestamp - long.opened_at).total_seconds()
                self._result.holding_times_seconds.append(held_s)
            except Exception:
                pass

            # Release long notional (proportional if partial close)
            close_notional = (long.entry_yes + long.entry_no) * close_size
            self._long_notional -= close_notional
            self._long_notional = max(0.0, self._long_notional)
            if self._portfolio is not None:
                self._portfolio.close_position(
                    self.config.event_key, self.config.market_id,
                    close_notional, self.config.days_to_resolution
                )

            # If long was larger, put remainder back
            if long.size > close_size:
                long.size -= close_size
                self._open_longs.insert(0, long)
        else:
            # Open a new short — check portfolio caps first
            yes_price = maker_price if maker_token == "YES" else taker_price
            no_price  = taker_price if maker_token == "YES" else maker_price
            open_notional = (yes_price + no_price) * size
            if self._portfolio is not None and not self._portfolio.can_open(
                self.config.event_key, self.config.market_id,
                open_notional, self.config.days_to_resolution
            ):
                # Portfolio cap hit — undo the cycle counter and skip
                self._result.num_ask_arb_cycles -= 1
                self._result.num_portfolio_blocked += 1
                return
            pos = _OpenPosition(
                direction="short",
                entry_yes=yes_price,
                entry_no=no_price,
                size=size,
                entry_fees_net=entry_fees_net,
                opened_at=timestamp,
            )
            self._open_shorts.append(pos)
            self._short_notional += open_notional
            self._result.num_shorts_opened += 1
            self._result.total_capital_consumed += open_notional
            self._result.max_concurrent_open = max(
                self._result.max_concurrent_open,
                len(self._open_longs) + len(self._open_shorts),
            )
            if self._portfolio is not None:
                self._portfolio.open_position(
                    self.config.event_key, self.config.market_id,
                    open_notional, self.config.days_to_resolution
                )

        self.inventory_manager.add_flatten(size, taker_price)

    # ------------------------------------------------------------------
    # Quote computation helpers
    # ------------------------------------------------------------------

    def _compute_quote(self, fv: float, timestamp) -> object | None:
        """Compute QuoteDecision for the current YES book state."""
        inv_state = self.inventory_manager.state()
        if self.config.resolution_time is not None:
            delta = self.config.resolution_time - timestamp
            time_to_res = max(0.0, delta.total_seconds() / 3600.0)
        else:
            time_to_res = self.config.time_to_resolution_hours
        regime_inp = RegimeInput(
            timestamp=timestamp,
            inventory=inv_state,
            adverse_selection=self._as_estimate,
            adverse_selection_threshold=self.config.adverse_selection_threshold,
            time_to_resolution_hours=time_to_res,
            pre_resolution_hours=self.config.pre_resolution_hours,
            max_inventory_contracts=self.config.max_inventory_contracts,
            warehouse_threshold_fraction=self.config.warehouse_threshold_fraction,
            fv=fv,
            best_bid=self._current_book.best_bid() if self._current_book else None,
            best_ask=self._current_book.best_ask() if self._current_book else None,
        )
        regime = self.regime_classifier.classify(regime_inp)

        fee_cost = self.fee_model.fee_flatten_expected(fv, self.hedgeability_assessor.fee_rate)
        actual_half_spread = max(self.quote_engine.half_spread_base,
                                 fee_cost + self.quote_engine.min_edge_floor)
        provisional_bid = fv - actual_half_spread
        hedge_result = self._assess_hedgeability(provisional_bid, self.config.quote_size)

        quote_inp = QuoteInput(
            fv=fv,
            regime=regime,
            hedgeability=hedge_result,
            adverse_selection=self._as_estimate,
            quote_size=self.config.quote_size,
        )
        return self.quote_engine.compute(quote_inp)

    def _compute_no_quote(self, fv: float) -> tuple[float, float]:
        """Compute NO bid and NO ask prices from YES fair value.

        NO fair value = 1 - fv_yes.
        Uses the same half-spread formula as the YES side (symmetric market).
        Returns (no_bid, no_ask).
        """
        no_fv = 1.0 - fv
        fee_cost = self.fee_model.fee_flatten_expected(no_fv, self.meta.fee_rate)
        half_spread = max(
            self.quote_engine.half_spread_base,
            fee_cost + self.quote_engine.min_edge_floor,
        )
        no_bid = round(max(0.01, min(0.99, no_fv - half_spread)), 2)
        no_ask = round(max(0.01, min(0.99, no_fv + half_spread)), 2)
        return no_bid, no_ask

    def _assess_hedgeability(self, quote_price: float, quote_size: float):
        """Run HedgeabilityAssessor for the given price/size."""
        book = self._current_book
        if book is None:
            from src.strategy.hedgeability import HedgeabilityResult
            return HedgeabilityResult(
                hedgeable_size=0.0,
                unhedgeable_size=quote_size,
                skew_accepted=0.0,
                skew_rejected=quote_size,
                max_flatten_price=0.0,
            )
        return self.hedgeability_assessor.assess(
            quote_side=Side.BUY,
            quote_price=quote_price,
            quote_size=quote_size,
            book=book,
            own_order_ids=set(),
            skew_config=self.skew_config,
        )

    # ------------------------------------------------------------------
    # Legacy single-book fill check (data/raw backward compatibility)
    # ------------------------------------------------------------------

    def _check_fill_legacy(self, trade: Fill, fv: float) -> None:
        """Legacy single-book YES bid fill check — queues fill for later flatten."""
        decision = self._compute_quote(fv, trade.timestamp)
        self._result.hedge_checks_total += 1
        if decision is None or decision.suspend or decision.bid_size == 0:
            return

        yes_bid = decision.bid_price
        book_size_at_bid = sum(
            lvl.size for lvl in self._current_book.bids
            if abs(lvl.price - yes_bid) < 1e-6
        )
        fill_inp = FillModelInput(
            quote_price=yes_bid,
            quote_size=decision.bid_size,
            market_trade_price=trade.price,
            market_trade_size=trade.size,
            book_size_at_price=book_size_at_bid,
        )
        fill_result = self.fill_model.simulate_fill(fill_inp)
        if fill_result.filled_size <= 0:
            return

        self._result.num_fills += 1
        filled = fill_result.filled_size

        hedge_result = self._assess_hedgeability(yes_bid, filled)
        is_skew = hedge_result.hedgeable_size == 0 and hedge_result.skew_accepted > 0

        sim_fill = Fill(
            fill_id=f"sim_{trade.fill_id}",
            market_id=self.meta.condition_id,
            side=Side.BUY,
            price=yes_bid,
            size=filled,
            timestamp=trade.timestamp,
            is_maker=True,
        )
        self.inventory_manager.add_fill(sim_fill, is_skew=is_skew)
        self._pending_yes.append(_PendingEntry(fill=sim_fill, is_skew=is_skew))
        self._as_tracker.on_fill(sim_fill.price, sim_fill.timestamp)

    # ------------------------------------------------------------------
    # Legacy single-book flatten logic (data/raw backward compatibility)
    # ------------------------------------------------------------------

    def _attempt_flatten(self, book: OrderBook, entry_obj: _PendingEntry) -> None:
        """Legacy: flatten a single slice against the best ask in `book`."""
        if not book.asks:
            return
        entry = entry_obj.fill
        flatten_price = book.asks[0].price
        p_max = self.fee_model.max_flatten_price(
            p_fill=entry.price,
            fee_rate=self.meta.fee_rate,
            rebate_fraction=self.meta.rebate_fraction,
            min_edge_floor=0.005,
        )
        if flatten_price > p_max:
            return
        flatten_size = min(entry.size, book.asks[0].size)
        if flatten_size <= 0:
            return
        self._record_flatten(entry_obj, flatten_price, flatten_size)

    def _attempt_flatten_via_trade(self, trade: Fill, entry_obj: _PendingEntry) -> None:
        """Legacy: flatten a slice using the incoming trade as a taker opportunity."""
        if self._current_book is None or not self._current_book.asks:
            return
        entry = entry_obj.fill
        p_max = self.fee_model.max_flatten_price(
            p_fill=entry.price,
            fee_rate=self.meta.fee_rate,
            rebate_fraction=self.meta.rebate_fraction,
            min_edge_floor=0.005,
        )
        flatten_price = self._current_book.asks[0].price
        if flatten_price > p_max:
            return
        flatten_size = min(entry.size, self._current_book.asks[0].size)
        if flatten_size <= 0:
            return
        self._record_flatten(entry_obj, flatten_price, flatten_size)

    def _record_flatten(
        self, entry_obj: _PendingEntry, flatten_price: float, flatten_size: float
    ) -> None:
        """Legacy: record a flatten cycle using the PnLEngine (taker flatten leg)."""
        entry = entry_obj.fill
        cycle = CompletedCycle(
            market_id=self.meta.condition_id,
            entry_price=entry.price,
            entry_size=entry.size,
            flatten_price=flatten_price,
            flatten_size=flatten_size,
            is_skew=entry_obj.is_skew,
        )
        cycle_result = self.pnl_engine.compute_cycle(cycle)
        net_cycle_pnl = cycle_result.spread_pnl + cycle_result.skew_pnl
        self._result.total_spread_pnl += cycle_result.spread_pnl
        self._result.total_skew_pnl += cycle_result.skew_pnl
        self._result.total_fees_paid += cycle_result.taker_fee_paid
        self._result.total_rebates_received += cycle_result.maker_rebate_received
        self._result.num_cycles_completed += 1
        self._result.per_cycle_pnl.append(net_cycle_pnl)
        if net_cycle_pnl > 0:
            self._result.num_profitable_cycles += 1

        self.inventory_manager.add_flatten(flatten_size, flatten_price)
        self._pending_yes.remove(entry_obj)
