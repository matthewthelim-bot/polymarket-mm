import json
import pytest
from pathlib import Path
from src.backtest.sweep import SweepRunner, SweepConfig, SweepResult


@pytest.fixture
def data_dir(tmp_path) -> Path:
    market = "sweep-001"
    events = [
        {"event_type":"trade","market_id":market,"fill_id":"s","timestamp":"2026-01-01T12:00:00Z",
         "side":"buy","price":0.50,"size":500,"is_maker":False},
        {"event_type":"book","market_id":market,"timestamp":"2026-01-01T12:00:01Z",
         "bids":[{"price":0.44,"size":500}],"asks":[{"price":0.52,"size":500}]},
        {"event_type":"trade","market_id":market,"fill_id":"e","timestamp":"2026-01-01T12:00:02Z",
         "side":"sell","price":0.44,"size":100,"is_maker":False},
        {"event_type":"book","market_id":market,"timestamp":"2026-01-01T12:00:03Z",
         "bids":[{"price":0.44,"size":400}],"asks":[{"price":0.52,"size":500}]},
        {"event_type":"trade","market_id":market,"fill_id":"f","timestamp":"2026-01-01T12:00:04Z",
         "side":"buy","price":0.52,"size":200,"is_maker":False},
    ]
    with (tmp_path / f"{market}.jsonl").open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return tmp_path


def test_sweep_runs_n_trials(data_dir):
    config = SweepConfig(
        market_id="sweep-001",
        data_dir=str(data_dir),
        fee_rate=0.04,
        rebate_fraction=0.20,
        n_trials=8,
        param_ranges={
            "half_spread_base": (0.010, 0.030),
            "min_edge_floor": (0.003, 0.010),
        },
    )
    runner = SweepRunner(config)
    results = runner.run()
    assert len(results) == 8


def test_sweep_results_have_required_fields(data_dir):
    config = SweepConfig(
        market_id="sweep-001",
        data_dir=str(data_dir),
        fee_rate=0.04,
        rebate_fraction=0.20,
        n_trials=4,
        param_ranges={"half_spread_base": (0.010, 0.030)},
    )
    results = SweepRunner(config).run()
    for r in results:
        assert hasattr(r, "params")
        assert hasattr(r, "total_pnl")
        assert hasattr(r, "num_fills")
        assert "half_spread_base" in r.params


def test_sweep_saves_csv(data_dir, tmp_path):
    out_csv = tmp_path / "sweep_results.csv"
    config = SweepConfig(
        market_id="sweep-001",
        data_dir=str(data_dir),
        fee_rate=0.04,
        rebate_fraction=0.20,
        n_trials=4,
        param_ranges={"half_spread_base": (0.010, 0.030)},
        output_csv=str(out_csv),
    )
    SweepRunner(config).run()
    assert out_csv.exists()
    lines = out_csv.read_text().splitlines()
    assert len(lines) == 5  # header + 4 rows
