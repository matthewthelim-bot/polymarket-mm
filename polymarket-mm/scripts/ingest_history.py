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
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
    r = requests.get(f"{GAMMA_BASE}/markets", params={"conditionId": condition_id}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"No market found for conditionId={condition_id}")
    needle = condition_id.lower()
    m = next((x for x in data if x.get("conditionId", "").lower() == needle), data[0])
    return condition_id, _extract_token_id(m), m.get("question", condition_id)


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
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ingest Polymarket trade history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--market", required=True,
        help="Polymarket URL, slug, or condition ID",
    )
    parser.add_argument("--out", default="data/raw", help="Output directory (default: data/raw)")
    parser.add_argument("--days", type=int, default=30, help="Days of history counting back from today (default: 30)")
    parser.add_argument("--since", default=None, help="Explicit start date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--spread", type=float, default=0.02,
                        help="Synthetic book half-spread in price units (default: 0.02)")
    parser.add_argument("--book-size", type=float, default=500,
                        help="Synthetic book depth in contracts per level (default: 500)")
    args = parser.parse_args()

    if args.since:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
    since_ts = int(since_dt.timestamp())

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Resolving: {args.market}")
    condition_id, token_id, title = resolve_market(args.market)

    print(f"  Market:       {title}")
    print(f"  Condition ID: {condition_id}")
    print(f"  Token ID:     {token_id}")
    print(f"  Since:        {since_dt.strftime('%Y-%m-%d')}")

    out_path = out_dir / f"{token_id}.jsonl"
    print(f"\nDownloading trades -> {out_path}")

    n = fetch_trades(condition_id, token_id, since_ts, out_path, args.spread, args.book_size)
    print(f"Done. {n} trades written (+ {n} synthetic book snapshots) to {out_path}")


if __name__ == "__main__":
    main()
