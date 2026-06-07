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

from src.data.schemas import OrderBook, PriceLevel, Fill, Side, MarketMetadata
from src.fee_model import FeeModel
from src.strategy.fair_value import FairValueEstimator
from src.strategy.regime import RegimeClassifier
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig
from src.strategy.quote_engine import QuoteEngine
from src.strategy.inventory import InventoryManager
from src.pnl import PnLEngine
from src.backtest.fill_model import FillModel, FillModelConfig, QueueModel
from src.backtest.simulator import BacktestSimulator, SimulatorConfig
from src.live.portfolio_state import PortfolioConstraints

ROOT_DIR     = Path(__file__).resolve().parent.parent
LIVE_DIR     = ROOT_DIR / "data" / "live"
FEE_RATE     = 0.07
REBATE_FRAC  = 0.50
LATENCY_MS   = 50
LADDER_LEVELS      = 5
LADDER_OFFSET      = 0.030
LADDER_TICK        = 0.010
LADDER_SIZE_RATIOS = [1.0, 1.5, 2.0, 2.5, 3.0]
PRICE_TOLERANCE    = 0.010
MAX_MARKET_NOTIONAL = 2_000.0

SCENARIOS = [
    ("Baseline  $10k  80% cap", 10_000.0, 0.80),
    ("$20k cap  $20k  80% cap", 20_000.0, 0.80),
    ("Loose cap $10k  95% cap", 10_000.0, 0.95),
    ("Both      $20k  95% cap", 20_000.0, 0.95),
]


# ── helpers (copied from run_live_backtest.py) ────────────────────────────────

def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def load_market_events(files):
    events = []
    seen = set()
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except Exception:
                continue
            et  = raw.get("event_type")
            ts  = parse_ts(raw.get("timestamp", ""))
            if ts is None:
                continue
            if et == "book":
                bids = [PriceLevel(float(b["price"]), float(b["size"])) for b in raw.get("bids", [])]
                asks = [PriceLevel(float(a["price"]), float(a["size"])) for a in raw.get("asks", [])]
                events.append((ts, OrderBook(
                    market_id=raw.get("market_id", ""), timestamp=ts,
                    bids=bids, asks=asks, token_side=raw.get("token_side", ""),
                )))
            elif et == "trade":
                fid = raw.get("fill_id", "")
                if fid and fid in seen:
                    continue
                if fid:
                    seen.add(fid)
                upper = raw.get("side", "").upper()
                token_side = upper if upper in ("YES", "NO") else ""
                side = Side.BUY if raw.get("side", "").lower() == "buy" else Side.SELL
                try:
                    events.append((ts, Fill(
                        fill_id=fid, market_id=raw.get("market_id", ""),
                        side=side, price=float(raw["price"]), size=float(raw["size"]),
                        timestamp=ts, is_maker=bool(raw.get("is_maker", False)),
                        token_side=token_side,
                    )))
                except Exception:
                    pass
    events.sort(key=lambda x: x[0])
    return [e for _, e in events]


def compute_avg_trade_size(events):
    sizes = [e.size for e in events if isinstance(e, Fill) and e.size > 0]
    return statistics.mean(sizes) if sizes else 100.0


def adaptive_quote_size(avg):
    return max(5.0, min(500.0, round(avg / 2)))


def is_dual_book(files):
    has_yes = has_no = has_trade = False
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                ev = json.loads(line.strip())
                ts = ev.get("token_side", "")
                et = ev.get("event_type", "")
                if et == "book" and ts == "YES": has_yes = True
                if et == "book" and ts == "NO":  has_no  = True
                if et == "trade":                has_trade = True
            except Exception:
                pass
        if has_yes and has_no and has_trade:
            break
    return has_yes and has_no and has_trade


def fetch_meta(cid):
    url = f"https://gamma-api.polymarket.com/markets?condition_id={cid}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        m = data[0] if isinstance(data, list) and data else {}
        end_str = m.get("end_date_iso") or m.get("endDate") or m.get("end_date") or ""
        events_list = m.get("events") or []
        event_id = str(events_list[0]["id"]) if events_list else ""
        if end_str:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            days_left = (end_dt - datetime.now(timezone.utc)).days
            end_date_str = end_dt.strftime("%Y-%m-%d")
            event_key = event_id if event_id else end_date_str
            return end_date_str, days_left, event_key
    except Exception:
        pass
    return "unknown", 9999, "unknown"


def make_sim(market_id, days_to_resolution, event_key, portfolio, quote_size):
    fm   = FeeModel()
    meta = MarketMetadata(
        condition_id=market_id, token_id_yes=market_id, token_id_no=market_id,
        category="unknown", fee_rate=FEE_RATE, fee_exponent=1,
        rebate_fraction=REBATE_FRAC, sports=False,
    )
    skew = SkewConfig(skew_tolerance=0.0, skew_edge_premium=0.005,
                      skew_hard_limit=0, skew_capital_charge_multiplier=3.0,
                      max_skew_notional=0.0, current_skew_notional=0.0)
    fv   = FairValueEstimator(twap_window_seconds=3600, external_weight=0.0)
    reg  = RegimeClassifier()
    ha   = HedgeabilityAssessor(fm, FEE_RATE, REBATE_FRAC, 0.005)
    qe   = QuoteEngine(fm, FEE_RATE, REBATE_FRAC, LADDER_OFFSET, 0.005)
    inv  = InventoryManager(market_id, 0.0003)
    pnl  = PnLEngine(fm, FEE_RATE, REBATE_FRAC)
    fm2  = FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=LATENCY_MS))
    return BacktestSimulator(
        metadata=meta, fee_model=fm,
        fv_estimator=fv, regime_classifier=reg,
        hedgeability_assessor=ha, quote_engine=qe,
        inventory_manager=inv, pnl_engine=pnl,
        fill_model=fm2, skew_config=skew,
        config=SimulatorConfig(
            start_capital=50000.0, quote_size=quote_size,
            time_to_resolution_hours=720.0,
            ladder_levels=LADDER_LEVELS, ladder_offset_from_best=LADDER_OFFSET,
            ladder_tick_spacing=LADDER_TICK, ladder_size_ratios=LADDER_SIZE_RATIOS,
            price_tolerance=PRICE_TOLERANCE, iceberg_display_size=0.0,
            days_to_resolution=days_to_resolution, event_key=event_key,
            market_id=market_id,
        ),
        portfolio=portfolio,
    )


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
        sim    = make_sim(mid, days_left, event_key, portfolio, qs)
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
