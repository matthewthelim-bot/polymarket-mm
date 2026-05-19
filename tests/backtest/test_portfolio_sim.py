"""Tests for PortfolioSimulator."""
import pytest
from unittest.mock import patch, MagicMock
from src.backtest.portfolio_sim import PortfolioSimulator, PortfolioConfig, PortfolioResult
from src.backtest.runner import RunConfig
from src.backtest.simulator import SimulationResult


def _make_run_config(market_id: str) -> RunConfig:
    return RunConfig(
        market_id=market_id,
        data_dir="data/raw",
        fee_rate=0.07,
        fee_exponent=1,
        rebate_fraction=0.5,
        sports=False,
    )


def _make_sim_result(fills=5, cycles=5, spread_pnl=10.0, profitable_cycles=4) -> SimulationResult:
    r = SimulationResult()
    r.num_fills = fills
    r.num_cycles_completed = cycles
    r.total_spread_pnl = spread_pnl
    r.num_profitable_cycles = profitable_cycles
    r.per_cycle_pnl = [2.0] * profitable_cycles + [-1.0] * (cycles - profitable_cycles)
    return r


class TestPortfolioSimulator:

    def test_empty_configs_returns_empty_result(self):
        ps = PortfolioSimulator([], PortfolioConfig(total_capital=50000.0))
        result = ps.run()
        assert isinstance(result, PortfolioResult)
        assert result.total_pnl == 0.0
        assert result.total_fills == 0
        assert result.total_cycles == 0
        assert result.overall_win_rate == 0.0
        assert len(result.market_results) == 0

    def test_single_market_aggregates_correctly(self):
        cfg = _make_run_config("mkt_a")
        ps = PortfolioSimulator([cfg], PortfolioConfig(total_capital=50000.0))

        sim_result = _make_sim_result(fills=10, cycles=8, spread_pnl=25.0, profitable_cycles=6)
        with patch("src.backtest.portfolio_sim.BacktestRunner") as MockRunner:
            MockRunner.return_value.run.return_value = sim_result
            result = ps.run()

        assert result.total_fills == 10
        assert result.total_cycles == 8
        assert abs(result.total_pnl - 25.0) < 1e-9
        assert abs(result.overall_win_rate - 6/8) < 1e-9
        assert "mkt_a" in result.market_results

    def test_two_markets_aggregate_pnl(self):
        cfgs = [_make_run_config("mkt_a"), _make_run_config("mkt_b")]
        ps = PortfolioSimulator(cfgs, PortfolioConfig(total_capital=50000.0))

        r_a = _make_sim_result(fills=5, cycles=5, spread_pnl=10.0, profitable_cycles=4)
        r_b = _make_sim_result(fills=3, cycles=3, spread_pnl=6.0, profitable_cycles=3)

        def side_effect(cfg):
            mock = MagicMock()
            if cfg.market_id == "mkt_a":
                mock.run.return_value = r_a
            else:
                mock.run.return_value = r_b
            return mock

        with patch("src.backtest.portfolio_sim.BacktestRunner", side_effect=side_effect):
            result = ps.run()

        assert result.total_fills == 8
        assert result.total_cycles == 8
        assert abs(result.total_pnl - 16.0) < 1e-9
        assert abs(result.overall_win_rate - 7/8) < 1e-9

    def test_result_has_capital_fields(self):
        ps = PortfolioSimulator([], PortfolioConfig(total_capital=50000.0))
        result = ps.run()
        assert hasattr(result, "total_capital")
        assert hasattr(result, "estimated_peak_capital_at_risk")
        assert hasattr(result, "runway_days")

    def test_runway_positive_pnl_returns_inf(self):
        """With positive total PnL, runway is effectively infinite."""
        cfg = _make_run_config("mkt_a")
        ps = PortfolioSimulator([cfg], PortfolioConfig(total_capital=50000.0))
        r = _make_sim_result(fills=5, cycles=5, spread_pnl=100.0, profitable_cycles=5)
        r.per_cycle_pnl = [20.0] * 5  # all profitable
        with patch("src.backtest.portfolio_sim.BacktestRunner") as MockRunner:
            MockRunner.return_value.run.return_value = r
            result = ps.run()
        assert result.runway_days == float("inf")

    def test_runway_losing_strategy(self):
        """With negative total PnL, runway = capital / |daily_loss|."""
        cfg = _make_run_config("mkt_a")
        ps = PortfolioSimulator([cfg], PortfolioConfig(total_capital=50000.0))
        # All cycles lose $2
        r = SimulationResult()
        r.num_fills = 6
        r.num_cycles_completed = 6
        r.total_spread_pnl = -12.0
        r.num_profitable_cycles = 0
        r.per_cycle_pnl = [-2.0] * 6
        with patch("src.backtest.portfolio_sim.BacktestRunner") as MockRunner:
            MockRunner.return_value.run.return_value = r
            result = ps.run()
        # 1 market, 6 cycles per day estimate, avg_cycle = -2 -> daily_loss = -12
        # runway = 50000 / 12 = ~4166 days
        assert result.runway_days > 0
        assert result.runway_days < float("inf")
        assert abs(result.runway_days - 50000.0 / 12.0) < 1.0

    def test_capital_utilization_calculation(self):
        """Peak capital at risk = n_markets * 0.5 * quote_size."""
        cfgs = [_make_run_config("a"), _make_run_config("b")]
        # Both have default quote_size=100
        ps = PortfolioSimulator(cfgs, PortfolioConfig(total_capital=50000.0))

        r = SimulationResult()
        with patch("src.backtest.portfolio_sim.BacktestRunner") as MockRunner:
            MockRunner.return_value.run.return_value = r
            result = ps.run()

        # 2 markets * 0.5 * 100 = $100 peak capital at risk
        assert abs(result.estimated_peak_capital_at_risk - 100.0) < 1e-9
        # utilization = 100 / 50000 = 0.2%
        assert abs(result.capital_utilization_pct - 0.002) < 1e-9
