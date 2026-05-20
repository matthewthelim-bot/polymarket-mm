"""
QuoteLoop — per-market live trading loop.

On each YES book update:
  1. Fetch YES + NO books (cached from feed or via REST fallback)
  2. Run exit viability check — skip if not viable
  3. Compute FV from recent trades
  4. Run quote engine to get bid price/size
  5. Manage resting order: cancel stale, place new if price changed
  6. Track open positions and enforce max_concurrent_positions

On fill notification:
  - Immediately attempt exit (place taker sell at best ask or market)
  - Remove position from tracking

Structured log events are emitted for all decisions (never logs credentials).

Design note:
    The quote loop runs synchronously in response to book update callbacks from
    BookFeed. It is designed to be called from a single thread per market.
    The ClobClient methods are blocking HTTP calls.
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.data.schemas import OrderBook, Fill, Side
from src.fee_model import FeeModel
from src.strategy.fair_value import FairValueEstimator, TradeObservation
from src.strategy.regime import RegimeClassifier, RegimeInput
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig
from src.strategy.quote_engine import QuoteEngine, QuoteInput
from src.strategy.inventory import InventoryManager
from src.live.clob_client import ClobClient, OrderRequest, OrderResponse
from src.live.exit_checker import ExitChecker

logger = logging.getLogger(__name__)


@dataclass
class QuoteLoopConfig:
    """Configuration for one market's quote loop."""
    market_id: str           # human-readable identifier (slug or question)
    yes_token_id: str
    no_token_id: str
    condition_id: str

    # Strategy parameters
    fee_rate: float = 0.07
    rebate_fraction: float = 0.5
    half_spread_base: float = 0.030
    min_edge_floor: float = 0.005
    quote_size: float = 100.0
    max_concurrent_positions: int = 1
    time_to_resolution_hours: float = 720.0

    # Exit checker
    max_loss_fraction: float = 0.10      # accept up to 10% loss for YES exit
    min_viable_size: float = 1.0

    # Order management
    price_tolerance: float = 0.005       # re-post if bid moved by more than this
    order_ttl_seconds: float = 300.0     # cancel and re-quote after this duration

    # Risk
    adverse_selection_threshold: float = 0.012
    max_inventory_contracts: float = 500.0
    daily_capital_charge_rate: float = 0.0003
    warehouse_threshold_fraction: float = 0.80
    pre_resolution_hours: float = 4.0

    # Dry run
    dry_run: bool = True                 # NEVER place orders unless False


@dataclass
class _OpenPosition:
    """Tracks a live fill awaiting exit."""
    fill_id: str
    entry_price: float
    size: float
    timestamp: datetime
    exit_order_id: Optional[str] = None


@dataclass
class QuoteLoopStats:
    """Aggregate statistics for one market's quote loop session."""
    book_updates: int = 0
    exit_checks: int = 0
    exit_viable: int = 0
    quotes_computed: int = 0
    orders_placed: int = 0
    orders_cancelled: int = 0
    fills_received: int = 0
    exits_attempted: int = 0
    exits_filled: int = 0
    total_pnl: float = 0.0
    errors: int = 0


class QuoteLoop:
    """
    Live market making loop for a single Polymarket market.

    Args:
        config: QuoteLoopConfig for this market.
        clob_client: Authenticated ClobClient (or unauthenticated for dry_run).
        fee_model: Shared FeeModel instance.
    """

    def __init__(
        self,
        config: QuoteLoopConfig,
        clob_client: ClobClient,
        fee_model: Optional[FeeModel] = None,
    ):
        self.config = config
        self._client = clob_client
        self._fm = fee_model or FeeModel()

        # Strategy components
        self._fv_estimator = FairValueEstimator(twap_window_seconds=300, external_weight=0.0)
        self._regime_classifier = RegimeClassifier()
        self._hedgeability_assessor = HedgeabilityAssessor(
            self._fm, config.fee_rate, config.rebate_fraction, config.min_edge_floor
        )
        self._quote_engine = QuoteEngine(
            self._fm, config.fee_rate, config.rebate_fraction,
            config.half_spread_base, config.min_edge_floor,
        )
        self._inventory_manager = InventoryManager(
            config.yes_token_id, config.daily_capital_charge_rate
        )
        self._skew_config = SkewConfig(
            skew_tolerance=0.0,
            skew_edge_premium=0.005,
            skew_hard_limit=0,
            skew_capital_charge_multiplier=3.0,
            max_skew_notional=0.0,
            current_skew_notional=0.0,
        )
        self._exit_checker = ExitChecker(
            fee_model=self._fm,
            fee_rate=config.fee_rate,
            rebate_fraction=config.rebate_fraction,
            min_edge_floor=config.min_edge_floor,
            max_loss_fraction=config.max_loss_fraction,
            min_viable_size=config.min_viable_size,
        )

        # State
        self._current_yes_book: Optional[OrderBook] = None
        self._current_no_book: Optional[OrderBook] = None
        self._open_positions: list[_OpenPosition] = []
        self._resting_order_id: Optional[str] = None
        self._resting_price: Optional[float] = None
        self._resting_size: Optional[float] = None
        self._resting_placed_at: Optional[float] = None   # time.monotonic()
        self._as_estimate: float = 0.0
        self.stats = QuoteLoopStats()

    # ------------------------------------------------------------------
    # Public entry points (called from BookFeed callbacks)
    # ------------------------------------------------------------------

    def on_yes_book_update(self, token_id: str, yes_book: OrderBook) -> None:
        """
        Called by BookFeed when the YES book for this market updates.
        Fetches the NO book via REST and runs one quote cycle.
        """
        self._current_yes_book = yes_book
        self.stats.book_updates += 1

        # Fetch current NO book (REST call — latency acceptable for MM)
        try:
            self._current_no_book = self._client.get_book(self.config.no_token_id)
        except Exception as exc:
            logger.warning(
                "[%s] Failed to fetch NO book: %s",
                self.config.market_id, exc,
            )
            self.stats.errors += 1
            return

        self._run_cycle()

    def on_no_book_update(self, token_id: str, no_book: OrderBook) -> None:
        """Called when the NO book updates (optional: reduces REST fetches)."""
        self._current_no_book = no_book
        if self._current_yes_book is not None:
            self._run_cycle()

    def on_fill(self, fill: Fill) -> None:
        """
        Called when a fill notification arrives from the CLOB.
        Records the position and immediately attempts exit.
        """
        self.stats.fills_received += 1
        pos = _OpenPosition(
            fill_id=fill.fill_id,
            entry_price=fill.price,
            size=fill.size,
            timestamp=fill.timestamp or datetime.now(timezone.utc),
        )
        self._open_positions.append(pos)
        self._resting_order_id = None  # our resting order was consumed
        self._resting_price = None
        self._resting_size = None

        logger.info(
            "[%s] FILL: entry_price=%.3f size=%.1f | open_positions=%d",
            self.config.market_id, fill.price, fill.size, len(self._open_positions),
        )
        self._try_exit_all()

    # ------------------------------------------------------------------
    # Core cycle
    # ------------------------------------------------------------------

    def _run_cycle(self) -> None:
        """One quote cycle: check exits, then decide whether to (re)quote."""
        now = time.monotonic()

        # Try to exit any pending positions first
        self._try_exit_all()

        # How many concurrent slots are open?
        open_count = len(self._open_positions)
        if self._resting_order_id:
            open_count += 1  # count the resting-but-not-yet-filled order

        if open_count >= self.config.max_concurrent_positions:
            return  # all slots used

        # Get FV (require some trade history)
        fv = self._fv_estimator.estimate(as_of=datetime.now(timezone.utc))
        if fv is None:
            return  # not enough trade history yet

        # Exit viability check
        self.stats.exit_checks += 1
        viability = self._exit_checker.check(
            yes_book=self._current_yes_book,
            no_book=self._current_no_book,
            entry_price=fv - self.config.half_spread_base,
            quote_size=self.config.quote_size,
        )
        if not viability.is_viable:
            logger.debug(
                "[%s] Exit not viable: max_quotable=%.0f (YES=%.0f NO=%.0f)",
                self.config.market_id,
                viability.max_quotable_size,
                viability.yes_exit_size,
                viability.no_exit_size,
            )
            return
        self.stats.exit_viable += 1

        # Compute quote
        decision = self._compute_quote(fv)
        if decision is None or decision.suspend or decision.bid_size <= 0:
            return

        self.stats.quotes_computed += 1

        # Check if existing resting order is still valid
        if self._resting_order_id:
            price_drift = abs(decision.bid_price - (self._resting_price or 0))
            age = now - (self._resting_placed_at or 0)
            if price_drift < self.config.price_tolerance and age < self.config.order_ttl_seconds:
                return  # existing order still good
            # Cancel stale order
            self._cancel_resting()

        # Place new order
        self._place_bid(decision.bid_price, min(decision.bid_size, viability.max_quotable_size))

    # ------------------------------------------------------------------
    # Quote computation
    # ------------------------------------------------------------------

    def _compute_quote(self, fv: float):
        """Compute QuoteDecision for current state."""
        inv_state = self._inventory_manager.state()
        regime_inp = RegimeInput(
            timestamp=datetime.now(timezone.utc),
            inventory=inv_state,
            adverse_selection=self._as_estimate,
            adverse_selection_threshold=self.config.adverse_selection_threshold,
            time_to_resolution_hours=self.config.time_to_resolution_hours,
            pre_resolution_hours=self.config.pre_resolution_hours,
            max_inventory_contracts=self.config.max_inventory_contracts,
            warehouse_threshold_fraction=self.config.warehouse_threshold_fraction,
            fv=fv,
            best_bid=self._current_yes_book.best_bid() if self._current_yes_book else None,
            best_ask=self._current_yes_book.best_ask() if self._current_yes_book else None,
        )
        regime = self._regime_classifier.classify(regime_inp)

        # Provisional bid for hedgeability
        fee_cost = self._fm.fee_flatten_expected(fv, self._hedgeability_assessor.fee_rate)
        actual_half_spread = max(
            self._quote_engine.half_spread_base,
            fee_cost + self._quote_engine.min_edge_floor,
        )
        provisional_bid = fv - actual_half_spread
        hedge_result = self._hedgeability_assessor.assess(
            quote_side=Side.BUY,
            quote_price=provisional_bid,
            quote_size=self.config.quote_size,
            book=self._current_yes_book,
            own_order_ids=set(),
            skew_config=self._skew_config,
        ) if self._current_yes_book else None

        if hedge_result is None:
            return None

        quote_inp = QuoteInput(
            fv=fv,
            regime=regime,
            hedgeability=hedge_result,
            adverse_selection=self._as_estimate,
            quote_size=self.config.quote_size,
        )
        return self._quote_engine.compute(quote_inp)

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def _place_bid(self, price: float, size: float) -> None:
        """Place a resting bid. Logs the intent; skips if dry_run."""
        log_prefix = "[DRY-RUN] " if self.config.dry_run else ""
        logger.info(
            "%s[%s] PLACE BID: price=%.3f size=%.1f",
            log_prefix, self.config.market_id, price, size,
        )

        if self.config.dry_run:
            self.stats.orders_placed += 1
            # Simulate the order being placed (track fake ID)
            self._resting_order_id = f"dry_run_{int(time.time())}"
            self._resting_price = price
            self._resting_size = size
            self._resting_placed_at = time.monotonic()
            return

        try:
            order = OrderRequest(
                token_id=self.config.yes_token_id,
                side=Side.BUY,
                price=price,
                size=size,
            )
            resp = self._client.place_order(order)
            self._resting_order_id = resp.order_id
            self._resting_price = price
            self._resting_size = size
            self._resting_placed_at = time.monotonic()
            self.stats.orders_placed += 1
            logger.info(
                "[%s] ORDER PLACED: id=%s status=%s",
                self.config.market_id, resp.order_id, resp.status,
            )
        except Exception as exc:
            logger.error("[%s] Order placement failed: %s", self.config.market_id, exc)
            self.stats.errors += 1

    def _cancel_resting(self) -> None:
        """Cancel the current resting order if any."""
        if not self._resting_order_id:
            return

        order_id = self._resting_order_id
        self._resting_order_id = None
        self._resting_price = None
        self._resting_size = None
        self._resting_placed_at = None

        if self.config.dry_run:
            logger.debug("[DRY-RUN] [%s] CANCEL order=%s", self.config.market_id, order_id)
            self.stats.orders_cancelled += 1
            return

        try:
            self._client.cancel_order(order_id)
            self.stats.orders_cancelled += 1
            logger.debug("[%s] Order cancelled: %s", self.config.market_id, order_id)
        except Exception as exc:
            logger.warning("[%s] Cancel failed for %s: %s", self.config.market_id, order_id, exc)
            self.stats.errors += 1

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def _try_exit_all(self) -> None:
        """Attempt to exit all open positions against the current NO book."""
        if not self._open_positions or self._current_no_book is None:
            return

        if not self._current_no_book.asks:
            return

        best_no_ask = self._current_no_book.asks[0].price
        exited = []

        for pos in self._open_positions:
            max_flatten = self._fm.max_flatten_price(
                p_fill=pos.entry_price,
                fee_rate=self.config.fee_rate,
                rebate_fraction=self.config.rebate_fraction,
                min_edge_floor=self.config.min_edge_floor,
            )
            if best_no_ask <= max_flatten:
                self._execute_exit(pos, best_no_ask)
                exited.append(pos)

        for pos in exited:
            self._open_positions.remove(pos)

    def _execute_exit(self, pos: _OpenPosition, exit_price: float) -> None:
        """Execute a taker exit for one position (buy NO to flatten YES)."""
        self.stats.exits_attempted += 1
        spread_pnl = (exit_price - (1.0 - pos.entry_price)) * pos.size  # approximate
        log_prefix = "[DRY-RUN] " if self.config.dry_run else ""
        logger.info(
            "%s[%s] EXIT: entry=%.3f exit=%.3f size=%.1f approx_pnl=%.4f",
            log_prefix, self.config.market_id,
            pos.entry_price, exit_price, pos.size, spread_pnl,
        )

        if self.config.dry_run:
            self.stats.exits_filled += 1
            self.stats.total_pnl += spread_pnl
            return

        try:
            order = OrderRequest(
                token_id=self.config.no_token_id,
                side=Side.BUY,
                price=exit_price,
                size=pos.size,
                time_in_force="IOC",   # immediate or cancel
            )
            resp = self._client.place_order(order)
            if resp.filled_size > 0:
                self.stats.exits_filled += 1
                self.stats.total_pnl += spread_pnl
                logger.info(
                    "[%s] EXIT FILLED: filled=%.1f order=%s",
                    self.config.market_id, resp.filled_size, resp.order_id,
                )
            else:
                logger.warning("[%s] Exit order unfilled", self.config.market_id)
        except Exception as exc:
            logger.error("[%s] Exit execution failed: %s", self.config.market_id, exc)
            self.stats.errors += 1
