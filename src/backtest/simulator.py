"""
BacktestSimulator — event-driven replay engine.

Processes a stream of OrderBook and Fill events in time order.
On each book update: attempts flatten for any pending inventory.
On each trade event: checks if our resting quote would have been filled (fill model).
When filled: records inventory, triggers hedge assessment.
When book arrives with pending entry: attempts flatten.

Uses the same FeeModel instance as all strategy components.
No separate fee approximations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Union

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


@dataclass
class SimulationResult:
    total_spread_pnl: float = 0.0
    total_skew_pnl: float = 0.0
    total_fees_paid: float = 0.0
    total_rebates_received: float = 0.0
    num_fills: int = 0
    num_book_updates: int = 0
    num_cycles_completed: int = 0

    def total_pnl(self) -> float:
        return self.total_spread_pnl + self.total_skew_pnl


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
        self._pending_entry: _PendingEntry | None = None
        self._as_estimate: float = 0.0
        self._result: SimulationResult = SimulationResult()

    def run(self, events: list[Event]) -> SimulationResult:
        self._result = SimulationResult()
        self._current_book = None
        self._pending_entry = None
        self._as_estimate = 0.0
        for event in events:
            if isinstance(event, OrderBook):
                self._on_book(event)
            elif isinstance(event, Fill):
                self._on_trade(event)
        return self._result

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_book(self, book: OrderBook) -> None:
        self._current_book = book
        self._result.num_book_updates += 1

        # Attempt flatten if we have pending inventory
        if self._pending_entry is not None:
            self._attempt_flatten(book)

    def _on_trade(self, trade: Fill) -> None:
        """Process a market trade observation.

        1. Update FV estimator.
        2. If we have a pending entry, also check whether this trade can flatten it.
        3. Derive strategy quotes and check if the trade would fill our resting bid.
        """
        # 1. Update fair-value estimator with every market trade
        self.fv_estimator.on_trade(
            TradeObservation(price=trade.price, size=trade.size, timestamp=trade.timestamp)
        )

        # 2. Try to flatten an existing pending position via this trade
        if self._pending_entry is not None and self._current_book is not None:
            self._attempt_flatten_via_trade(trade)

        # 3. Only try to acquire new positions if no position is pending
        if self._pending_entry is not None:
            return

        if self._current_book is None:
            return

        fv = self.fv_estimator.estimate(as_of=trade.timestamp)
        if fv is None:
            return

        decision = self._compute_quote(fv, trade.timestamp)
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
        self._pending_entry = _PendingEntry(fill=sim_fill, is_skew=is_skew)

    # ------------------------------------------------------------------
    # Quote computation helpers
    # ------------------------------------------------------------------

    def _compute_quote(self, fv: float, timestamp) -> object | None:
        """Compute QuoteDecision for the current state."""
        inv_state = self.inventory_manager.state()
        regime_inp = RegimeInput(
            timestamp=timestamp,
            inventory=inv_state,
            adverse_selection=self._as_estimate,
            adverse_selection_threshold=self.config.adverse_selection_threshold,
            time_to_resolution_hours=self.config.time_to_resolution_hours,
            pre_resolution_hours=self.config.pre_resolution_hours,
            max_inventory_contracts=self.config.max_inventory_contracts,
            warehouse_threshold_fraction=self.config.warehouse_threshold_fraction,
            fv=fv,
            best_bid=self._current_book.best_bid() if self._current_book else None,
            best_ask=self._current_book.best_ask() if self._current_book else None,
        )
        regime = self.regime_classifier.classify(regime_inp)

        # Provisional bid price for hedgeability check.
        # Uses half_spread_base as approximation; actual bid may differ by regime/fee adjustment.
        provisional_bid = fv - self.quote_engine.half_spread_base
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

    def _attempt_flatten(self, book: OrderBook) -> None:
        """Try to flatten pending entry against the best ask in `book`."""
        if self._pending_entry is None:
            return
        if not book.asks:
            return

        entry = self._pending_entry.fill
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
        self._record_flatten(entry, flatten_price, flatten_size)

    def _attempt_flatten_via_trade(self, trade: Fill) -> None:
        """Try to flatten by treating the incoming trade as a taker opportunity."""
        if self._pending_entry is None:
            return

        entry = self._pending_entry.fill
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
        self._record_flatten(entry, flatten_price, flatten_size)

    def _record_flatten(
        self, entry: Fill, flatten_price: float, flatten_size: float
    ) -> None:
        """Record a flatten, compute PnL, update inventory."""
        cycle = CompletedCycle(
            market_id=self.meta.condition_id,
            entry_price=entry.price,
            entry_size=entry.size,
            flatten_price=flatten_price,
            flatten_size=flatten_size,
            is_skew=self._pending_entry.is_skew if self._pending_entry else False,
        )
        cycle_result = self.pnl_engine.compute_cycle(cycle)
        self._result.total_spread_pnl += cycle_result.spread_pnl
        self._result.total_skew_pnl += cycle_result.skew_pnl
        self._result.total_fees_paid += cycle_result.taker_fee_paid
        self._result.total_rebates_received += cycle_result.maker_rebate_received
        self._result.num_cycles_completed += 1

        self.inventory_manager.add_flatten(flatten_size, flatten_price)
        self._pending_entry = None
