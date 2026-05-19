#!/usr/bin/env python3
"""
Download historical trade data from Polymarket and save as JSONL.

Usage — pass anything from the browser URL bar:
    py scripts/ingest_history.py --market "polymarket.com/sports/epl/epl-bou-mac-2026-05-19"
    py scripts/ingest_history.py --market "epl-bou-mac-2026-05-19"
    py scripts/ingest_history.py --market "0xabc123..."

The script auto-detects whether you passed a URL, slug, or condition ID
and resolves everything automatically — no manual ID lookup needed.

Optional flags:
    --out data/raw      output directory (default: data/raw)
    --days 30           days of history to download (default: 30)
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

    # Already a condition ID
    if re.match(r"^0x[0-9a-fA-F]{10,}$", raw):
        return _resolve_by_condition_id(raw)

    # URL or slug — take the last path segment
    slug = raw.split("/")[-1].split("?")[0]
    return _resolve_by_slug(slug)


def _resolve_by_slug(slug: str) -> tuple[str, str, str]:
    # Try events endpoint first (sports events have multiple sub-markets)
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

    # Fall back to markets endpoint
    r = requests.get(f"{GAMMA_BASE}/markets", params={"slug": slug}, timeout=10)
    r.raise_for_status()
    markets = r.json()

    if not markets:
        raise ValueError(
            f"No market found for '{slug}'.\n"
            f"Check that the URL is from polymarket.com and the market is still active."
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
# Trade fetching (public endpoint — no auth required)
# ---------------------------------------------------------------------------

def fetch_trades(condition_id: str, token_id: str, days: int, out_path: Path) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_ts = int(since.timestamp())
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

                    event = {
                        "event_type": "trade",
                        "market_id": token_id,
                        "fill_id": trade.get("transactionHash", f"tx_{total}"),
                        "timestamp": datetime.fromtimestamp(
                            trade_ts, tz=timezone.utc
                        ).isoformat(),
                        "side": trade.get("side", "BUY").upper(),
                        "price": float(trade.get("price", 0)),
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
        epilog="Pass any Polymarket URL, slug, or condition ID to --market.",
    )
    parser.add_argument(
        "--market", required=True,
        help='Polymarket URL, slug, or condition ID  '
             '(e.g. "polymarket.com/sports/epl/epl-bou-mac-2026-05-19")',
    )
    parser.add_argument("--out", default="data/raw", help="Output directory (default: data/raw)")
    parser.add_argument("--days", type=int, default=30, help="Days of history (default: 30)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Resolving: {args.market}")
    condition_id, token_id, title = resolve_market(args.market)

    print(f"  Market:       {title}")
    print(f"  Condition ID: {condition_id}")
    print(f"  Token ID:     {token_id}")

    out_path = out_dir / f"{token_id}.jsonl"
    print(f"\nDownloading {args.days} days of trades -> {out_path}")

    n = fetch_trades(condition_id, token_id, args.days, out_path)
    print(f"Done. {n} trade events written to {out_path}")


if __name__ == "__main__":
    main()
