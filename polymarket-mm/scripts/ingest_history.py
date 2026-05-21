#!/usr/bin/env python3
"""
Download historical trade data from Polymarket and save as JSONL.

For each trade we also emit a synthetic order-book snapshot so the
backtest simulator has a live book to work with (the public API does
not provide historical L2 snapshots).

Usage — paste any Polymarket URL:
    py scripts/ingest_history.py --market "polymarket.com/sports/epl/epl-bou-mac-2026-05-19"
    py scripts/ingest_history.py --market "epl-bou-mac-2026-05-19"
    py scripts/ingest_history.py --market "0xabc123..."

Optional flags:
    --out data/raw          output directory (default: data/raw)
    --days 30               days of history counting back from today (default: 30)
    --since 2024-09-01      explicit start date (overrides --days)
    --spread 0.02           synthetic book half-spread in price units (default: 0.02)
    --book-size 500         synthetic book depth in contracts per level (default: 500)
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests

DATA_API   = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


# ---------------------------------------------------------------------------
# Market resolution: URL / slug / condition ID -> (condition_id, token_id, title)
# ---------------------------------------------------------------------------

def resolve_market(market_input: str) -> tuple[str, str, str]:
    """
    Accept any of:
      - Full URL:      https://polymarket.com/sports/epl/epl-bou-mac-2026-05-19
      - Bare URL:      polymarket.com/sports/epl/epl-bou-mac-2026-05-19
      - Slug:          epl-bou-mac-2026-05-19
      - Condition ID:  0xabc123...

    Returns (condition_id, token_id, title).
    """
    raw = market_input.strip().rstrip("/")

    if re.match(r"^0x[0-9a-fA-F]{10,}$", raw):
        return _resolve_by_condition_id(raw)

    slug = raw.split("/")[-1].split("?")[0]
    return _resolve_by_slug(slug)


def _resolve_by_slug(slug: str) -> tuple[str, str, str]:
    # Sports events have multiple sub-markets — try events endpoint first
    r = requests.get(f"{GAMMA_BASE}/events", params={"slug": slug}, timeout=10)
    r.raise_for_status()
    events = r.json()

    if events:
        event = events[0]
        markets = event.get("markets", [])
        if markets:
            m = markets[0]
            condition_id = m.get("conditionId", "")
            token_id = _extract_token_id(m)
            title = event.get("title", slug)
            if condition_id:
                return condition_id, token_id, title

    r = requests.get(f"{GAMMA_BASE}/markets", params={"slug": slug}, timeout=10)
    r.raise_for_status()
    markets = r.json()

    # Retry with closed=true for resolved markets
    if not markets:
        r = requests.get(f"{GAMMA_BASE}/markets", params={"slug": slug, "closed": "true"}, timeout=10)
        r.raise_for_status()
        markets = r.json()

    if not markets:
        raise ValueError(
            f"No market found for '{slug}'.\n"
            f"Check that the URL is from polymarket.com and the market exists."
        )

    m = markets[0]
    condition_id = m.get("conditionId", "")
    token_id = _extract_token_id(m)
    title = m.get("question", slug)

    if not condition_id:
        raise ValueError(f"Could not find conditionId for slug '{slug}'.")

    return condition_id, token_id, title


def _resolve_by_condition_id(condition_id: str) -> tuple[str, str, str]:
    needle = condition_id.lower()

    # Strategy 1: direct markets lookup (works for standalone markets)
    r = requests.get(f"{GAMMA_BASE}/markets", params={"conditionId": condition_id}, timeout=10)
    r.raise_for_status()
    data = r.json()
    m = next((x for x in data if x.get("conditionId", "").lower() == needle), None)
    if m is not None:
        return condition_id, _extract_token_id(m), m.get("question", condition_id)

    # Strategy 2: search events (sub-markets of events don't appear in /markets?conditionId=)
    # Fetch recent active events and scan their sub-markets for a matching conditionId
    for offset in range(0, 1000, 200):
        r = requests.get(f"{GAMMA_BASE}/events", params={
            "active": "true", "limit": 200, "offset": offset,
            "order": "volume24hr", "ascending": "false"
        }, timeout=15)
        r.raise_for_status()
        events = r.json()
        if not events:
            break
        for event in events:
            for sub in event.get("markets", []):
                if sub.get("conditionId", "").lower() == needle:
                    title = event.get("title", sub.get("question", condition_id))
                    return condition_id, _extract_token_id(sub), title

    raise ValueError(
        f"conditionId={condition_id} not found in Gamma API. "
        f"Try passing the market slug instead."
    )


def _extract_token_id(market: dict) -> str:
    raw = market.get("clobTokenIds") or market.get("clob_token_ids") or ""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
    if isinstance(raw, list) and raw:
        return raw[0]
    return market.get("conditionId", "")


# ---------------------------------------------------------------------------
# Synthetic order-book builder
# ---------------------------------------------------------------------------

def make_book_event(
    market_id: str,
    timestamp_iso: str,
    yes_trade_price: float,
    spread: float,
    book_size: float,
) -> dict:
    """
    Construct a synthetic NO-side order-book event from a YES-token trade.

    The backtest simulator uses the book to:
      - Assess whether the NO-side is hedgeable (hedgeability assessor)
      - Find a flatten price when we hold YES inventory

    NO price = 1 - YES price.  We place one level on each side of the NO mid.
    """
    no_mid = 1.0 - yes_trade_price
    no_bid = round(max(0.01, no_mid - spread / 2), 4)
    no_ask = round(min(0.99, no_mid + spread / 2), 4)
    return {
        "event_type": "book",
        "market_id": market_id,
        "timestamp": timestamp_iso,
        "bids": [{"price": no_bid, "size": book_size}],
        "asks": [{"price": no_ask, "size": book_size}],
    }


# ---------------------------------------------------------------------------
# Trade fetching
# ---------------------------------------------------------------------------

def fetch_trades(
    condition_id: str,
    token_id: str,
    since_ts: int,
    out_path: Path,
    spread: float,
    book_size: float,
) -> int:
    offset = 0
    limit = 500
    total = 0
    seen_hashes: set[str] = set()   # deduplicate: each fill appears as BUY + SELL record

    tmp_path = out_path.with_suffix(".jsonl.tmp")
    try:
        with tmp_path.open("w") as f:
            while True:
                params = {
                    "market": condition_id,
                    "limit": limit,
                    "offset": offset,
                    "takerOnly": "false",
                }
                r = requests.get(f"{DATA_API}/trades", params=params, timeout=15)
                if r.status_code == 400:
                    # Data API caps offset at ~3500; treat as end-of-data
                    break
                r.raise_for_status()
                trades = r.json()

                if not trades:
                    break

                stop_early = False
                for trade in trades:
                    trade_ts = int(float(trade.get("timestamp", 0)))
                    if trade_ts < since_ts:
                        stop_early = True
                        break

                    # Skip NO-token trades — condition ID returns both YES and NO trades.
                    # Filter to YES token only using the `asset` field.
                    if str(trade.get("asset", "")) != str(token_id):
                        continue

                    # Deduplicate: each fill comes as both a BUY and a SELL record
                    # with the same transactionHash.  Keep only the first occurrence.
                    tx_hash = trade.get("transactionHash", "")
                    if tx_hash:
                        if tx_hash in seen_hashes:
                            continue
                        seen_hashes.add(tx_hash)

                    yes_price = float(trade.get("price", 0))
                    timestamp_iso = datetime.fromtimestamp(
                        trade_ts, tz=timezone.utc
                    ).isoformat()

                    # Synthetic book snapshot — emitted just before the trade
                    book = make_book_event(token_id, timestamp_iso, yes_price, spread, book_size)
                    f.write(json.dumps(book) + "\n")

                    # Trade event
                    event = {
                        "event_type": "trade",
                        "market_id": token_id,
                        "fill_id": trade.get("transactionHash", f"tx_{total}"),
                        "timestamp": timestamp_iso,
                        "side": trade.get("side", "BUY").upper(),
                        "price": yes_price,
                        "size": float(trade.get("size", 0)),
                        "is_maker": False,
                    }
                    f.write(json.dumps(event) + "\n")
                    total += 1

                if stop_early or len(trades) < limit:
                    break

                offset += limit
                time.sleep(0.2)

        tmp_path.replace(out_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    return total


# ---------------------------------------------------------------------------
# High-level ingest helpers
# ---------------------------------------------------------------------------

def ingest_one(
    market_input: str,
    out_dir: Path,
    days: int = 30,
    since_str: Optional[str] = None,
    spread: float = 0.02,
    book_size: float = 500.0,
    skip_existing: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Ingest one market by URL/slug/condition_id.
    Returns a result dict with keys: market_input, condition_id, token_id,
    title, n_trades, skipped (bool), error (str or None).
    """
    from datetime import datetime, timezone, timedelta
    if since_str:
        since_dt = datetime.strptime(since_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_ts = int(since_dt.timestamp())

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        condition_id, token_id, title = resolve_market(market_input)
    except Exception as exc:
        return {"market_input": market_input, "condition_id": "", "token_id": "",
                "title": "", "n_trades": 0, "skipped": False, "error": str(exc)}

    out_path = out_dir / f"{token_id}.jsonl"

    if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
        if verbose:
            print(f"  SKIP (exists): {title[:60]}")
        return {"market_input": market_input, "condition_id": condition_id,
                "token_id": token_id, "title": title,
                "n_trades": 0, "skipped": True, "error": None}

    if verbose:
        print(f"  Ingesting: {title[:60]}")

    try:
        n = fetch_trades(condition_id, token_id, since_ts, out_path, spread, book_size)
    except Exception as exc:
        return {"market_input": market_input, "condition_id": condition_id,
                "token_id": token_id, "title": title,
                "n_trades": 0, "skipped": False, "error": str(exc)}

    # Write sidecar
    sidecar_path = out_dir / f"{token_id}.json"
    if not sidecar_path.exists():
        sidecar = {"condition_id": condition_id, "yes_token_id": token_id, "title": title}
        with sidecar_path.open("w") as sf:
            json.dump(sidecar, sf, indent=2)

    return {"market_input": market_input, "condition_id": condition_id,
            "token_id": token_id, "title": title,
            "n_trades": n, "skipped": False, "error": None}


def _bulk_ingest_from_universe(
    universe_path: Path,
    out_dir: Path,
    days: int,
    spread: float,
    book_size: float,
    workers: int,
    skip_existing: bool,
) -> None:
    """Bulk-ingest all active, un-ingested markets from universe.json."""
    import threading
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.data.universe import MarketUniverse
    from dataclasses import replace as dc_replace

    universe = MarketUniverse()
    universe.load(universe_path)

    markets = universe.markets_needing_ingest()
    if not markets:
        print("No markets need ingestion.")
        return

    print(f"Ingesting {len(markets)} markets with {workers} worker(s)...")

    import concurrent.futures

    _print_lock = threading.Lock()
    results = []

    def _worker(m):
        result = ingest_one(
            market_input=m.condition_id,
            out_dir=out_dir,
            days=days,
            spread=spread,
            book_size=book_size,
            skip_existing=skip_existing,
            verbose=False,
        )
        with _print_lock:
            status = "SKIP" if result["skipped"] else ("ERR" if result["error"] else f"{result['n_trades']} trades")
            print(f"  [{status}] {m.question[:60]}")
        # Rate limit between workers
        time.sleep(0.5)
        return m.condition_id, result

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_worker, m): m for m in markets}
        for fut in concurrent.futures.as_completed(futures):
            try:
                condition_id, result = fut.result()
                results.append(result)
                if not result["error"] and not result["skipped"]:
                    # Mark as ingested in universe
                    m = universe.get(condition_id)
                    if m:
                        universe.update(dc_replace(m, ingested=True))
            except Exception as exc:
                print(f"  Worker error: {exc}", file=sys.stderr)

    universe.save(universe_path)

    n_ok = sum(1 for r in results if not r["error"] and not r["skipped"])
    n_skip = sum(1 for r in results if r["skipped"])
    n_err = sum(1 for r in results if r["error"])
    print(f"\nBulk ingest complete: {n_ok} ingested, {n_skip} skipped, {n_err} errors")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ingest Polymarket trade history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--market", required=False, default=None,
        help="Polymarket URL, slug, or condition ID",
    )
    parser.add_argument("--out", default="data/raw", help="Output directory (default: data/raw)")
    parser.add_argument("--days", type=int, default=30, help="Days of history counting back from today (default: 30)")
    parser.add_argument("--since", default=None, help="Explicit start date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--spread", type=float, default=0.02,
                        help="Synthetic book half-spread in price units (default: 0.02)")
    parser.add_argument("--book-size", type=float, default=500,
                        help="Synthetic book depth in contracts per level (default: 500)")
    parser.add_argument("--from-universe", type=str, default=None,
                        metavar="FILE",
                        help="Read universe.json, ingest all markets with ingested=False")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel ingest workers (default 1, max 8)")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip markets that already have a .jsonl file (default True)")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = parser.parse_args()

    if args.from_universe:
        _bulk_ingest_from_universe(
            universe_path=Path(args.from_universe),
            out_dir=Path(args.out),
            days=args.days,
            spread=args.spread,
            book_size=args.book_size,
            workers=min(max(1, args.workers), 8),
            skip_existing=args.skip_existing,
        )
        return

    if not args.market:
        parser.error("--market is required unless --from-universe is specified")

    result = ingest_one(
        market_input=args.market,
        out_dir=Path(args.out),
        days=args.days,
        since_str=args.since,
        spread=args.spread,
        book_size=args.book_size,
        skip_existing=False,  # single-market call: always ingest
        verbose=True,
    )
    if result["error"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    n = result["n_trades"]
    token_id = result["token_id"]
    out_path = Path(args.out) / f"{token_id}.jsonl"
    print(f"Done. {n} trades written to {out_path}")


if __name__ == "__main__":
    main()
