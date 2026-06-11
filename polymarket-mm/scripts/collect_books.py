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
# Series feed groups — each group gets its OWN WebSocket connection.
#
# The Polymarket WS pushes events for only ~WS_MARKETS_PER_CONNECTION active
# markets per connection, so coverage scales with the number of connections.
# Groups are sized so each stays comfortably under that cap; the per-feed
# saturation gauge in the stats output (e.g. "ser-mlb: 50/~50 SATURATED")
# tells you when a group needs to be split further.
# ---------------------------------------------------------------------------
WS_MARKETS_PER_CONNECTION = 50      # empirical server-side throttle
SATURATION_WARN_THRESHOLD = 45      # warn when a feed pins near the cap

SERIES_FEED_GROUPS: dict[str, list[str]] = {
    # Rolling 5-minute windows — one connection per asset (gauge showed
    # maj/alt pairs still pinned at the cap)
    "ser-5m-btc": ["btc-up-or-down-5m"],
    "ser-5m-eth": ["eth-up-or-down-5m"],
    "ser-5m-sol": ["sol-up-or-down-5m"],
    "ser-5m-xrp": ["xrp-up-or-down-5m"],
    # Rolling 15-minute windows — same per-asset split
    "ser-15m-btc": ["btc-up-or-down-15m"],
    "ser-15m-eth": ["eth-up-or-down-15m"],
    "ser-15m-sol": ["sol-up-or-down-15m"],
    "ser-15m-xrp": ["xrp-up-or-down-15m"],
    # Daily up/down (only ~4 markets exist — gauge reads ~4/50, no shard needed)
    "ser-daily": ["btc-up-or-down-daily", "eth-up-or-down-daily"],
    "ser-wk": [
        "btc-multi-strikes-weekly",
        "ethereum-multi-strikes-weekly",
        "xrp-multi-strikes-weekly",
        "solana-multi-strikes-weekly",
    ],
    # Sports. MLB alone has ~16 betting lines per game x ~15 games/day —
    # far beyond one connection's cap, so its tokens are sharded across
    # multiple connections (see SERIES_GROUP_SHARDS).
    "ser-mlb": ["mlb"],
    "ser-ufc": ["ufc"],
}

# Groups whose market list is split across N connections (token-level
# sharding within one slug group). Use when a single group has more active
# markets than one connection's ~50 cap and it can't be split by slug.
SERIES_GROUP_SHARDS: dict[str, int] = {
    "ser-mlb": 7,   # ~283 active betting lines on game days
    "ser-ufc": 3,
    "ser-wk": 2,    # still pins, but weekly-strike books are synthetic
                    # negRisk liquidity — low maker-taker value, accepted gap
}

# Flat list for backwards-compat (fetch_series_markets default)
TRACKED_SERIES = [s for slugs in SERIES_FEED_GROUPS.values() for s in slugs]

# Tag-based feed groups — for market families with no series slug, discovered
# via Gamma's tag filter. negRisk events are INCLUDED here (soccer match
# events are negRisk 3-way groups whose sub-markets are real binary books,
# unlike the synthetic negRisk series the slug fetcher skips).
# label -> {"tag_id": Gamma tag id, "shards": connections}
TAG_FEED_GROUPS: dict[str, dict] = {
    # 2026 FIFA World Cup — match-day events (winner/draw/O-U/halftime/etc.)
    # appear day-of like MLB games; group stage = 4-6 matches/day.
    "ser-fifa": {"tag_id": 102232, "shards": 3},
}


def fetch_tag_markets(tag_id: int) -> list[dict]:
    """Fetch active markets from all events carrying a Gamma tag.

    Unlike fetch_series_markets, negRisk events are kept — tag groups are
    curated for families (e.g. World Cup matches) where negRisk sub-markets
    have genuine order books.
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results: list[dict] = []
    for offset in range(0, 500, 100):
        url = (
            f"https://gamma-api.polymarket.com/events"
            f"?tag_id={tag_id}&closed=false&end_date_min={today}"
            f"&limit=100&offset={offset}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                events = json.loads(resp.read())
        except Exception as exc:
            logger.warning("Tag fetch failed for tag_id=%s: %s", tag_id, exc)
            break
        if not events:
            break
        for ev in events:
            for m in ev.get("markets", []):
                if m.get("active") and not m.get("closed"):
                    results.append(m)
        if len(events) < 100:
            break
    return results

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
    # 1. Fetch active markets (standard + series), one labeled feed each.
    # ------------------------------------------------------------------
    logger.info(
        "Fetching active markets from Gamma API (min_volume=$%.0f) ...", min_volume
    )
    markets = fetch_active_markets(all_pages=True, min_volume=min_volume)
    logger.info("Fetched %d standard markets with 24h volume >= $%.0f", len(markets), min_volume)

    # feed_tokens: label -> list of token_ids for that connection.
    # Standard markets split into volume tiers (Gamma returns them sorted by
    # volume24hr desc, so contiguous chunks = tiers; each shard captures its
    # own ~top-50 instead of one global top-50). Each series group gets its
    # own connection (see SERIES_FEED_GROUPS).
    feed_tokens: dict[str, list[str]] = {}
    token_to_condition: dict[str, str] = {}
    token_to_side: dict[str, str] = {}
    condition_to_question: dict[str, str] = {}
    token_to_feed: dict[str, str] = {}   # for the per-feed saturation gauge

    def _register(label: str, mkts: list[dict]) -> None:
        tok_cond, tok_side, cond_q = build_token_maps(mkts)
        feed_tokens[label] = list(tok_cond.keys())
        token_to_condition.update(tok_cond)
        token_to_side.update(tok_side)
        condition_to_question.update(cond_q)
        for tid in tok_cond:
            token_to_feed[tid] = label

    # group_labels: routing-group name -> feed labels in that group.
    # The refresh thread round-robins new tokens across a group's labels.
    group_labels: dict[str, list[str]] = {}

    def _register_group(group: str, mkts: list[dict], shards: int = 1) -> None:
        """Register a market group, splitting across `shards` connections."""
        shards = max(1, shards)
        size = (len(mkts) + shards - 1) // shards if mkts else 0
        labels = []
        for i in range(shards):
            chunk = mkts[i * size:(i + 1) * size]
            if chunk:
                label = group if shards == 1 else f"{group}-{i + 1}"
                _register(label, chunk)
                labels.append(label)
        group_labels[group] = labels

    _register_group("std", markets, shards=max(1, std_shards))

    for group, slugs in SERIES_FEED_GROUPS.items():
        group_markets = fetch_series_markets(slugs=slugs)
        _register_group(group, group_markets,
                        shards=SERIES_GROUP_SHARDS.get(group, 1))

    for group, cfg in TAG_FEED_GROUPS.items():
        group_markets = fetch_tag_markets(cfg["tag_id"])
        _register_group(group, group_markets, shards=cfg.get("shards", 1))

    logger.info(
        "Feeds: %s",
        "  ".join(f"{lbl}={len(tids)}tok" for lbl, tids in feed_tokens.items()),
    )

    if not any(feed_tokens.values()):
        logger.error("No token IDs found — cannot subscribe. Exiting.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Define callbacks (shared by all feeds)
    # ------------------------------------------------------------------
    # Saturation gauge: distinct markets seen per feed in the current stats
    # window. The WS server pushes events for only ~WS_MARKETS_PER_CONNECTION
    # active markets per connection — a feed pinned at that count is
    # saturated and silently dropping the rest of its subscription.
    active_by_feed: dict[str, set] = defaultdict(set)

    def on_book_update(token_id: str, book: OrderBook) -> None:
        condition_id = token_to_condition.get(token_id)
        if not condition_id:
            return
        active_by_feed[token_to_feed.get(token_id, "?")].add(condition_id)
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
        active_by_feed[token_to_feed.get(token_id, "?")].add(condition_id)
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
    # 3. Start the BookFeeds — one WS connection per label.
    # ------------------------------------------------------------------
    feeds: dict[str, BookFeed] = {
        label: BookFeed(tids) for label, tids in feed_tokens.items() if tids
    }

    all_feeds = list(feeds.values())
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

    for label, feed in feeds.items():
        feed.start()
        logger.info("Feed %-8s started: %d tokens", label, len(feed_tokens[label]))
    logger.info("Writing to %s", writer.get_dir())

    # ------------------------------------------------------------------
    # 4. Market refresh thread — discovers new series windows + any new
    #    standard markets that come online after startup.
    #    New standard tokens round-robin across std shards; series tokens
    #    go to their group's feed.
    # ------------------------------------------------------------------
    _refresh_stop = threading.Event()
    _group_cursor: dict[str, int] = defaultdict(int)  # round-robin per group

    def _subscribe_new(group: str, tok_cond: dict, tok_side: dict) -> int:
        """Register unknown tokens, round-robining across the group's feeds."""
        labels = [lbl for lbl in group_labels.get(group, []) if lbl in feeds]
        if not labels:
            return 0
        added = 0
        for tid, cid in tok_cond.items():
            if tid not in token_to_condition:
                token_to_condition[tid] = cid
                token_to_side[tid] = tok_side[tid]
                label = labels[_group_cursor[group] % len(labels)]
                _group_cursor[group] += 1
                feeds[label].add_token(tid)
                token_to_feed[tid] = label
                added += 1
        return added

    def _refresh_markets():
        """Periodically re-scan Gamma for new markets and subscribe to the right feed."""
        while not _refresh_stop.wait(timeout=refresh_interval):
            try:
                new_standard = fetch_active_markets(all_pages=True, min_volume=min_volume)
                std_tok, std_side, std_q = build_token_maps(new_standard)
                added = _subscribe_new("std", std_tok, std_side)
                new_q = dict(std_q)
                counts_str = []
                for group, slugs in SERIES_FEED_GROUPS.items():
                    grp = fetch_series_markets(slugs=slugs)
                    g_tok, g_side, g_q = build_token_maps(grp)
                    added += _subscribe_new(group, g_tok, g_side)
                    new_q.update(g_q)
                    counts_str.append(f"{group}:{len(grp)}")
                for group, cfg in TAG_FEED_GROUPS.items():
                    grp = fetch_tag_markets(cfg["tag_id"])
                    g_tok, g_side, g_q = build_token_maps(grp)
                    added += _subscribe_new(group, g_tok, g_side)
                    new_q.update(g_q)
                    counts_str.append(f"{group}:{len(grp)}")
                for cid, q in new_q.items():
                    if cid not in condition_to_question:
                        condition_to_question[cid] = q
                if added:
                    logger.info(
                        "Market refresh: +%d new tokens — %d std, %s",
                        added, len(new_standard), " ".join(counts_str),
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
                _print_stats(writer, condition_to_question, start_time,
                             active_by_feed=active_by_feed)
                # Reset gauge sets for the next window
                for s in active_by_feed.values():
                    s.clear()
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
    _print_stats(writer, condition_to_question, start_time, final=True,
                 active_by_feed=active_by_feed)
    logger.info("Done. Files written to %s", writer.get_dir())


def _print_stats(
    writer: BufferedMarketWriter,
    condition_to_question: dict[str, str],
    start_time: float,
    final: bool = False,
    active_by_feed: dict[str, set] | None = None,
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

    # Per-feed saturation gauge: distinct active markets this window vs the
    # ~50-market WS push cap. A feed pinned at the cap is silently dropping
    # the rest of its subscription — split it (raise --std-shards or break
    # up the SERIES_FEED_GROUPS entry).
    if active_by_feed:
        gauge_parts = []
        saturated = []
        for feed_label in sorted(active_by_feed):
            n = len(active_by_feed[feed_label])
            mark = ""
            if n >= SATURATION_WARN_THRESHOLD:
                mark = " SATURATED"
                saturated.append(feed_label)
            gauge_parts.append(
                f"{feed_label}:{n}/~{WS_MARKETS_PER_CONNECTION}{mark}"
            )
        print(f"  Feed activity: {'  '.join(gauge_parts)}", flush=True)
        if saturated:
            logger.warning(
                "SATURATION: feed(s) %s pinned at the ~%d-market WS cap — "
                "markets are being dropped. Increase --std-shards or split "
                "the series group to capture more.",
                ", ".join(saturated), WS_MARKETS_PER_CONNECTION,
            )

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
