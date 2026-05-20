#!/usr/bin/env python3
# scripts/run_live.py
"""
Live market making runner.

Discovers markets from data/raw (or --markets flag), starts WebSocket book feed,
and runs a QuoteLoop per market.

SECURITY:
  - Loads credentials from environment / .env file — never prints them
  - --dry-run is the DEFAULT — pass --live to actually place orders
  - All credential loading goes through src.live.credentials

Usage:
    # Dry run (default — no orders placed):
    py -3 scripts/run_live.py

    # Specific markets:
    py -3 scripts/run_live.py --markets data/raw/1116682...jsonl data/raw/2700472...jsonl

    # Live trading (opt-in):
    py -3 scripts/run_live.py --live

    # Parameters:
    py -3 scripts/run_live.py --half-spread 0.030 --quote-size 100 --max-concurrent 1

Ctrl-C for graceful shutdown.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fee_model import FeeModel
from src.live.credentials import load_credentials, CredentialError
from src.live.clob_client import ClobClient
from src.live.book_feed import BookFeed
from src.live.quote_loop import QuoteLoop, QuoteLoopConfig


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def discover_markets(data_dir: Path) -> list[Path]:
    """Return all .jsonl files in data_dir, sorted."""
    return sorted(data_dir.glob("*.jsonl"))


def load_sidecar(jsonl_path: Path) -> dict:
    """Load sidecar .json for a market (contains condition_id, token IDs, etc.)."""
    sidecar = jsonl_path.with_suffix(".json")
    if sidecar.exists():
        with sidecar.open() as f:
            return json.load(f)
    return {}


def resolve_market_tokens(
    jsonl_path: Path,
    client: ClobClient,
) -> tuple[str, str, str, str] | None:
    """
    Return (yes_token_id, no_token_id, condition_id, market_question) for a market.

    Tries sidecar first, then CLOB API. Returns None on failure.
    """
    log = logging.getLogger("run_live")
    market_id = jsonl_path.stem
    sidecar = load_sidecar(jsonl_path)

    yes_token = sidecar.get("yes_token_id")
    condition_id = sidecar.get("condition_id")
    title = sidecar.get("title", market_id[:40])

    if not yes_token:
        # Filename is the YES token (from ingest_history.py)
        if market_id.isdigit() and len(market_id) > 30:
            yes_token = market_id
        else:
            log.warning("Cannot determine YES token for %s", market_id[:40])
            return None

    # Get condition_id from CLOB /book if not in sidecar
    if not condition_id:
        try:
            condition_id = client.get_condition_id_for_token(yes_token)
        except Exception as exc:
            log.warning("Cannot resolve condition_id for %s: %s", market_id[:40], exc)
            return None

    # Get YES and NO tokens from CLOB /markets/{condition_id}
    try:
        yes_token_resolved, no_token = client.get_market_tokens(condition_id)
        # Prefer resolved YES token (may differ from filename in edge cases)
        yes_token = yes_token_resolved
    except Exception as exc:
        log.warning("Cannot resolve tokens for %s: %s", condition_id[:20], exc)
        return None

    # Try to get market question if not in sidecar
    if title == market_id[:40]:
        try:
            import requests as _req
            r = _req.get(f"https://clob.polymarket.com/markets/{condition_id}", timeout=5)
            if r.ok:
                title = r.json().get("question", title)[:80]
        except Exception:
            pass

    return yes_token, no_token, condition_id, title


def build_quote_loop(
    yes_token: str,
    no_token: str,
    condition_id: str,
    title: str,
    client: ClobClient,
    fee_model: FeeModel,
    args: argparse.Namespace,
) -> QuoteLoop:
    """Construct a QuoteLoop for one market from CLI args."""
    config = QuoteLoopConfig(
        market_id=title,
        yes_token_id=yes_token,
        no_token_id=no_token,
        condition_id=condition_id,
        fee_rate=args.fee_rate,
        rebate_fraction=args.rebate,
        half_spread_base=args.half_spread,
        min_edge_floor=args.min_edge,
        quote_size=args.quote_size,
        max_concurrent_positions=args.max_concurrent,
        time_to_resolution_hours=args.time_to_resolution,
        max_loss_fraction=args.max_loss,
        min_viable_size=1.0,
        price_tolerance=0.005,
        order_ttl_seconds=300.0,
        adverse_selection_threshold=0.012,
        daily_capital_charge_rate=0.0003,
        dry_run=not args.live,
    )
    return QuoteLoop(config=config, clob_client=client, fee_model=fee_model)


def print_startup_banner(loops: list[QuoteLoop], dry_run: bool) -> None:
    log = logging.getLogger("run_live")
    mode = "DRY-RUN (no orders will be placed)" if dry_run else "*** LIVE TRADING ***"
    log.info("=" * 60)
    log.info("Polymarket Market Maker — %s", mode)
    log.info("=" * 60)
    log.info("Markets (%d):", len(loops))
    for loop in loops:
        log.info("  %s", loop.config.market_id[:70])
    log.info("=" * 60)


def print_stats(loops: list[QuoteLoop]) -> None:
    log = logging.getLogger("run_live")
    log.info("--- STATS ---")
    total_pnl = 0.0
    for loop in loops:
        s = loop.stats
        log.info(
            "  %-40s updates=%d quotes=%d fills=%d exits=%d pnl=%.4f errors=%d",
            loop.config.market_id[:40],
            s.book_updates, s.quotes_computed, s.fills_received,
            s.exits_filled, s.total_pnl, s.errors,
        )
        total_pnl += s.total_pnl
    log.info("  TOTAL PnL (approx): %.4f", total_pnl)


async def main_async(args: argparse.Namespace) -> None:
    log = logging.getLogger("run_live")

    # Load credentials (required even for dry-run to test connection)
    if args.live:
        try:
            creds = load_credentials()
            client = ClobClient(credentials=creds)
            log.info("Credentials loaded (LIVE mode)")
        except CredentialError as exc:
            log.error("Cannot start live trading: %s", exc)
            sys.exit(1)
    else:
        client = ClobClient()   # no auth needed for dry-run (public endpoints)
        log.info("No credentials loaded (dry-run mode)")

    fee_model = FeeModel()

    # Discover markets
    if args.markets:
        market_paths = [Path(m) for m in args.markets]
    else:
        data_dir = Path(args.data)
        if not data_dir.exists():
            log.error("Data directory %s not found", data_dir)
            sys.exit(1)
        market_paths = discover_markets(data_dir)

    if not market_paths:
        log.error("No markets found. Use --data or --markets.")
        sys.exit(1)

    log.info("Resolving %d markets...", len(market_paths))

    # Resolve tokens for each market
    loops: list[QuoteLoop] = []
    token_ids: list[str] = []
    for path in market_paths:
        result = resolve_market_tokens(path, client)
        if result is None:
            log.warning("Skipping unresolvable market: %s", path.stem[:40])
            continue
        yes_token, no_token, condition_id, title = result
        loop = build_quote_loop(
            yes_token, no_token, condition_id, title, client, fee_model, args
        )
        loops.append(loop)
        token_ids.extend([yes_token, no_token])
        time.sleep(0.1)   # rate limit resolution calls

    if not loops:
        log.error("No markets could be resolved. Exiting.")
        sys.exit(1)

    print_startup_banner(loops, dry_run=not args.live)

    # Build token→loop mapping for callbacks
    token_to_loop: dict[str, QuoteLoop] = {}
    for loop in loops:
        token_to_loop[loop.config.yes_token_id] = loop

    # Set up book feed
    feed = BookFeed(token_ids=token_ids)

    def on_book_update(token_id: str, book):
        loop = token_to_loop.get(token_id)
        if loop:
            loop.on_yes_book_update(token_id, book)

    feed.on_any_book_update(on_book_update)

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _signal_handler(sig, frame):
        log.info("Shutdown signal received, stopping...")
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Run feed until stop
    feed_task = asyncio.create_task(feed.run())

    log.info("Book feed started. Waiting for market data...")
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=None)
    except asyncio.TimeoutError:
        pass
    except asyncio.CancelledError:
        pass
    finally:
        feed.stop()
        feed_task.cancel()
        try:
            await feed_task
        except asyncio.CancelledError:
            pass

    print_stats(loops)
    log.info("Shutdown complete.")


def main():
    parser = argparse.ArgumentParser(description="Polymarket live market maker")
    parser.add_argument(
        "--live", action="store_true", default=False,
        help="Enable live order placement (default: dry-run, no orders placed)"
    )
    parser.add_argument(
        "--data", default="data/raw",
        help="Directory with .jsonl market data (default: data/raw)"
    )
    parser.add_argument(
        "--markets", nargs="+",
        help="Specific .jsonl paths to trade (overrides --data)"
    )
    parser.add_argument("--quote-size", type=float, default=100.0)
    parser.add_argument("--half-spread", type=float, default=0.030)
    parser.add_argument("--fee-rate", type=float, default=0.07)
    parser.add_argument("--rebate", type=float, default=0.5)
    parser.add_argument("--min-edge", type=float, default=0.005)
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--time-to-resolution", type=float, default=720.0,
                        help="Hours to resolution (default 720 = 30 days)")
    parser.add_argument("--max-loss", type=float, default=0.10,
                        help="Max YES exit loss fraction (default 0.10)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.live:
        log = logging.getLogger("run_live")
        log.warning("=" * 60)
        log.warning("LIVE MODE ENABLED — orders WILL be placed on Polymarket")
        log.warning("Press Ctrl-C within 5 seconds to abort...")
        log.warning("=" * 60)
        time.sleep(5)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
