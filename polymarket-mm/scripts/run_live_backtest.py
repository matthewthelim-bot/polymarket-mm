#!/usr/bin/env python3
"""
Backtest against data/live — merges date-subdirectory files per market,
runs the dual-book maker-taker simulator, reports PnL + risk + exposure.
"""
import json
import sys
import statistics
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

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

LIVE_DIR    = Path("data/live")
FEE_RATE    = 0.07
REBATE_FRAC = 0.50
HALF_SPREAD = 0.030
QUOTE_SIZE  = 100.0
LATENCY_MS  = 50


def parse_ts(ts_str):
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def load_market_events(files):
    """Merge events from multiple date-partitioned JSONL files, sort by timestamp."""
    events = []
    seen_fill_ids = set()
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = raw.get("event_type")
            ts = parse_ts(raw.get("timestamp", ""))
            if ts is None:
                continue
            if et == "book":
                token_side = raw.get("token_side", "")
                bids = [PriceLevel(float(b["price"]), float(b["size"])) for b in raw.get("bids", [])]
                asks = [PriceLevel(float(a["price"]), float(a["size"])) for a in raw.get("asks", [])]
                events.append((ts, OrderBook(
                    market_id=raw.get("market_id", ""),
                    timestamp=ts,
                    bids=bids,
                    asks=asks,
                    token_side=token_side,
                )))
            elif et == "trade":
                fid = raw.get("fill_id", "")
                if fid and fid in seen_fill_ids:
                    continue
                if fid:
                    seen_fill_ids.add(fid)
                raw_side = raw.get("side", "")
                upper = raw_side.upper()
                token_side = upper if upper in ("YES", "NO") else ""
                side = Side.BUY if raw_side.lower() == "buy" else Side.SELL
                try:
                    events.append((ts, Fill(
                        fill_id=fid,
                        market_id=raw.get("market_id", ""),
                        side=side,
                        price=float(raw["price"]),
                        size=float(raw["size"]),
                        timestamp=ts,
                        is_maker=bool(raw.get("is_maker", False)),
                        token_side=token_side,
                    )))
                except (KeyError, ValueError):
                    pass
    events.sort(key=lambda x: x[0])
    return [e for _, e in events]


def make_simulator(market_id):
    fm = FeeModel()
    meta = MarketMetadata(
        condition_id=market_id,
        token_id_yes=market_id,
        token_id_no=market_id,
        category="unknown",
        fee_rate=FEE_RATE,
        fee_exponent=1,
        rebate_fraction=REBATE_FRAC,
        sports=False,
    )
    skew_config = SkewConfig(
        skew_tolerance=0.0, skew_edge_premium=0.005,
        skew_hard_limit=0, skew_capital_charge_multiplier=3.0,
        max_skew_notional=0.0, current_skew_notional=0.0,
    )
    fv   = FairValueEstimator(twap_window_seconds=3600, external_weight=0.0)
    reg  = RegimeClassifier()
    ha   = HedgeabilityAssessor(fm, FEE_RATE, REBATE_FRAC, 0.005)
    qe   = QuoteEngine(fm, FEE_RATE, REBATE_FRAC, HALF_SPREAD, 0.005)
    inv  = InventoryManager(market_id, 0.0003)
    pnl  = PnLEngine(fm, FEE_RATE, REBATE_FRAC)
    fm2  = FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=LATENCY_MS))
    return BacktestSimulator(
        metadata=meta, fee_model=fm,
        fv_estimator=fv, regime_classifier=reg,
        hedgeability_assessor=ha, quote_engine=qe,
        inventory_manager=inv, pnl_engine=pnl,
        fill_model=fm2, skew_config=skew_config,
        config=SimulatorConfig(
            start_capital=50000.0,
            quote_size=QUOTE_SIZE,
            time_to_resolution_hours=720.0,
        ),
    )


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


def main():
    # Discover markets
    market_files = defaultdict(list)
    for f in sorted(LIVE_DIR.glob("**/*.jsonl")):
        market_files[f.stem].append(f)

    print("Scanning for dual-book markets ...")
    eligible = [(mid, files) for mid, files in market_files.items() if is_dual_book(files)]
    print(f"Found {len(eligible)} dual-book markets. Running backtest ...\n")

    results = []
    for i, (mid, files) in enumerate(eligible, 1):
        events = load_market_events(files)
        sim = make_simulator(mid)
        r = sim.run(events)
        results.append((mid, r))
        if i % 25 == 0:
            print(f"  {i}/{len(eligible)} markets done ...")

    # Aggregate
    total_pnl        = sum(r.total_pnl()               for _, r in results)
    total_fees       = sum(r.total_fees_paid            for _, r in results)
    total_rebates    = sum(r.total_rebates_received     for _, r in results)
    total_cycles     = sum(r.num_cycles_completed       for _, r in results)
    total_fills      = sum(r.num_fills                  for _, r in results)
    total_books      = sum(r.num_book_updates           for _, r in results)
    total_profitable = sum(r.num_profitable_cycles      for _, r in results)
    total_bid_arb    = sum(r.num_bid_arb_cycles         for _, r in results)
    total_ask_arb    = sum(r.num_ask_arb_cycles         for _, r in results)
    all_cycle_pnl    = [p for _, r in results for p in r.per_cycle_pnl]

    period_days = 2.5  # May 21-24

    # Collateral at risk: both legs open simultaneously for LATENCY_MS
    # Each cycle: we hold maker leg (YES or NO, 100 contracts) for ~50ms
    # Max adverse move in 50ms on prediction market: ~0.001 cents
    # Dollar risk per cycle ~ size * price_vol_per_50ms
    # Conservative: collateral approach
    collateral_per_cycle = QUOTE_SIZE * (1 - 2 * HALF_SPREAD) * 2  # both legs

    print("\n" + "=" * 65)
    print("BACKTEST RESULTS  --  data/live  (May 21-24, 2026, ~2.5 days)")
    print("=" * 65)

    print(f"\n  ACTIVITY")
    print(f"  Markets run:           {len(eligible)}")
    print(f"  Book snapshots seen:   {total_books:,}")
    print(f"  Market trades seen:    {total_fills:,}   (events that could fill us)")
    print(f"  Arb cycles completed:  {total_cycles}")
    print(f"    Bid-arb (both cheap) {total_bid_arb}")
    print(f"    Ask-arb (both dear)  {total_ask_arb}")
    win_rate = (total_profitable / total_cycles * 100) if total_cycles else 0
    print(f"  Win rate:              {win_rate:.1f}%")

    print(f"\n  PnL")
    print(f"  Gross spread PnL:      ${total_pnl + total_fees - total_rebates:+.4f}")
    print(f"  Maker rebates earned:  ${total_rebates:+.4f}")
    print(f"  Taker fees paid:       $-{total_fees:.4f}")
    print(f"  NET PnL:               ${total_pnl:+.4f}")
    if total_cycles:
        print(f"  Avg per cycle:         ${total_pnl/total_cycles:+.4f}")
    print(f"  PnL/day (est.):        ${total_pnl/period_days:+.4f}")
    print(f"  Annualised (est.):     ${total_pnl/period_days*365:+.2f}")

    print(f"\n  RISK & EXPOSURE  (quote_size={QUOTE_SIZE:.0f} contracts, spread={HALF_SPREAD:.3f})")
    print(f"  Collateral locked/cycle: ${collateral_per_cycle:.2f} USDC")
    print(f"    (={QUOTE_SIZE:.0f} contracts x $1.00 x 2 legs, minus {HALF_SPREAD*2:.3f} spread)")
    print(f"  Maker->taker latency:  {LATENCY_MS}ms modeled (real: ~50-200ms)")
    print(f"  Exposure per cycle:    {LATENCY_MS}ms (open position window)")
    total_exposure_s = total_cycles * LATENCY_MS / 1000.0
    print(f"  Total exposure time:   {total_exposure_s:.1f}s  ({total_exposure_s/60:.2f} min)")
    print(f"  Exposure as % of period: {total_exposure_s/(period_days*86400)*100:.4f}%")

    if all_cycle_pnl:
        pos = [x for x in all_cycle_pnl if x > 0]
        neg = [x for x in all_cycle_pnl if x <= 0]
        print(f"\n  CYCLE PnL DISTRIBUTION  (n={len(all_cycle_pnl)})")
        print(f"  Profitable:  {len(pos)}  avg ${sum(pos)/len(pos):.4f}  best ${max(all_cycle_pnl):.4f}")
        if neg:
            print(f"  Losing:      {len(neg)}  avg ${sum(neg)/len(neg):.4f}  worst ${min(all_cycle_pnl):.4f}")
        if len(all_cycle_pnl) > 1:
            print(f"  Std dev:     ${statistics.stdev(all_cycle_pnl):.4f}")
            print(f"  Sharpe (daily, rough): {(total_pnl/period_days) / (statistics.stdev(all_cycle_pnl) * (total_cycles/period_days)**0.5 + 1e-9):.2f}")

    print(f"\n  TOP MARKETS BY PnL")
    print(f"  {'market':<24} {'net_pnl':>9} {'cycles':>7} {'win%':>6} {'gross':>9} {'fees':>9}")
    ranked = sorted(results, key=lambda x: -x[1].total_pnl())
    for mid, r in ranked[:15]:
        if r.num_cycles_completed == 0:
            continue
        gross = r.total_pnl() + r.total_fees_paid - r.total_rebates_received
        wr = r.win_rate() * 100
        print(f"  {mid[:24]:<24} ${r.total_pnl():>8.4f} {r.num_cycles_completed:>7} "
              f"{wr:>5.0f}% ${gross:>8.4f} $-{r.total_fees_paid:>7.4f}")

    print(f"\n  ZERO-CYCLE MARKETS: {sum(1 for _,r in results if r.num_cycles_completed==0)} "
          f"(book data but no arb opportunity found)")
    print()


if __name__ == "__main__":
    main()
