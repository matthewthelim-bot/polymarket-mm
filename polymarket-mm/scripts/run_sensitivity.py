#!/usr/bin/env python3
"""
Portfolio sensitivity analysis — sweeps TOTAL_CAPITAL and MAX_LONG_TERM_FRACTION.

Usage:
    py scripts/run_sensitivity.py [--no-sync]
"""
import json, sys, statistics, math, os, urllib.request
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.live.portfolio_state import PortfolioConstraints
from src.backtest.live_harness import (
    load_market_events, is_dual_book,
    compute_avg_trade_size, adaptive_quote_size, make_simulator,
)

ROOT_DIR     = Path(__file__).resolve().parent.parent
LIVE_DIR     = ROOT_DIR / "data" / "live"
MAX_MARKET_NOTIONAL = 2_000.0

SCENARIOS = [
    ("Tight     $20k  20% cap", 20_000.0, 0.20),
    ("Default   $20k  30% cap", 20_000.0, 0.30),
    ("Mid       $20k  50% cap", 20_000.0, 0.50),
    ("Legacy    $20k  80% cap", 20_000.0, 0.80),
]


def fetch_meta(cid):
    """(end_date_str, days_left, event_key) via CLOB REST.

    Gamma's ?condition_id= filter is broken server-side (returns an unrelated
    market) — do not revert to it. event_key falls back to the end-date string.
    """
    url = f"https://clob.polymarket.com/markets/{cid}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            m = json.loads(resp.read())
        end_str = m.get("end_date_iso") or ""
        if end_str:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            days_left = max(0, (end_dt - datetime.now(timezone.utc)).days)
            end_date_str = end_dt.strftime("%Y-%m-%d")
            return end_date_str, days_left, end_date_str
    except Exception:
        pass
    return "unknown", 9999, "unknown"


def run_scenario(label, total_capital, lt_frac, eligible, market_resolution, period_days):
    portfolio = PortfolioConstraints(
        total_capital=total_capital,
        max_long_term_fraction=lt_frac,
        max_event_notional=0.0,
        max_market_notional=MAX_MARKET_NOTIONAL,
    )
    results = []
    for mid, files in eligible:
        end_date_str, days_left, event_key = market_resolution[mid]
        events = load_market_events(files)
        avg_ts = compute_avg_trade_size(events)
        qs     = adaptive_quote_size(avg_ts)
        sim    = make_simulator(mid, days_to_resolution=days_left,
                                event_key=event_key, portfolio=portfolio, quote_size=qs)
        r      = sim.run(events)
        results.append((mid, r, avg_ts, qs))

    total_blocked  = sum(r.num_portfolio_blocked for _, r, _, _ in results)
    total_pnl      = sum(r.total_pnl()           for _, r, _, _ in results)
    total_cycles   = sum(r.num_cycles_completed  for _, r, _, _ in results)
    total_fees     = sum(r.total_fees_paid        for _, r, _, _ in results)
    total_rebates  = sum(r.total_rebates_received for _, r, _, _ in results)
    total_longs    = sum(r.num_longs_opened       for _, r, _, _ in results)
    total_shorts   = sum(r.num_shorts_opened      for _, r, _, _ in results)
    total_capital_c= sum(r.total_capital_consumed for _, r, _, _ in results)
    all_cycle_pnl  = [p for _, r, _, _ in results for p in r.per_cycle_pnl]
    total_positions= total_longs + total_shorts

    avg_notional   = (total_capital_c / total_positions) if total_positions else 0
    peak_conc      = max((r.max_concurrent_open for _, r, _, _ in results), default=0)
    peak_locked    = peak_conc * avg_notional

    if len(all_cycle_pnl) >= 2:
        mean_c = statistics.mean(all_cycle_pnl)
        std_c  = statistics.stdev(all_cycle_pnl)
        cpd    = len(all_cycle_pnl) / period_days
        sharpe = math.sqrt(252 * cpd) * mean_c / std_c if std_c > 0 else float("nan")
    else:
        sharpe = float("nan")

    win_rate = sum(1 for p in all_cycle_pnl if p > 0) / len(all_cycle_pnl) * 100 if all_cycle_pnl else 0
    arb_total= sum(r.num_bid_arb_cycles + r.num_ask_arb_cycles for _, r, _, _ in results)

    return {
        "label":         label,
        "capital":       total_capital,
        "lt_frac":       lt_frac,
        "pnl":           total_pnl,
        "pnl_day":       total_pnl / period_days,
        "cycles":        len(all_cycle_pnl),
        "arb_events":    arb_total,
        "blocked":       total_blocked,
        "blocked_pct":   total_blocked / (arb_total + total_blocked) * 100 if (arb_total + total_blocked) else 0,
        "sharpe":        sharpe,
        "win_rate":      win_rate,
        "peak_locked":   peak_locked,
        "deployed":      total_capital_c,
        "fees":          total_fees,
        "rebates":       total_rebates,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args()

    if not args.no_sync:
        import subprocess
        EC2_HOST = "ubuntu@100.52.215.239"
        EC2_KEY  = str(ROOT_DIR / "polymarket-key.pem")
        EC2_DATA = "/opt/polymarket-mm/polymarket-mm/data/live"
        print("Syncing from EC2 ...")
        r = subprocess.run(
            ["ssh", "-i", EC2_KEY, "-o", "StrictHostKeyChecking=no", EC2_HOST, f"ls {EC2_DATA}"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            print("EC2 unreachable, pass --no-sync to use local data.")
            sys.exit(1)
        print("  Sync skipped (use run_live_backtest.py to sync).")

    # Discover eligible markets
    market_files = defaultdict(list)
    for f in sorted(LIVE_DIR.glob("**/*.jsonl")):
        market_files[f.stem].append(f)

    print("Scanning dual-book markets ...")
    eligible = [(mid, files) for mid, files in market_files.items() if is_dual_book(files)]
    print(f"Found {len(eligible)} dual-book markets.")

    print("Fetching resolution dates ...")
    market_resolution = {}
    for mid, _ in eligible:
        market_resolution[mid] = fetch_meta(mid)
    print(f"  Done ({len(market_resolution)} resolved).\n")

    mtimes = [os.path.getmtime(f) for files in market_files.values() for f in files]
    period_days = max((max(mtimes) - min(mtimes)) / 86400, 0.1) if len(mtimes) >= 2 else 1.0

    # Run all scenarios
    scenario_results = []
    for label, capital, lt_frac in SCENARIOS:
        print(f"Running: {label} ...")
        sr = run_scenario(label, capital, lt_frac, eligible, market_resolution, period_days)
        scenario_results.append(sr)

    # Print comparison table
    print()
    print("=" * 90)
    print("  SENSITIVITY ANALYSIS  —  portfolio cap impact")
    print("=" * 90)
    hdr = f"  {'Scenario':<26} {'Capital':>8} {'LT%':>5} {'Cycles':>7} {'Blocked':>8} {'Block%':>7} {'Net PnL':>9} {'$/day':>7} {'Sharpe':>7}"
    print(hdr)
    print("  " + "-" * 88)
    for sr in scenario_results:
        print(
            f"  {sr['label']:<26} ${sr['capital']:>7,.0f} {sr['lt_frac']*100:>4.0f}%"
            f" {sr['cycles']:>7} {sr['blocked']:>8} {sr['blocked_pct']:>6.1f}%"
            f"  ${sr['pnl']:>8.2f} ${sr['pnl_day']:>6.2f} {sr['sharpe']:>7.2f}"
        )
    print("=" * 90)

    print()
    print("  PnL DETAIL")
    print(f"  {'Scenario':<26} {'Gross':>8} {'Rebates':>9} {'Taker fees':>11} {'Win%':>6}")
    print("  " + "-" * 70)
    for sr in scenario_results:
        gross = sr['pnl'] + sr['fees'] - sr['rebates']
        print(
            f"  {sr['label']:<26} ${gross:>7.2f}  ${sr['rebates']:>7.2f}  $-{sr['fees']:>8.2f}"
            f"  {sr['win_rate']:>5.1f}%"
        )

    print()
    print(f"  Period: {period_days:.1f} days  |  {len(eligible)} markets")


if __name__ == "__main__":
    main()
