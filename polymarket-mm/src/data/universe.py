"""
MarketUniverse — scored market registry persisted to data/universe.json.

ScoredMarket holds all scoring signals for one market.
MarketUniverse manages the full collection with load/save/update/query.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ScoredMarket:
    condition_id: str
    slug: str
    question: str
    yes_token: str
    no_token: str
    score: float
    volatility_std: float
    volume_24h: float
    max_quotable: float
    trades_per_day: float
    end_date: str
    days_to_resolution: float
    status: str          # "active" | "expired" | "below_threshold"
    last_scored_at: str  # ISO timestamp
    ingested: bool


class MarketUniverse:
    """Registry of all scored markets. Thread-safe for reads; callers must
    synchronise writes if using across threads."""

    def __init__(self) -> None:
        self._markets: dict[str, ScoredMarket] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: Path) -> None:
        """Load from universe.json. Silently no-ops if the file does not exist."""
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for raw in data.get("markets", []):
            m = ScoredMarket(**{k: raw[k] for k in ScoredMarket.__dataclass_fields__ if k in raw})
            self._markets[m.condition_id] = m

    def save(self, path: Path) -> None:
        """Atomically write universe.json."""
        markets_list = [asdict(m) for m in self._markets.values()]
        active_count = sum(1 for m in self._markets.values() if m.status == "active")
        payload = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_scored": len(self._markets),
            "active_count": active_count,
            "markets": markets_list,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update(self, market: ScoredMarket) -> None:
        """Insert or replace a market by condition_id."""
        self._markets[market.condition_id] = market

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def active_markets(self) -> list[ScoredMarket]:
        return [m for m in self._markets.values() if m.status == "active"]

    def markets_needing_ingest(self) -> list[ScoredMarket]:
        return [m for m in self._markets.values()
                if m.status == "active" and not m.ingested]

    def get(self, condition_id: str) -> Optional[ScoredMarket]:
        return self._markets.get(condition_id)

    def all_markets(self) -> list[ScoredMarket]:
        return list(self._markets.values())
