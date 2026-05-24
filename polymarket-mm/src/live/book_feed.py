"""
BookFeed — WebSocket subscriber for real-time Polymarket L2 order book updates.

Connects to the Polymarket CLOB WebSocket, subscribes to the 'book' channel for
multiple token IDs, and maintains the current OrderBook state per token.
Calls registered callbacks on each book update.

WebSocket endpoint: wss://ws-subscriptions-clob.polymarket.com/ws/
Protocol: JSON messages

Subscription message:
    {"type": "subscribe", "channel": "book", "assets_ids": ["token_id1", ...]}

Book update message (delta):
    {"event_type": "book", "asset_id": "...", "bids": [...], "asks": [...], "hash": "..."}

Price update message:
    {"event_type": "price_change", "asset_id": "...", "changes": [...]}

Reconnects automatically on disconnection with exponential backoff.

Usage:
    feed = BookFeed(["token_a", "token_b"])
    feed.on_book_update("token_a", callback_fn)
    asyncio.run(feed.run())

Or non-async:
    feed = BookFeed(["token_a"])
    feed.start()           # starts background thread
    book = feed.get_book("token_a")
    feed.stop()
"""

from __future__ import annotations
import asyncio
import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from src.data.schemas import OrderBook, PriceLevel

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

BookCallback = Callable[[str, OrderBook], None]   # (token_id, book) -> None
TradeCallback = Callable[[str, float, float], None]  # (token_id, price, size) -> None


@dataclass
class BookFeedConfig:
    reconnect_delay_seconds: float = 1.0
    max_reconnect_delay_seconds: float = 60.0
    reconnect_backoff_factor: float = 2.0
    ping_interval_seconds: float = 20.0
    ping_timeout_seconds: float = 10.0


class BookFeed:
    """
    Subscribes to Polymarket WebSocket and maintains live L2 order books.

    Args:
        token_ids: List of YES or NO token IDs to subscribe to.
        config: Reconnection and timing parameters.
    """

    def __init__(
        self,
        token_ids: list[str],
        config: Optional[BookFeedConfig] = None,
    ):
        self._token_ids = list(token_ids)
        self._config = config or BookFeedConfig()
        self._books: dict[str, OrderBook] = {}
        self._callbacks: dict[str, list[BookCallback]] = defaultdict(list)
        self._global_callbacks: list[BookCallback] = []
        self._global_trade_callbacks: list[TradeCallback] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_book_update(
        self,
        token_id: str,
        callback: BookCallback,
    ) -> None:
        """Register a callback for updates to a specific token's book."""
        self._callbacks[token_id].append(callback)

    def on_any_book_update(self, callback: BookCallback) -> None:
        """Register a callback that fires on any book update."""
        self._global_callbacks.append(callback)

    def on_any_trade(self, callback: TradeCallback) -> None:
        """Register a callback that fires on every last_trade_price event."""
        self._global_trade_callbacks.append(callback)

    def get_book(self, token_id: str) -> Optional[OrderBook]:
        """Return the current best-known OrderBook for a token, or None."""
        with self._lock:
            return self._books.get(token_id)

    def get_all_books(self) -> dict[str, OrderBook]:
        """Return a snapshot of all current OrderBook states."""
        with self._lock:
            return dict(self._books)

    def add_token(self, token_id: str) -> None:
        """Subscribe to an additional token (sends re-subscribe on next cycle)."""
        if token_id not in self._token_ids:
            self._token_ids.append(token_id)

    def start(self) -> None:
        """Start the feed in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_thread, daemon=True, name="BookFeedThread"
        )
        self._thread.start()
        logger.info("BookFeed started for %d tokens", len(self._token_ids))

    def stop(self) -> None:
        """Signal the feed to stop and wait for the thread to exit."""
        self._stop_event.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("BookFeed stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    async def run(self) -> None:
        """
        Async entry point. Runs the WebSocket loop with reconnection until stopped.
        Call this with asyncio.run() for single-thread use.
        """
        self._loop = asyncio.get_event_loop()
        delay = self._config.reconnect_delay_seconds
        while not self._stop_event.is_set():
            try:
                await self._connect_and_consume()
                delay = self._config.reconnect_delay_seconds  # reset on clean exit
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.warning(
                    "WebSocket disconnected (%s). Reconnecting in %.1fs...",
                    exc, delay,
                )
                await asyncio.sleep(delay)
                delay = min(
                    delay * self._config.reconnect_backoff_factor,
                    self._config.max_reconnect_delay_seconds,
                )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_thread(self) -> None:
        """Target for the background daemon thread."""
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.run())
        finally:
            loop.close()
            self._loop = None

    async def _connect_and_consume(self) -> None:
        """Establish one WebSocket connection and consume messages until error/stop."""
        try:
            import websockets
        except ImportError:
            raise RuntimeError(
                "websockets package is required for BookFeed. "
                "Install it: pip install websockets"
            )

        logger.info("Connecting to %s", WS_URL)
        async with websockets.connect(
            WS_URL,
            ping_interval=self._config.ping_interval_seconds,
            ping_timeout=self._config.ping_timeout_seconds,
        ) as ws:
            # Subscribe to market book channel for all tokens.
            # Polymarket's WS server silently drops subscriptions in very large
            # single messages, so chunk into batches of 500 tokens.
            CHUNK = 500
            token_ids = list(self._token_ids)
            for i in range(0, len(token_ids), CHUNK):
                chunk = token_ids[i:i + CHUNK]
                sub_msg = json.dumps({
                    "assets_ids": chunk,
                    "type": "Market",
                })
                await ws.send(sub_msg)
            logger.info(
                "Subscribed to book channel for %d tokens (%d chunks)",
                len(token_ids), (len(token_ids) + CHUNK - 1) // CHUNK,
            )

            async for raw_msg in ws:
                if self._stop_event.is_set():
                    break
                self._process_message(raw_msg)

    def _process_message(self, raw: str) -> None:
        """Parse and dispatch one incoming WebSocket message."""
        try:
            msgs = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Non-JSON WebSocket message: %s", raw[:100])
            return

        # Messages may arrive as a single dict or a list of dicts
        if isinstance(msgs, dict):
            msgs = [msgs]
        elif not isinstance(msgs, list):
            return

        for msg in msgs:
            event_type = msg.get("event_type", msg.get("type", ""))
            if event_type == "book":
                self._handle_book_snapshot(msg)
            elif event_type == "price_change":
                self._handle_price_change(msg)
            elif event_type == "last_trade_price":
                self._handle_last_trade_price(msg)
            elif event_type in ("subscribed", "info", "ack"):
                pass  # informational, ignore
            else:
                logger.debug("Unknown WS event_type=%s", event_type)

    def _handle_book_snapshot(self, msg: dict) -> None:
        """Handle a full book snapshot event."""
        token_id = msg.get("asset_id", "")
        if not token_id:
            return

        bids = sorted(
            [PriceLevel(price=float(b["price"]), size=float(b["size"]))
             for b in msg.get("bids", []) if float(b.get("size", 0)) > 0],
            key=lambda l: -l.price,
        )
        asks = sorted(
            [PriceLevel(price=float(a["price"]), size=float(a["size"]))
             for a in msg.get("asks", []) if float(a.get("size", 0)) > 0],
            key=lambda l: l.price,
        )

        book = OrderBook(
            market_id=token_id,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
        )

        with self._lock:
            self._books[token_id] = book

        self._fire_callbacks(token_id, book)

    def _handle_price_change(self, msg: dict) -> None:
        """Handle an incremental price/size change event."""
        token_id = msg.get("asset_id", "")
        if not token_id:
            return

        with self._lock:
            existing = self._books.get(token_id)
            if existing is None:
                # No snapshot yet — can't apply delta
                return
            bids = {lvl.price: lvl.size for lvl in existing.bids}
            asks = {lvl.price: lvl.size for lvl in existing.asks}

        for change in msg.get("changes", []):
            price = float(change["price"])
            size = float(change["size"])
            side = change.get("side", "").upper()
            if side == "BUY":
                if size <= 0:
                    bids.pop(price, None)
                else:
                    bids[price] = size
            elif side == "SELL":
                if size <= 0:
                    asks.pop(price, None)
                else:
                    asks[price] = size

        sorted_bids = sorted(
            [PriceLevel(price=p, size=s) for p, s in bids.items()],
            key=lambda l: -l.price,
        )
        sorted_asks = sorted(
            [PriceLevel(price=p, size=s) for p, s in asks.items()],
            key=lambda l: l.price,
        )

        book = OrderBook(
            market_id=token_id,
            bids=sorted_bids,
            asks=sorted_asks,
            timestamp=datetime.now(timezone.utc),
        )

        with self._lock:
            self._books[token_id] = book

        self._fire_callbacks(token_id, book)

    def _handle_last_trade_price(self, msg: dict) -> None:
        """Handle a last_trade_price event — feeds real-time trade prices to FV estimators."""
        token_id = msg.get("asset_id", "")
        if not token_id:
            return
        try:
            price = float(msg["price"])
            size = float(msg.get("size", 0.0))
        except (KeyError, ValueError, TypeError):
            return

        logger.debug("TRADE: token=%s... price=%.4f size=%.1f", token_id[:16], price, size)
        for cb in self._global_trade_callbacks:
            try:
                cb(token_id, price, size)
            except Exception:
                logger.exception("Trade callback error for token %s", token_id[:20])

    def _fire_callbacks(self, token_id: str, book: OrderBook) -> None:
        """Invoke all registered callbacks for this token."""
        for cb in self._callbacks.get(token_id, []):
            try:
                cb(token_id, book)
            except Exception:
                logger.exception("Callback error for token %s", token_id[:20])
        for cb in self._global_callbacks:
            try:
                cb(token_id, book)
            except Exception:
                logger.exception("Global callback error for token %s", token_id[:20])
