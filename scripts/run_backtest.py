#!/usr/bin/env python3
"""
Run a single-market backtest from the command line.

Usage:
    python scripts/run_backtest.py --market test-001 --data data/raw/ \
        --fee-rate 0.04 --rebate 0.20 --capital 50000

Output: summary table printed to stdout.
"""

import argparse
from src.backtest.runner import BacktestRunner, RunConfig


def main():
    parser = argparse.ArgumentParser(description="Run Polymarket MM backtest")
    parser.add_argument("--market", required=True, help="Market ID")
    parser.add_argument("--data", default="data/raw", help="Data directory")
    parser.add_argument("--fee-rate", type=float, default=0.04, help="Fee rate")
    parser.add_argument("--rebate", type=float, default=0.20, help="Rebate fraction")
    parser.add_argument("--capital", type=float, default=50000.0, help="Starting capital")
    parser.add_argument("--quote-size", type=float, default=100.0, help="Quote size")
    parser.add_argument("--queue-model", default="FRONT", choices=["FRONT", "PRO_RATA", "BACK"],
                        help="Fill queue model")
    parser.add_argument("--sports", action="store_true", help="Use sports fee formula")
    args = parser.parse_args()

    config = RunConfig(
        market_id=args.market,
        data_dir=args.data,
        fee_rate=args.fee_rate,
        fee_exponent=1,
        rebate_fraction=args.rebate,
        sports=args.sports,
        start_capital=args.capital,
        quote_size=args.quote_size,
        queue_model=args.queue_model,
    )

    print(f"\nRunning backtest: market={args.market}, queue={args.queue_model}")
    result = BacktestRunner(config).run()

    print("\n=== BACKTEST RESULTS ===")
    print(f"  Spread PnL:        ${result.total_spread_pnl:>10.4f}")
    print(f"  Skew PnL:          ${result.total_skew_pnl:>10.4f}")
    print(f"  Total PnL:         ${result.total_pnl():>10.4f}")
    print(f"  Fees paid:         ${result.total_fees_paid:>10.4f}")
    print(f"  Rebates received:  ${result.total_rebates_received:>10.4f}")
    print(f"  Fills:             {result.num_fills}")
    print(f"  Cycles completed:  {result.num_cycles_completed}")
    print(f"  Book updates:      {result.num_book_updates}")
    print()


if __name__ == "__main__":
    main()
