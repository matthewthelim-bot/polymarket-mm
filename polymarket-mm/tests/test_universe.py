import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pytest
from src.data.universe import ScoredMarket, MarketUniverse


def make_market(condition_id="0xabc", status="active", ingested=False, score=100.0, std=0.06, days=5.0):
    return ScoredMarket(
        condition_id=condition_id,
        slug=f"slug-{condition_id}",
        question=f"Question {condition_id}?",
        yes_token="111",
        no_token="222",
        score=score,
        volatility_std=std,
        volume_24h=10000.0,
        max_quotable=50.0,
        trades_per_day=100.0,
        end_date="2026-12-01",
        days_to_resolution=days,
        status=status,
        last_scored_at="2026-05-21T00:00:00Z",
        ingested=ingested,
    )


def test_update_and_active_markets():
    u = MarketUniverse()
    u.update(make_market("0xaaa", status="active"))
    u.update(make_market("0xbbb", status="expired"))
    u.update(make_market("0xccc", status="below_threshold"))
    active = u.active_markets()
    assert len(active) == 1
    assert active[0].condition_id == "0xaaa"


def test_markets_needing_ingest():
    u = MarketUniverse()
    u.update(make_market("0xaaa", status="active", ingested=False))
    u.update(make_market("0xbbb", status="active", ingested=True))
    u.update(make_market("0xccc", status="expired", ingested=False))
    need = u.markets_needing_ingest()
    assert len(need) == 1
    assert need[0].condition_id == "0xaaa"


def test_update_replaces_existing():
    u = MarketUniverse()
    u.update(make_market("0xaaa", score=100.0))
    u.update(make_market("0xaaa", score=200.0))
    assert len(u.active_markets()) == 1
    assert u.active_markets()[0].score == 200.0


def test_save_and_load_roundtrip():
    u = MarketUniverse()
    u.update(make_market("0xaaa", status="active", ingested=True))
    u.update(make_market("0xbbb", status="expired"))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "universe.json"
        u.save(path)

        u2 = MarketUniverse()
        u2.load(path)

        assert len(u2.active_markets()) == 1
        assert u2.active_markets()[0].condition_id == "0xaaa"
        assert u2.active_markets()[0].ingested is True


def test_save_writes_metadata():
    u = MarketUniverse()
    u.update(make_market("0xaaa", status="active"))
    u.update(make_market("0xbbb", status="expired"))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "universe.json"
        u.save(path)
        data = json.loads(path.read_text())

    assert "last_updated" in data
    assert data["total_scored"] == 2
    assert data["active_count"] == 1
    assert len(data["markets"]) == 2


def test_load_empty_file_ok():
    u = MarketUniverse()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "missing.json"
        u.load(path)   # should not raise
    assert u.active_markets() == []
