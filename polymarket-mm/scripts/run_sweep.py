#!/usr/bin/env python3
"""
Run a Sobol parameter sweep over a single market.

Usage:
    python scripts/run_sweep.py --market test-001 --data data/raw/ \
        --n-trials 64 --out results/sweep.csv

Sweeps: half_spread_base [0.010, 0.030], min_edge_floor [0.003, 0.010]
"""

import argparse
from src.backtest.sweep import SweepRunner, SweepConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True)
    parser.add_argument("--data", default="data/raw")
    parser.add_argument("--fee-rate", type=float, default=0.04)
    parser.add_argument("--rebate", type=float, default=0.20)
    parser.add_argument("--n-trials", type=int, default=64)
    parser.add_argument("--out", default="results/sweep.csv")
    args = parser.parse_args()

    config = SweepConfig(
        market_id=args.market,
        data_dir=args.data,
        fee_rate=args.fee_rate,
        rebate_fraction=args.rebate,
        n_trials=args.n_trials,
        param_ranges={
            "half_spread_base": (0.010, 0.030),
            "min_edge_floor": (0.003, 0.010),
            "adverse_selection_threshold": (0.008, 0.020),
        },
        output_csv=args.out,
    )

    import os; os.makedirs("results", exist_ok=True)
    print(f"Running {args.n_trials}-trial Sobol sweep on {args.market}...")
    results = SweepRunner(config).run()

    best = max(results, key=lambda r: r.total_pnl)
    print(f"\nBest params: {best.params}")
    print(f"Best PnL:    ${best.total_pnl:.4f}")
    print(f"Results saved to: {args.out}")


if __name__ == "__main__":
    main()
