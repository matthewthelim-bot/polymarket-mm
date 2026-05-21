#!/usr/bin/env python3
# scripts/run_discovery.py
"""
Perpetual market discovery daemon.

Re-scans all Polymarket markets every --interval seconds (default 4h),
updates universe.json with newly qualifying and expired markets,
and auto-ingests the last 7 days of data for new active markets.

Does NOT place any orders. This is the discovery/data layer only.
run_live.py polls universe.json and manages QuoteLoops independently.

Usage:
    py -3 scripts/run_discovery.py                      # runs forever, updates every 4h
    py -3 scripts/run_discovery.py --interval 3600      # re-scan every 1h
    py -3 scripts/run_discovery.py --dry-run            # score only, don't ingest or save
    py -3 scripts/run_discovery.py --once               # run one cycle then exit

Ctrl-C for graceful shutdown.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from dataclasses import replace as dc_replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.universe import MarketUniverse
from scripts.build_universe import build_universe
from scripts.ingest_history import _bulk_ingest_from_universe


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )


def run_one_cycle(
    universe_path: Path,
    out_dir: Path,
    warm_up_days: int,
    min_std: float,
    min_quotable: float,
    use_volatility: bool,
    dry_run: bool,
    workers: int,
) -> None:
    log = logging.getLogger("run_discovery")
    log.info("Starting discovery cycle...")

    # Load existing universe to preserve ingested flags
    existing = MarketUniverse()
    existing.load(universe_path)
    existing_by_id = {m.condition_id: m for m in existing.all_markets()}

    # Re-score all markets
    new_universe = build_universe(
        pages="all",
        use_volatility=use_volatility,
        top_n=10000,       # no hard cap — scoring filter decides
        min_std=min_std,
        min_quotable=min_quotable,
    )

    # Preserve ingested=True flags from previous run
    for m in new_universe.all_markets():
        prev = existing_by_id.get(m.condition_id)
        if prev and prev.ingested:
            new_universe.update(dc_replace(m, ingested=True))

    active = new_universe.active_markets()
    need_ingest = new_universe.markets_needing_ingest()

    log.info(
        "Cycle complete: %d total, %d active, %d need ingest",
        len(new_universe.all_markets()), len(active), len(need_ingest),
    )

    if dry_run:
        log.info("DRY RUN — not saving universe or ingesting data")
        return

    new_universe.save(universe_path)
    log.info("Universe saved to %s", universe_path)

    if need_ingest:
        log.info(
            "Auto-ingesting %d new markets (%d-day warm-up)...",
            len(need_ingest), warm_up_days,
        )
        _bulk_ingest_from_universe(
            universe_path=universe_path,
            out_dir=out_dir,
            days=warm_up_days,
            spread=0.02,
            book_size=500.0,
            workers=workers,
            skip_existing=True,
        )
        log.info("Auto-ingest complete")
    else:
        log.info("No new markets to ingest")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Perpetual Polymarket discovery daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--interval", type=int, default=14400,
                        help="Seconds between re-scan cycles (default 14400 = 4h)")
    parser.add_argument("--warm-up-days", type=int, default=7,
                        help="Days of history to ingest for new active markets (default 7)")
    parser.add_argument("--min-std", type=float, default=0.03,
                        help="Minimum volatility std (default 0.03)")
    parser.add_argument("--min-quotable", type=float, default=20.0,
                        help="Minimum exit liquidity in contracts (default 20)")
    parser.add_argument("--volatility", action="store_true", default=True,
                        help="Fetch volatility for each market (default True)")
    parser.add_argument("--no-volatility", dest="volatility", action="store_false")
    parser.add_argument("--workers", type=int, default=2,
                        help="Parallel ingest workers (default 2)")
    parser.add_argument("--out", default="data/raw",
                        help="Output directory for .jsonl files (default data/raw)")
    parser.add_argument("--universe", default="data/universe.json",
                        help="Path for universe.json (default data/universe.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Score only, don't save universe or ingest data")
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle then exit")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("run_discovery")

    universe_path = Path(args.universe)
    out_dir = Path(args.out)

    stop = False

    def _handle_signal(sig, frame):
        nonlocal stop
        log.info("Shutdown signal received, stopping after current cycle...")
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info(
        "Discovery daemon starting. interval=%ds, dry_run=%s, volatility=%s",
        args.interval, args.dry_run, args.volatility,
    )

    while not stop:
        try:
            run_one_cycle(
                universe_path=universe_path,
                out_dir=out_dir,
                warm_up_days=args.warm_up_days,
                min_std=args.min_std,
                min_quotable=args.min_quotable,
                use_volatility=args.volatility,
                dry_run=args.dry_run,
                workers=min(max(1, args.workers), 8),
            )
        except Exception as exc:
            log.error("Cycle failed: %s", exc, exc_info=True)

        if args.once or stop:
            break

        log.info("Sleeping %ds until next cycle...", args.interval)
        # Sleep in 10s increments to remain responsive to Ctrl-C
        elapsed = 0
        while elapsed < args.interval and not stop:
            time.sleep(min(10, args.interval - elapsed))
            elapsed += 10

    log.info("Discovery daemon stopped.")


if __name__ == "__main__":
    main()
