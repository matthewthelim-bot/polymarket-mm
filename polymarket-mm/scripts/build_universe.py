#!/usr/bin/env python3
# scripts/build_universe.py
"""
One-shot pipeline: scan all Polymarket markets -> score -> write universe.json -> bulk ingest.

Usage:
    py -3 scripts/build_universe.py --pages all --volatility --top 300 --days 90 --workers 4
    py -3 scripts/build_universe.py --pages 5 --volatility --top 50 --skip-ingest

Flags:
    --pages N|all     Gamma API pages to scan (500 markets/page; default: all)
    --volatility      Fetch last 200 trades per market for price std (slower, recommended)
    --top N           Mark top N markets active and ingest them (default 300)
    --days N          History window for ingestion in days (default 90)
    --workers N       Parallel ingest workers (default 4, max 8)
    --skip-ingest     Score and write universe.json only, skip downloading data
    --min-std FLOAT   Minimum volatility std threshold (default 0.03)
    --min-quotable F  Minimum exit liquidity threshold in contracts (default 20)
    --out DIR         Output directory for .jsonl files (default data/raw)
    --universe FILE   Path for universe.json (default data/universe.json)
    --delay FLOAT     Seconds between CLOB requests (default 0.15)
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fee_model import FeeModel
from src.live.clob_client import ClobClient
from src.live.exit_checker import ExitChecker
from src.data.universe import MarketUniverse, ScoredMarket

from scripts.scan_markets import (
    fetch_active_markets,
    scan_one,
    fetch_volatility,
    compute_score,
)


def build_universe(
    pages: int | str,       # int or "all"
    use_volatility: bool,
    top_n: int,
    min_std: float,
    min_quotable: float,
    fee_rate: float = 0.07,
    rebate: float = 0.5,
    min_edge: float = 0.005,
    max_loss: float = 0.10,
    half_spread: float = 0.025,
    delay: float = 0.15,
) -> MarketUniverse:
    """
    Scan Gamma, score all markets, return populated MarketUniverse.
    Top-N qualifying markets (by score) are marked active; rest get below_threshold or expired.
    """
    fm = FeeModel()
    client = ClobClient()
    exit_checker = ExitChecker(
        fee_model=fm,
        fee_rate=fee_rate,
        rebate_fraction=rebate,
        min_edge_floor=min_edge,
        max_loss_fraction=max_loss,
        min_viable_size=1.0,
    )

    all_pages = (pages == "all")
    limit = 10000 if all_pages else int(pages) * 500

    print(f"Fetching {'all' if all_pages else limit} markets from Gamma API...")
    markets = fetch_active_markets(
        limit=limit,
        all_pages=all_pages,
    )
    print(f"  Got {len(markets)} markets. Scoring each one...")

    scans = []
    for i, market in enumerate(markets):
        q = market.get("question", "?")[:55]
        q_safe = q.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace")
        print(f"  [{i+1:>4}/{len(markets)}] {q_safe:<55}", end="\r", flush=True)

        scan = scan_one(
            market=market,
            client=client,
            exit_checker=exit_checker,
            half_spread=half_spread,
            min_price=0.03,
            max_price=0.97,
            fetch_vol=use_volatility,
        )
        scans.append(scan)

        if delay > 0:
            time.sleep(delay)

    print(" " * 80, end="\r")
    print(f"  Scoring complete. {len(scans)} markets processed.")

    # Build universe: sort by score, assign status
    now_iso = datetime.now(timezone.utc).isoformat()
    universe = MarketUniverse()

    # Qualifying markets: viable + pass min thresholds
    viable = [s for s in scans if s.viable and s.max_quotable >= min_quotable]
    if use_volatility:
        viable = [s for s in viable if s.volatility_std >= min_std]
    viable.sort(key=lambda s: -s.score)

    active_ids = {s.condition_id for s in viable[:top_n]}

    for scan in scans:
        # Determine days_to_resolution
        days_remaining = 999.0
        if scan.end_date:
            try:
                end_dt = datetime.fromisoformat(scan.end_date).replace(tzinfo=timezone.utc)
                days_remaining = (end_dt - datetime.now(timezone.utc)).total_seconds() / 86400.0
            except Exception:
                pass

        if days_remaining <= 1.0:
            status = "expired"
        elif scan.condition_id in active_ids:
            status = "active"
        else:
            status = "below_threshold"

        m = ScoredMarket(
            condition_id=scan.condition_id,
            slug=scan.slug,
            question=scan.question,
            yes_token=scan.yes_token,
            no_token=scan.no_token,
            score=scan.score,
            volatility_std=scan.volatility_std,
            volume_24h=scan.volume_24h,
            max_quotable=scan.max_quotable,
            trades_per_day=scan.trades_per_day,
            end_date=scan.end_date,
            days_to_resolution=max(0.0, days_remaining),
            status=status,
            last_scored_at=now_iso,
            ingested=False,
        )
        universe.update(m)

    return universe


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build market universe and optionally bulk-ingest history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--pages", default="all",
                        help="Gamma pages to scan (N or 'all'; default: all)")
    parser.add_argument("--volatility", action="store_true",
                        help="Fetch last 200 trades per market for price std")
    parser.add_argument("--top", type=int, default=300,
                        help="Mark top N markets active and ingest them (default 300)")
    parser.add_argument("--days", type=int, default=90,
                        help="History window for ingestion in days (default 90)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel ingest workers (default 4)")
    parser.add_argument("--skip-ingest", action="store_true",
                        help="Score only, don't download data")
    parser.add_argument("--min-std", type=float, default=0.03,
                        help="Minimum volatility std (default 0.03)")
    parser.add_argument("--min-quotable", type=float, default=20.0,
                        help="Minimum exit liquidity in contracts (default 20)")
    parser.add_argument("--out", default="data/raw",
                        help="Output directory for .jsonl files (default data/raw)")
    parser.add_argument("--universe", default="data/universe.json",
                        help="Path for universe.json (default data/universe.json)")
    parser.add_argument("--delay", type=float, default=0.15,
                        help="Seconds between CLOB requests (default 0.15)")
    args = parser.parse_args()

    # Parse pages argument
    try:
        pages = int(args.pages)
    except ValueError:
        pages = "all"

    print(f"Building universe: pages={args.pages}, volatility={args.volatility}, "
          f"top={args.top}, min_std={args.min_std}, min_quotable={args.min_quotable}")

    universe = build_universe(
        pages=pages,
        use_volatility=args.volatility,
        top_n=args.top,
        min_std=args.min_std,
        min_quotable=args.min_quotable,
        delay=args.delay,
    )

    universe_path = Path(args.universe)
    universe.save(universe_path)

    active = universe.active_markets()
    total = len(universe.all_markets())
    print(f"\nUniverse written to {universe_path}")
    print(f"  Total scored:         {total}")
    print(f"  Active (top {args.top}):  {len(active)}")
    print(f"  Need ingest:          {len(universe.markets_needing_ingest())}")

    if args.skip_ingest:
        print("  Skipping ingest (--skip-ingest)")
        return

    if not universe.markets_needing_ingest():
        print("  All markets already ingested.")
        return

    print(f"\nStarting bulk ingest: {len(universe.markets_needing_ingest())} markets, "
          f"{args.days} days history, {args.workers} workers...")

    from scripts.ingest_history import _bulk_ingest_from_universe
    _bulk_ingest_from_universe(
        universe_path=universe_path,
        out_dir=Path(args.out),
        days=args.days,
        spread=0.02,
        book_size=500.0,
        workers=min(max(1, args.workers), 8),
        skip_existing=True,
    )

    # Reload to get updated ingested counts
    universe2 = MarketUniverse()
    universe2.load(universe_path)
    ingested = sum(1 for m in universe2.active_markets() if m.ingested)
    print(f"\nSummary:")
    print(f"  Markets scanned:  {total}")
    print(f"  Qualifying:       {len(active)}")
    print(f"  Ingested:         {ingested}")
    print(f"  Skipped/errors:   {len(active) - ingested}")


if __name__ == "__main__":
    main()
