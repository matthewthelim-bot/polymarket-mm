import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from src.data.loader import HistoricalDataLoader, LoaderConfig
from src.data.schemas import OrderBook, Fill, Side


SAMPLE_BOOK_EVENT = {
    "event_type": "book",
    "market_id": "m1",
    "timestamp": "2026-01-01T12:00:00Z",
    "bids": [{"price": 0.45, "size": 100.0}, {"price": 0.44, "size": 50.0}],
    "asks": [{"price": 0.55, "size": 100.0}, {"price": 0.56, "size": 50.0}],
}

SAMPLE_TRADE_EVENT = {
    "event_type": "trade",
    "market_id": "m1",
    "fill_id": "fill-001",
    "timestamp": "2026-01-01T12:00:05Z",
    "side": "buy",
    "price": 0.55,
    "size": 10.0,
    "is_maker": False,
}


@pytest.fixture
def data_file(tmp_path) -> Path:
    p = tmp_path / "m1.jsonl"
    with p.open("w") as f:
        f.write(json.dumps(SAMPLE_BOOK_EVENT) + "\n")
        f.write(json.dumps(SAMPLE_TRADE_EVENT) + "\n")
    return p


def test_loader_yields_order_book(data_file):
    loader = HistoricalDataLoader(LoaderConfig(data_dir=str(data_file.parent)))
    events = list(loader.load_market("m1"))
    books = [e for e in events if isinstance(e, OrderBook)]
    assert len(books) == 1
    assert books[0].best_bid() == pytest.approx(0.45)
    assert books[0].best_ask() == pytest.approx(0.55)


def test_loader_yields_fills(data_file):
    loader = HistoricalDataLoader(LoaderConfig(data_dir=str(data_file.parent)))
    events = list(loader.load_market("m1"))
    fills = [e for e in events if isinstance(e, Fill)]
    assert len(fills) == 1
    assert fills[0].price == pytest.approx(0.55)
    assert fills[0].side == Side.BUY


def test_events_sorted_by_timestamp(data_file):
    loader = HistoricalDataLoader(LoaderConfig(data_dir=str(data_file.parent)))
    events = list(loader.load_market("m1"))
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps)


def test_loader_skips_unknown_event_types(tmp_path):
    p = tmp_path / "m1.jsonl"
    with p.open("w") as f:
        f.write(json.dumps({"event_type": "unknown", "market_id": "m1"}) + "\n")
        f.write(json.dumps(SAMPLE_BOOK_EVENT) + "\n")
    loader = HistoricalDataLoader(LoaderConfig(data_dir=str(tmp_path)))
    events = list(loader.load_market("m1"))
    assert len(events) == 1  # only the book event


def test_loader_raises_on_missing_file(tmp_path):
    loader = HistoricalDataLoader(LoaderConfig(data_dir=str(tmp_path)))
    with pytest.raises(FileNotFoundError):
        list(loader.load_market("nonexistent-market"))
