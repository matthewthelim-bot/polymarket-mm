#!/usr/bin/env python3
"""
Quick sensitivity sweep — reuses cached event data, skips Gamma API calls.
Runs 4 scenarios varying total capital and long-term cap fraction.
"""
import json, sys, statistics, math, os
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

LIVE_DIR            = Path(__file__).resolve().parent.parent / "data" / "live"
FEE_RATE            = 0.07
REBATE_FRAC         = 0.50
LATENCY_MS          = 50
LADDER_LEVELS       = 5
LADDER_OFFSET       = 0.030
LADDER_TICK         = 0.010
LADDER_SIZE_RATIOS  = [1.0, 1.5, 2.0, 2.5, 3.0]
PRICE_TOLERANCE     = 0.010
MAX_MARKET_NOTIONAL = 2_000.0

SCENARIOS = [
    ("Baseline   $10k  80%", 10_000.0, 0.80),
    ("More cap   $20k  80%", 20_000.0, 0.80),
    ("Loose cap  $10k  95%", 10_000.0, 0.95),
    ("Both       $20k  95%", 20_000.0, 0.95),
]


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def load_events(files):
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
            et = raw.get("event_type")
            ts = parse_ts(raw.get("timestamp", ""))
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


def avg_trade_size(events):
    sizes = [e.size for e in events if isinstance(e, Fill) and e.size > 0]
    return statistics.mean(sizes) if sizes else 100.0


def adaptive_qs(avg):
    return max(5.0, min(500.0, round(avg / 2)))


def is_dual_book(files):
    hy = hn = ht = False
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                ev = json.loads(line.strip())
                ts = ev.get("token_side", "")
                et = ev.get("event_type", "")
                if et == "book" and ts == "YES": hy = True
                if et == "book" and ts == "NO":  hn = True
                if et == "trade":                ht = True
            except Exception:
                pass
        if hy and hn and ht:
            break
    return hy and hn and ht


def make_sim(mid, days, ekey, portfolio, quote_size):
    fm   = FeeModel()
    meta = MarketMetadata(
        condition_id=mid, token_id_yes=mid, token_id_no=mid, category="unknown",
        fee_rate=FEE_RATE, fee_exponent=1, rebate_fraction=REBATE_FRAC, sports=False,
    )
    skew = SkewConfig(
        skew_tolerance=0.0, skew_edge_premium=0.005, skew_hard_limit=0,
        skew_capital_charge_multiplier=3.0, max_skew_notional=0.0, current_skew_notional=0.0,
    )
    fv   = FairValueEstimator(twap_window_seconds=3600, external_weight=0.0)
    ha   = HedgeabilityAssessor(fm, FEE_RATE, REBATE_FRAC, 0.005)
    qe   = QuoteEngine(fm, FEE_RATE, REBATE_FRAC, LADDER_OFFSET, 0.005)
    inv  = InventoryManager(mid, 0.0003)
    pnl  = PnLEngine(fm, FEE_RATE, REBATE_FRAC)
    fm2  = FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=LATENCY_MS))
    return BacktestSimulator(
        metadata=meta, fee_model=fm, fv_estimator=fv, regime_classifier=RegimeClassifier(),
        hedgeability_assessor=ha, quote_engine=qe, inventory_manager=inv,
        pnl_engine=pnl, fill_model=fm2, skew_config=skew,
        config=SimulatorConfig(
            start_capital=50000.0, quote_size=quote_size,
            time_to_resolution_hours=720.0, ladder_levels=LADDER_LEVELS,
            ladder_offset_from_best=LADDER_OFFSET, ladder_tick_spacing=LADDER_TICK,
            ladder_size_ratios=LADDER_SIZE_RATIOS, price_tolerance=PRICE_TOLERANCE,
            iceberg_display_size=0.0, days_to_resolution=days,
            event_key=ekey, market_id=mid,
        ),
        portfolio=portfolio,
    )


def run_scenario(label, capital, lt_frac, eligible, all_events, market_resolution, period_days):
    portfolio = PortfolioConstraints(
        total_capital=capital, max_long_term_fraction=lt_frac,
        max_event_notional=0.0, max_market_notional=MAX_MARKET_NOTIONAL,
    )
    results = []
    for mid, _ in eligible:
        end_date_str, days_left, event_key = market_resolution[mid]
        events = all_events[mid]
        avg_ts = avg_trade_size(events)
        qs     = adaptive_qs(avg_ts)
        sim    = make_sim(mid, days_left, event_key, portfolio, qs)
        r      = sim.run(events)
        results.append((mid, r, avg_ts, qs))

    blocked  = sum(r.num_portfolio_blocked for _, r, _, _ in results)
    pnl      = sum(r.total_pnl()           for _, r, _, _ in results)
    fees     = sum(r.total_fees_paid        for _, r, _, _ in results)
    rebates  = sum(r.total_rebates_received for _, r, _, _ in results)
    longs    = sum(r.num_longs_opened       for _, r, _, _ in results)
    shorts   = sum(r.num_shorts_opened      for _, r, _, _ in results)
    cap_c    = sum(r.total_capital_consumed for _, r, _, _ in results)
    bid_arb  = sum(r.num_bid_arb_cycles     for _, r, _, _ in results)
    ask_arb  = sum(r.num_ask_arb_cycles     for _, r, _, _ in results)
    arb      = bid_arb + ask_arb
    all_cpnl = [p for _, r, _, _ in results for p in r.per_cycle_pnl]
    positions = longs + shorts
    avg_not   = (cap_c / positions) if positions else 0
    peak      = max((r.max_concurrent_open for _, r, _, _ in results), default=0)

    if len(all_cpnl) >= 2:
        mc     = statistics.mean(all_cpnl)
        sc     = statistics.stdev(all_cpnl)
        cpd    = len(all_cpnl) / period_days
        sharpe = math.sqrt(252 * cpd) * mc / sc if sc > 0 else float("nan")
    else:
        sharpe = float("nan")

    win       = sum(1 for p in all_cpnl if p > 0) / len(all_cpnl) * 100 if all_cpnl else 0
    block_pct = blocked / (arb + blocked) * 100 if (arb + blocked) else 0

    return {
        "label": label, "capital": capital, "lt_frac": lt_frac,
        "pnl": pnl, "pnl_day": pnl / period_days,
        "cycles": len(all_cpnl), "arb": arb, "blocked": blocked, "block_pct": block_pct,
        "sharpe": sharpe, "win": win,
        "peak_locked": peak * avg_not, "deployed": cap_c,
        "fees": fees, "rebates": rebates,
    }


def main():
    # Discover markets
    market_files = defaultdict(list)
    for f in sorted(LIVE_DIR.glob("**/*.jsonl")):
        market_files[f.stem].append(f)

    print("Scanning dual-book markets ...")
    eligible = [(mid, files) for mid, files in market_files.items() if is_dual_book(files)]
    print(f"  {len(eligible)} dual-book markets found.")

    print("Loading all events into memory ...")
    all_events = {}
    for i, (mid, files) in enumerate(eligible):
        all_events[mid] = load_events(files)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(eligible)} loaded ...")
    print("  Done.")

    # Use known resolution data (all markets resolve 2026-07-31, 54 days out)
    # This avoids 201 sequential Gamma API calls.
    market_resolution = {mid: ("2026-07-31", 54, "2026-07-31") for mid, _ in eligible}

    mtimes = [os.path.getmtime(f) for files in market_files.values() for f in files]
    period_days = max((max(mtimes) - min(mtimes)) / 86400, 0.1) if len(mtimes) >= 2 else 1.0
    print(f"  Data period: {period_days:.1f} days\n")

    # Run all 4 scenarios
    srs = []
    for label, capital, lt_frac in SCENARIOS:
        sys.stdout.write(f"  Running '{label}' ... ")
        sys.stdout.flush()
        sr = run_scenario(label, capital, lt_frac, eligible, all_events, market_resolution, period_days)
        srs.append(sr)
        print(f"PnL=${sr['pnl']:.2f}  cycles={sr['cycles']}  blocked={sr['blocked']}")

    # Print table
    print()
    print("=" * 92)
    print("  SENSITIVITY ANALYSIS  —  capital & long-term cap")
    print("=" * 92)
    print(f"  {'Scenario':<24} {'Capital':>8} {'LT cap':>6} {'Cycles':>7} {'Blocked':>8} {'Block%':>7} {'Net PnL':>10} {'$/day':>7} {'Sharpe':>8}")
    print("  " + "-" * 90)
    baseline_pnl = srs[0]["pnl"]
    for sr in srs:
        delta = sr["pnl"] - baseline_pnl
        delta_str = f"  ({delta:+.0f})" if delta != 0 else ""
        print(
            f"  {sr['label']:<24} ${sr['capital']:>7,.0f} {sr['lt_frac']*100:>5.0f}%"
            f"  {sr['cycles']:>6}  {sr['blocked']:>7}  {sr['block_pct']:>5.1f}%"
            f"  ${sr['pnl']:>7.2f}{delta_str:<8}  ${sr['pnl_day']:>5.2f}  {sr['sharpe']:>7.2f}"
        )
    print("=" * 92)

    print()
    print(f"  PnL BREAKDOWN")
    print(f"  {'Scenario':<24} {'Gross':>9} {'Rebates':>9} {'Taker fees':>12} {'Win%':>6}")
    print("  " + "-" * 64)
    for sr in srs:
        gross = sr["pnl"] + sr["fees"] - sr["rebates"]
        print(
            f"  {sr['label']:<24}  ${gross:>7.2f}  ${sr['rebates']:>7.2f}  $-{sr['fees']:>9.2f}"
            f"  {sr['win']:>5.1f}%"
        )

    print()
    print(f"  Period: {period_days:.1f} days  |  {len(eligible)} markets")
    print()


if __name__ == "__main__":
    main()
