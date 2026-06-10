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

import urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Top series to track, split by activity rate.
#
# HIGH_FREQ_SERIES: 5-min and 15-min windows — very active per-second,
#   fill the WS throttle quota quickly. Keep on a dedicated connection.
#
# LOW_FREQ_SERIES: daily, weekly, and sports — lower per-second activity,
#   need their own dedicated WS connection so they aren't crowded out by
#   the high-frequency windows.
#
# The Polymarket WS throttles to ~50 active markets per connection.
# Splitting into separate feeds ensures each group gets its fair share.
# ---------------------------------------------------------------------------
HIGH_FREQ_SERIES = [
    # Rolling 5-minute price up/down — new window every 5 min
    "btc-up-or-down-5m",
    "eth-up-or-down-5m",
    "sol-up-or-down-5m",
    "xrp-up-or-down-5m",
    # Rolling 15-minute price up/down — new window every 15 min
    "btc-up-or-down-15m",
    "eth-up-or-down-15m",
    "sol-up-or-down-15m",
    "xrp-up-or-down-15m",
]

LOW_FREQ_SERIES = [
    # Daily price up/down
    "btc-up-or-down-daily",
    "eth-up-or-down-daily",
    # Sports
    "mlb",
    "ufc",
    # Weekly crypto strike markets
    "btc-multi-strikes-weekly",
    "ethereum-multi-strikes-weekly",
    "xrp-multi-strikes-weekly",
    "solana-multi-strikes-weekly",
]

# Combined list for backwards-compat (used by fetch_series_markets)
TRACKED_SERIES = HIGH_FREQ_SERIES + LOW_FREQ_SERIES

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
        self._locks: dict[str, threading.Lock] = {}
        self._last_flush: dict[str, float] = defaultdict(float)
        self._total_events: int = 0
        self._market_counts: dict[str, int] = defaultdict(int)
        self._global_lock = threading.Lock()

    def _lock_for(self, condition_id: str) -> threading.Lock:
        """Per-market lock, created under the global lock.

        defaultdict(threading.Lock) is NOT safe here: two feed threads
        hitting the same new key concurrently can each construct a distinct
        Lock and both enter the critical section.
        """
        with self._global_lock:
            lock = self._locks.get(condition_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[condition_id] = lock
            return lock

    def write(self, condition_id: str, event: dict) -> None:
        line = json.dumps(event, separators=(",", ":"))
        now = time.monotonic()
        with self._global_lock:
            self._total_events += 1
            self._market_counts[condition_id] += 1
        with self._lock_for(condition_id):
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
            with self._lock_for(condition_id):
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


def fetch_series_markets(slugs: list[str] | None = None) -> list[dict]:
    """Fetch currently active markets from tracked series.

    Series markets (BTC 5-min, ETH daily, MLB game lines, etc.) rotate on a
    fixed schedule and never appear in the standard /markets volume scan because
    each individual window is short-lived.  We discover them by querying each
    series directly for its active events.

    Args:
        slugs: List of series slugs to fetch. Defaults to TRACKED_SERIES (all).

    Returns a flat list of Gamma market dicts, same shape as fetch_active_markets().
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if slugs is None:
        slugs = TRACKED_SERIES

    results: list[dict] = []
    for slug in slugs:
        # end_date_min filters out expired markets that Polymarket never marks closed.
        # Without it, series like btc-up-or-down-5m return December 2025 stale events.
        # limit=30 covers BTC 5m which pre-creates ~12 windows (1 hour ahead).
        url = (
            f"https://gamma-api.polymarket.com/events"
            f"?series_slug={slug}&closed=false&end_date_min={today}&limit=30"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                events = json.loads(resp.read())
            added = 0
            for ev in events:
                if ev.get("negRisk", False):
                    continue  # skip negRisk series (e.g. Elon Tweets)
                for m in ev.get("markets", []):
                    if m.get("active") and not m.get("closed"):
                        results.append(m)
                        added += 1
            if added:
                logger.debug("Series %s: %d active markets", slug, added)
        except Exception as exc:
            logger.warning("Series fetch failed for %s: %s", slug, exc)
    return results


def run_collector(out_dir: str, stats_interval: int, min_volume: float = 5_000.0,
                  refresh_interval: int = 300, std_shards: int = 3) -> None:
    base_dir = Path(out_dir)
    writer = BufferedMarketWriter(base_dir)

    # ------------------------------------------------------------------
    # 1. Fetch active markets (standard + series)
    # ------------------------------------------------------------------
    logger.info(
        "Fetching active markets from Gamma API (min_volume=$%.0f) ...", min_volume
    )
    markets = fetch_active_markets(all_pages=True, min_volume=min_volume)
    logger.info("Fetched %d standard markets with 24h volume >= $%.0f", len(markets), min_volume)

    hf_markets = fetch_series_markets(slugs=HIGH_FREQ_SERIES)
    lf_markets = fetch_series_markets(slugs=LOW_FREQ_SERIES)
    logger.info(
        "Fetched %d high-freq series (%d slugs) + %d low-freq series (%d slugs)",
        len(hf_markets), len(HIGH_FREQ_SERIES),
        len(lf_markets), len(LOW_FREQ_SERIES),
    )

    # Build separate token maps so each feed gets its own WS connection.
    # The Polymarket WS pushes events for only ~50 active markets per
    # connection regardless of subscription size, so coverage scales with the
    # number of connections:
    #   - std shards: standard markets split into volume tiers (Gamma returns
    #     them sorted by volume24hr desc, so contiguous chunks = tiers; each
    #     shard captures its own top-50 instead of one global top-50)
    #   - hf_feed:    5m/15m BTC/ETH/SOL/XRP  (very active per-second)
    #   - lf_feed:    daily, weekly, MLB, UFC  (lower per-second rate)
    std_shards = max(1, std_shards)
    shard_size = (len(markets) + std_shards - 1) // std_shards if markets else 0
    std_shard_maps = []
    for i in range(std_shards):
        chunk = markets[i * shard_size:(i + 1) * shard_size]
        if chunk:
            std_shard_maps.append(build_token_maps(chunk))
    hf_tok_cond, hf_tok_side, hf_cond_q = build_token_maps(hf_markets)
    lf_tok_cond, lf_tok_side, lf_cond_q = build_token_maps(lf_markets)

    # Shared mutable maps (written by refresh thread, read by callbacks)
    token_to_condition: dict[str, str] = {**hf_tok_cond, **lf_tok_cond}
    token_to_side: dict[str, str]      = {**hf_tok_side, **lf_tok_side}
    condition_to_question: dict[str, str] = {**hf_cond_q, **lf_cond_q}
    for tok_cond, tok_side, cond_q in std_shard_maps:
        token_to_condition.update(tok_cond)
        token_to_side.update(tok_side)
        condition_to_question.update(cond_q)

    std_shard_token_ids = [list(m[0].keys()) for m in std_shard_maps]
    hf_token_ids = list(hf_tok_cond.keys())
    lf_token_ids = list(lf_tok_cond.keys())

    logger.info(
        "Token maps: %s std tokens in %d shards (%d mkts) | %d hf-series (%d mkts) | %d lf-series (%d mkts)",
        "+".join(str(len(t)) for t in std_shard_token_ids) or "0",
        len(std_shard_token_ids), len(markets),
        len(hf_token_ids), len(hf_markets),
        len(lf_token_ids), len(lf_markets),
    )

    if not any([std_shard_token_ids, hf_token_ids, lf_token_ids]):
        logger.error("No token IDs found — cannot subscribe. Exiting.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Define callbacks (shared by both feeds)
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
    # 3. Start the BookFeeds — N standard shards + hf + lf, one WS each.
    # ------------------------------------------------------------------
    std_feeds = [BookFeed(tids) for tids in std_shard_token_ids if tids]
    hf_feed = BookFeed(hf_token_ids) if hf_token_ids else None
    lf_feed = BookFeed(lf_token_ids) if lf_token_ids else None

    all_feeds = [f for f in (*std_feeds, hf_feed, lf_feed) if f is not None]
    for feed in all_feeds:
        feed.on_any_book_update(on_book_update)
        feed.on_any_trade(on_trade)

    # Graceful shutdown on Ctrl+C or SIGTERM
    def _shutdown(signum, frame):
        logger.info("Shutdown signal received — stopping feeds...")
        for feed in all_feeds:
            feed.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    for i, feed in enumerate(std_feeds):
        feed.start()
        logger.info("Standard shard %d/%d started: %d tokens",
                    i + 1, len(std_feeds), len(std_shard_token_ids[i]))
    if hf_feed:
        hf_feed.start()
        logger.info("High-freq series feed:    %d tokens (5m/15m BTC/ETH/SOL/XRP)", len(hf_token_ids))
    if lf_feed:
        lf_feed.start()
        logger.info("Low-freq series feed:     %d tokens (daily/weekly/MLB/UFC). Writing to %s",
                    len(lf_token_ids), writer.get_dir())

    # ------------------------------------------------------------------
    # 4. Market refresh thread — discovers new series windows + any new
    #    standard markets that come online after startup.
    #    New standard tokens round-robin across std shards; series tokens
    #    go to their dedicated feed.
    # ------------------------------------------------------------------
    _refresh_stop = threading.Event()
    _next_shard = [0]  # round-robin cursor for new standard tokens

    def _refresh_markets():
        """Periodically re-scan Gamma for new markets and subscribe to the right feed."""
        while not _refresh_stop.wait(timeout=refresh_interval):
            try:
                new_standard = fetch_active_markets(all_pages=True, min_volume=min_volume)
                new_hf       = fetch_series_markets(slugs=HIGH_FREQ_SERIES)
                new_lf       = fetch_series_markets(slugs=LOW_FREQ_SERIES)
                new_std_tok, new_std_side, new_std_q = build_token_maps(new_standard)
                new_hf_tok,  new_hf_side,  new_hf_q  = build_token_maps(new_hf)
                new_lf_tok,  new_lf_side,  new_lf_q  = build_token_maps(new_lf)
                added_std = added_hf = added_lf = 0
                for tid, cid in new_std_tok.items():
                    if tid not in token_to_condition:
                        token_to_condition[tid] = cid
                        token_to_side[tid]      = new_std_side[tid]
                        if std_feeds:
                            std_feeds[_next_shard[0] % len(std_feeds)].add_token(tid)
                            _next_shard[0] += 1
                        added_std += 1
                for tid, cid in new_hf_tok.items():
                    if tid not in token_to_condition:
                        token_to_condition[tid] = cid
                        token_to_side[tid]      = new_hf_side[tid]
                        if hf_feed:
                            hf_feed.add_token(tid)
                        added_hf += 1
                for tid, cid in new_lf_tok.items():
                    if tid not in token_to_condition:
                        token_to_condition[tid] = cid
                        token_to_side[tid]      = new_lf_side[tid]
                        if lf_feed:
                            lf_feed.add_token(tid)
                        added_lf += 1
                for cid, q in {**new_std_q, **new_hf_q, **new_lf_q}.items():
                    if cid not in condition_to_question:
                        condition_to_question[cid] = q
                added = added_std + added_hf + added_lf
                if added:
                    logger.info(
                        "Market refresh: +%d new tokens (+%d std, +%d hf, +%d lf) — "
                        "totals: %d std / %d hf / %d lf",
                        added, added_std, added_hf, added_lf,
                        len(new_standard), len(new_hf), len(new_lf),
                    )
                else:
                    logger.debug(
                        "Market refresh: no new tokens "
                        "(%d std + %d hf + %d lf scanned)",
                        len(new_standard), len(new_hf), len(new_lf),
                    )
            except Exception as exc:
                logger.warning("Market refresh error: %s", exc)

    refresh_thread = threading.Thread(target=_refresh_markets, daemon=True,
                                      name="market-refresh")
    refresh_thread.start()
    logger.info("Market refresh thread started (interval=%ds)", refresh_interval)

    # ------------------------------------------------------------------
    # 5. Stats loop
    # ------------------------------------------------------------------
    start_time = time.time()
    last_stats = start_time

    def _any_feed_running() -> bool:
        return any(f.is_running() for f in all_feeds)

    try:
        while _any_feed_running():
            time.sleep(1.0)
            now = time.time()
            if now - last_stats >= stats_interval:
                last_stats = now
                _print_stats(writer, condition_to_question, start_time)
    except KeyboardInterrupt:
        # SIGINT already handled above, but just in case
        for feed in all_feeds:
            feed.stop()

    # ------------------------------------------------------------------
    # 6. Flush & final stats
    # ------------------------------------------------------------------
    _refresh_stop.set()
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
        default=5_000.0,
        metavar="USD",
        help="Minimum 24h volume to collect a standard market (default: 5000)",
    )
    parser.add_argument(
        "--refresh-interval",
        type=int,
        default=300,
        metavar="SECS",
        help="Seconds between market re-scans to pick up new/rolling series windows (default: 300)",
    )
    parser.add_argument(
        "--std-shards",
        type=int,
        default=3,
        metavar="N",
        help="Number of WS connections for standard markets. The WS pushes "
             "events for only ~50 active markets per connection, so more "
             "shards = more coverage (default: 3)",
    )
    args = parser.parse_args()

    run_collector(
        out_dir=args.out,
        stats_interval=args.stats_interval,
        min_volume=args.min_volume,
        refresh_interval=args.refresh_interval,
        std_shards=args.std_shards,
    )


if __name__ == "__main__":
    main()
