#!/usr/bin/env python3
"""
Backtest against data/live — merges date-subdirectory files per market,
runs the dual-book maker-taker simulator, reports PnL + risk + exposure.

Data source: EC2 collector at EC2_HOST.  By default the script syncs the
latest data from EC2 before running (pass --no-sync to skip).
"""
import json
import os
import statistics
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.live.portfolio_state import PortfolioConstraints
from src.backtest.live_harness import (
    LADDER_LEVELS, LADDER_OFFSET, LADDER_TICK, LADDER_SIZE_RATIOS,
    ICEBERG_DISPLAY_SIZE,
    load_market_events, is_dual_book,
    compute_avg_trade_size, adaptive_quote_size, make_simulator,
)

# --- EC2 collector config ---------------------------------------------------
EC2_HOST     = "ubuntu@100.52.215.239"
ROOT_DIR     = Path(__file__).resolve().parent.parent
EC2_KEY      = str(ROOT_DIR / "polymarket-key.pem")
EC2_DATA_DIR = "/opt/polymarket-mm/polymarket-mm/data/live"
# ---------------------------------------------------------------------------
LIVE_DIR    = ROOT_DIR / "data" / "live"

# Portfolio-level risk caps — mirror what you'd fund the live wallet with.
TOTAL_CAPITAL           = 10_000.0   # USDC in wallet
MAX_LONG_TERM_FRACTION  = 0.30       # max 30 % lockable in >30-day positions — liquidity guard
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run backtest against EC2 collector data")
    parser.add_argument("--no-sync", action="store_true",
                        help="Skip EC2 sync and use whatever is in data/live already")
    parser.add_argument("--capital", type=float, default=None,
                        help="Override TOTAL_CAPITAL (default: use script constant)")
    args = parser.parse_args()

    # Allow CLI override of capital
    global TOTAL_CAPITAL
    if args.capital is not None:
        TOTAL_CAPITAL = args.capital

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

        Uses CLOB REST path lookup — the Gamma ?condition_id= query filter is
        broken server-side (returns an unrelated market), which would silently
        misclassify short-duration markets as long-term. event_key is the
        end-date string (markets resolving the same day share an event cap
        when MAX_EVENT_NOTIONAL > 0; it defaults to 0/disabled).
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
    total_contracts    = sum(r.total_contracts_traded      for _, r, _, _ in results)
    total_volume       = sum(r.total_traded_notional       for _, r, _, _ in results)
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
    #  Peak CONCURRENT capital — the number that actually binds vs the    #
    #  wallet. Open intervals release capital at close time; positions    #
    #  still open at data end release at the market's resolution date     #
    #  (so a 5m window that resolved mid-window hands capital back the    #
    #  same day instead of counting as "locked" forever).                 #
    # ------------------------------------------------------------------ #
    from datetime import timedelta
    cap_events = []          # (time, +/- notional)
    window_end = datetime.now(timezone.utc)
    still_locked_at_end = 0.0
    for mid, r, _, _ in results:
        end_date_str = market_resolution.get(mid, ("unknown",))[0]
        resolution_ts = None
        if end_date_str not in ("", "unknown"):
            try:
                # Release at end of resolution day UTC (conservative upper bound)
                resolution_ts = datetime.fromisoformat(end_date_str).replace(
                    tzinfo=timezone.utc) + timedelta(days=1)
            except ValueError:
                pass
        for opened_at, closed_at, notional in r.position_intervals:
            if opened_at is None:
                continue
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            release = closed_at if closed_at is not None else resolution_ts
            if release is not None and release.tzinfo is None:
                release = release.replace(tzinfo=timezone.utc)
            cap_events.append((opened_at, +notional))
            if release is not None and release <= window_end:
                cap_events.append((release, -notional))
            else:
                still_locked_at_end += notional
    cap_events.sort(key=lambda e: e[0])
    peak_locked, running, peak_locked_at = 0.0, 0.0, None
    for ts_e, delta in cap_events:
        running += delta
        if running > peak_locked:
            peak_locked, peak_locked_at = running, ts_e

    # ------------------------------------------------------------------ #
    #  Derived summary metrics                                            #
    # ------------------------------------------------------------------ #
    import math
    win_rate        = (total_profitable / total_cycles * 100) if total_cycles else 0
    total_positions = total_longs + total_shorts
    recycled_pct    = (total_roundtrips / total_positions * 100) if total_positions else 0
    avg_notional    = (total_capital / total_positions) if total_positions else 0

    # Net open positions at end of window (still locked awaiting resolution)
    # bid-arbs that opened longs minus ask-arbs that closed longs
    longs_closed_by_arb  = total_bid_arb - total_longs   # bid-arbs that closed shorts
    shorts_closed_by_arb = total_ask_arb - total_shorts  # ask-arbs that closed longs
    net_longs_open  = total_longs  - shorts_closed_by_arb
    net_shorts_open = total_shorts - longs_closed_by_arb
    net_open        = net_longs_open + net_shorts_open
    capital_at_resolution = net_open * avg_notional

    # Return on capital uses PEAK CONCURRENT locked capital — the true
    # binding constraint vs the wallet. Cumulative deployment re-counts the
    # same recycled dollars; locked-at-end ignores intra-window resolutions.
    lt_budget       = TOTAL_CAPITAL * MAX_LONG_TERM_FRACTION  # the portfolio cap ceiling
    roc             = (total_pnl / peak_locked * 100) if peak_locked else 0

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
    print(f"  Not arb-closed      {net_open:>6}  "
          f"({net_longs_open} longs + {net_shorts_open} shorts — settle at each "
          f"market's resolution; most resolved IN-window, see capital lines)")
    if total_portfolio_blocked:
        print(f"  Portfolio blocked   {total_portfolio_blocked:>6}  "
              f"(opens skipped: long-term cap or event cap hit)")
    print(f"  Avg notional        ${avg_notional:>8,.2f}  per position (both legs)")
    print(f"  Recycling           {recycled_pct:>5.1f}%  "
          f"({total_roundtrips} closed within window / {total_positions} opened)")
    # Long-term locked = open positions in markets resolving >30 days out.
    # Only this counts against the LT budget; short-duration positions don't.
    lt_open_positions = 0
    for mid, r, _, _ in results:
        days_left = market_resolution.get(mid, ("", 9999, ""))[1]
        if days_left > 30:
            longs_closed  = r.num_ask_arb_cycles - r.num_shorts_opened
            shorts_closed = r.num_bid_arb_cycles - r.num_longs_opened
            lt_open_positions += (max(0, r.num_longs_opened - longs_closed)
                                  + max(0, r.num_shorts_opened - shorts_closed))
    lt_locked = lt_open_positions * avg_notional
    print(f"  Trading volume      ${total_volume:>8,.0f}  USDC across both legs  "
          f"(${total_volume / period_days:,.0f}/day, {total_contracts:,.0f} contracts)")
    print(f"  Cumulative deployed ${total_capital:>8,.0f}  USDC across {total_positions} opens (recycled capital re-counted)")
    print(f"  Peak concurrent     ${peak_locked:>8,.0f}  USDC max locked at once"
          + (f"  ({peak_locked_at:%m-%d %H:%M} UTC)" if peak_locked_at else "")
          + f"  [{peak_locked / TOTAL_CAPITAL * 100:.0f}% of wallet]")
    print(f"  Locked at win. end  ${still_locked_at_end:>8,.0f}  USDC awaiting post-window resolution")
    print(f"  LT cap budget       ${lt_budget:>8,.0f}  USDC  "
          f"({MAX_LONG_TERM_FRACTION*100:.0f}% of ${TOTAL_CAPITAL:,.0f} wallet — "
          f"${lt_locked:,.0f} used by >30-day positions, ${lt_budget - lt_locked:,.0f} remaining)")
    print(f"  Net PnL             ${total_pnl:>+8.2f}  "
          f"(${total_pnl/period_days:.2f}/day  ~${total_pnl/period_days*365:,.0f}/yr)")
    print(f"  Return on capital   {roc:>+7.2f}%  over {period_days:.1f} days  "
          f"(~{roc/period_days*365:.0f}% ann.)  [vs ${peak_locked:,.0f} peak concurrent]")
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
    # Gross + Costs = Net.  The round-trip/resolution components are
    # net-of-fees in the simulator, so they decompose NET, not gross.
    gross_pnl    = total_pnl + total_fees - total_rebates
    net_fee_cost = total_fees - total_rebates
    print(f"\n  PnL BREAKDOWN")
    print(f"  Gross (pre-fee)     ${gross_pnl:+10,.2f}")
    print(f"  Costs               ${-net_fee_cost:+10,.2f}")
    print(f"    Taker fees        ${-total_fees:+10,.2f}")
    print(f"    Maker rebates     ${total_rebates:+10,.2f}")
    print(f"  Net PnL             ${total_pnl:+10,.2f}")
    print(f"    Round-trip PnL    ${total_roundtrip_pnl:+10,.2f}  (closed in window, net of fees)")
    print(f"    Resolution PnL    ${total_res_pnl:+10,.2f}  (settled at $1.00, net of fees)")
    print(f"  Win rate            {win_rate:.1f}%")

    # Per-level fill breakdown — aggregate fills_by_level across all markets
    max_level = max(
        (len(r.fills_by_level) for _, r, _, _ in results if r.fills_by_level),
        default=0
    )
    if max_level > 0:
        level_totals = [0] * max_level
        for _, r, _, _ in results:
            for lvl, cnt in enumerate(r.fills_by_level):
                level_totals[lvl] += cnt
        total_level_fills = sum(level_totals)
        print(f"\n  FILLS BY LADDER LEVEL  (offset={LADDER_OFFSET:.3f} + n×{LADDER_TICK:.3f})")
        for lvl, cnt in enumerate(level_totals):
            offset = LADDER_OFFSET + lvl * LADDER_TICK
            ratio  = LADDER_SIZE_RATIOS[lvl] if lvl < len(LADDER_SIZE_RATIOS) else LADDER_SIZE_RATIOS[-1]
            pct    = cnt / total_level_fills * 100 if total_level_fills else 0
            bar    = "#" * int(pct / 5)
            print(f"  L{lvl}  -{offset:.3f}  {ratio:.1f}x base   {cnt:>4} fills  {pct:>5.1f}%  {bar}")

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
