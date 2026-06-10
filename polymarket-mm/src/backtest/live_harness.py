"""Shared harness for backtests that replay data/live collector recordings.

Used by scripts/run_live_backtest.py and scripts/run_sensitivity.py — keeps
the event loader, market-eligibility filter, adaptive sizing, ladder
parameters, and simulator factory in one place so the analysis scripts can't
drift apart.

The constants here mirror live QuoteLoopConfig defaults; change them together
or the backtest stops modelling what production will do.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from src.data.schemas import OrderBook, PriceLevel, Fill, Side, MarketMetadata
from src.fee_model import FeeModel
from src.strategy.fair_value import FairValueEstimator
from src.strategy.regime import RegimeClassifier
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig
from src.strategy.quote_engine import QuoteEngine
from src.strategy.inventory import InventoryManager
from src.pnl import PnLEngine
from src.backtest.fill_model import FillModel, FillModelConfig, QueueModel
from src.backtest.simulator import BacktestSimulator, SimulatorConfig

# ---------------------------------------------------------------------------
# Strategy parameters (mirror live QuoteLoopConfig)
# ---------------------------------------------------------------------------
FEE_RATE    = 0.07
REBATE_FRAC = 0.50
QUOTE_SIZE  = 100.0   # fallback when a market has no observed trades
LATENCY_MS  = 50

# Ladder: levels anchored to best bid/ask, ascending size going deeper.
LADDER_LEVELS       = 5
LADDER_OFFSET       = 0.030   # L0 sits this far below best bid / above best ask
LADDER_TICK         = 0.010   # each successive level goes one tick deeper
LADDER_SIZE_RATIOS  = [1.0, 1.5, 2.0, 2.5, 3.0]

PRICE_TOLERANCE      = 0.010  # min best-bid drift before repricing ladder anchor
ICEBERG_DISPLAY_SIZE = 0.0    # 0 = off; >0 only for sensitivity analysis


# ---------------------------------------------------------------------------
# Event loading
# ---------------------------------------------------------------------------

def parse_ts(ts_str: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


def load_market_events(files: Iterable[Path]) -> list:
    """Merge events from multiple date-partitioned JSONL files, sorted by time.

    Deduplicates trades by fill_id (overlapping collector sessions wrote some
    events twice).
    """
    events = []
    seen_fill_ids: set[str] = set()
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = raw.get("event_type")
            ts = parse_ts(raw.get("timestamp", ""))
            if ts is None:
                continue
            if et == "book":
                bids = [PriceLevel(float(b["price"]), float(b["size"]))
                        for b in raw.get("bids", [])]
                asks = [PriceLevel(float(a["price"]), float(a["size"]))
                        for a in raw.get("asks", [])]
                events.append((ts, OrderBook(
                    market_id=raw.get("market_id", ""),
                    timestamp=ts,
                    bids=bids,
                    asks=asks,
                    token_side=raw.get("token_side", ""),
                )))
            elif et == "trade":
                fid = raw.get("fill_id", "")
                if fid and fid in seen_fill_ids:
                    continue
                if fid:
                    seen_fill_ids.add(fid)
                raw_side = raw.get("side", "")
                upper = raw_side.upper()
                token_side = upper if upper in ("YES", "NO") else ""
                side = Side.BUY if raw_side.lower() == "buy" else Side.SELL
                try:
                    events.append((ts, Fill(
                        fill_id=fid,
                        market_id=raw.get("market_id", ""),
                        side=side,
                        price=float(raw["price"]),
                        size=float(raw["size"]),
                        timestamp=ts,
                        is_maker=bool(raw.get("is_maker", False)),
                        token_side=token_side,
                    )))
                except (KeyError, ValueError):
                    pass
    events.sort(key=lambda x: x[0])
    return [e for _, e in events]


def is_dual_book(files: Iterable[Path]) -> bool:
    """True iff the files contain YES and NO book snapshots plus >=1 trade.

    The dual-book simulator can only run markets where both legs were
    recorded.
    """
    has_yes = has_no = has_trade = False
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                ev = json.loads(line.strip())
                ts = ev.get("token_side", "")
                et = ev.get("event_type", "")
                if et == "book" and ts == "YES":
                    has_yes = True
                if et == "book" and ts == "NO":
                    has_no = True
                if et == "trade":
                    has_trade = True
            except Exception:
                pass
        if has_yes and has_no and has_trade:
            break
    return has_yes and has_no and has_trade


# ---------------------------------------------------------------------------
# Adaptive sizing
# ---------------------------------------------------------------------------

def compute_avg_trade_size(events) -> float:
    """Mean observed trade size; falls back to QUOTE_SIZE if no trades."""
    sizes = [e.size for e in events if isinstance(e, Fill) and e.size > 0]
    return statistics.mean(sizes) if sizes else QUOTE_SIZE


def adaptive_quote_size(avg_trade_size: float) -> float:
    """Base ladder quote size from a market's average trade size.

    With ratios [1.0, 1.5, 2.0, 2.5, 3.0] and base = avg/2, the middle level
    (L2) matches a typical full trade. Clamped to [5, 500] contracts.
    """
    return max(5.0, min(500.0, round(avg_trade_size / 2)))


# ---------------------------------------------------------------------------
# Simulator factory
# ---------------------------------------------------------------------------

def make_simulator(market_id: str, days_to_resolution: int = 9999,
                   event_key: str = "", portfolio=None,
                   quote_size: Optional[float] = None,
                   iceberg_display_size: float = ICEBERG_DISPLAY_SIZE,
                   ) -> BacktestSimulator:
    """Build a dual-book BacktestSimulator with the standard live parameters."""
    fm = FeeModel()
    meta = MarketMetadata(
        condition_id=market_id, token_id_yes=market_id, token_id_no=market_id,
        category="unknown", fee_rate=FEE_RATE, fee_exponent=1,
        rebate_fraction=REBATE_FRAC, sports=False,
    )
    skew = SkewConfig(
        skew_tolerance=0.0, skew_edge_premium=0.005,
        skew_hard_limit=0, skew_capital_charge_multiplier=3.0,
        max_skew_notional=0.0, current_skew_notional=0.0,
    )
    return BacktestSimulator(
        metadata=meta, fee_model=fm,
        fv_estimator=FairValueEstimator(twap_window_seconds=3600, external_weight=0.0),
        regime_classifier=RegimeClassifier(),
        hedgeability_assessor=HedgeabilityAssessor(fm, FEE_RATE, REBATE_FRAC, 0.005),
        quote_engine=QuoteEngine(fm, FEE_RATE, REBATE_FRAC, LADDER_OFFSET, 0.005),
        inventory_manager=InventoryManager(market_id, 0.0003),
        pnl_engine=PnLEngine(fm, FEE_RATE, REBATE_FRAC),
        fill_model=FillModel(FillModelConfig(queue_model=QueueModel.FRONT,
                                             latency_ms=LATENCY_MS)),
        skew_config=skew,
        config=SimulatorConfig(
            start_capital=50000.0,
            quote_size=quote_size if quote_size is not None else QUOTE_SIZE,
            time_to_resolution_hours=720.0,
            ladder_levels=LADDER_LEVELS,
            ladder_offset_from_best=LADDER_OFFSET,
            ladder_tick_spacing=LADDER_TICK,
            ladder_size_ratios=LADDER_SIZE_RATIOS,
            price_tolerance=PRICE_TOLERANCE,
            iceberg_display_size=iceberg_display_size,
            days_to_resolution=days_to_resolution,
            event_key=event_key,
            market_id=market_id,
        ),
        portfolio=portfolio,
    )
