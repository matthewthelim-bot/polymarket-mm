import json
import pytest
from pathlib import Path
from src.backtest.runner import BacktestRunner, RunConfig


@pytest.fixture
def data_dir(tmp_path) -> Path:
    # Minimal JSONL data: a few trades and books for market "test-001"
    market_id = "test-001"
    events = [
        {"event_type": "trade", "market_id": market_id, "fill_id": "t0",
         "timestamp": "2026-01-01T12:00:00Z", "side": "buy",
         "price": 0.50, "size": 200.0, "is_maker": False},
        {"event_type": "book", "market_id": market_id,
         "timestamp": "2026-01-01T12:00:01Z",
         "bids": [{"price": 0.44, "size": 500.0}],
         "asks": [{"price": 0.52, "size": 500.0}]},
        {"event_type": "trade", "market_id": market_id, "fill_id": "t1",
         "timestamp": "2026-01-01T12:00:02Z", "side": "sell",
         "price": 0.44, "size": 100.0, "is_maker": False},
        {"event_type": "book", "market_id": market_id,
         "timestamp": "2026-01-01T12:00:03Z",
         "bids": [{"price": 0.44, "size": 400.0}],
         "asks": [{"price": 0.52, "size": 500.0}]},
        {"event_type": "trade", "market_id": market_id, "fill_id": "t2",
         "timestamp": "2026-01-01T12:00:04Z", "side": "buy",
         "price": 0.52, "size": 100.0, "is_maker": False},
    ]
    p = tmp_path / f"{market_id}.jsonl"
    with p.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return tmp_path


@pytest.fixture
def run_config(data_dir) -> RunConfig:
    return RunConfig(
        market_id="test-001",
        data_dir=str(data_dir),
        fee_rate=0.04,
        fee_exponent=1,
        rebate_fraction=0.20,
        sports=False,
        start_capital=10000.0,
        quote_size=100.0,
        queue_model="FRONT",
        latency_ms=0,
        twap_window_seconds=300,
        external_weight=0.0,
        min_edge_floor=0.005,
        half_spread_base=0.015,
        max_inventory_contracts=500.0,
        adverse_selection_threshold=0.012,
        time_to_resolution_hours=48.0,
        skew_tolerance=0.0,
        skew_hard_limit=0,
        max_skew_notional=0.0,
    )


def test_runner_completes_without_error(run_config):
    runner = BacktestRunner(run_config)
    result = runner.run()
    assert result is not None


def test_runner_result_has_pnl_fields(run_config):
    runner = BacktestRunner(run_config)
    result = runner.run()
    assert hasattr(result, "total_spread_pnl")
    assert hasattr(result, "total_skew_pnl")
    assert hasattr(result, "num_fills")


def test_runner_num_book_updates_positive(run_config):
    runner = BacktestRunner(run_config)
    result = runner.run()
    assert result.num_book_updates >= 1


def test_runner_rejects_invalid_queue_model(data_dir):
    cfg = RunConfig(
        market_id="test-001",
        data_dir=str(data_dir),
        fee_rate=0.04,
        fee_exponent=1,
        rebate_fraction=0.20,
        sports=False,
        queue_model="INVALID",
    )
    with pytest.raises(ValueError):
        BacktestRunner(cfg).run()
