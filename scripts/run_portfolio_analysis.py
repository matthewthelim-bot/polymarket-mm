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
    quote_staleness_threshold: float,
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
            quote_staleness_threshold=quote_staleness_threshold,
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
          f"{'HedgeAcc':>9} {'AS Rate':>7}")
    print("-" * 80)

    for cfg in configs:
        mid = cfg.market_id
        r = portfolio_result.market_results.get(mid)
        if r is None:
            continue
        win_pct = r.win_rate() * 100
        hedge_pct = r.hedge_accessibility() * 100
        as_rate_pct = getattr(r, "as_rate", 0.0) * 100
        pnl = r.total_pnl()
        print(f"{mid[:20]:<20} {r.num_fills:>6} {r.num_cycles_completed:>7} "
              f"{win_pct:>5.1f}% {pnl:>8.2f} {hedge_pct:>8.1f}% {as_rate_pct:>6.1f}%")

    print("-" * 80)
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
    parser.add_argument("--staleness-threshold", type=float, default=0.0,
                        help="Quote staleness threshold (0 = disabled; e.g. 0.01)")
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
        quote_staleness_threshold=args.staleness_threshold,
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
