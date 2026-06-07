#!/usr/bin/env python3
"""
Backtest against data/live — merges date-subdirectory files per market,
runs the dual-book maker-taker simulator, reports PnL + risk + exposure.

Data source: EC2 collector at EC2_HOST.  By default the script syncs the
latest data from EC2 before running (pass --no-sync to skip).
"""
import json
import os
import subprocess
import sys
import statistics
import tarfile
import tempfile
import urllib.request
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
from src.live.portfolio_state import PortfolioConstraints

# --- EC2 collector config ---------------------------------------------------
EC2_HOST     = "ubuntu@100.52.215.239"
ROOT_DIR     = Path(__file__).resolve().parent.parent
EC2_KEY      = str(ROOT_DIR / "polymarket-key.pem")
EC2_DATA_DIR = "/opt/polymarket-mm/polymarket-mm/data/live"
# ---------------------------------------------------------------------------
LIVE_DIR    = ROOT_DIR / "data" / "live"
FEE_RATE    = 0.07
REBATE_FRAC = 0.50
QUOTE_SIZE  = 100.0
LATENCY_MS  = 50

# Ladder: 3 levels anchored to best bid/ask, increasing size deeper
LADDER_LEVELS       = 3
LADDER_OFFSET       = 0.030   # L0 sits this far below best bid / above best ask
LADDER_TICK         = 0.010   # each successive level goes one tick deeper
LADDER_SIZE_RATIOS  = [1.0, 2.0, 3.0]   # 100 / 200 / 300 contracts

# Iceberg orders — set to 0 to disable, or e.g. 50 to show only 50 contracts
# per slice and sweep through the hidden reserve on each large market trade.
ICEBERG_DISPLAY_SIZE = 50.0   # contracts per visible slice (0 = no iceberg)

# Order management — must match live QuoteLoopConfig defaults so the backtest
# faithfully models what will happen in production.
PRICE_TOLERANCE     = 0.010   # min best-bid drift before repricing ladder anchor (1 tick)

# Portfolio-level risk caps — mirror what you'd fund the live wallet with.
TOTAL_CAPITAL           = 10_000.0   # USDC in wallet
MAX_LONG_TERM_FRACTION  = 0.80       # max 80 % in positions resolving >30 days out (~$8k)
MAX_EVENT_NOTIONAL      = 0.0        # per-event cap disabled — per-market cap handles concentration
MAX_MARKET_NOTIONAL     = 2_000.0    # max USDC per individual market (prevents single-name blowup)


def sync_from_ec2() -> None:
    """Pull any date directories from EC2 that are missing or newer locally.

    Raises SystemExit if EC2 is unreachable — the backtest should not silently
    fall back to stale local data.  Pass --no-sync explicitly if you intend to
    run offline.
    """
    print("Syncing data from EC2 ...")

    # 1. Ask EC2 which date dirs it has
    result = subprocess.run(
        ["ssh", "-i", EC2_KEY, "-o", "StrictHostKeyChecking=no",
         EC2_HOST, f"ls {EC2_DATA_DIR}"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"\nERROR: could not reach EC2 collector at {EC2_HOST}")
        print(f"  {result.stderr.strip()}")
        print("\nThe backtest requires live EC2 data.")
        print("If you intentionally want to run against local data, pass --no-sync.")
        sys.exit(1)

    remote_dates = result.stdout.split()
    local_dates  = {d.name for d in LIVE_DIR.iterdir() if d.is_dir()} if LIVE_DIR.exists() else set()
    today        = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Sync all remote dates; always re-sync today (still being written)
    to_sync = [d for d in remote_dates if d not in local_dates or d == today]
    if not to_sync:
        print("  Already up to date.")
        return

    print(f"  Fetching {len(to_sync)} date(s): {', '.join(to_sync)}")

    # 2. Tar the needed dates on EC2 and pipe to scp
    tar_args = " ".join(to_sync)
    remote_tar = f"/tmp/polymarket_sync_{os.getpid()}.tar.gz"
    subprocess.run(
        ["ssh", "-i", EC2_KEY, "-o", "StrictHostKeyChecking=no",
         EC2_HOST, f"cd {EC2_DATA_DIR} && tar czf {remote_tar} {tar_args} && echo ok"],
        check=True, timeout=120,
    )

    # 3. Download the tarball
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        local_tar = tmp.name

    try:
        subprocess.run(
            ["scp", "-i", EC2_KEY, "-o", "StrictHostKeyChecking=no",
             f"{EC2_HOST}:{remote_tar}", local_tar],
            check=True, timeout=120,
        )

        # 4. Extract into LIVE_DIR
        LIVE_DIR.mkdir(parents=True, exist_ok=True)
        with tarfile.open(local_tar, "r:gz") as tf:
            tf.extractall(LIVE_DIR)

        print(f"  Sync complete. Local data now covers: "
              f"{sorted(d.name for d in LIVE_DIR.iterdir() if d.is_dir())}")
    finally:
        Path(local_tar).unlink(missing_ok=True)
        # Clean up remote tar
        subprocess.run(
            ["ssh", "-i", EC2_KEY, "-o", "StrictHostKeyChecking=no",
             EC2_HOST, f"rm -f {remote_tar}"],
            timeout=10,
        )


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


def compute_avg_trade_size(events) -> float:
    """Return mean trade size from a market's event stream.

    Only counts Fill events (actual observed trades, not synthetic book events).
    Falls back to QUOTE_SIZE if no trades are present.
    """
    sizes = [e.size for e in events if isinstance(e, Fill) and e.size > 0]
    if not sizes:
        return QUOTE_SIZE
    return statistics.mean(sizes)


def adaptive_quote_size(avg_trade_size: float) -> float:
    """Derive quote_size so L1 (ratio 2x) matches the market's avg trade size.

    L0 = avg/2,  L1 = avg,  L2 = 1.5x avg  (with 1:2:3 ratios and base=avg/2)
    Clamped to [5, 500] contracts — upper bound set high enough that liquid
    markets (avg trade 200–1000+) are not artificially capped.
    """
    return max(5.0, min(500.0, round(avg_trade_size / 2)))


def make_simulator(market_id, days_to_resolution=9999, event_key="", portfolio=None,
                   quote_size=None, sim_market_id=""):
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
    qe   = QuoteEngine(fm, FEE_RATE, REBATE_FRAC, LADDER_OFFSET, 0.005)
    inv  = InventoryManager(market_id, 0.0003)
    pnl  = PnLEngine(fm, FEE_RATE, REBATE_FRAC)
    qs   = quote_size if quote_size is not None else QUOTE_SIZE
    fm2  = FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=LATENCY_MS))
    return BacktestSimulator(
        metadata=meta, fee_model=fm,
        fv_estimator=fv, regime_classifier=reg,
        hedgeability_assessor=ha, quote_engine=qe,
        inventory_manager=inv, pnl_engine=pnl,
        fill_model=fm2, skew_config=skew_config,
        config=SimulatorConfig(
            start_capital=50000.0,
            quote_size=qs,
            time_to_resolution_hours=720.0,
            ladder_levels=LADDER_LEVELS,
            ladder_offset_from_best=LADDER_OFFSET,
            ladder_tick_spacing=LADDER_TICK,
            ladder_size_ratios=LADDER_SIZE_RATIOS,
            price_tolerance=PRICE_TOLERANCE,
            iceberg_display_size=ICEBERG_DISPLAY_SIZE,
            days_to_resolution=days_to_resolution,
            event_key=event_key,
            market_id=sim_market_id,
        ),
        portfolio=portfolio,
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
    import argparse
    parser = argparse.ArgumentParser(description="Run backtest against EC2 collector data")
    parser.add_argument("--no-sync", action="store_true",
                        help="Skip EC2 sync and use whatever is in data/live already")
    args = parser.parse_args()

    if not args.no_sync:
        sync_from_ec2()
    else:
        print("WARNING: --no-sync specified — using local data/live/ as-is (may be stale).")

    # Discover markets
    market_files = defaultdict(list)
    for f in sorted(LIVE_DIR.glob("**/*.jsonl")):
        market_files[f.stem].append(f)

    print("Scanning for dual-book markets ...")
    eligible = [(mid, files) for mid, files in market_files.items() if is_dual_book(files)]
    print(f"Found {len(eligible)} dual-book markets.")

    # Fetch resolution dates + event IDs for all eligible markets
    print("Fetching resolution dates from Gamma API ...")
    market_resolution: dict[str, tuple[str, int, str]] = {}  # mid -> (end_date_str, days_left, event_id)

    def _fetch_market_meta(cid: str) -> tuple[str, int, str]:
        """Returns (end_date_str, days_left, event_key).

        event_key is the Gamma event ID (e.g. "23784") when available — this
        correctly groups sub-markets of the same parent event under a shared
        notional cap.  Falls back to end_date_str so the cap still fires even
        when the API doesn't return an event.
        """
        url = f"https://gamma-api.polymarket.com/markets?condition_id={cid}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            m = data[0] if isinstance(data, list) and data else {}
            end_str = m.get("end_date_iso") or m.get("endDate") or m.get("end_date") or ""
            # Extract parent event ID — sub-markets of the same event share one cap
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

    for mid, _ in eligible:
        market_resolution[mid] = _fetch_market_meta(mid)
    print(f"  Done ({len(market_resolution)} markets resolved).")

    # Shared portfolio constraints — enforced across all simulators sequentially.
    # NOTE: The backtest runs markets one at a time (not interleaved), so the portfolio
    # state accumulates across markets in the order they are processed.  This is an
    # approximation of the true concurrent live behavior but gives a conservative
    # upper bound on how quickly caps would be hit.
    portfolio = PortfolioConstraints(
        total_capital=TOTAL_CAPITAL,
        max_long_term_fraction=MAX_LONG_TERM_FRACTION,
        max_event_notional=MAX_EVENT_NOTIONAL,
        max_market_notional=MAX_MARKET_NOTIONAL,
    )

    lt_cap = TOTAL_CAPITAL * MAX_LONG_TERM_FRACTION
    print(f"Running backtest with portfolio caps: "
          f"long-term <={MAX_LONG_TERM_FRACTION*100:.0f}% of ${TOTAL_CAPITAL:,.0f} "
          f"(<=${lt_cap:,.0f}), "
          f"per-market <=${MAX_MARKET_NOTIONAL:,.0f}"
          + (f", event <=${MAX_EVENT_NOTIONAL:,.0f}" if MAX_EVENT_NOTIONAL > 0 else "")
          + "\n")

    results = []   # (mid, SimulationResult, avg_trade_size, quote_size_used)
    for i, (mid, files) in enumerate(eligible, 1):
        end_date_str, days_left, event_key = market_resolution[mid]
        events = load_market_events(files)
        avg_ts = compute_avg_trade_size(events)
        qs     = adaptive_quote_size(avg_ts)
        sim = make_simulator(
            mid,
            days_to_resolution=days_left,
            event_key=event_key,
            portfolio=portfolio,
            quote_size=qs,
            sim_market_id=mid,
        )
        r = sim.run(events)
        results.append((mid, r, avg_ts, qs))
        if i % 25 == 0:
            print(f"  {i}/{len(eligible)} markets done ...")

    # Aggregate
    total_portfolio_blocked = sum(r.num_portfolio_blocked for _, r, _, _ in results)
    total_pnl          = sum(r.total_pnl()               for _, r, _, _ in results)
    total_fees         = sum(r.total_fees_paid            for _, r, _, _ in results)
    total_rebates      = sum(r.total_rebates_received     for _, r, _, _ in results)
    total_cycles       = sum(r.num_cycles_completed       for _, r, _, _ in results)
    total_fills        = sum(r.num_fills                  for _, r, _, _ in results)
    total_books        = sum(r.num_book_updates           for _, r, _, _ in results)
    total_profitable   = sum(r.num_profitable_cycles      for _, r, _, _ in results)
    total_bid_arb      = sum(r.num_bid_arb_cycles         for _, r, _, _ in results)
    total_ask_arb      = sum(r.num_ask_arb_cycles         for _, r, _, _ in results)
    total_longs        = sum(r.num_longs_opened           for _, r, _, _ in results)
    total_shorts       = sum(r.num_shorts_opened          for _, r, _, _ in results)
    total_roundtrips   = sum(r.num_round_trips            for _, r, _, _ in results)
    total_held         = sum(r.num_held_to_resolution     for _, r, _, _ in results)
    total_roundtrip_pnl= sum(r.round_trip_pnl             for _, r, _, _ in results)
    total_res_pnl      = sum(r.resolution_pnl             for _, r, _, _ in results)
    total_capital      = sum(r.total_capital_consumed     for _, r, _, _ in results)
    peak_concurrent    = max((r.max_concurrent_open for _, r, _, _ in results), default=0)
    all_cycle_pnl      = [p for _, r, _, _ in results for p in r.per_cycle_pnl]
    all_rt_pnl         = [p for _, r, _, _ in results for p in r.per_roundtrip_pnl]
    all_hold_times     = [t for _, r, _, _ in results for t in r.holding_times_seconds]

    # Compute data period dynamically from event timestamps (estimate from file mtimes)
    import os
    mtimes = [os.path.getmtime(f) for files in market_files.values() for f in files]
    if len(mtimes) >= 2:
        period_days = (max(mtimes) - min(mtimes)) / 86400
    else:
        period_days = 1.0
    period_days = max(period_days, 0.1)

    iceberg_desc = (
        f"iceberg={int(ICEBERG_DISPLAY_SIZE)} contracts/slice"
        if ICEBERG_DISPLAY_SIZE > 0 else "iceberg=off"
    )
    ladder_desc = (
        f"{LADDER_LEVELS} levels  "
        f"offset={LADDER_OFFSET:.3f}  tick={LADDER_TICK:.3f}  "
        f"sizes=adaptive (base=avg_trade/2)  {iceberg_desc}"
    )

    # ------------------------------------------------------------------ #
    #  Derived summary metrics                                            #
    # ------------------------------------------------------------------ #
    import math
    win_rate        = (total_profitable / total_cycles * 100) if total_cycles else 0
    total_positions = total_longs + total_shorts
    recycled_pct    = (total_roundtrips / total_positions * 100) if total_positions else 0
    avg_notional    = (total_capital / total_positions) if total_positions else 0
    # Peak capital = peak concurrent positions × actual avg notional per position.
    # (Not QUOTE_SIZE × ladder_ratios, which would be max-possible, not actual.)
    peak_locked     = peak_concurrent * avg_notional
    roc             = (total_pnl / peak_locked * 100) if peak_locked else 0

    # Net open positions at end of window (still locked awaiting resolution)
    # bid-arbs that opened longs minus ask-arbs that closed longs
    longs_closed_by_arb  = total_bid_arb - total_longs   # bid-arbs that closed shorts
    shorts_closed_by_arb = total_ask_arb - total_shorts  # ask-arbs that closed longs
    net_longs_open  = total_longs  - shorts_closed_by_arb
    net_shorts_open = total_shorts - longs_closed_by_arb
    net_open        = net_longs_open + net_shorts_open
    capital_at_resolution = net_open * avg_notional

    # Sharpe ratio (annualised, cycle-frequency method, no risk-free rate)
    #
    #   Each cycle i has PnL p_i.  Assume cycles are independent (iid).
    #   Daily PnL ~ sum of (cycles/day) independent draws:
    #     E[daily PnL]   = (N/T) * mean(p_i)
    #     Std[daily PnL] = sqrt(N/T) * std(p_i)        [var scales linearly]
    #   Daily Sharpe     = E[daily] / Std[daily]
    #                    = sqrt(N/T) * mean(p_i) / std(p_i)
    #   Annualised (x sqrt(252)):
    #     Sharpe_ann     = sqrt(252 * N/T) * mean(p_i) / std(p_i)
    #
    if len(all_cycle_pnl) >= 2:
        n_cycles_f   = float(len(all_cycle_pnl))
        mean_cycle   = statistics.mean(all_cycle_pnl)
        std_cycle    = statistics.stdev(all_cycle_pnl)
        cycles_per_day = n_cycles_f / period_days
        sharpe_ann   = (math.sqrt(252.0 * cycles_per_day) * mean_cycle / std_cycle
                        if std_cycle > 0 else float('nan'))
    else:
        mean_cycle = std_cycle = cycles_per_day = sharpe_ann = float('nan')

    # ------------------------------------------------------------------ #
    #  SUMMARY CARD  (always printed, always the same 8 lines)            #
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 55)
    print(f"  BACKTEST  {period_days:.1f} days  |  {ladder_desc}")
    print("=" * 55)
    print(f"  Arb events          {total_bid_arb + total_ask_arb:>6}  "
          f"({total_bid_arb} bid-arb / {total_ask_arb} ask-arb)")
    print(f"  Longs opened        {total_longs:>6}  "
          f"({shorts_closed_by_arb} bid-arbs closed existing shorts)")
    print(f"  Shorts opened       {total_shorts:>6}  "
          f"({longs_closed_by_arb} ask-arbs closed existing longs)")
    print(f"  Round-trips         {total_roundtrips:>6}  "
          f"(= {longs_closed_by_arb} + {shorts_closed_by_arb})")
    print(f"  Open at end         {net_open:>6}  "
          f"({net_longs_open} longs + {net_shorts_open} shorts  ~${capital_at_resolution:,.0f} locked until resolution)")
    if total_portfolio_blocked:
        print(f"  Portfolio blocked   {total_portfolio_blocked:>6}  "
              f"(opens skipped: long-term cap or event cap hit)")
    print(f"  Avg notional        ${avg_notional:>8,.2f}  per position (both legs)")
    print(f"  Recycling           {recycled_pct:>5.1f}%  "
          f"({total_roundtrips} closed within window / {total_positions} opened)")
    print(f"  Peak capital locked ${peak_locked:>8,.0f}  USDC  "
          f"({peak_concurrent} concurrent positions × ${avg_notional:.2f})")
    print(f"  Net PnL             ${total_pnl:>+8.2f}  "
          f"(${total_pnl/period_days:.2f}/day  ~${total_pnl/period_days*365:,.0f}/yr)")
    print(f"  Return on capital   {roc:>+7.2f}%  over {period_days:.1f} days  "
          f"(~{roc/period_days*365:.0f}% ann.)")
    if not math.isnan(sharpe_ann):
        print(f"  Sharpe (ann.)       {sharpe_ann:>7.2f}")
    print("=" * 55)

    # Show the Sharpe calculation so it can always be verified
    if not math.isnan(sharpe_ann):
        print(f"\n  SHARPE CALCULATION")
        print(f"  Formula : sqrt(252 x cycles/day) x mean_cycle / std_cycle")
        print(f"  Inputs  : {n_cycles_f:.0f} cycles over {period_days:.2f} days"
              f"  =>  {cycles_per_day:.2f} cycles/day")
        print(f"            mean cycle PnL = ${mean_cycle:.4f}")
        print(f"            std  cycle PnL = ${std_cycle:.4f}")
        print(f"  =  sqrt(252 x {cycles_per_day:.2f}) x {mean_cycle:.4f} / {std_cycle:.4f}")
        print(f"  =  sqrt({252*cycles_per_day:.1f}) x {mean_cycle/std_cycle:.4f}")
        print(f"  =  {math.sqrt(252*cycles_per_day):.3f} x {mean_cycle/std_cycle:.4f}")
        print(f"  =  {sharpe_ann:.2f}")

    # ------------------------------------------------------------------ #
    #  DETAIL SECTIONS  (full breakdown below the card)                   #
    # ------------------------------------------------------------------ #
    print(f"\n  PnL BREAKDOWN")
    print(f"  Round-trip PnL      ${total_roundtrip_pnl:+.2f}  (open + close captured)")
    print(f"  Resolution PnL      ${total_res_pnl:+.2f}  (held to $1.00)")
    print(f"  Gross (pre-fee)     ${total_pnl + total_fees - total_rebates:+.2f}")
    print(f"  Maker rebates       ${total_rebates:+.2f}")
    print(f"  Taker fees          $-{total_fees:.2f}")
    print(f"  Win rate            {win_rate:.1f}%")

    if all_hold_times:
        avg_hold = statistics.mean(all_hold_times)
        med_hold = statistics.median(all_hold_times)
        print(f"\n  HOLDING TIME  (round-trips only)")
        print(f"  Avg   {avg_hold/3600:.2f}h    Median  {med_hold/3600:.2f}h")

    if all_rt_pnl:
        rt_pos = [x for x in all_rt_pnl if x > 0]
        rt_neg = [x for x in all_rt_pnl if x <= 0]
        print(f"\n  ROUND-TRIP PnL DISTRIBUTION  (n={len(all_rt_pnl)})")
        if rt_pos:
            print(f"  Profitable  {len(rt_pos):>3}   avg ${sum(rt_pos)/len(rt_pos):.4f}   best ${max(all_rt_pnl):.4f}")
        if rt_neg:
            print(f"  Losing      {len(rt_neg):>3}   avg ${sum(rt_neg)/len(rt_neg):.4f}   worst ${min(all_rt_pnl):.4f}")

    print(f"\n  TOP MARKETS BY PnL")
    print(f"  {'market':<24} {'net_pnl':>9} {'cycles':>7} {'win%':>6} {'rt':>5} "
          f"{'held':>5} {'avg_ts':>7} {'qs':>5} {'hfail':>6}")
    ranked = sorted(results, key=lambda x: -x[1].total_pnl())
    for mid, r, avg_ts, qs in ranked[:15]:
        if r.num_cycles_completed == 0:
            continue
        wr = r.win_rate() * 100
        print(f"  {mid[:24]:<24} ${r.total_pnl():>8.2f} {r.num_cycles_completed:>7} "
              f"{wr:>5.0f}%  {r.num_round_trips:>4}  {r.num_held_to_resolution:>4} "
              f"  {avg_ts:>5.1f}  {int(qs):>4}  {r.num_no_hedge_depth:>5}")

    print(f"\n  Markets with no cycles: "
          f"{sum(1 for _,r,_,_ in results if r.num_cycles_completed==0)} of {len(eligible)}")

    # ------------------------------------------------------------------ #
    #  OPEN POSITIONS BY DAYS-TO-RESOLUTION                               #
    # ------------------------------------------------------------------ #
    # Compute net open per market
    open_by_market = {}  # mid -> (net_longs_open, net_shorts_open)
    for mid, r, _, _ in results:
        longs_closed  = r.num_ask_arb_cycles - r.num_shorts_opened   # ask-arbs that closed longs
        shorts_closed = r.num_bid_arb_cycles - r.num_longs_opened    # bid-arbs that closed shorts
        nl = max(0, r.num_longs_opened  - longs_closed)
        ns = max(0, r.num_shorts_opened - shorts_closed)
        if nl + ns > 0:
            open_by_market[mid] = (nl, ns)

    if open_by_market:
        print(f"\n  OPEN POSITIONS BY DAYS-TO-RESOLUTION")

        # Reuse already-fetched resolution data (market_resolution dict from above)
        # Unpack 3-tuple: (end_date_str, days_left, event_key) — drop event_key for display
        end_dates = {mid: market_resolution.get(mid, ("unknown", 9999, "unknown"))[:2]
                     for mid in open_by_market}

        # Print per-market table (sorted by days_left)
        rows_open = sorted(
            [(mid, nl, ns, *end_dates[mid]) for mid, (nl, ns) in open_by_market.items()],
            key=lambda x: x[4],   # days_left
        )
        print(f"\n  {'market':<24} {'longs':>6} {'shorts':>7} {'total':>6} "
              f"{'notional':>10} {'end_date':>12} {'days_left':>10}")
        print("  " + "-" * 82)
        for mid, nl, ns, end_dt_str, days_left in rows_open:
            total_pos = nl + ns
            notional  = total_pos * avg_notional
            dl_str    = str(days_left) if days_left != 9999 else "?"
            print(f"  {mid[:24]:<24} {nl:>6} {ns:>7} {total_pos:>6} "
                  f"  ${notional:>8,.0f} {end_dt_str:>12} {dl_str:>10}")

        # Bucket summary
        buckets = [
            ("<7 days",   lambda d: d < 7),
            ("7-30 days", lambda d: 7 <= d < 30),
            ("30-90 days",lambda d: 30 <= d < 90),
            (">90 days",  lambda d: d >= 90),
            ("unknown",   lambda d: d == 9999),
        ]
        print(f"\n  BUCKET SUMMARY")
        print(f"  {'bucket':<14} {'positions':>10} {'notional':>12} {'% of total':>12}")
        print("  " + "-" * 52)
        for label, pred in buckets:
            subset = [(nl + ns) for mid, nl, ns, _, dl in rows_open if pred(dl)]
            if not subset:
                continue
            n_pos    = sum(subset)
            notional = n_pos * avg_notional
            pct      = n_pos / net_open * 100 if net_open else 0
            print(f"  {label:<14} {n_pos:>10}   ${notional:>9,.0f}   {pct:>9.1f}%")
        print("  " + "-" * 52)
        print(f"  {'TOTAL':<14} {net_open:>10}   ${capital_at_resolution:>9,.0f}")

    print()


if __name__ == "__main__":
    main()
