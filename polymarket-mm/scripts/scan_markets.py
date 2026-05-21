#!/usr/bin/env python3
# scripts/scan_markets.py
"""
Scan active Polymarket markets for fill viability.

Queries the Gamma API for active markets, fetches live YES+NO books,
and scores each market on TWO axes:

  1. Hedge accessibility  — real NO ask depth at max_flatten_price
                            (can we exit if filled?)
  2. Trade frequency      — 24h volume from Gamma API
                            (will we actually get filled?)

Sorted by a composite score: log(volume24h+1) * max_quotable.
Both axes must pass their minimums to appear in the output.

Use this to find markets worth ingesting history for, then backtest.

Usage:
    py -3 scripts/scan_markets.py                          # top 50, any price
    py -3 scripts/scan_markets.py --limit 300              # scan more markets
    py -3 scripts/scan_markets.py --min-volume 1000        # active markets only
    py -3 scripts/scan_markets.py --min-price 0.10 --max-price 0.90
    py -3 scripts/scan_markets.py --min-quotable 100       # deep exit liquidity
    py -3 scripts/scan_markets.py --sort volume            # sort by volume only
    py -3 scripts/scan_markets.py --sort hedge             # sort by hedge depth only
    py -3 scripts/scan_markets.py --tag politics           # filter by category
    py -3 scripts/scan_markets.py --ingest                 # print ingest commands

No credentials needed (public endpoints only).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fee_model import FeeModel
from src.live.clob_client import ClobClient
from src.live.exit_checker import ExitChecker

GAMMA_BASE = "https://gamma-api.polymarket.com"
DATA_API   = "https://data-api.polymarket.com"
CLOB_BASE  = "https://clob.polymarket.com"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MarketScan:
    condition_id: str
    slug: str
    question: str
    yes_token: str
    no_token: str
    yes_mid: Optional[float]
    no_mid: Optional[float]
    entry_price: float           # yes_mid - half_spread
    yes_exit_size: float
    no_exit_size: float
    max_quotable: float
    max_flatten_price: float
    viable: bool
    error: Optional[str]
    tags: list[str]
    # Volume / activity metrics from Gamma API
    volume_24h: float = 0.0      # USDC traded in last 24h
    volume_total: float = 0.0    # all-time USDC volume
    spread_pct: float = 0.0      # (ask - bid) / mid as fraction
    end_date: str = ""           # resolution date if known
    # Composite score used for ranking
    score: float = 0.0
    volatility_std: float = 0.0   # price std from last 200 trades (0 = not fetched)
    trades_per_day: float = 0.0   # estimated from 24h trade count


# ---------------------------------------------------------------------------
# Gamma API helpers
# ---------------------------------------------------------------------------

def fetch_active_markets(
    limit: int = 100,
    tag: Optional[str] = None,
    min_volume: float = 0.0,
    all_pages: bool = False,
) -> list[dict]:
    """
    Fetch active, open markets from the Gamma API.
    If all_pages=True, paginates until exhausted (ignores limit).
    """
    results = []
    offset = 0
    page_size = 500
    MAX_PAGES = 200
    page_num = 0

    while True:
        page_num += 1
        if page_num > MAX_PAGES:
            print(f"  Warning: hit {MAX_PAGES}-page safety limit, stopping pagination", file=sys.stderr)
            break
        params: dict = {
            "active": "true",
            "closed": "false",
            "limit": page_size,
            "offset": offset,
            "order": "volume24hr",
            "ascending": "false",
        }
        if tag:
            params["tag"] = tag

        try:
            r = requests.get(f"{GAMMA_BASE}/markets", params=params, timeout=15)
            r.raise_for_status()
            page = r.json()
        except Exception as exc:
            print(f"  Gamma API error: {exc}", file=sys.stderr)
            break

        if not page:
            break

        for m in page:
            if min_volume > 0:
                vol = float(m.get("volume", m.get("volume24hr", 0)) or 0)
                if vol < min_volume:
                    continue
            results.append(m)

        if len(page) < page_size:
            break   # last page

        offset += page_size

        if not all_pages and len(results) >= limit:
            break

    return results if all_pages else results[:limit]


def extract_token_ids(market: dict) -> tuple[str, str] | None:
    """Extract (yes_token_id, no_token_id) from a Gamma market dict."""
    raw = market.get("clobTokenIds") or market.get("clob_token_ids") or ""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
    if isinstance(raw, list) and len(raw) >= 2:
        return raw[0], raw[1]
    return None


def extract_tags(market: dict) -> list[str]:
    tags = market.get("tags") or []
    if isinstance(tags, list):
        return [t.get("label", t) if isinstance(t, dict) else str(t) for t in tags]
    return []


def extract_volume(market: dict) -> tuple[float, float]:
    """Return (volume_24h, volume_total) in USDC."""
    v24 = float(market.get("volume24hr") or market.get("volume24Hr") or 0)
    vtot = float(market.get("volume") or 0)
    return v24, vtot


def extract_end_date(market: dict) -> str:
    """Return resolution date string, shortened to YYYY-MM-DD."""
    raw = market.get("endDate") or market.get("end_date") or ""
    if raw:
        return str(raw)[:10]
    return ""


def fetch_volatility(condition_id: str, yes_token_id: str, n_trades: int = 200) -> tuple[float, float]:
    """
    Fetch last N trades for a market and compute price std and trades/day.
    Returns (volatility_std, trades_per_day). Returns (0.0, 0.0) on error.
    """
    import math
    try:
        r = requests.get(
            f"{DATA_API}/trades",
            params={"market": condition_id, "limit": n_trades, "takerOnly": "false"},
            timeout=10,
        )
        r.raise_for_status()
        trades = r.json()
    except Exception:
        return 0.0, 0.0

    if not trades:
        return 0.0, 0.0

    prices = [
        float(t["price"])
        for t in trades
        if str(t.get("asset", "")) == str(yes_token_id)
           and "price" in t
    ]
    if len(prices) < 2:
        return 0.0, 0.0

    mean = sum(prices) / len(prices)
    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
    std = math.sqrt(variance)

    # Estimate trades/day from timestamps of first/last trade
    try:
        ts_list = [float(t["timestamp"]) for t in trades if "timestamp" in t]
        if len(ts_list) >= 2:
            span_seconds = max(ts_list) - min(ts_list)
            if span_seconds > 0:
                trades_per_day = len(prices) / (span_seconds / 86400.0)
            else:
                trades_per_day = 0.0
        else:
            trades_per_day = 0.0
    except Exception:
        trades_per_day = 0.0

    return std, trades_per_day


def compute_score(volume_24h: float, max_quotable: float, volatility_std: float = 0.0) -> float:
    """
    Composite score: log(volume+1) * max_quotable * volatility_multiplier.
    volatility_multiplier = min(std/0.05, 2.0) when std is known; 1.0 (neutral) when std=0 (not fetched).
    Returns 0 if max_quotable=0 (no exit liquidity).
    """
    import math
    if max_quotable <= 0:
        return 0.0
    if volatility_std <= 0:
        # No volatility data: use neutral multiplier (don't penalise or reward)
        volatility_multiplier = 1.0
    else:
        volatility_multiplier = min(volatility_std / 0.05, 2.0)
    return math.log1p(volume_24h) * max_quotable * volatility_multiplier


# ---------------------------------------------------------------------------
# Per-market scan
# ---------------------------------------------------------------------------

def scan_one(
    market: dict,
    client: ClobClient,
    exit_checker: ExitChecker,
    half_spread: float,
    min_price: float,
    max_price: float,
    fetch_vol: bool = False,
) -> MarketScan:
    condition_id = market.get("conditionId", "")
    slug = market.get("slug", "")
    question = market.get("question", slug)[:80]
    tags = extract_tags(market)
    volume_24h, volume_total = extract_volume(market)
    end_date = extract_end_date(market)

    token_ids = extract_token_ids(market)
    if token_ids is None:
        return MarketScan(
            condition_id=condition_id, slug=slug, question=question,
            yes_token="", no_token="", yes_mid=None, no_mid=None,
            entry_price=0.0, yes_exit_size=0.0, no_exit_size=0.0,
            max_quotable=0.0, max_flatten_price=0.0, viable=False,
            error="No token IDs", tags=tags,
            volume_24h=volume_24h, volume_total=volume_total, end_date=end_date,
        )

    yes_token, no_token = token_ids

    # Fetch books
    try:
        yes_book = client.get_book(yes_token)
    except Exception as exc:
        return MarketScan(
            condition_id=condition_id, slug=slug, question=question,
            yes_token=yes_token, no_token=no_token, yes_mid=None, no_mid=None,
            entry_price=0.0, yes_exit_size=0.0, no_exit_size=0.0,
            max_quotable=0.0, max_flatten_price=0.0, viable=False,
            error=f"YES book: {exc}", tags=tags,
            volume_24h=volume_24h, volume_total=volume_total, end_date=end_date,
        )

    try:
        no_book = client.get_book(no_token)
    except Exception as exc:
        return MarketScan(
            condition_id=condition_id, slug=slug, question=question,
            yes_token=yes_token, no_token=no_token, yes_mid=None, no_mid=None,
            entry_price=0.0, yes_exit_size=0.0, no_exit_size=0.0,
            max_quotable=0.0, max_flatten_price=0.0, viable=False,
            error=f"NO book: {exc}", tags=tags,
            volume_24h=volume_24h, volume_total=volume_total, end_date=end_date,
        )

    # Compute mids and spread
    yes_mid = None
    spread_pct = 0.0
    if yes_book.bids and yes_book.asks:
        yes_mid = (yes_book.bids[0].price + yes_book.asks[0].price) / 2.0
        if yes_mid > 0:
            spread_pct = (yes_book.asks[0].price - yes_book.bids[0].price) / yes_mid
    elif yes_book.bids:
        yes_mid = yes_book.bids[0].price
    elif yes_book.asks:
        yes_mid = yes_book.asks[0].price

    no_mid = None
    if no_book.bids and no_book.asks:
        no_mid = (no_book.bids[0].price + no_book.asks[0].price) / 2.0

    # Skip markets outside the price filter
    if yes_mid is not None and (yes_mid < min_price or yes_mid > max_price):
        return MarketScan(
            condition_id=condition_id, slug=slug, question=question,
            yes_token=yes_token, no_token=no_token,
            yes_mid=yes_mid, no_mid=no_mid,
            entry_price=0.0, yes_exit_size=0.0, no_exit_size=0.0,
            max_quotable=0.0, max_flatten_price=0.0, viable=False,
            error=f"Price {yes_mid:.2f} outside [{min_price:.2f}, {max_price:.2f}]",
            tags=tags,
            volume_24h=volume_24h, volume_total=volume_total,
            spread_pct=spread_pct, end_date=end_date,
        )

    entry_price = (yes_mid - half_spread) if yes_mid is not None else (0.5 - half_spread)
    entry_price = max(0.01, min(0.99, entry_price))

    viability = exit_checker.check(
        yes_book=yes_book,
        no_book=no_book,
        entry_price=entry_price,
        quote_size=100.0,
    )

    vol_std, trades_per_day = 0.0, 0.0
    if fetch_vol:
        vol_std, trades_per_day = fetch_volatility(condition_id, yes_token)
        time.sleep(0.1)  # rate limit volatility fetches

    score = compute_score(volume_24h, viability.max_quotable_size, vol_std)

    return MarketScan(
        condition_id=condition_id,
        slug=slug,
        question=question,
        yes_token=yes_token,
        no_token=no_token,
        yes_mid=yes_mid,
        no_mid=no_mid,
        entry_price=entry_price,
        yes_exit_size=viability.yes_exit_size,
        no_exit_size=viability.no_exit_size,
        max_quotable=viability.max_quotable_size,
        max_flatten_price=viability.max_flatten_price,
        viable=viability.is_viable,
        error=None,
        tags=tags,
        volume_24h=volume_24h,
        volume_total=volume_total,
        spread_pct=spread_pct,
        end_date=end_date,
        score=score,
        volatility_std=vol_std,
        trades_per_day=trades_per_day,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(
    scans: list[MarketScan],
    top_n: int,
    min_quotable: float,
    min_volume: float,
    show_ingest: bool,
    half_spread: float,
    sort_by: str,
    min_std: float = 0.0,
    min_trades_day: float = 0.0,
) -> None:
    viable = [
        s for s in scans
        if s.viable
        and s.max_quotable >= min_quotable
        and s.volume_24h >= min_volume
        and (min_std <= 0 or s.volatility_std >= min_std)
        and (min_trades_day <= 0 or s.trades_per_day >= min_trades_day)
    ]

    sort_keys = {
        "score":  lambda s: -s.score,
        "volume": lambda s: -s.volume_24h,
        "hedge":  lambda s: -s.max_quotable,
        "spread": lambda s: -(s.spread_pct or 0),
    }
    viable.sort(key=sort_keys.get(sort_by, sort_keys["score"]))

    errors = [s for s in scans if s.error and "outside" not in (s.error or "")]
    skipped_price = [s for s in scans if s.error and "outside" in (s.error or "")]
    skipped_vol = [
        s for s in scans
        if not s.error and s.viable and s.max_quotable >= min_quotable
        and s.volume_24h < min_volume
    ]

    print()
    print("=" * 120)
    print(f"MARKET SCAN  (half_spread={half_spread:.3f}, min_quotable={min_quotable:.0f}, "
          f"min_volume_24h=${min_volume:,.0f}, sort={sort_by})")
    print("=" * 120)
    print(f"  Total scanned:        {len(scans)}")
    print(f"  Viable (both axes):   {len(viable)}")
    print(f"  Skipped (price):      {len(skipped_price)}")
    print(f"  Skipped (low volume): {len(skipped_vol)}")
    print(f"  Errors:               {len(errors)}")
    print()

    if not viable:
        print("  No markets pass both filters.")
        print("  Try: --min-quotable 0  --min-volume 0  or adjust --min-price/--max-price")
        return

    show = viable[:top_n]
    show_std = any(s.volatility_std > 0 for s in show)

    if show_std:
        hdr = (f"{'#':>3}  {'Question':<44} {'Ends':>10} {'Mid':>5} "
               f"{'Std':>5} {'MaxQ':>6} {'Vol24h':>9} {'VolTot':>10}  Tags")
    else:
        hdr = (f"{'#':>3}  {'Question':<48} {'Ends':>10} {'Mid':>5} "
               f"{'Sprd':>5} {'MaxQ':>6} {'Vol24h':>9} {'VolTot':>10}  Tags")
    print(hdr)
    print("-" * 120)

    for i, s in enumerate(show, 1):
        tags_str = ", ".join(s.tags[:2]) if s.tags else ""
        vol24_str = f"${s.volume_24h:>8,.0f}" if s.volume_24h else "       $0"
        voltot_str = f"${s.volume_total:>9,.0f}" if s.volume_total else "        $0"
        if show_std:
            std_str = f"{s.volatility_std:.3f}" if s.volatility_std > 0 else "  n/a"
            print(
                f"{i:>3}  {s.question:<44} "
                f"{s.end_date:>10} "
                f"{(s.yes_mid or 0):>5.3f} "
                f"{std_str:>5} "
                f"{s.max_quotable:>6.0f} "
                f"{vol24_str} "
                f"{voltot_str}  "
                f"{tags_str}"
            )
        else:
            sprd_str = f"{s.spread_pct*100:.1f}%" if s.spread_pct else "  n/a"
            print(
                f"{i:>3}  {s.question:<48} "
                f"{s.end_date:>10} "
                f"{(s.yes_mid or 0):>5.3f} "
                f"{sprd_str:>5} "
                f"{s.max_quotable:>6.0f} "
                f"{vol24_str} "
                f"{voltot_str}  "
                f"{tags_str}"
            )

    print("-" * 120)

    if len(viable) > top_n:
        print(f"  ... {len(viable) - top_n} more viable markets not shown (use --top N)")
    print()

    if errors:
        print(f"ERRORS ({len(errors)} markets):")
        for s in errors[:5]:
            print(f"  {s.question[:60]:<60}  {s.error}")
        if len(errors) > 5:
            print(f"  ... {len(errors) - 5} more errors")
        print()

    if show_ingest:
        print("INGEST COMMANDS (copy-paste to download history):")
        print()
        for s in show:
            print(f"  py -3 scripts/ingest_history.py --market \"{s.condition_id}\"")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scan active Polymarket markets for hedge accessibility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--limit", type=int, default=100,
                        help="Max markets to fetch from Gamma API (default 100)")
    parser.add_argument("--top", type=int, default=50,
                        help="Show top N markets in report (default 50)")
    parser.add_argument("--half-spread", type=float, default=0.025,
                        help="Half-spread to compute entry price from mid (default 0.025)")
    parser.add_argument("--min-price", type=float, default=0.05,
                        help="Skip markets where YES mid < this (default 0.05)")
    parser.add_argument("--max-price", type=float, default=0.95,
                        help="Skip markets where YES mid > this (default 0.95)")
    parser.add_argument("--min-quotable", type=float, default=50.0,
                        help="Only show markets with max_quotable >= this (default 50)")
    parser.add_argument("--min-volume", type=float, default=0.0,
                        help="Only show markets with 24h volume >= this in USDC (default 0)")
    parser.add_argument("--sort", default="score",
                        choices=["score", "volume", "hedge", "spread"],
                        help="Sort order: score=composite (default), volume, hedge, spread")
    parser.add_argument("--tag", type=str, default=None,
                        help="Filter by tag/category (e.g. politics, sports, crypto)")
    parser.add_argument("--fee-rate", type=float, default=0.07)
    parser.add_argument("--rebate", type=float, default=0.5)
    parser.add_argument("--min-edge", type=float, default=0.005)
    parser.add_argument("--max-loss", type=float, default=0.10)
    parser.add_argument("--delay", type=float, default=0.15,
                        help="Seconds between CLOB book requests (default 0.15)")
    parser.add_argument("--ingest", action="store_true",
                        help="Print ingest commands for viable markets")
    parser.add_argument("--all", action="store_true",
                        help="Paginate through ALL Gamma markets (ignores --limit)")
    parser.add_argument("--volatility", action="store_true",
                        help="Fetch last 200 trades per market for price std (slower)")
    parser.add_argument("--export", type=str, default=None,
                        help="Write viable scored MarketScan results to JSON file")
    parser.add_argument("--min-std", type=float, default=0.0,
                        help="Minimum volatility std to include in output (default 0)")
    parser.add_argument("--min-trades-day", type=float, default=0.0,
                        help="Minimum trades/day filter (default 0)")
    args = parser.parse_args()

    fm = FeeModel()
    client = ClobClient()
    exit_checker = ExitChecker(
        fee_model=fm,
        fee_rate=args.fee_rate,
        rebate_fraction=args.rebate,
        min_edge_floor=args.min_edge,
        max_loss_fraction=args.max_loss,
        min_viable_size=1.0,
    )

    print(f"Fetching up to {args.limit} active markets from Gamma API...")
    markets = fetch_active_markets(
        limit=args.limit,
        tag=args.tag,
        min_volume=args.min_volume,
        all_pages=args.all,
    )
    print(f"  Got {len(markets)} markets. Fetching live books...\n")

    scans: list[MarketScan] = []
    for i, market in enumerate(markets):
        question = market.get("question", "?")[:55]
        print(f"  [{i+1:>3}/{len(markets)}] {question:<55}", end="\r", flush=True)

        scan = scan_one(
            market=market,
            client=client,
            exit_checker=exit_checker,
            half_spread=args.half_spread,
            min_price=args.min_price,
            max_price=args.max_price,
            fetch_vol=args.volatility,
        )
        scans.append(scan)

        if args.delay > 0:
            time.sleep(args.delay)

    print(" " * 80, end="\r")  # clear progress line

    if args.export:
        import dataclasses
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_viable = [
            s for s in scans
            if s.viable
            and s.max_quotable >= args.min_quotable
            and s.volume_24h >= args.min_volume
            and (args.min_std <= 0 or s.volatility_std >= args.min_std)
            and (args.min_trades_day <= 0 or s.trades_per_day >= args.min_trades_day)
        ]
        export_data = [dataclasses.asdict(s) for s in export_viable]
        export_path.write_text(json.dumps(export_data, indent=2), encoding="utf-8")
        print(f"Exported {len(export_data)} viable markets -> {args.export}")

    print_report(
        scans=scans,
        top_n=args.top,
        min_quotable=args.min_quotable,
        min_volume=args.min_volume,
        show_ingest=args.ingest,
        half_spread=args.half_spread,
        sort_by=args.sort,
        min_std=args.min_std,
        min_trades_day=args.min_trades_day,
    )


if __name__ == "__main__":
    main()
