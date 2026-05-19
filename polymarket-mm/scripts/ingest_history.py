#!/usr/bin/env python3
"""
Download historical trade data from Polymarket APIs and save as JSONL.

Usage:
    python scripts/ingest_history.py --market CONDITION_ID --out data/raw/ --days 30

Endpoints used:
  GET https://gamma-api.polymarket.com/markets?conditionId={condition_id}
      -> get token_id (for output filename) and market metadata
  GET https://data-api.polymarket.com/trades?market={condition_id}&limit=500
      -> public endpoint, no auth required, returns all trades for a market

Note: Polymarket does not provide full historical order book snapshots via public API.
The ingestion stores trade events. For higher-fidelity backtesting, use the WebSocket
feed captured in real-time.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass  # dotenv optional

DATA_API  = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


def fetch_market_info(condition_id: str) -> dict:
    url = f"{GAMMA_BASE}/markets?conditionId={condition_id}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"No market found for conditionId={condition_id}")
    # Filter to find the exact market (API may return a whole event group)
    needle = condition_id.lower()
    for m in data:
        if m.get("conditionId", "").lower() == needle:
            return m
    return data[0]


def fetch_trades(condition_id: str, token_id: str, days: int, out_path: Path) -> int:
    """
    Fetch all public trades for `condition_id` from data-api.polymarket.com.
    No authentication required.
    """
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
                    # timestamp is a Unix float/int in this API
                    raw_ts = trade.get("timestamp", 0)
                    trade_ts = int(float(raw_ts))
                    if trade_ts < since_ts:
                        stop_early = True
                        break

                    event = {
                        "event_type": "trade",
                        "market_id": token_id,   # use token_id as market_id for loader compatibility
                        "fill_id": trade.get("transactionHash", f"tx_{total}"),
                        "timestamp": datetime.fromtimestamp(trade_ts, tz=timezone.utc).isoformat(),
                        "side": trade.get("side", "BUY").upper(),
                        "price": float(trade.get("price", 0)),
                        "size": float(trade.get("size", 0)),
                        "is_maker": False,  # data API does not distinguish maker/taker
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


def main():
    parser = argparse.ArgumentParser(description="Ingest Polymarket historical trade data")
    parser.add_argument("--market", required=True, help="Condition ID (from market URL)")
    parser.add_argument("--out", default="data/raw", help="Output directory")
    parser.add_argument("--days", type=int, default=30, help="Days of history to fetch")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching market info for {args.market}...")
    info = fetch_market_info(args.market)
    raw_tokens = info.get("clobTokenIds") or info.get("clob_token_ids")
    if not raw_tokens:
        raise ValueError(f"No token ID found for {args.market}")
    if isinstance(raw_tokens, str):
        raw_tokens = json.loads(raw_tokens)
    token_id = raw_tokens[0]
    if not token_id:
        raise ValueError(f"No token ID found for {args.market}")

    print(f"Token ID:   {token_id}")
    print(f"Market:     {info.get('question', args.market)}")
    out_path = out_dir / f"{token_id}.jsonl"

    print(f"Downloading {args.days} days of trades -> {out_path}")
    n = fetch_trades(args.market, token_id, args.days, out_path)
    print(f"Done. {n} trade events written to {out_path}")


if __name__ == "__main__":
    main()
