"""
PortfolioSimulator — runs multiple markets against a shared capital pool.

Runs each market independently using BacktestRunner, then aggregates results.

Capital constraint note: this is an *optimistic* simulation — it does not
prevent trades when capital is exhausted. Instead, it estimates peak capital
at risk to flag when the constraint would bind. A future improvement would
merge event streams and gate entries on available capital.

Capital at risk per trade = fill_price * quote_size (e.g. 0.50 * 100 = $50).
"""

from __future__ import annotations
import sys
from dataclasses import dataclass, field

from src.backtest.runner import BacktestRunner, RunConfig
from src.backtest.simulator import SimulationResult


@dataclass
class PortfolioConfig:
    total_capital: float = 50000.0


@dataclass
class PortfolioResult:
    market_results: dict[str, SimulationResult] = field(default_factory=dict)
    total_pnl: float = 0.0
    total_fills: int = 0
    total_cycles: int = 0
    total_profitable_cycles: int = 0
    overall_win_rate: float = 0.0
    total_capital: float = 50000.0
    estimated_peak_capital_at_risk: float = 0.0  # optimistic estimate
    capital_utilization_pct: float = 0.0         # peak / total_capital
    runway_days: float = 0.0                      # capital / |daily_loss| when losing


class PortfolioSimulator:
    """
    Runs a list of markets independently and aggregates results.

    Args:
        run_configs: one RunConfig per market
        portfolio_config: capital pool settings
    """

    def __init__(self, run_configs: list[RunConfig], portfolio_config: PortfolioConfig):
        self.run_configs = run_configs
        self.portfolio_config = portfolio_config

    def run(self) -> PortfolioResult:
        result = PortfolioResult(total_capital=self.portfolio_config.total_capital)

        if not self.run_configs:
            return result

        for cfg in self.run_configs:
            try:
                mkt_result = BacktestRunner(cfg).run()
            except (FileNotFoundError, OSError) as exc:
                print(f"WARNING: skipping {cfg.market_id}: {exc}", file=sys.stderr)
                continue
            result.market_results[cfg.market_id] = mkt_result
            result.total_pnl += mkt_result.total_pnl()
            result.total_fills += mkt_result.num_fills
            result.total_cycles += mkt_result.num_cycles_completed
            result.total_profitable_cycles += mkt_result.num_profitable_cycles

        # Win rate
        if result.total_cycles > 0:
            result.overall_win_rate = result.total_profitable_cycles / result.total_cycles

        # Estimate peak capital at risk.
        # Each fill uses approximately fill_price * quote_size capital.
        # With hourly data, at most one position open per market at a time.
        # Conservative estimate: assume all markets had a position simultaneously.
        n_markets = len(self.run_configs)
        avg_quote_size = (
            sum(c.quote_size for c in self.run_configs) / n_markets
            if n_markets > 0 else 100.0
        )
        # Average fill price ~0.5 for near-50/50 markets; use 0.5 as conservative default
        avg_fill_price = 0.5
        result.estimated_peak_capital_at_risk = n_markets * avg_fill_price * avg_quote_size
        result.capital_utilization_pct = (
            result.estimated_peak_capital_at_risk / result.total_capital
            if result.total_capital > 0 else 0.0
        )

        # Runway: capital / |daily_loss_rate|
        # Collect all per-cycle PnL across all markets
        all_cycle_pnl: list[float] = []
        for mkt_result in result.market_results.values():
            all_cycle_pnl.extend(mkt_result.per_cycle_pnl)

        if all_cycle_pnl:
            avg_cycle_pnl = sum(all_cycle_pnl) / len(all_cycle_pnl)
            # Estimate cycles per day: assume ~1 cycle per market per 4h avg hold
            # With hourly data and n_markets, cycles_per_day ≈ n_markets * 6
            cycles_per_day_est = n_markets * 6
            daily_pnl_est = avg_cycle_pnl * cycles_per_day_est
            if daily_pnl_est >= 0:
                result.runway_days = float("inf")
            else:
                result.runway_days = result.total_capital / abs(daily_pnl_est)
        else:
            result.runway_days = float("inf")

        return result
