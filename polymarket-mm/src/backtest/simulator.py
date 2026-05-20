"""
BacktestSimulator — event-driven replay engine.

Processes a stream of OrderBook and Fill events in time order.
On each book update: attempts flatten for any pending inventory.
On each trade event: checks if our resting quote would have been filled (fill model).
When filled: records inventory, triggers hedge assessment.
When book arrives with pending entry: attempts flatten.

Iceberg / concurrent positions:
    SimulatorConfig.max_concurrent_positions controls how many independent
    resting slices we can hold simultaneously (default 1 = classic single-entry).
    With max_concurrent_positions=N the simulator keeps re-quoting a new slice
    as long as open_positions < N, simulating an iceberg order that always
    shows a fresh small quote to the market.

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
    max_concurrent_positions: int = 1       # iceberg slices: always re-quote until this many open


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
    # Extended analytics (added fields — all default to zero/empty for backward compatibility)
    num_profitable_cycles: int = 0          # cycles with net_pnl > 0
    hedge_accessible_count: int = 0         # quote attempts where hedge depth was found
    hedge_checks_total: int = 0             # total hedge checks (FV available + book present)
    per_cycle_pnl: list = field(default_factory=list)  # net PnL per completed cycle
    as_events_measured: int = 0             # fills with a completed AS measurement
    as_rate: float = 0.0                    # fraction classified as adverse
    num_stale_quote_skips: int = 0          # fill checks skipped due to FV jump

    def total_pnl(self) -> float:
        return self.total_spread_pnl + self.total_skew_pnl

    def win_rate(self) -> float:
        """Fraction of completed cycles that were profitable."""
        if self.num_cycles_completed == 0:
            return 0.0
        return self.num_profitable_cycles / self.num_cycles_completed

    def hedge_accessibility(self) -> float:
        """Fraction of quoting opportunities that had hedgeable depth."""
        if self.hedge_checks_total == 0:
            return 0.0
        return self.hedge_accessible_count / self.hedge_checks_total


@dataclass
class _PendingEntry:
    """Tracks a passive fill awaiting a hedge/flatten."""
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

        self._current_book: OrderBook | None = None
        self._pending_entries: list[_PendingEntry] = []
        self._as_estimate: float = 0.0
        self._last_fv: float | None = None
        self._as_tracker = AdverseSelectionTracker(
            window_seconds=config.adverse_selection_window_seconds,
            adverse_threshold=config.adverse_selection_adverse_threshold,
        )
        self._result: SimulationResult = SimulationResult()

    def run(self, events: list[Event]) -> SimulationResult:
        self._result = SimulationResult()
        self._current_book = None
        self._pending_entries = []
        self._as_estimate = 0.0
        self._last_fv = None
        self._as_tracker = AdverseSelectionTracker(
            window_seconds=self.config.adverse_selection_window_seconds,
            adverse_threshold=self.config.adverse_selection_adverse_threshold,
        )
        for event in events:
            if isinstance(event, OrderBook):
                self._on_book(event)
            elif isinstance(event, Fill):
                self._on_trade(event)

        # Record unrealized open positions (positions that never flattened)
        self._result.num_open_positions = len(self._pending_entries)

        # Finalize adverse-selection stats
        stats = self._as_tracker.stats()
        self._result.as_events_measured = stats["num_measured"]
        self._result.as_rate = stats["as_rate"]

        return self._result

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_book(self, book: OrderBook) -> None:
        self._current_book = book
        self._result.num_book_updates += 1

        # Attempt flatten for each open iceberg slice
        for entry_obj in list(self._pending_entries):
            self._attempt_flatten(book, entry_obj)

    def _on_trade(self, trade: Fill) -> None:
        """Process a market trade observation.

        Correct real-world ordering:
        1. Check fills/flattens against CURRENT resting-order prices (pre-trade FV).
        2. THEN update FV with the incoming trade price.
        3. Update AS tracker and re-estimate adverse selection.

        A resting order is posted at a fixed price computed from FV *before* this trade
        arrives. Checking fills after absorbing the trade would use a stale price.
        """
        # 1a. Try to flatten each open iceberg slice via this trade (pre-FV-update)
        if self._current_book is not None:
            for entry_obj in list(self._pending_entries):
                self._attempt_flatten_via_trade(trade, entry_obj)

        # 1b. If below max concurrent positions, check whether this trade fills a new slice.
        open_count = len(self._pending_entries)
        if open_count < self.config.max_concurrent_positions and self._current_book is not None:
            fv = self.fv_estimator.estimate(as_of=trade.timestamp)
            if fv is not None:
                # Staleness check: skip fill if FV jumped since last check
                threshold = self.config.quote_staleness_threshold
                if threshold > 0 and self._last_fv is not None:
                    if abs(fv - self._last_fv) > threshold:
                        self._result.num_stale_quote_skips += 1
                        self._last_fv = None  # reset so only first post-jump trade is skipped
                    else:
                        self._check_fill(trade, fv)
                        self._last_fv = fv
                else:
                    self._check_fill(trade, fv)
                    self._last_fv = fv

        # 2. Update fair-value estimator AFTER fill check (correct information order)
        self.fv_estimator.on_trade(
            TradeObservation(price=trade.price, size=trade.size, timestamp=trade.timestamp)
        )

        # 3. Advance AS tracker; update rolling estimate
        self._as_tracker.on_trade(trade.price, trade.timestamp)
        self._as_estimate = self._as_tracker.estimate()

    def _check_fill(self, trade: Fill, fv: float) -> None:
        """Check whether a market trade fills our resting bid (pre-FV-update state)."""
        decision = self._compute_quote(fv, trade.timestamp)
        # Track hedge accessibility: count how often the book had hedgeable depth
        self._result.hedge_checks_total += 1
        if decision is not None and not decision.suspend and decision.bid_size > 0:
            self._result.hedge_accessible_count += 1
        if decision is None or decision.suspend or decision.bid_size == 0:
            return

        # Check if market trade hits our bid
        book_size_at_bid = sum(
            lvl.size for lvl in self._current_book.bids
            if abs(lvl.price - decision.bid_price) < 1e-6
        )
        fill_inp = FillModelInput(
            quote_price=decision.bid_price,
            quote_size=decision.bid_size,
            market_trade_price=trade.price,
            market_trade_size=trade.size,
            book_size_at_price=book_size_at_bid,
        )
        fill_result = self.fill_model.simulate_fill(fill_inp)

        if fill_result.filled_size <= 0:
            return

        # Record the fill
        self._result.num_fills += 1

        # Determine skew classification
        hedge_result = self._assess_hedgeability(decision.bid_price, fill_result.filled_size)
        # Simplification: classify entire fill as skew only when no hedge is available.
        # Partial hedges (hedgeable_size > 0 but < fill_size) are attributed to spread.
        # Full two-bucket split is a future improvement.
        is_skew = hedge_result.hedgeable_size == 0 and hedge_result.skew_accepted > 0

        sim_fill = Fill(
            fill_id=f"sim_{trade.fill_id}",
            market_id=self.meta.condition_id,
            side=Side.BUY,
            price=decision.bid_price,
            size=fill_result.filled_size,
            timestamp=trade.timestamp,
            is_maker=True,
        )
        self.inventory_manager.add_fill(sim_fill, is_skew=is_skew)
        self._pending_entries.append(_PendingEntry(fill=sim_fill, is_skew=is_skew))
        self._as_tracker.on_fill(sim_fill.price, sim_fill.timestamp)

    # ------------------------------------------------------------------
    # Quote computation helpers
    # ------------------------------------------------------------------

    def _compute_quote(self, fv: float, timestamp) -> object | None:
        """Compute QuoteDecision for the current state."""
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

        # Provisional bid price for hedgeability check.
        # Use fee-adjusted half-spread (same formula as QuoteEngine) so the hedgeability
        # threshold matches the actual bid price the engine will compute.
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

    def _assess_hedgeability(self, quote_price: float, quote_size: float):
        """Run HedgeabilityAssessor for the given price/size."""
        book = self._current_book
        if book is None:
            # No book: assume nothing is hedgeable
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
    # Flatten logic
    # ------------------------------------------------------------------

    def _attempt_flatten(self, book: OrderBook, entry_obj: _PendingEntry) -> None:
        """Try to flatten a single iceberg slice against the best ask in `book`."""
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
            return  # not yet profitable

        flatten_size = min(entry.size, book.asks[0].size)
        if flatten_size <= 0:
            return
        self._record_flatten(entry_obj, flatten_price, flatten_size)

    def _attempt_flatten_via_trade(self, trade: Fill, entry_obj: _PendingEntry) -> None:
        """Try to flatten a single slice by treating the incoming trade as a taker opportunity."""
        entry = entry_obj.fill
        p_max = self.fee_model.max_flatten_price(
            p_fill=entry.price,
            fee_rate=self.meta.fee_rate,
            rebate_fraction=self.meta.rebate_fraction,
            min_edge_floor=0.005,
        )
        # A BUY trade means someone is taking ask liquidity — we can also flatten
        # (taker-buy No side) if there's depth visible in the book.
        # For simplicity we use the book's best ask as the flatten price.
        if self._current_book is None or not self._current_book.asks:
            return
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
        """Record a flatten for one iceberg slice, compute PnL, update inventory."""
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
        self._pending_entries.remove(entry_obj)
