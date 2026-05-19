#!/usr/bin/env python3
"""
Download historical CLOB data from Polymarket APIs and save as JSONL.

Usage:
    python scripts/ingest_history.py --market CONDITION_ID --out data/raw/ --days 30

Endpoints used:
  GET https://gamma-api.polymarket.com/markets?conditionId={condition_id}
  GET https://clob.polymarket.com/trades?market={token_id}&limit=500

Note: Polymarket does not provide full historical order book snapshots via public API.
The ingestion stores trade events. For higher-fidelity backtesting, use the WebSocket
feed captured in real-time.
"""

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

API_KEY = os.environ.get("POLYMARKET_API_KEY", "")

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


def fetch_market_info(condition_id: str) -> dict:
    url = f"{GAMMA_BASE}/markets?conditionId={condition_id}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"No market found for conditionId={condition_id}")
    # Filter to find the exact market (API may return a group)
    needle = condition_id.lower()
    for m in data:
        if m.get("conditionId", "").lower() == needle:
            return m
    return data[0]


def fetch_trades(token_id: str, days: int, out_path: Path) -> int:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_ts = int(since.timestamp())
    cursor = None
    total = 0

    tmp_path = out_path.with_suffix(".jsonl.tmp")
    try:
        with tmp_path.open("w") as f:
            while True:
                params = {"market": token_id, "limit": 500}
                if cursor:
                    params["next_cursor"] = cursor
                headers = {}
                if API_KEY:
                    headers["Authorization"] = f"Bearer {API_KEY}"
                r = requests.get(f"{CLOB_BASE}/trades", params=params, headers=headers, timeout=15)
                if r.status_code == 401:
                    raise PermissionError(
                        "CLOB /trades requires authentication. "
                        "Set POLYMARKET_API_KEY environment variable. "
                        "See: https://docs.polymarket.com/developers/clob/api-keys"
                    )
                r.raise_for_status()
                data = r.json()

                trades = data.get("data", [])
                next_cursor = data.get("next_cursor")

                stop_early = False
                for trade in trades:
                    trade_ts = int(trade.get("timestamp", 0))
                    if trade_ts < since_ts:
                        stop_early = True
                        break
                    event = {
                        "event_type": "trade",
                        "market_id": token_id,
                        "fill_id": trade.get("id", ""),
                        "timestamp": datetime.fromtimestamp(trade_ts, tz=timezone.utc).isoformat(),
                        "side": trade.get("side", "buy").lower(),
                        "price": float(trade.get("price", 0)),
                        "size": float(trade.get("size", 0)),
                        "is_maker": bool(trade.get("maker_address") is not None),
                    }
                    f.write(json.dumps(event) + "\n")
                    total += 1

                if stop_early or not next_cursor or not trades:
                    break
                cursor = next_cursor
                time.sleep(0.2)

        tmp_path.replace(out_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return total


def main():
    parser = argparse.ArgumentParser(description="Ingest Polymarket historical data")
    parser.add_argument("--market", required=True, help="Condition ID")
    parser.add_argument("--out", default="data/raw", help="Output directory")
    parser.add_argument("--days", type=int, default=30, help="Days of history")
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

    print(f"Token ID: {token_id}")
    out_path = out_dir / f"{token_id}.jsonl"

    print(f"Downloading {args.days} days of trades -> {out_path}")
    n = fetch_trades(token_id, args.days, out_path)
    print(f"Done. {n} trade events written to {out_path}")


if __name__ == "__main__":
    main()
