"""
QuoteLoop — per-market live trading loop implementing maker-taker arb.

Rests 4 orders simultaneously: YES bid, YES ask, NO bid, NO ask.
When any maker order fills, immediately hedges with a taker order on the
opposing token to lock in the spread.

Fill handling (the critical path):
  YES bid fills → cancel NO bid → if cancelled: taker BUY NO (IOC)
                                → if cancel rejected (already filled): maker-maker cycle

  NO bid fills  → cancel YES bid → if cancelled: taker BUY YES (IOC)
                                 → if cancel rejected: maker-maker cycle

  YES ask fills → cancel NO ask  → if cancelled: taker SELL NO (IOC)
                                 → if cancel rejected: maker-maker cycle

  NO ask fills  → cancel YES ask → if cancelled: taker SELL YES (IOC)
                                 → if cancel rejected: maker-maker cycle

If cancel is rejected (return False), the opposing order likely already filled
independently — producing a maker-maker cycle which is MORE profitable (two
maker rebates instead of one rebate minus a taker fee). No taker needed.

If the taker hedge is not profitable at current book prices, the fill is
recorded as an open position and re-tried on every subsequent book update.

Structured log events are emitted for all decisions. Credentials are never
logged, printed, or included in any log event.
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

    # Strategy parameters — fee_rate/rebate_fraction should be set per market
    # from Gamma's feeSchedule (fees are PER-CATEGORY: crypto 0.07/20%,
    # sports 0.03/25%, politics-finance 0.04/25%, geopolitics free).
    # Defaults are the worst case: highest fee, lowest rebate share.
    fee_rate: float = 0.07
    rebate_fraction: float = 0.20
    half_spread_base: float = 0.030
    min_edge_floor: float = 0.005
    quote_size: float = 100.0
    time_to_resolution_hours: float = 720.0

    # Ladder quoting — anchored to best bid/ask, ascending size going deeper.
    # Re-post on fill happens automatically: every on_fill() calls _run_cycle()
    # which immediately re-posts any empty slot at the current market price.
    ladder_levels: int = 5
    ladder_offset_from_best: float = 0.030  # L0 sits this far below best bid / above best ask
    ladder_tick_spacing: float = 0.010       # price gap between consecutive levels
    # Sizes ascend with depth: small near market (less capital at risk, fills more easily),
    # large deep (absorbs big sweeps). Multiplied by quote_size.
    ladder_size_ratios: list = field(default_factory=lambda: [1.0, 1.5, 2.0, 2.5, 3.0])

    # Order management
    price_tolerance: float = 0.010       # re-post only if quote drifted by more than this (1 tick)
    order_ttl_seconds: float = 300.0     # cancel and re-quote after this duration
    min_reprice_interval: float = 30.0   # minimum seconds between reprices per slot (reduces API churn)

    # Iceberg orders — hide total capacity from the market.
    # When > 0, each ladder level posts only `iceberg_display_size` contracts
    # visibly.  After a display-size fill, the hidden reserve is re-posted at
    # the same price until the full level_size is consumed.
    # 0 = disabled (full size shown — current behaviour).
    # Typical value: 50–100 contracts.
    iceberg_display_size: float = 0.0

    # Notional exposure cap per direction.
    # When cumulative long notional reaches this, pull bids but keep asks live to close longs.
    # When short notional reaches this, pull asks but keep bids live to close shorts.
    # Set to 0 to disable.
    max_open_notional: float = 2000.0

    # Portfolio-level context for cross-market caps.
    # days_to_resolution: days until market resolves (used by PortfolioConstraints).
    # event_key: groups sub-markets of the same parent event (use end_date_iso).
    days_to_resolution: int = 9999
    event_key: str = ""

    # Risk
    adverse_selection_threshold: float = 0.012
    max_inventory_contracts: float = 500.0
    daily_capital_charge_rate: float = 0.0003
    warehouse_threshold_fraction: float = 0.80
    pre_resolution_hours: float = 4.0
    max_open_positions: int = 4          # max unhedged fills before pausing new quotes

    # Exit checker (for open-position retry)
    max_loss_fraction: float = 0.10
    min_viable_size: float = 1.0

    # Dry run
    dry_run: bool = True                 # NEVER place orders unless False


@dataclass
class _RestingOrder:
    """Tracks one resting order (bid or ask) on one token."""
    order_id: str
    token_id: str
    side: Side               # BUY = bid, SELL = ask
    price: float
    size: float              # currently displayed size on the book
    placed_at: float         # time.monotonic()
    token_side: str          # "YES" or "NO"
    order_side: str          # "bid" or "ask"
    level: int = 0           # ladder level index (0 = closest to FV)
    last_reprice_at: float = 0.0  # time.monotonic() of most recent cancel+replace
    # Iceberg tracking: full hidden capacity at this price level.
    # 0 means no iceberg (full size was displayed).
    # After each display-size fill, remaining_hidden is decremented and a new
    # display order is re-posted until remaining_hidden drops to zero.
    remaining_hidden: float = 0.0


@dataclass
class _OpenPosition:
    """Tracks a fill where taker hedge was not yet sent."""
    fill_type: str           # "yes_bid", "yes_ask", "no_bid", "no_ask"
    maker_price: float
    size: float
    timestamp: datetime
    attempts: int = 0        # number of hedge retry attempts


@dataclass
class QuoteLoopStats:
    """Aggregate statistics for one market's quote loop session."""
    book_updates: int = 0
    quotes_computed: int = 0
    orders_placed: int = 0
    orders_cancelled: int = 0
    fills_received: int = 0
    takers_sent: int = 0
    takers_filled: int = 0
    maker_maker_cycles: int = 0
    open_positions: int = 0
    unroutable_fills: int = 0    # fills moved to the dead-letter list (reconcile manually)
    total_pnl: float = 0.0
    errors: int = 0


class QuoteLoop:
    """
    Live market-making loop implementing the maker-taker arb model.

    Maintains 4 resting orders (YES bid, YES ask, NO bid, NO ask) and
    hedges each maker fill immediately with a taker order on the opposing token.

    Args:
        config: QuoteLoopConfig for this market.
        clob_client: Authenticated ClobClient (or unauthenticated for dry_run).
        fee_model: Shared FeeModel instance.
    """

    # Book updates an unroutable (unknown_*) fill may wait before being moved
    # to the dead-letter list. At one update per second this is ~5 minutes.
    UNROUTABLE_MAX_ATTEMPTS = 300

    def __init__(
        self,
        config: QuoteLoopConfig,
        clob_client: ClobClient,
        fee_model: Optional[FeeModel] = None,
        portfolio=None,   # Optional[PortfolioConstraints] — avoids circular import
    ):
        self.config = config
        self._client = clob_client
        self._fm = fee_model or FeeModel()
        self._portfolio = portfolio  # shared cross-market constraints (may be None)

        # Strategy components
        self._fv_estimator = FairValueEstimator(twap_window_seconds=14400, external_weight=0.0)
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

        # Live books
        self._current_yes_book: Optional[OrderBook] = None
        self._current_no_book: Optional[OrderBook] = None

        # Ladder resting orders — list[level] for each of the 4 sides.
        # Index 0 = closest to FV (smallest size), index N-1 = deepest (largest size).
        n = config.ladder_levels
        self._yes_bids: list[Optional[_RestingOrder]] = [None] * n
        self._yes_asks: list[Optional[_RestingOrder]] = [None] * n
        self._no_bids:  list[Optional[_RestingOrder]] = [None] * n
        self._no_asks:  list[Optional[_RestingOrder]] = [None] * n

        # Fills where the taker hedge hasn't been sent yet
        self._open_positions: list[_OpenPosition] = []
        # Dead-letter list: unroutable fills (unknown_*) that exhausted their
        # retry budget. They hold REAL exposure but cannot be auto-hedged
        # (token/side unknown) — parked here so they stop blocking
        # max_open_positions, surfaced via stats and error logs for manual
        # reconciliation against the account's position page.
        self._unroutable_fills: list[_OpenPosition] = []

        # Notional exposure tracking per direction.
        # Incremented on each completed bid-arb (long) or ask-arb (short) cycle.
        # Decremented when the opposing direction closes the position.
        # Bids are suppressed when _long_notional >= max_open_notional;
        # asks are suppressed when _short_notional >= max_open_notional.
        self._long_notional: float = 0.0
        self._short_notional: float = 0.0

        self._as_estimate: float = 0.0
        self._last_fv: Optional[float] = None
        self.stats = QuoteLoopStats()

    # ------------------------------------------------------------------
    # Public entry points (called from BookFeed callbacks)
    # ------------------------------------------------------------------

    # Max age of the WS-delivered NO book before we fall back to a REST
    # fetch. The NO token has its own WS subscription (on_no_book_update);
    # a blocking REST call on EVERY YES tick would stall the shared feed
    # thread for all markets — up to 10s per timeout — exactly when books
    # move fastest (e.g. a goal in a soccer match).
    NO_BOOK_STALE_SECONDS = 30.0

    def snapshot(self) -> dict:
        """JSON-safe operational snapshot for the live status monitor."""
        return {
            "market": self.config.market_id[:60],
            "condition_id": self.config.condition_id,
            "book_updates": self.stats.book_updates,
            "orders_placed": self.stats.orders_placed,
            "orders_cancelled": self.stats.orders_cancelled,
            "fills": self.stats.fills_received,
            "takers_sent": self.stats.takers_sent,
            "takers_filled": self.stats.takers_filled,
            "maker_maker_cycles": self.stats.maker_maker_cycles,
            "open_unhedged": len(self._open_positions),
            "unroutable": self.stats.unroutable_fills,
            "errors": self.stats.errors,
            "pnl": round(self.stats.total_pnl, 4),
            "long_notional": round(self._long_notional, 2),
            "short_notional": round(self._short_notional, 2),
            "last_fv": round(self._last_fv, 4) if self._last_fv is not None else None,
        }

    def on_yes_book_update(self, token_id: str, yes_book: OrderBook) -> None:
        """YES book updated — run one quote cycle using the WS-fed NO book."""
        self._current_yes_book = yes_book
        self.stats.book_updates += 1
        no_book = self._current_no_book
        no_age = None
        if no_book is not None:
            no_ts = no_book.timestamp
            if no_ts.tzinfo is None:
                no_ts = no_ts.replace(tzinfo=timezone.utc)
            no_age = (datetime.now(timezone.utc) - no_ts).total_seconds()
        if no_book is None or no_age is None or no_age > self.NO_BOOK_STALE_SECONDS:
            # Fallback only: WS hasn't delivered a (recent) NO book. Rate-limit
            # so a quiet (but valid) NO book doesn't trigger REST every tick.
            now_mono = time.monotonic()
            if now_mono - getattr(self, "_last_no_rest_fetch", 0.0) >= 5.0:
                self._last_no_rest_fetch = now_mono
                try:
                    self._current_no_book = self._client.get_book(self.config.no_token_id)
                except Exception as exc:
                    logger.warning("[%s] Failed to fetch NO book: %s", self.config.market_id, exc)
                    self.stats.errors += 1
                    return
            elif no_book is None:
                return  # nothing usable yet and fetch is rate-limited
        # Retry any open positions now that books are fresh
        self._retry_open_positions()
        self._run_cycle()

    def on_no_book_update(self, token_id: str, no_book: OrderBook) -> None:
        """NO book updated directly (reduces REST round-trips when subscribed to both)."""
        self._current_no_book = no_book
        self._retry_open_positions()
        if self._current_yes_book is not None:
            self._run_cycle()

    def on_trade(self, token_id: str, price: float, size: float) -> None:
        """Market trade on this market — update fair value estimator.

        Only YES token trades update the FV estimator; NO token trades are
        ignored here because the FV is expressed in YES-token probability space.
        """
        if token_id == self.config.yes_token_id:
            self._fv_estimator.on_trade(
                TradeObservation(price=price, size=size, timestamp=datetime.now(timezone.utc))
            )

    def on_fill(self, fill: Fill) -> None:
        """
        A fill notification for one of our resting orders.

        Routes to the correct handler based on which order was hit:
          - Matched by fill.token_side + price proximity to our resting order.
          - If a fill can't be routed, logs a warning and records as open position.
        """
        self.stats.fills_received += 1
        logger.info(
            "[%s] FILL received: token_side=%s side=%s price=%.3f size=%.1f",
            self.config.market_id,
            fill.token_side, fill.side.value if fill.side else "?",
            fill.price, fill.size,
        )

        order_key = self._identify_filled_order(fill)
        # order_key format: "<side>_<level>" e.g. "yes_bid_0", "no_ask_2"

        if order_key.startswith("yes_bid_"):
            level = int(order_key.rsplit("_", 1)[1])
            filled_order = self._yes_bids[level]
            self._yes_bids[level] = None
            self._handle_yes_bid_fill(fill.price, fill.size)
            # Iceberg: re-post next slice at same price if hidden reserve remains
            if filled_order and filled_order.remaining_hidden > 0.5:
                self._repost_iceberg_slice(self._yes_bids, level, filled_order)
        elif order_key.startswith("yes_ask_"):
            level = int(order_key.rsplit("_", 1)[1])
            filled_order = self._yes_asks[level]
            self._yes_asks[level] = None
            self._handle_yes_ask_fill(fill.price, fill.size)
            if filled_order and filled_order.remaining_hidden > 0.5:
                self._repost_iceberg_slice(self._yes_asks, level, filled_order)
        elif order_key.startswith("no_bid_"):
            level = int(order_key.rsplit("_", 1)[1])
            filled_order = self._no_bids[level]
            self._no_bids[level] = None
            self._handle_no_bid_fill(fill.price, fill.size)
            if filled_order and filled_order.remaining_hidden > 0.5:
                self._repost_iceberg_slice(self._no_bids, level, filled_order)
        elif order_key.startswith("no_ask_"):
            level = int(order_key.rsplit("_", 1)[1])
            filled_order = self._no_asks[level]
            self._no_asks[level] = None
            self._handle_no_ask_fill(fill.price, fill.size)
            if filled_order and filled_order.remaining_hidden > 0.5:
                self._repost_iceberg_slice(self._no_asks, level, filled_order)
        else:
            logger.warning(
                "[%s] Could not route fill (token_side=%s price=%.3f) — recording as open",
                self.config.market_id, fill.token_side, fill.price,
            )
            self._open_positions.append(_OpenPosition(
                fill_type=f"unknown_{fill.token_side}",
                maker_price=fill.price,
                size=fill.size,
                timestamp=fill.timestamp or datetime.now(timezone.utc),
            ))

        # Re-quote all 4 sides after any fill
        self._run_cycle()

    # ------------------------------------------------------------------
    # Fill handlers — the maker-taker critical path
    # ------------------------------------------------------------------

    def _cancel_ladder(
        self, ladder: list[Optional[_RestingOrder]], label_prefix: str
    ) -> bool:
        """
        Cancel every resting order in a ladder list.

        Returns True if ALL cancels succeeded (or nothing was resting).
        Returns False if ANY cancel failed (opposing order likely already filled).
        Sets cancelled slots to None regardless.
        """
        all_ok = True
        for i, order in enumerate(ladder):
            if order is not None:
                ok = self._cancel_resting(order, label=f"{label_prefix}_L{i}")
                ladder[i] = None
                if not ok:
                    all_ok = False
        return all_ok

    def _handle_yes_bid_fill(self, maker_price: float, size: float) -> None:
        """YES BID filled (any ladder level): cancel ALL NO bids → taker BUY NO."""
        logger.info(
            "[%s] YES BID FILL @ %.3f x %.1f — cancelling NO bid ladder, sending taker BUY NO",
            self.config.market_id, maker_price, size,
        )
        all_cancelled = self._cancel_ladder(self._no_bids, "NO bid")
        if all_cancelled:
            self._send_taker(
                fill_type="yes_bid",
                maker_price=maker_price,
                size=size,
                hedge_token=self.config.no_token_id,
                hedge_side=Side.BUY,
                book=self._current_no_book,
                get_hedge_price=lambda b: b.asks[0].price if b and b.asks else None,
                is_profitable=lambda mp, hp: mp + hp < 1.0,
            )
        else:
            # At least one NO bid level also filled — maker-maker cycle on that pair
            self._record_maker_maker_cycle("yes_bid + no_bid", maker_price)

    def _handle_no_bid_fill(self, maker_price: float, size: float) -> None:
        """NO BID filled (any ladder level): cancel ALL YES bids → taker BUY YES."""
        logger.info(
            "[%s] NO BID FILL @ %.3f x %.1f — cancelling YES bid ladder, sending taker BUY YES",
            self.config.market_id, maker_price, size,
        )
        all_cancelled = self._cancel_ladder(self._yes_bids, "YES bid")
        if all_cancelled:
            self._send_taker(
                fill_type="no_bid",
                maker_price=maker_price,
                size=size,
                hedge_token=self.config.yes_token_id,
                hedge_side=Side.BUY,
                book=self._current_yes_book,
                get_hedge_price=lambda b: b.asks[0].price if b and b.asks else None,
                is_profitable=lambda mp, hp: mp + hp < 1.0,
            )
        else:
            self._record_maker_maker_cycle("no_bid + yes_bid", maker_price)

    def _handle_yes_ask_fill(self, maker_price: float, size: float) -> None:
        """YES ASK filled (any ladder level): cancel ALL NO asks → taker SELL NO."""
        logger.info(
            "[%s] YES ASK FILL @ %.3f x %.1f — cancelling NO ask ladder, sending taker SELL NO",
            self.config.market_id, maker_price, size,
        )
        all_cancelled = self._cancel_ladder(self._no_asks, "NO ask")
        if all_cancelled:
            self._send_taker(
                fill_type="yes_ask",
                maker_price=maker_price,
                size=size,
                hedge_token=self.config.no_token_id,
                hedge_side=Side.SELL,
                book=self._current_no_book,
                get_hedge_price=lambda b: b.bids[0].price if b and b.bids else None,
                is_profitable=lambda mp, hp: mp + hp > 1.0,
            )
        else:
            self._record_maker_maker_cycle("yes_ask + no_ask", maker_price)

    def _handle_no_ask_fill(self, maker_price: float, size: float) -> None:
        """NO ASK filled (any ladder level): cancel ALL YES asks → taker SELL YES."""
        logger.info(
            "[%s] NO ASK FILL @ %.3f x %.1f — cancelling YES ask ladder, sending taker SELL YES",
            self.config.market_id, maker_price, size,
        )
        all_cancelled = self._cancel_ladder(self._yes_asks, "YES ask")
        if all_cancelled:
            self._send_taker(
                fill_type="no_ask",
                maker_price=maker_price,
                size=size,
                hedge_token=self.config.yes_token_id,
                hedge_side=Side.SELL,
                book=self._current_yes_book,
                get_hedge_price=lambda b: b.bids[0].price if b and b.bids else None,
                is_profitable=lambda mp, hp: mp + hp > 1.0,
            )
        else:
            self._record_maker_maker_cycle("no_ask + yes_ask", maker_price)

    # ------------------------------------------------------------------
    # Taker execution
    # ------------------------------------------------------------------

    def _send_taker(
        self,
        fill_type: str,
        maker_price: float,
        size: float,
        hedge_token: str,
        hedge_side: Side,
        book: Optional[OrderBook],
        get_hedge_price,
        is_profitable,
    ) -> None:
        """
        Send an IOC taker order to hedge a maker fill.

        get_hedge_price: callable(book) -> float | None
        is_profitable:   callable(maker_price, hedge_price) -> bool
        """
        self.stats.takers_sent += 1

        hedge_price = get_hedge_price(book) if book else None
        if hedge_price is None:
            logger.warning(
                "[%s] No hedge depth for %s fill — recording as open position",
                self.config.market_id, fill_type,
            )
            self._open_positions.append(_OpenPosition(
                fill_type=fill_type, maker_price=maker_price,
                size=size, timestamp=datetime.now(timezone.utc),
            ))
            self.stats.open_positions += 1
            return

        if not is_profitable(maker_price, hedge_price):
            logger.info(
                "[%s] Taker hedge unprofitable (%.3f + %.3f = %.3f) — open position",
                self.config.market_id, maker_price, hedge_price,
                maker_price + hedge_price,
            )
            self._open_positions.append(_OpenPosition(
                fill_type=fill_type, maker_price=maker_price,
                size=size, timestamp=datetime.now(timezone.utc),
            ))
            self.stats.open_positions += 1
            return

        log_prefix = "[DRY-RUN] " if self.config.dry_run else ""
        logger.info(
            "%s[%s] TAKER HEDGE %s: %s %s @ %.3f x %.1f  arb=%.4f",
            log_prefix, self.config.market_id, fill_type,
            hedge_side.value, "YES" if hedge_token == self.config.yes_token_id else "NO",
            hedge_price, size,
            abs(1.0 - maker_price - hedge_price),
        )

        if self.config.dry_run:
            self._record_cycle_pnl(fill_type, maker_price, hedge_price, size)
            self.stats.takers_filled += 1
            return

        try:
            req = OrderRequest(
                token_id=hedge_token,
                side=hedge_side,
                price=hedge_price,
                size=size,
                time_in_force="IOC",
            )
            resp = self._client.place_order(req)
            if resp.filled_size > 0:
                self._record_cycle_pnl(fill_type, maker_price, hedge_price, resp.filled_size)
                self.stats.takers_filled += 1
                logger.info(
                    "[%s] TAKER FILLED: filled=%.1f order=%s",
                    self.config.market_id, resp.filled_size, resp.order_id,
                )
                # Partial fill: open position for remainder
                remainder = size - resp.filled_size
                if remainder > self.config.min_viable_size:
                    self._open_positions.append(_OpenPosition(
                        fill_type=fill_type, maker_price=maker_price,
                        size=remainder, timestamp=datetime.now(timezone.utc),
                    ))
                    self.stats.open_positions += 1
            else:
                logger.warning("[%s] Taker IOC unfilled — open position", self.config.market_id)
                self._open_positions.append(_OpenPosition(
                    fill_type=fill_type, maker_price=maker_price,
                    size=size, timestamp=datetime.now(timezone.utc),
                ))
                self.stats.open_positions += 1
        except Exception as exc:
            logger.error("[%s] Taker execution failed: %s", self.config.market_id, exc)
            self._open_positions.append(_OpenPosition(
                fill_type=fill_type, maker_price=maker_price,
                size=size, timestamp=datetime.now(timezone.utc),
            ))
            self.stats.open_positions += 1
            self.stats.errors += 1

    def _retry_open_positions(self) -> None:
        """
        Re-attempt taker hedges for open positions on each book update.
        Positions are retried until the hedge becomes profitable or they expire.
        """
        if not self._open_positions:
            return

        still_open: list[_OpenPosition] = []
        for pos in self._open_positions:
            pos.attempts += 1
            # Route to correct books/hedge based on fill_type
            if pos.fill_type == "yes_bid":
                book = self._current_no_book
                hedge_token = self.config.no_token_id
                hedge_side = Side.BUY
                get_price = lambda b: b.asks[0].price if b and b.asks else None
                is_profitable = lambda mp, hp: mp + hp < 1.0
            elif pos.fill_type == "no_bid":
                book = self._current_yes_book
                hedge_token = self.config.yes_token_id
                hedge_side = Side.BUY
                get_price = lambda b: b.asks[0].price if b and b.asks else None
                is_profitable = lambda mp, hp: mp + hp < 1.0
            elif pos.fill_type == "yes_ask":
                book = self._current_no_book
                hedge_token = self.config.no_token_id
                hedge_side = Side.SELL
                get_price = lambda b: b.bids[0].price if b and b.bids else None
                is_profitable = lambda mp, hp: mp + hp > 1.0
            elif pos.fill_type == "no_ask":
                book = self._current_yes_book
                hedge_token = self.config.yes_token_id
                hedge_side = Side.SELL
                get_price = lambda b: b.bids[0].price if b and b.bids else None
                is_profitable = lambda mp, hp: mp + hp > 1.0
            else:
                # Unroutable (unknown_*) — can never match a hedge route.
                # Give it a bounded retry budget in case a later code path
                # learns to route it, then park it in the dead-letter list so
                # it stops counting against max_open_positions forever.
                if pos.attempts >= self.UNROUTABLE_MAX_ATTEMPTS:
                    self._unroutable_fills.append(pos)
                    self.stats.unroutable_fills += 1
                    logger.error(
                        "[%s] UNROUTABLE FILL parked after %d attempts: %s "
                        "price=%.3f size=%.1f — REAL exposure, RECONCILE "
                        "MANUALLY against the account position page",
                        self.config.market_id, pos.attempts, pos.fill_type,
                        pos.maker_price, pos.size,
                    )
                else:
                    still_open.append(pos)
                continue

            hedge_price = get_price(book)
            if hedge_price is None or not is_profitable(pos.maker_price, hedge_price):
                still_open.append(pos)
                continue

            # Profitable hedge available — execute
            logger.info(
                "[%s] RETRY HEDGE %s (attempt %d): %.3f + %.3f = %.3f",
                self.config.market_id, pos.fill_type, pos.attempts,
                pos.maker_price, hedge_price, pos.maker_price + hedge_price,
            )
            if self.config.dry_run:
                self._record_cycle_pnl(pos.fill_type, pos.maker_price, hedge_price, pos.size)
                self.stats.takers_filled += 1
                continue

            try:
                req = OrderRequest(
                    token_id=hedge_token,
                    side=hedge_side,
                    price=hedge_price,
                    size=pos.size,
                    time_in_force="IOC",
                )
                resp = self._client.place_order(req)
                if resp.filled_size > 0:
                    self._record_cycle_pnl(pos.fill_type, pos.maker_price, hedge_price, resp.filled_size)
                    self.stats.takers_filled += 1
                    if pos.size - resp.filled_size > self.config.min_viable_size:
                        pos.size -= resp.filled_size
                        still_open.append(pos)
                else:
                    still_open.append(pos)
            except Exception as exc:
                logger.error("[%s] Retry hedge failed: %s", self.config.market_id, exc)
                still_open.append(pos)
                self.stats.errors += 1

        self._open_positions = still_open
        self.stats.open_positions = len(still_open)

    # ------------------------------------------------------------------
    # Quote cycle — maintain 4 resting orders
    # ------------------------------------------------------------------

    def _run_cycle(self) -> None:
        """Compute quotes and maintain all 4 resting orders."""
        if self._current_yes_book is None or self._current_no_book is None:
            return

        # Pause new quotes if too many unhedged taker-hedge positions
        if len(self._open_positions) >= self.config.max_open_positions:
            logger.warning(
                "[%s] Open positions at limit (%d) — pausing new quotes",
                self.config.market_id, len(self._open_positions),
            )
            self._cancel_all()
            return

        fv = self._fv_estimator.estimate(as_of=datetime.now(timezone.utc))
        if fv is None:
            return  # not enough trade history
        self._last_fv = fv

        decision = self._compute_quote(fv)
        if decision is None or decision.suspend:
            self._cancel_all()
            return

        self.stats.quotes_computed += 1

        # --- Notional cap: determine which sides are open for quoting ---
        # Per-market cap: when long notional hits max_open_notional, suppress bids.
        # Portfolio cap: when the shared PortfolioConstraints object says no more
        # long-term or per-event exposure, also suppress the relevant side.
        # The per-market long/short caps are mutually exclusive by construction.
        cap = self.config.max_open_notional
        long_capped  = cap > 0 and self._long_notional  >= cap
        short_capped = cap > 0 and self._short_notional >= cap

        # Portfolio-level cap: probe with a minimal notional to see if any new open
        # would be rejected (use a small probe rather than actual quote notional to
        # avoid false negatives on large size orders).
        #
        # can_open() has no direction — it caps gross exposure. If we suppressed
        # BOTH sides whenever it binds, the side that closes existing inventory
        # would go dark and the position could never be unwound (capital locked
        # until resolution). So: suppress only the dominant-exposure side; keep
        # the opposing side live as the exit path. Only when this market holds
        # no inventory at all does the portfolio cap suppress both sides.
        if self._portfolio is not None and not (long_capped and short_capped):
            probe = 0.01  # 1 cent probe — if even this is blocked, we're at cap
            portfolio_capped = not self._portfolio.can_open(
                self.config.event_key, self.config.market_id,
                probe, self.config.days_to_resolution
            )
            if portfolio_capped:
                if self._long_notional > self._short_notional:
                    long_capped = True   # asks stay live to close longs
                elif self._short_notional > self._long_notional:
                    short_capped = True  # bids stay live to close shorts
                else:
                    long_capped = True
                    short_capped = True

        if long_capped:
            logger.info(
                "[%s] Long cap hit (market=$%.0f/$%.0f, portfolio) — suppressing bids",
                self.config.market_id, self._long_notional, cap,
            )
        if short_capped:
            logger.info(
                "[%s] Short cap hit (market=$%.0f/$%.0f, portfolio) — suppressing asks",
                self.config.market_id, self._short_notional, cap,
            )

        # --- Base prices (L0) — anchored to current best bid/ask ---
        # Each ladder level sits `ladder_offset_from_best` + n * tick below the
        # best bid (for bids) or above the best ask (for asks).  The offset is
        # chosen so L0 is still far enough from mid to cover the 7% taker fee on
        # the opposing leg (default 0.030 >= fee cost + edge floor).
        yes_best_bid = self._current_yes_book.best_bid()
        yes_best_ask = self._current_yes_book.best_ask()
        no_best_bid  = self._current_no_book.best_bid()
        no_best_ask  = self._current_no_book.best_ask()

        offset = self.config.ladder_offset_from_best
        fv_fallback = 1.0 - fv  # used only when NO book has no depth

        yes_bid_base = round(max(0.01, min(0.99,
            (yes_best_bid - offset) if yes_best_bid is not None else decision.bid_price
        )), 2)
        yes_ask_base = round(max(0.01, min(0.99,
            (yes_best_ask + offset) if yes_best_ask is not None else decision.ask_price
        )), 2)
        no_bid_base = round(max(0.01, min(0.99,
            (no_best_bid - offset) if no_best_bid is not None else fv_fallback - offset
        )), 2)
        no_ask_base = round(max(0.01, min(0.99,
            (no_best_ask + offset) if no_best_ask is not None else fv_fallback + offset
        )), 2)

        # --- Build ladder prices ---
        # Each successive level moves one tick_spacing further from FV.
        # Bids step DOWN (better for us if filled deeper), asks step UP.
        n = self.config.ladder_levels
        tick = self.config.ladder_tick_spacing
        yes_bid_prices = [round(yes_bid_base - i * tick, 2) for i in range(n)]
        yes_ask_prices = [round(yes_ask_base + i * tick, 2) for i in range(n)]
        no_bid_prices  = [round(no_bid_base  - i * tick, 2) for i in range(n)]
        no_ask_prices  = [round(no_ask_base  + i * tick, 2) for i in range(n)]

        # --- Ladder sizes (increasing deeper) ---
        # Pad ratios if config list is shorter than ladder_levels.
        ratios = list(self.config.ladder_size_ratios)
        while len(ratios) < n:
            ratios.append(ratios[-1] if ratios else 1.0)
        # Bids and asks size independently: in ONE_SIDE_FILLED the engine sets
        # bid_size=0 but keeps ask_size>0 so the flatten leg stays quoted.
        bid_sizes = [decision.bid_size * ratios[i] for i in range(n)]
        ask_sizes = [decision.ask_size * ratios[i] for i in range(n)]

        # --- Maintain all ladder levels (asymmetric when capped) ---
        now = time.monotonic()
        for i in range(n):
            # Bids open longs → cancel if long-capped or engine sized to zero
            if long_capped or bid_sizes[i] <= 0:
                self._cancel_resting(self._yes_bids[i], label=f"yes_bid_{i}_cap")
                self._yes_bids[i] = None
            else:
                self._yes_bids[i] = self._maintain_order(
                    self._yes_bids[i], self.config.yes_token_id, Side.BUY,
                    yes_bid_prices[i], bid_sizes[i], f"yes_bid_{i}", now,
                )
            # Asks open shorts → cancel if short-capped or engine sized to zero
            if short_capped or ask_sizes[i] <= 0:
                self._cancel_resting(self._yes_asks[i], label=f"yes_ask_{i}_cap")
                self._yes_asks[i] = None
            else:
                self._yes_asks[i] = self._maintain_order(
                    self._yes_asks[i], self.config.yes_token_id, Side.SELL,
                    yes_ask_prices[i], ask_sizes[i], f"yes_ask_{i}", now,
                )
            if long_capped or bid_sizes[i] <= 0:
                self._cancel_resting(self._no_bids[i], label=f"no_bid_{i}_cap")
                self._no_bids[i] = None
            else:
                self._no_bids[i] = self._maintain_order(
                    self._no_bids[i], self.config.no_token_id, Side.BUY,
                    no_bid_prices[i], bid_sizes[i], f"no_bid_{i}", now,
                )
            if short_capped or ask_sizes[i] <= 0:
                self._cancel_resting(self._no_asks[i], label=f"no_ask_{i}_cap")
                self._no_asks[i] = None
            else:
                self._no_asks[i] = self._maintain_order(
                    self._no_asks[i], self.config.no_token_id, Side.SELL,
                    no_ask_prices[i], ask_sizes[i], f"no_ask_{i}", now,
                )

    def _maintain_order(
        self,
        current: Optional[_RestingOrder],
        token_id: str,
        side: Side,
        target_price: float,
        size: float,
        slot: str,
        now: float,
    ) -> Optional[_RestingOrder]:
        """
        Cancel + replace an order if price drifted or TTL expired, otherwise leave it.
        Returns the (possibly unchanged) resting order, or None on placement failure.
        """
        if current is not None:
            age = now - current.placed_at
            price_drift = abs(current.price - target_price)

            # Still within tolerance — definitely keep it
            if price_drift <= self.config.price_tolerance and age <= self.config.order_ttl_seconds:
                return current

            # Drifted or TTL expired, but repriced too recently — absorb the churn
            # (protects queue position and keeps API call rate manageable)
            since_last_reprice = now - current.last_reprice_at
            if since_last_reprice < self.config.min_reprice_interval:
                return current

            # Genuinely stale — cancel and replace
            self._cancel_resting(current, label=slot)

        # Iceberg: only show `iceberg_display_size` contracts; track full reserve.
        display = self.config.iceberg_display_size
        if display > 0 and size > display:
            display_size   = display
            hidden_reserve = size - display   # remaining to re-post after fills
        else:
            display_size   = size
            hidden_reserve = 0.0

        resp = self._place_order(token_id, side, target_price, display_size, slot)
        if resp is not None:
            # Extract level from slot name e.g. "yes_bid_2" → 2
            try:
                level = int(slot.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                level = 0
            return _RestingOrder(
                order_id=resp.order_id,
                token_id=token_id,
                side=side,
                price=target_price,
                size=display_size,
                placed_at=now,
                token_side="YES" if token_id == self.config.yes_token_id else "NO",
                order_side="bid" if side == Side.BUY else "ask",
                level=level,
                last_reprice_at=now,
                remaining_hidden=hidden_reserve,
            )
        return None

    # ------------------------------------------------------------------
    # Order helpers
    # ------------------------------------------------------------------

    def _place_order(
        self, token_id: str, side: Side, price: float, size: float, label: str
    ) -> Optional[OrderResponse]:
        """Place one limit order. Returns OrderResponse or None on failure."""
        token_label = "YES" if token_id == self.config.yes_token_id else "NO"
        side_label = "BID" if side == Side.BUY else "ASK"
        log_prefix = "[DRY-RUN] " if self.config.dry_run else ""
        logger.info(
            "%s[%s] PLACE %s %s: price=%.3f size=%.1f",
            log_prefix, self.config.market_id, token_label, side_label, price, size,
        )

        if self.config.dry_run:
            self.stats.orders_placed += 1
            return OrderResponse(
                order_id=f"dry_{label}_{int(time.time())}",
                status="live",
                filled_size=0.0,
                remaining_size=size,
            )

        try:
            req = OrderRequest(token_id=token_id, side=side, price=price, size=size)
            resp = self._client.place_order(req)
            self.stats.orders_placed += 1
            logger.info(
                "[%s] ORDER PLACED %s %s: id=%s status=%s",
                self.config.market_id, token_label, side_label, resp.order_id, resp.status,
            )
            return resp
        except Exception as exc:
            logger.error(
                "[%s] Place order failed (%s %s): %s",
                self.config.market_id, token_label, side_label, exc,
            )
            self.stats.errors += 1
            return None

    def _repost_iceberg_slice(
        self,
        ladder: list[Optional[_RestingOrder]],
        level: int,
        filled_order: _RestingOrder,
    ) -> None:
        """
        After a display-size iceberg fill, re-post the next slice at the same
        price if there is remaining hidden inventory.

        This is called immediately after a fill handler determines the filled order
        was an iceberg order (remaining_hidden > 0).  The new slice is placed at
        the same price; its own remaining_hidden is decremented accordingly.
        """
        display = self.config.iceberg_display_size
        if display <= 0 or filled_order.remaining_hidden <= 0.5:
            return

        next_size   = min(display, filled_order.remaining_hidden)
        next_hidden = filled_order.remaining_hidden - next_size

        slot = f"{'yes' if filled_order.token_id == self.config.yes_token_id else 'no'}" \
               f"_{'bid' if filled_order.side == Side.BUY else 'ask'}_{level}"

        resp = self._place_order(
            filled_order.token_id, filled_order.side,
            filled_order.price, next_size, slot,
        )
        if resp is not None:
            now = time.monotonic()
            ladder[level] = _RestingOrder(
                order_id=resp.order_id,
                token_id=filled_order.token_id,
                side=filled_order.side,
                price=filled_order.price,
                size=next_size,
                placed_at=now,
                token_side=filled_order.token_side,
                order_side=filled_order.order_side,
                level=level,
                last_reprice_at=now,
                remaining_hidden=next_hidden,
            )
            logger.info(
                "[%s] ICEBERG re-post L%d: %s @ %.3f x %.1f  (hidden_remaining=%.0f)",
                self.config.market_id, level,
                filled_order.order_side.upper(), filled_order.price, next_size, next_hidden,
            )

    def _cancel_resting(self, order: Optional[_RestingOrder], label: str = "") -> bool:
        """
        Cancel a resting order.

        Returns True if successfully cancelled (order was still live).
        Returns False ONLY if the exchange explicitly rejected the cancel —
        meaning the order was already filled. A network error is NOT a
        rejection: the order may still be live, so we retry once and, if the
        retry also errors, return True so the caller still sends the hedge
        (an occasional double-hedge is recoverable; a naked fill is not).
        """
        if order is None:
            return True  # nothing to cancel

        if self.config.dry_run:
            logger.debug(
                "[DRY-RUN] [%s] CANCEL %s order=%s price=%.3f",
                self.config.market_id, label, order.order_id, order.price,
            )
            self.stats.orders_cancelled += 1
            return True  # dry-run: always "succeeds"

        for attempt in (1, 2):
            try:
                ok = self._client.cancel_order(order.order_id)
                if ok:
                    self.stats.orders_cancelled += 1
                    logger.debug(
                        "[%s] Cancelled %s order=%s", self.config.market_id, label, order.order_id,
                    )
                else:
                    logger.info(
                        "[%s] Cancel rejected for %s order=%s — likely already filled",
                        self.config.market_id, label, order.order_id,
                    )
                return ok
            except Exception as exc:
                logger.warning(
                    "[%s] Cancel error (attempt %d) for %s %s: %s",
                    self.config.market_id, attempt, label, order.order_id, exc,
                )
                self.stats.errors += 1
        # Both attempts errored: order state unknown, assume still live so the
        # fill handler sends the taker hedge rather than booking a fictitious
        # maker-maker cycle and leaving the position naked.
        return True

    def _cancel_all(self) -> None:
        """Cancel all resting orders across all ladder levels on all 4 sides."""
        for prefix, ladder in [
            ("yes_bid", self._yes_bids), ("yes_ask", self._yes_asks),
            ("no_bid",  self._no_bids),  ("no_ask",  self._no_asks),
        ]:
            self._cancel_ladder(ladder, prefix)

    # ------------------------------------------------------------------
    # Fill routing
    # ------------------------------------------------------------------

    def _identify_filled_order(self, fill: Fill) -> str:
        """
        Identify which resting order was filled across all ladder levels.

        Matches by token_side + price proximity. Returns a level-qualified key
        such as "yes_bid_0", "no_ask_2", or "unknown".
        """
        candidates: list[tuple[str, _RestingOrder]] = []

        if fill.token_side == "YES":
            for i, order in enumerate(self._yes_bids):
                if order and abs(order.price - fill.price) <= self.config.price_tolerance:
                    candidates.append((f"yes_bid_{i}", order))
            for i, order in enumerate(self._yes_asks):
                if order and abs(order.price - fill.price) <= self.config.price_tolerance:
                    candidates.append((f"yes_ask_{i}", order))
        elif fill.token_side == "NO":
            for i, order in enumerate(self._no_bids):
                if order and abs(order.price - fill.price) <= self.config.price_tolerance:
                    candidates.append((f"no_bid_{i}", order))
            for i, order in enumerate(self._no_asks):
                if order and abs(order.price - fill.price) <= self.config.price_tolerance:
                    candidates.append((f"no_ask_{i}", order))

        if len(candidates) == 1:
            return candidates[0][0]
        if len(candidates) > 1:
            # Ambiguous — pick the closest price match
            return min(candidates, key=lambda c: abs(c[1].price - fill.price))[0]
        return "unknown"

    # ------------------------------------------------------------------
    # Quote computation
    # ------------------------------------------------------------------

    def _compute_quote(self, fv: float):
        """Compute QuoteDecision for current YES book state."""
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
    # PnL recording
    # ------------------------------------------------------------------

    def _record_cycle_pnl(
        self, fill_type: str, maker_price: float, taker_price: float, size: float
    ) -> None:
        """Record PnL from a completed maker-taker arb cycle."""
        maker_rebate = self._fm.maker_rebate(
            size=size, price=maker_price,
            fee_rate=self.config.fee_rate,
            rebate_fraction=self.config.rebate_fraction,
        )
        taker_fee = self._fm.taker_fee(
            size=size, price=taker_price,
            fee_rate=self.config.fee_rate,
        )
        notional = (maker_price + taker_price) * size
        # NOTE: by the time we're here, both legs have executed — the position
        # is real. Portfolio caps are enforced BEFORE quoting (see the
        # can_open() probes in _check_inventory_caps). Here we only record
        # reality; if a cap was exceeded anyway (race between fill and quote
        # suppression), log it loudly but never drop the accounting.
        if fill_type in ("yes_bid", "no_bid"):
            gross = (1.0 - maker_price - taker_price) * size
            if self._portfolio is not None and not self._portfolio.can_open(
                self.config.event_key, self.config.market_id,
                notional, self.config.days_to_resolution
            ):
                logger.warning(
                    "[%s] CYCLE %s exceeded portfolio cap — position recorded "
                    "anyway (caps enforce at quote time, not fill time)",
                    self.config.market_id, fill_type,
                )
            self._long_notional += notional
            if self._portfolio is not None:
                self._portfolio.open_position(
                    self.config.event_key, self.config.market_id,
                    notional, self.config.days_to_resolution
                )
        else:  # yes_ask, no_ask
            gross = (maker_price + taker_price - 1.0) * size
            if self._long_notional > 0:
                # Ask-arb closes an existing long — decrement long notional
                self._long_notional -= notional
                self._long_notional = max(0.0, self._long_notional)
                if self._portfolio is not None:
                    self._portfolio.close_position(
                        self.config.event_key, self.config.market_id,
                        notional, self.config.days_to_resolution
                    )
            else:
                # No longs to close — opening a new short
                if self._portfolio is not None and not self._portfolio.can_open(
                    self.config.event_key, self.config.market_id,
                    notional, self.config.days_to_resolution
                ):
                    logger.warning(
                        "[%s] CYCLE %s exceeded portfolio cap — position "
                        "recorded anyway (caps enforce at quote time)",
                        self.config.market_id, fill_type,
                    )
                self._short_notional += notional
                if self._portfolio is not None:
                    self._portfolio.open_position(
                        self.config.event_key, self.config.market_id,
                        notional, self.config.days_to_resolution
                    )
        net = gross + maker_rebate - taker_fee
        self.stats.total_pnl += net
        logger.info(
            "[%s] CYCLE %s: maker=%.3f taker=%.3f size=%.1f gross=%.4f net=%.4f  "
            "long_notional=%.0f short_notional=%.0f",
            self.config.market_id, fill_type,
            maker_price, taker_price, size, gross, net,
            self._long_notional, self._short_notional,
        )

    def _record_maker_maker_cycle(self, label: str, price_a: float) -> None:
        """
        Log a maker-maker cycle (both sides of a pair filled passively).
        Accounting is handled when the second fill arrives via on_fill().
        """
        self.stats.maker_maker_cycles += 1
        logger.info(
            "[%s] MAKER-MAKER CYCLE (%s) — second leg will fire its own on_fill",
            self.config.market_id, label,
        )
