"""
HistoricalDataLoader — reads line-delimited JSON files produced by scripts/ingest_history.py.

Each line is one event:
  {"event_type": "book", "market_id": ..., "timestamp": ..., "bids": [...], "asks": [...]}
  {"event_type": "trade", "market_id": ..., "fill_id": ..., "timestamp": ..., ...}

Yields OrderBook and Fill objects sorted by timestamp.
"""

from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Union

logger = logging.getLogger(__name__)

from src.data.schemas import OrderBook, PriceLevel, Fill, Side


@dataclass
class LoaderConfig:
    data_dir: Union[str, Path]   # directory where market JSONL files are stored


Event = Union[OrderBook, Fill]


class HistoricalDataLoader:

    def __init__(self, config: LoaderConfig):
        self.data_dir = Path(config.data_dir)

    def load_market(self, market_id: str) -> Iterator[Event]:
        """
        Load all events for a market, sorted by timestamp.
        Raises FileNotFoundError if the market file doesn't exist.
        """
        path = self.data_dir / f"{market_id}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"No data file for market {market_id}: {path}")

        events: list[Event] = []
        seen_fill_ids: set[str] = set()   # deduplicate fills (CLOB returns BUY+SELL per trade)
        with path.open() as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    event = self._parse_event(raw)
                    if event is None:
                        continue
                    # Deduplicate Fill events — each historical trade may appear as both
                    # a BUY and a SELL record with the same fill_id.
                    if isinstance(event, Fill) and event.fill_id:
                        if event.fill_id in seen_fill_ids:
                            continue
                        seen_fill_ids.add(event.fill_id)
                    events.append(event)
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning("Skipping malformed event on line %d: %s", line_num, e)
                    continue

        events.sort(key=lambda e: e.timestamp)
        yield from events

    def _parse_event(self, raw: dict) -> Event | None:
        event_type = raw.get("event_type")
        if event_type == "book":
            return self._parse_book(raw)
        elif event_type == "trade":
            return self._parse_fill(raw)
        return None

    def _parse_book(self, raw: dict) -> OrderBook:
        return OrderBook(
            market_id=raw["market_id"],
            timestamp=self._parse_ts(raw["timestamp"]),
            bids=[PriceLevel(b["price"], b["size"]) for b in raw.get("bids", [])],
            asks=[PriceLevel(a["price"], a["size"]) for a in raw.get("asks", [])],
            token_side=raw.get("token_side", ""),
        )

    def _parse_fill(self, raw: dict) -> Fill:
        raw_side = raw.get("side", "")
        # Live data uses "YES"/"NO"; historical data uses "buy"/"sell"
        upper = raw_side.upper()
        token_side = upper if upper in ("YES", "NO") else ""
        side = Side.BUY if raw_side.lower() == "buy" else Side.SELL
        return Fill(
            fill_id=raw.get("fill_id", ""),
            market_id=raw["market_id"],
            side=side,
            price=float(raw["price"]),
            size=float(raw["size"]),
            timestamp=self._parse_ts(raw["timestamp"]),
            is_maker=bool(raw.get("is_maker", False)),
            token_side=token_side,
        )

    @staticmethod
    def _parse_ts(ts: object) -> datetime:
        """Parse an ISO-8601 string or numeric epoch timestamp (UTC).

        Numeric epochs appear in some ingest formats; an unsupported type
        raises ValueError so load_market's malformed-line handler skips the
        line instead of crashing the whole backtest.
        """
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        raise ValueError(f"Unsupported timestamp type: {type(ts).__name__}")
