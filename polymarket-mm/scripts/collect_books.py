#!/usr/bin/env python3
# scripts/collect_books.py
"""
Overnight book/trade data collector for Polymarket.

Fetches ALL active markets via Gamma API, subscribes to YES and NO token
WebSocket feeds, and records every book snapshot and trade event to disk
in JSONL format compatible with HistoricalDataLoader.

Output:  data/live/YYYY-MM-DD/{condition_id}.jsonl
Format:  One JSON event per line (book or trade), same schema as data/raw/*.jsonl

Usage:
    py -3 scripts/collect_books.py
    py -3 scripts/collect_books.py --out data/live --stats-interval 60
    py -3 scripts/collect_books.py --stats-interval 10   # quick test

No credentials needed — read-only WebSocket subscription.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.scan_markets import fetch_active_markets, extract_token_ids
from src.live.book_feed import BookFeed
from src.data.schemas import OrderBook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Buffered file writer
# ---------------------------------------------------------------------------

class BufferedMarketWriter:
    """
    Writes JSONL events to per-market files with buffering.
    Flushes every FLUSH_EVENTS lines or FLUSH_SECS seconds, whichever comes first.
    Thread-safe via per-file locks.
    """

    FLUSH_EVENTS = 100
    FLUSH_SECS = 5.0

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        self._buffers: dict[str, list[str]] = defaultdict(list)
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._last_flush: dict[str, float] = defaultdict(float)
        self._total_events: int = 0
        self._market_counts: dict[str, int] = defaultdict(int)
        self._global_lock = threading.Lock()

    def write(self, condition_id: str, event: dict) -> None:
        line = json.dumps(event, separators=(",", ":"))
        now = time.monotonic()
        with self._global_lock:
            self._total_events += 1
            self._market_counts[condition_id] += 1
        with self._locks[condition_id]:
            self._buffers[condition_id].append(line)
            n = len(self._buffers[condition_id])
            elapsed = now - self._last_flush[condition_id]
            if n >= self.FLUSH_EVENTS or elapsed >= self.FLUSH_SECS:
                self._flush_locked(condition_id)

    def _flush_locked(self, condition_id: str) -> None:
        """Flush buffer to disk. Must be called with self._locks[condition_id] held."""
        buf = self._buffers[condition_id]
        if not buf:
            return
        path = self._get_path(condition_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(buf) + "\n")
        self._buffers[condition_id] = []
        self._last_flush[condition_id] = time.monotonic()

    def flush_all(self) -> None:
        """Flush all pending buffers to disk."""
        for condition_id in list(self._buffers.keys()):
            with self._locks[condition_id]:
                self._flush_locked(condition_id)

    def _get_path(self, condition_id: str) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._base_dir / date_str / f"{condition_id}.jsonl"

    def get_dir(self) -> str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return str(self._base_dir / date_str)

    def total_events(self) -> int:
        with self._global_lock:
            return self._total_events

    def market_counts(self) -> dict[str, int]:
        with self._global_lock:
            return dict(self._market_counts)

    def estimated_size_mb(self) -> float:
        """Rough estimate: ~150 bytes per event on average."""
        with self._global_lock:
            return self._total_events * 150 / 1_000_000


# ---------------------------------------------------------------------------
# Main collector
# ---------------------------------------------------------------------------

def build_token_maps(
    markets: list[dict],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """
    Returns:
        token_to_condition: token_id -> condition_id
        token_to_side:      token_id -> "YES" or "NO"
        condition_to_question: condition_id -> question text (for display)
    """
    token_to_condition: dict[str, str] = {}
    token_to_side: dict[str, str] = {}
    condition_to_question: dict[str, str] = {}

    for market in markets:
        condition_id = market.get("conditionId", "")
        if not condition_id:
            continue
        tokens = extract_token_ids(market)
        if tokens is None:
            continue
        yes_token, no_token = tokens
        token_to_condition[yes_token] = condition_id
        token_to_condition[no_token] = condition_id
        token_to_side[yes_token] = "YES"
        token_to_side[no_token] = "NO"
        question = market.get("question", market.get("slug", condition_id))[:80]
        condition_to_question[condition_id] = question

    return token_to_condition, token_to_side, condition_to_question


def run_collector(out_dir: str, stats_interval: int, min_volume: float = 20_000.0) -> None:
    base_dir = Path(out_dir)
    writer = BufferedMarketWriter(base_dir)

    # ------------------------------------------------------------------
    # 1. Fetch active markets above volume threshold
    # ------------------------------------------------------------------
    logger.info(
        "Fetching active markets from Gamma API (min_volume=$%.0f) ...", min_volume
    )
    markets = fetch_active_markets(all_pages=True, min_volume=min_volume)
    logger.info("Fetched %d markets with 24h volume >= $%.0f", len(markets), min_volume)

    token_to_condition, token_to_side, condition_to_question = build_token_maps(markets)
    all_token_ids = list(token_to_condition.keys())
    logger.info(
        "Built token map: %d tokens across %d markets",
        len(all_token_ids),
        len(condition_to_question),
    )

    if not all_token_ids:
        logger.error("No token IDs found — cannot subscribe. Exiting.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Define callbacks
    # ------------------------------------------------------------------

    def on_book_update(token_id: str, book: OrderBook) -> None:
        condition_id = token_to_condition.get(token_id)
        if not condition_id:
            return
        event = {
            "event_type": "book",
            "market_id": condition_id,
            "token_side": token_to_side.get(token_id, ""),
            "timestamp": book.timestamp.isoformat(),
            "bids": [{"price": lvl.price, "size": lvl.size} for lvl in book.bids],
            "asks": [{"price": lvl.price, "size": lvl.size} for lvl in book.asks],
        }
        writer.write(condition_id, event)

    def on_trade(token_id: str, price: float, size: float) -> None:
        condition_id = token_to_condition.get(token_id)
        if not condition_id:
            return
        side = token_to_side.get(token_id, "unknown")
        event = {
            "event_type": "trade",
            "market_id": condition_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "side": side,
            "price": price,
            "size": size,
            "is_maker": False,
        }
        writer.write(condition_id, event)

    # ------------------------------------------------------------------
    # 3. Start BookFeed
    # ------------------------------------------------------------------
    feed = BookFeed(all_token_ids)
    feed.on_any_book_update(on_book_update)
    feed.on_any_trade(on_trade)

    # Graceful shutdown on Ctrl+C or SIGTERM
    def _shutdown(signum, frame):
        logger.info("Shutdown signal received — stopping feed...")
        feed.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    feed.start()
    logger.info(
        "BookFeed started. Subscribed to %d tokens. Writing to %s",
        len(all_token_ids),
        writer.get_dir(),
    )

    # ------------------------------------------------------------------
    # 4. Stats loop
    # ------------------------------------------------------------------
    start_time = time.time()
    last_stats = start_time

    try:
        while feed.is_running():
            time.sleep(1.0)
            now = time.time()
            if now - last_stats >= stats_interval:
                last_stats = now
                _print_stats(writer, condition_to_question, start_time)
    except KeyboardInterrupt:
        # SIGINT already handled above, but just in case
        feed.stop()

    # ------------------------------------------------------------------
    # 5. Flush & final stats
    # ------------------------------------------------------------------
    logger.info("Flushing buffers...")
    writer.flush_all()
    _print_stats(writer, condition_to_question, start_time, final=True)
    logger.info("Done. Files written to %s", writer.get_dir())


def _print_stats(
    writer: BufferedMarketWriter,
    condition_to_question: dict[str, str],
    start_time: float,
    final: bool = False,
) -> None:
    now_str = datetime.now().strftime("%H:%M:%S")
    total = writer.total_events()
    counts = writer.market_counts()
    n_markets = len(counts)
    size_mb = writer.estimated_size_mb()
    elapsed = time.time() - start_time
    elapsed_str = f"{int(elapsed // 3600)}h{int((elapsed % 3600) // 60):02d}m"

    # Top 5 most active markets
    top = sorted(counts.items(), key=lambda x: -x[1])[:5]
    top_str = ", ".join(
        f"{condition_to_question.get(cid, cid[:12]+'...')[:30]} ({n})"
        for cid, n in top
    )

    label = "FINAL" if final else "STATS"
    print(
        f"\n[{now_str}] {label}: {total:,} events | {n_markets} markets | "
        f"running {elapsed_str}",
        flush=True,
    )
    if top_str:
        print(f"  Top active: {top_str}", flush=True)
    print(
        f"  Output: {writer.get_dir()}  |  Est. size: {size_mb:.1f} MB",
        flush=True,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Collect live Polymarket order book and trade data to JSONL files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--out",
        default="data/live",
        help="Output base directory (default: data/live)",
    )
    parser.add_argument(
        "--stats-interval",
        type=int,
        default=60,
        metavar="N",
        help="Seconds between progress stats (default: 60)",
    )
    parser.add_argument(
        "--min-volume",
        type=float,
        default=20_000.0,
        metavar="USD",
        help="Minimum 24h volume to collect a market (default: 20000)",
    )
    args = parser.parse_args()

    run_collector(out_dir=args.out, stats_interval=args.stats_interval, min_volume=args.min_volume)


if __name__ == "__main__":
    main()
