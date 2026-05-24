#!/usr/bin/env python3
# scripts/run_portfolio_analysis.py
"""
Multi-market portfolio backtest analysis.

Usage:
    python scripts/run_portfolio_analysis.py --data data/raw [--capital 50000] [--quote-size 100]

Discovers all *.jsonl files in --data directory, runs each market as a
BacktestRunner with shared portfolio tracking, and prints aggregate metrics.

Fee parameters are read from a sidecar config file per market if present:
    data/raw/{market_id}.json  ->  {"fee_rate": 0.04, "fee_exponent": 1, "rebate_fraction": 0.5, "sports": false}

If no sidecar is found, defaults to standard crypto parameters (fee_rate=0.07).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.runner import RunConfig
from src.backtest.portfolio_sim import PortfolioSimulator, PortfolioConfig


DEFAULT_FEE_PARAMS = {
    "fee_rate": 0.07,
    "fee_exponent": 1,
    "rebate_fraction": 0.5,
    "sports": False,
}


def load_market_configs(
    data_dir: Path,
    quote_size: float,
    half_spread_base: float,
    time_to_resolution_hours: float,
    adverse_selection_window_seconds: float,
    adverse_selection_adverse_threshold: float,
    quote_staleness_threshold: float,
    skew_tolerance: float,
    skew_edge_premium: float,
    max_concurrent_positions: int,
    twap_window_seconds: int = 3600,
) -> list[RunConfig]:
    configs = []
    for jsonl_path in sorted(data_dir.glob("*.jsonl")):
        market_id = jsonl_path.stem
        sidecar = data_dir / f"{market_id}.json"
        if sidecar.exists():
            with sidecar.open() as f:
                params = json.load(f)
        else:
            params = DEFAULT_FEE_PARAMS.copy()

        # When skew_tolerance > 0, set permissive circuit-breaker limits so
        # skew_tolerance is the sole throttle in backtesting.
        skew_hard_limit = int(skew_tolerance * 10) if skew_tolerance > 0 else 0
        max_skew_notional = skew_tolerance * 2.0 if skew_tolerance > 0 else 0.0

        cfg = RunConfig(
            market_id=market_id,
            data_dir=str(data_dir),
            fee_rate=params.get("fee_rate", DEFAULT_FEE_PARAMS["fee_rate"]),
            fee_exponent=params.get("fee_exponent", DEFAULT_FEE_PARAMS["fee_exponent"]),
            rebate_fraction=params.get("rebate_fraction", DEFAULT_FEE_PARAMS["rebate_fraction"]),
            sports=params.get("sports", DEFAULT_FEE_PARAMS["sports"]),
            quote_size=quote_size,
            half_spread_base=half_spread_base,
            time_to_resolution_hours=time_to_resolution_hours,
            adverse_selection_window_seconds=adverse_selection_window_seconds,
            adverse_selection_adverse_threshold=adverse_selection_adverse_threshold,
            quote_staleness_threshold=quote_staleness_threshold,
            skew_tolerance=skew_tolerance,
            skew_edge_premium=skew_edge_premium,
            skew_hard_limit=skew_hard_limit,
            max_skew_notional=max_skew_notional,
            max_concurrent_positions=max_concurrent_positions,
            twap_window_seconds=twap_window_seconds,
        )
        configs.append(cfg)
    return configs


def print_report(portfolio_result, configs, capital: float) -> None:
    print()
    print("=" * 80)
    print("PORTFOLIO BACKTEST REPORT")
    print("=" * 80)
    print(f"Markets analyzed: {len(portfolio_result.market_results)}")
    print(f"Total capital:    ${capital:,.0f}")
    print()

    print(f"{'Market ID':<20} {'Fills':>6} {'Cycles':>7} {'Win%':>6} {'PnL $':>8} "
          f"{'HedgeAcc':>9} {'AS Rate':>7} {'FV-Skip%':>9}")
    print("-" * 90)

    for cfg in configs:
        mid = cfg.market_id
        r = portfolio_result.market_results.get(mid)
        if r is None:
            continue
        win_pct = r.win_rate() * 100
        hedge_pct = r.hedge_accessibility() * 100
        as_rate_pct = getattr(r, "as_rate", 0.0) * 100
        pnl = r.total_pnl()
        fv_none = getattr(r, "num_fv_none_skips", 0)
        total_checks = r.hedge_checks_total + fv_none
        fv_skip_pct = 100.0 * fv_none / total_checks if total_checks > 0 else 0.0
        print(f"{mid[:20]:<20} {r.num_fills:>6} {r.num_cycles_completed:>7} "
              f"{win_pct:>5.1f}% {pnl:>8.2f} {hedge_pct:>8.1f}% {as_rate_pct:>6.1f}%"
              f" {fv_skip_pct:>8.1f}%")

    print("-" * 90)
    print()

    r = portfolio_result
    print(f"AGGREGATE SUMMARY")
    print(f"  Total fills:           {r.total_fills}")
    print(f"  Total cycles:          {r.total_cycles}")
    print(f"  Total profitable:      {r.total_profitable_cycles}")
    print(f"  Overall win rate:      {r.overall_win_rate * 100:.1f}%")
    print(f"  Total PnL:             ${r.total_pnl:,.2f}")
    print(f"  Est. peak capital at risk: ${r.estimated_peak_capital_at_risk:,.0f} "
          f"({r.capital_utilization_pct * 100:.1f}% of capital)")

    if r.runway_days == float("inf"):
        runway_str = "infinite (strategy is profitable)"
    else:
        runway_str = f"{r.runway_days:.0f} days"
    print(f"  Runway:                {runway_str}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Portfolio backtest analysis")
    parser.add_argument("--data", default="data/raw", help="Directory with JSONL market data")
    parser.add_argument("--capital", type=float, default=50000.0, help="Total capital ($)")
    parser.add_argument("--quote-size", type=float, default=100.0, help="Quote size per fill")
    parser.add_argument("--half-spread", type=float, default=0.015, help="Half-spread base")
    parser.add_argument("--time-to-resolution", type=float, default=2160.0,
                        help="Hours to resolution (default 2160 = 90 days)")
    parser.add_argument("--as-window", type=float, default=300.0,
                        help="Adverse selection measurement window (seconds)")
    parser.add_argument("--as-threshold", type=float, default=0.005,
                        help="Adverse selection classification threshold (default 0.005 = 0.5 cents)")
    parser.add_argument("--staleness-threshold", type=float, default=0.0,
                        help="Quote staleness threshold (0 = disabled; e.g. 0.01)")
    parser.add_argument("--skew-tolerance", type=float, default=0.0,
                        help="Max unhedgeable contracts to accept as skew inventory (0 = disabled)")
    parser.add_argument("--skew-edge-premium", type=float, default=0.005,
                        help="Extra edge required on skew quotes above min_edge_floor (default 0.005)")
    parser.add_argument("--max-concurrent", type=int, default=1,
                        help="Max concurrent iceberg slices per market (default 1 = no iceberg)")
    parser.add_argument("--twap-window", type=int, default=3600,
                        help="FV TWAP window in seconds (default 3600 = 1h; increase for sparse markets)")
    args = parser.parse_args()

    data_dir = Path(args.data)
    if not data_dir.exists():
        print(f"ERROR: data directory {data_dir} not found", file=sys.stderr)
        sys.exit(1)

    configs = load_market_configs(
        data_dir=data_dir,
        quote_size=args.quote_size,
        half_spread_base=args.half_spread,
        time_to_resolution_hours=args.time_to_resolution,
        adverse_selection_window_seconds=args.as_window,
        adverse_selection_adverse_threshold=args.as_threshold,
        quote_staleness_threshold=args.staleness_threshold,
        skew_tolerance=args.skew_tolerance,
        skew_edge_premium=args.skew_edge_premium,
        max_concurrent_positions=args.max_concurrent,
        twap_window_seconds=args.twap_window,
    )

    if not configs:
        print(f"No .jsonl files found in {data_dir}")
        sys.exit(0)

    print(f"Found {len(configs)} markets in {data_dir}")
    print("Running backtest...")

    portfolio_cfg = PortfolioConfig(total_capital=args.capital)
    ps = PortfolioSimulator(configs, portfolio_cfg)
    result = ps.run()

    print_report(result, configs, args.capital)


if __name__ == "__main__":
    main()
