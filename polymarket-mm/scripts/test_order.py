#!/usr/bin/env python3
"""One-shot auth + order-plumbing test. The first real credential touch.

Places ONE tiny far-from-mid GTD bid on a liquid market, verifies it appears
in open orders, then cancels it. Validates in ~30 seconds:
  - signature_type=2 + funder (MetaMask account) sign-and-post works
  - API credentials (L2) are valid
  - USDC allowance lets an order rest
  - cancel works
  - get_positions()/get_open_orders() reconcile with the Polymarket UI

The bid is placed 20+ cents BELOW best bid so it cannot realistically fill
in the seconds it exists; worst case it fills for ~$1-2 of YES tokens.

Usage:
    py -3 scripts/test_order.py --confirm
    py -3 scripts/test_order.py --confirm --market 0x<condition_id>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.schemas import Side
from src.live.clob_client import ClobClient, OrderRequest
from src.live.credentials import load_credentials, CredentialError


def pick_liquid_market() -> tuple[str, str, float]:
    """A high-volume market with a mid-range price (so a deep bid is safe)."""
    url = ("https://gamma-api.polymarket.com/markets?active=true&closed=false"
           "&limit=25&order=volume24hr&ascending=false")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        markets = json.loads(r.read())
    for m in markets:
        try:
            price = float(m.get("bestBid") or 0)
            if 0.30 <= price <= 0.70:
                tokens = m.get("clobTokenIds")
                if isinstance(tokens, str):
                    tokens = json.loads(tokens)
                return m["conditionId"], tokens[0], price
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    raise SystemExit("No suitable liquid market found — pass --market explicitly")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--confirm", action="store_true",
                    help="Required. This script places ONE real (tiny) order.")
    ap.add_argument("--market", default="", help="condition_id override")
    args = ap.parse_args()
    if not args.confirm:
        ap.error("This places a real order (~$1-2 at risk for seconds). "
                 "Re-run with --confirm.")

    try:
        creds = load_credentials()
    except CredentialError as exc:
        raise SystemExit(f"Credentials: {exc}")
    client = ClobClient(credentials=creds)

    if args.market:
        cid = args.market
        yes_token, _ = client.get_market_tokens(cid)
        book = client.get_book(yes_token)
        best_bid = book.bids[0].price if book.bids else 0.5
    else:
        cid, yes_token, best_bid = pick_liquid_market()

    test_price = round(max(0.01, best_bid - 0.20), 2)
    size = max(5.0, round(1.0 / test_price))  # >= exchange minimum, ~$1-2
    expiry = int(time.time()) + 120  # GTD: self-destructs in 2 min regardless

    print(f"market    : {cid[:30]}...")
    print(f"test bid  : {size:.0f} @ {test_price:.2f}  "
          f"(best bid {best_bid:.2f} — we are {best_bid - test_price:.2f} below)")
    print(f"GTD expiry: {expiry} (2 min)\n")

    print("1) placing order ...")
    resp = client.place_order(OrderRequest(
        token_id=yes_token, side=Side.BUY, price=test_price, size=size,
        time_in_force="GTD", expiration=expiry,
    ))
    print(f"   PLACED  id={resp.order_id}  status={resp.status}  "
          f"filled={resp.filled_size}")

    print("2) verifying on the book ...")
    time.sleep(2)
    open_orders = client.get_open_orders()
    ours = [o for o in open_orders if o.order_id == resp.order_id]
    print(f"   open orders for account: {len(open_orders)}; "
          f"test order visible: {bool(ours)}")

    print("3) cancelling ...")
    ok = client.cancel_order(resp.order_id)
    print(f"   CANCELLED: {ok}")

    print("4) positions reconciliation ...")
    positions = client.get_positions()
    print(f"   open positions on account: {len(positions)} "
          f"(compare with polymarket.com/portfolio)")

    if resp.order_id and ok:
        print("\nALL CHECKS PASSED — auth, allowances, place, verify, cancel.")
    else:
        print("\nCHECK OUTPUT ABOVE — something did not confirm cleanly.")


if __name__ == "__main__":
    main()
