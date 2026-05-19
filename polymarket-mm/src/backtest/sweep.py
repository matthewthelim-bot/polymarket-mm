"""
Parameter sweep runner using Sobol quasi-random sampling.

Samples `n_trials` parameter combinations from `param_ranges` using
scipy.stats.qmc.Sobol for low-discrepancy coverage, then runs a
BacktestRunner for each and collects results.
"""

from __future__ import annotations
import csv
from dataclasses import dataclass, field
from typing import Optional

from scipy.stats.qmc import Sobol
import numpy as np

from src.backtest.runner import BacktestRunner, RunConfig


@dataclass
class SweepConfig:
    market_id: str
    data_dir: str
    fee_rate: float
    rebate_fraction: float
    n_trials: int = 64
    param_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    output_csv: Optional[str] = None
    # Fixed params passed through to all runs
    sports: bool = False
    fee_exponent: int = 1
    start_capital: float = 50000.0
    quote_size: float = 100.0
    queue_model: str = "FRONT"
    latency_ms: int = 50
    time_to_resolution_hours: float = 48.0


@dataclass
class SweepResult:
    params: dict
    total_pnl: float
    total_spread_pnl: float
    total_skew_pnl: float
    num_fills: int
    num_cycles_completed: int
    total_fees_paid: float
    total_rebates_received: float


class SweepRunner:

    def __init__(self, config: SweepConfig):
        self.config = config

    def run(self) -> list[SweepResult]:
        cfg = self.config
        param_names = list(cfg.param_ranges.keys())
        n_dims = max(len(param_names), 1)

        # Sobol requires n_dims >= 1 and n_trials to be a power of 2 for best coverage
        # We use scramble=True for robustness with non-power-of-2 counts
        sampler = Sobol(d=n_dims, scramble=True, seed=42)
        unit_samples = sampler.random(cfg.n_trials)  # shape: (n_trials, n_dims)

        results = []
        for i in range(cfg.n_trials):
            params = {}
            for j, name in enumerate(param_names):
                lo, hi = cfg.param_ranges[name]
                params[name] = lo + unit_samples[i, j] * (hi - lo)

            run_config = self._make_run_config(params)
            sim_result = BacktestRunner(run_config).run()

            results.append(SweepResult(
                params=params,
                total_pnl=sim_result.total_pnl(),
                total_spread_pnl=sim_result.total_spread_pnl,
                total_skew_pnl=sim_result.total_skew_pnl,
                num_fills=sim_result.num_fills,
                num_cycles_completed=sim_result.num_cycles_completed,
                total_fees_paid=sim_result.total_fees_paid,
                total_rebates_received=sim_result.total_rebates_received,
            ))

        if cfg.output_csv:
            self._write_csv(results, cfg.output_csv, param_names)

        return results

    def _make_run_config(self, params: dict) -> RunConfig:
        cfg = self.config
        return RunConfig(
            market_id=cfg.market_id,
            data_dir=cfg.data_dir,
            fee_rate=cfg.fee_rate,
            fee_exponent=cfg.fee_exponent,
            rebate_fraction=cfg.rebate_fraction,
            sports=cfg.sports,
            start_capital=cfg.start_capital,
            quote_size=cfg.quote_size,
            queue_model=cfg.queue_model,
            latency_ms=cfg.latency_ms,
            time_to_resolution_hours=cfg.time_to_resolution_hours,
            half_spread_base=params.get("half_spread_base", 0.015),
            min_edge_floor=params.get("min_edge_floor", 0.005),
            adverse_selection_threshold=params.get("adverse_selection_threshold", 0.012),
            skew_tolerance=params.get("skew_tolerance", 0.0),
            skew_hard_limit=0,
            max_skew_notional=0.0,
        )

    @staticmethod
    def _write_csv(results: list[SweepResult], path: str, param_names: list[str]):
        if not results:
            return
        with open(path, "w", newline="") as f:
            fieldnames = param_names + [
                "total_pnl", "total_spread_pnl", "total_skew_pnl",
                "num_fills", "num_cycles_completed",
                "total_fees_paid", "total_rebates_received",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                row = {**r.params,
                       "total_pnl": r.total_pnl,
                       "total_spread_pnl": r.total_spread_pnl,
                       "total_skew_pnl": r.total_skew_pnl,
                       "num_fills": r.num_fills,
                       "num_cycles_completed": r.num_cycles_completed,
                       "total_fees_paid": r.total_fees_paid,
                       "total_rebates_received": r.total_rebates_received}
                writer.writerow(row)
