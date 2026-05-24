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

        self._current_book: OrderBook | None = None  # YES book (or legacy single book)
        self._no_book: OrderBook | None = None       # NO book (dual-book data only)
        # Legacy single-book mode pending queue
        self._pending_yes: list[_PendingEntry] = []
        self._pending_no: list[_PendingEntry] = []   # unused in legacy, kept for compat
        self._ever_seen_tagged_book: bool = False    # True once any tagged YES/NO book seen
        self._as_estimate: float = 0.0
        self._last_fv: float | None = None
        self._as_tracker = AdverseSelectionTracker(
            window_seconds=config.adverse_selection_window_seconds,
            adverse_threshold=config.adverse_selection_adverse_threshold,
        )
        self._result: SimulationResult = SimulationResult()

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
        self._as_estimate = 0.0
        self._last_fv = None
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
        self._result.num_open_positions = len(self._pending_yes) + len(self._pending_no)

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
        """YES bid fill → immediately take NO at best NO ask (taker).

        Arb condition (user-specified): YES_bid + NO_ask < 1.0
        PnL = (1 - YES_bid - NO_ask) * size + YES_maker_rebate - NO_taker_fee

        Only executes when the combined cost is below $1 (profitable before fees).
        Skips if the NO book has moved and the arb is no longer available.
        """
        decision = self._compute_quote(fv, trade.timestamp)
        self._result.hedge_checks_total += 1
        if decision is None or decision.suspend or decision.bid_size == 0:
            return

        yes_bid = decision.bid_price

        # Direction check: a market SELL at price ≤ yes_bid fills our resting bid
        if trade.price > yes_bid + 1e-9:
            return

        # Taker hedge: buy NO at best NO ask
        if not self._no_book or not self._no_book.asks:
            self._result.num_no_hedge_depth += 1
            return

        no_ask = self._no_book.asks[0].price

        # Profitability guard: only execute when combined cost < $1 (user condition: "result < 1")
        if yes_bid + no_ask >= 1.0 - 1e-9:
            return

        # Maker fill size on YES
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
        maker_filled = self.fill_model.simulate_fill(fill_inp).filled_size
        if maker_filled <= 0:
            return

        hedge_available = self._no_book.asks[0].size
        cycle_size = min(maker_filled, hedge_available)
        if cycle_size <= 0:
            return

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

    def _check_yes_ask_fill(self, trade: Fill, fv: float) -> None:
        """YES ask fill → immediately take NO bid (taker sell NO).

        Arb condition (user-specified): YES_ask + NO_bid > 1.0
        PnL = (YES_ask + NO_bid - 1) * size + YES_maker_rebate - NO_taker_fee

        Only executes when combined proceeds exceed $1 (profitable before fees).
        In a fairly-priced market yes_ask + no_bid ≈ $1.00 so this rarely triggers.
        """
        decision = self._compute_quote(fv, trade.timestamp)
        if decision is None or decision.suspend:
            return

        yes_ask = decision.ask_price

        # Direction check: a market BUY at price ≥ yes_ask fills our resting ask
        if trade.price < yes_ask - 1e-9:
            return

        # Taker hedge: sell NO at best NO bid
        if not self._no_book or not self._no_book.bids:
            self._result.num_no_hedge_depth += 1
            return

        no_bid = self._no_book.bids[0].price

        # Profitability guard: only execute when combined proceeds > $1 (user condition: "result > 1")
        if yes_ask + no_bid <= 1.0 + 1e-9:
            return

        # Maker fill size on YES ask (FRONT model: min(trade_size, quote_size))
        maker_filled = min(trade.size, decision.ask_size)
        if maker_filled <= 0:
            return

        hedge_available = self._no_book.bids[0].size
        cycle_size = min(maker_filled, hedge_available)
        if cycle_size <= 0:
            return

        self._result.num_fills += 1
        self._record_ask_arb_cycle(
            maker_price=yes_ask,
            taker_price=no_bid,
            size=cycle_size,
            timestamp=trade.timestamp,
            maker_token="YES",
        )
        self._as_tracker.on_fill(yes_ask, trade.timestamp)

    def _check_no_bid_fill(self, trade: Fill, fv: float) -> None:
        """NO bid fill → immediately take YES at best YES ask (taker).

        Arb condition (user-specified): NO_bid + YES_ask < 1.0
        PnL = (1 - NO_bid - YES_ask) * size + NO_maker_rebate - YES_taker_fee

        Only executes when the combined cost is below $1 (profitable before fees).
        """
        no_bid, _no_ask = self._compute_no_quote(fv)
        self._result.hedge_checks_total += 1

        # Check suspension via YES quote (same regime)
        decision = self._compute_quote(fv, trade.timestamp)
        if decision is None or decision.suspend:
            return

        # Direction check: a market SELL at price ≤ no_bid fills our resting NO bid
        if trade.price > no_bid + 1e-9:
            return

        # Taker hedge: buy YES at best YES ask
        if not self._current_book or not self._current_book.asks:
            self._result.num_no_hedge_depth += 1
            return

        yes_ask = self._current_book.asks[0].price

        # Profitability guard: only execute when combined cost < $1 (user condition: "result < 1")
        if no_bid + yes_ask >= 1.0 - 1e-9:
            return

        # Maker fill size on NO
        book_size_at_no_bid = sum(
            lvl.size for lvl in self._no_book.bids
            if abs(lvl.price - no_bid) < 1e-6
        )
        fill_inp = FillModelInput(
            quote_price=no_bid,
            quote_size=self.config.quote_size,
            market_trade_price=trade.price,
            market_trade_size=trade.size,
            book_size_at_price=book_size_at_no_bid,
        )
        maker_filled = self.fill_model.simulate_fill(fill_inp).filled_size
        if maker_filled <= 0:
            return

        hedge_available = self._current_book.asks[0].size
        cycle_size = min(maker_filled, hedge_available)
        if cycle_size <= 0:
            return

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

    def _check_no_ask_fill(self, trade: Fill, fv: float) -> None:
        """NO ask fill → immediately take YES bid (taker sell YES).

        Arb condition (user-specified): NO_ask + YES_bid > 1.0
        PnL = (NO_ask + YES_bid - 1) * size + NO_maker_rebate - YES_taker_fee

        Only executes when combined proceeds exceed $1 (profitable before fees).
        """
        _no_bid, no_ask = self._compute_no_quote(fv)

        decision = self._compute_quote(fv, trade.timestamp)
        if decision is None or decision.suspend:
            return

        # Direction check: a market BUY at price ≥ no_ask fills our resting NO ask
        if trade.price < no_ask - 1e-9:
            return

        # Taker hedge: sell YES at best YES bid
        if not self._current_book or not self._current_book.bids:
            self._result.num_no_hedge_depth += 1
            return

        yes_bid = self._current_book.bids[0].price

        # Profitability guard: only execute when combined proceeds > $1 (user condition: "result > 1")
        if no_ask + yes_bid <= 1.0 + 1e-9:
            return

        # Maker fill size on NO ask (FRONT model)
        maker_filled = min(trade.size, self.config.quote_size)
        if maker_filled <= 0:
            return

        hedge_available = self._current_book.bids[0].size
        cycle_size = min(maker_filled, hedge_available)
        if cycle_size <= 0:
            return

        self._result.num_fills += 1
        self._record_ask_arb_cycle(
            maker_price=no_ask,
            taker_price=yes_bid,
            size=cycle_size,
            timestamp=trade.timestamp,
            maker_token="NO",
        )
        self._as_tracker.on_fill(no_ask, trade.timestamp)

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
        """Record a completed bid-side arb cycle.

        Maker leg: bought maker_token at maker_price (passive fill, receive rebate).
        Taker leg: bought opposing token at taker_price (aggressive fill, pay fee).
        PnL = (1 - maker_price - taker_price) * size + maker_rebate - taker_fee
        """
        gross = (1.0 - maker_price - taker_price) * size
        maker_rebate = self.fee_model.maker_rebate(
            size=size, price=maker_price,
            fee_rate=self.meta.fee_rate,
            rebate_fraction=self.meta.rebate_fraction,
        )
        taker_fee = self.fee_model.taker_fee(
            size=size, price=taker_price,
            fee_rate=self.meta.fee_rate,
        )
        net = gross + maker_rebate - taker_fee

        self._result.total_spread_pnl += net
        self._result.total_rebates_received += maker_rebate
        self._result.total_fees_paid += taker_fee
        self._result.num_cycles_completed += 1
        self._result.num_bid_arb_cycles += 1
        self._result.per_cycle_pnl.append(net)
        if net > 0:
            self._result.num_profitable_cycles += 1

        self.inventory_manager.add_flatten(size, taker_price)

    def _record_ask_arb_cycle(
        self,
        maker_price: float,
        taker_price: float,
        size: float,
        timestamp,
        maker_token: str,
    ) -> None:
        """Record a completed ask-side arb cycle.

        Maker leg: sold maker_token at maker_price (passive fill, receive rebate).
        Taker leg: sold opposing token at taker_price (aggressive fill, pay fee).
        PnL = (maker_price + taker_price - 1) * size + maker_rebate - taker_fee
        """
        gross = (maker_price + taker_price - 1.0) * size
        maker_rebate = self.fee_model.maker_rebate(
            size=size, price=maker_price,
            fee_rate=self.meta.fee_rate,
            rebate_fraction=self.meta.rebate_fraction,
        )
        taker_fee = self.fee_model.taker_fee(
            size=size, price=taker_price,
            fee_rate=self.meta.fee_rate,
        )
        net = gross + maker_rebate - taker_fee

        self._result.total_spread_pnl += net
        self._result.total_rebates_received += maker_rebate
        self._result.total_fees_paid += taker_fee
        self._result.num_cycles_completed += 1
        self._result.num_ask_arb_cycles += 1
        self._result.per_cycle_pnl.append(net)
        if net > 0:
            self._result.num_profitable_cycles += 1

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
