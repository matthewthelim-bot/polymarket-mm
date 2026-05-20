#!/usr/bin/env python3
# scripts/check_exit_liquidity.py
"""
Diagnostic: show real exit liquidity for all markets in data/raw.

For each market JSONL file, looks up its YES and NO token IDs (from
corresponding .json sidecar or Gamma API), fetches live L2 books from
the Polymarket CLOB, and runs the exit viability check.

Output shows whether each market is currently tradeable given real depth.

Usage:
    py -3 scripts/check_exit_liquidity.py [--data data/raw] [--quote-size 100]
    py -3 scripts/check_exit_liquidity.py --data data/raw --half-spread 0.030

No credentials needed (uses public endpoints only).
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fee_model import FeeModel
from src.live.clob_client import ClobClient
from src.live.exit_checker import ExitChecker


DEFAULT_FEE_RATE = 0.07
DEFAULT_REBATE = 0.5
DEFAULT_MIN_EDGE = 0.005


def load_token_ids_from_sidecar(sidecar_path: Path) -> tuple[str, str] | None:
    """Try to get YES/NO token IDs from a market sidecar .json file."""
    if not sidecar_path.exists():
        return None
    try:
        with sidecar_path.open() as f:
            data = json.load(f)
        yes_token = data.get("yes_token_id") or data.get("token_id_yes")
        no_token = data.get("no_token_id") or data.get("token_id_no")
        if yes_token and no_token:
            return yes_token, no_token
    except (json.JSONDecodeError, OSError):
        pass
    return None


def load_token_ids_from_gamma(
    client: ClobClient, condition_id: str
) -> tuple[str, str] | None:
    """Try to resolve YES/NO token IDs from Gamma API using condition_id."""
    try:
        return client.get_market_token_ids(condition_id)
    except Exception as exc:
        return None


def infer_token_ids(
    client: ClobClient,
    market_id: str,
    sidecar_path: Path,
) -> tuple[str, str] | None:
    """
    Try multiple strategies to find YES/NO token IDs for a market.

    Strategy 1: Read from .json sidecar (yes_token_id / no_token_id fields).
    Strategy 2: market_id is a YES token (long numeric string from ingest_history.py).
                Use CLOB /book to get condition_id, then /markets/{cond} for both tokens.
    Strategy 3: market_id is a condition_id (0x…). Use Gamma API directly.
    """
    # Strategy 1: sidecar
    result = load_token_ids_from_sidecar(sidecar_path)
    if result:
        return result

    # Strategy 2: market_id looks like a YES token_id (long numeric from ingest_history.py)
    if market_id.isdigit() and len(market_id) > 30:
        try:
            # Step 1: get condition_id from CLOB /book endpoint
            condition_id = client.get_condition_id_for_token(market_id)
            # Step 2: get both YES and NO tokens via CLOB /markets/{condition_id}
            yes_token, no_token = client.get_market_tokens(condition_id)
            return yes_token, no_token
        except Exception:
            pass

    # Strategy 3: try market_id as condition_id (0x… format)
    if market_id.startswith("0x"):
        try:
            yes_token, no_token = client.get_market_tokens(market_id)
            return yes_token, no_token
        except Exception:
            pass
        # Fallback to Gamma API
        result = load_token_ids_from_gamma(client, market_id)
        if result:
            return result

    return None


def get_market_question(sidecar_path: Path, market_id: str) -> str:
    """Try to get a human-readable market question from sidecar."""
    if sidecar_path.exists():
        try:
            with sidecar_path.open() as f:
                data = json.load(f)
            return data.get("title", data.get("question", market_id[:40]))
        except (json.JSONDecodeError, OSError):
            pass
    return market_id[:40]


def check_market(
    client: ClobClient,
    exit_checker: ExitChecker,
    market_id: str,
    sidecar_path: Path,
    entry_price: float,
    quote_size: float,
    fee_rate: float,
) -> dict:
    """
    Run exit viability check for one market. Returns a result dict.
    """
    result = {
        "market_id": market_id,
        "question": get_market_question(sidecar_path, market_id),
        "error": None,
        "yes_token": None,
        "no_token": None,
        "yes_best_bid": None,
        "no_best_ask": None,
        "yes_exit_size": None,
        "no_exit_size": None,
        "max_quotable": None,
        "max_flatten_price": None,
        "viable": False,
        "yes_bid_levels": 0,
        "no_ask_levels": 0,
    }

    token_ids = infer_token_ids(client, market_id, sidecar_path)
    if token_ids is None:
        result["error"] = "Could not resolve token IDs"
        return result

    yes_token, no_token = token_ids
    result["yes_token"] = yes_token[:20] + "..."
    result["no_token"] = no_token[:20] + "..."

    try:
        yes_book = client.get_book(yes_token)
        # Try to get market question from CLOB if not in sidecar
        if result["question"] == market_id[:40] and yes_book.market_id.startswith("0x"):
            try:
                import requests as _req
                r = _req.get(
                    f"https://clob.polymarket.com/markets/{yes_book.market_id}",
                    timeout=5
                )
                if r.ok:
                    result["question"] = r.json().get("question", result["question"])[:38]
            except Exception:
                pass
    except Exception as exc:
        result["error"] = f"YES book fetch failed: {exc}"
        return result

    try:
        no_book = client.get_book(no_token)
    except Exception as exc:
        result["error"] = f"NO book fetch failed: {exc}"
        return result

    viability = exit_checker.check(yes_book, no_book, entry_price, quote_size)

    result["yes_best_bid"] = viability.yes_best_bid
    result["no_best_ask"] = viability.no_best_ask
    result["yes_exit_size"] = viability.yes_exit_size
    result["no_exit_size"] = viability.no_exit_size
    result["max_quotable"] = viability.max_quotable_size
    result["max_flatten_price"] = viability.max_flatten_price
    result["viable"] = viability.is_viable
    result["yes_bid_levels"] = len(yes_book.bids)
    result["no_ask_levels"] = len(no_book.asks)
    return result


def print_report(results: list[dict], quote_size: float, entry_price: float) -> None:
    viable = [r for r in results if r["viable"]]
    errors = [r for r in results if r["error"]]
    not_viable = [r for r in results if not r["viable"] and not r["error"]]

    print()
    print("=" * 100)
    print(f"EXIT LIQUIDITY REPORT  (entry_price={entry_price:.3f}, quote_size={quote_size:.0f})")
    print("=" * 100)
    print()

    # Header
    hdr = (f"{'Question':<38} {'YBid':>6} {'NAsk':>6} {'YExit':>7} "
           f"{'NExit':>7} {'MaxQ':>7} {'MaxFlt':>7} {'Status'}")
    print(hdr)
    print("-" * 100)

    for r in sorted(results, key=lambda x: (not x["viable"], x["error"] is not None, x["market_id"])):
        label = r.get("question", r["market_id"])[:38]
        if r["error"]:
            print(f"{label:<38} ERROR: {r['error']}")
            continue
        status = "OK  VIABLE" if r["viable"] else "--- thin"
        print(
            f"{label:<38} "
            f"{r['yes_best_bid']:>6.3f} "
            f"{r['no_best_ask']:>6.3f} "
            f"{r['yes_exit_size']:>7.0f} "
            f"{r['no_exit_size']:>7.0f} "
            f"{r['max_quotable']:>7.0f} "
            f"{r['max_flatten_price']:>7.3f} "
            f"  {status}"
        )

    print("-" * 100)
    print()
    print(f"  Total markets:  {len(results)}")
    print(f"  Viable:         {len(viable)} ({len(viable)/max(len(results),1)*100:.0f}%)")
    print(f"  Thin/no depth:  {len(not_viable)}")
    print(f"  Errors:         {len(errors)}")
    print()

    if viable:
        print("VIABLE MARKETS (can quote up to max_quotable contracts):")
        for r in viable:
            label = r.get("question", r["market_id"])[:60]
            print(f"  {label:<60}  ->  {r['max_quotable']:.0f} contracts")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Check real exit liquidity for all markets in data dir"
    )
    parser.add_argument("--data", default="data/raw", help="Directory with JSONL market data")
    parser.add_argument("--quote-size", type=float, default=100.0, help="Target quote size")
    parser.add_argument("--half-spread", type=float, default=0.030,
                        help="Half-spread used to compute entry price from mid (default 0.030)")
    parser.add_argument("--entry-price", type=float, default=None,
                        help="Fixed entry price to check (overrides --half-spread)")
    parser.add_argument("--fee-rate", type=float, default=DEFAULT_FEE_RATE)
    parser.add_argument("--rebate", type=float, default=DEFAULT_REBATE)
    parser.add_argument("--min-edge", type=float, default=DEFAULT_MIN_EDGE)
    parser.add_argument("--max-loss", type=float, default=0.10,
                        help="Max acceptable loss fraction for YES exit (default 0.10)")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="Seconds between API calls to avoid rate limits (default 0.3)")
    args = parser.parse_args()

    data_dir = Path(args.data)
    if not data_dir.exists():
        print(f"ERROR: {data_dir} not found", file=sys.stderr)
        sys.exit(1)

    jsonl_files = sorted(data_dir.glob("*.jsonl"))
    if not jsonl_files:
        print(f"No .jsonl files found in {data_dir}")
        sys.exit(0)

    print(f"Found {len(jsonl_files)} markets in {data_dir}")
    print("Fetching live L2 books from Polymarket CLOB...")

    fm = FeeModel()
    client = ClobClient()  # public endpoints only
    exit_checker = ExitChecker(
        fee_model=fm,
        fee_rate=args.fee_rate,
        rebate_fraction=args.rebate,
        min_edge_floor=args.min_edge,
        max_loss_fraction=args.max_loss,
        min_viable_size=1.0,
    )

    results = []
    for i, jsonl_path in enumerate(jsonl_files):
        market_id = jsonl_path.stem
        sidecar_path = data_dir / f"{market_id}.json"

        # Determine entry price: either fixed or mid - half_spread
        if args.entry_price is not None:
            entry_price = args.entry_price
        else:
            # Fetch book first to get mid, then compute entry price
            # Use 0.50 as default mid if we can't resolve book yet
            entry_price = 0.50 - args.half_spread

        print(f"  [{i+1}/{len(jsonl_files)}] {market_id[:60]}...", end="\r", flush=True)

        r = check_market(
            client=client,
            exit_checker=exit_checker,
            market_id=market_id,
            sidecar_path=sidecar_path,
            entry_price=entry_price,
            quote_size=args.quote_size,
            fee_rate=args.fee_rate,
        )
        results.append(r)

        if args.delay > 0 and i < len(jsonl_files) - 1:
            time.sleep(args.delay)

    print(" " * 80, end="\r")  # clear progress line
    print_report(results, args.quote_size, entry_price)


if __name__ == "__main__":
    main()
