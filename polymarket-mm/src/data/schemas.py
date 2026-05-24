"""
Shared dataclasses used across all components.

These are the sole data contracts between modules.
No component defines its own versions of these types.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


class Regime(Enum):
    QUOTE_ACTIVE = "quote_active"
    ONE_SIDE_FILLED = "one_side_filled"
    HEDGE_PENDING = "hedge_pending"
    INVENTORY_REDUCED = "inventory_reduced"
    INVENTORY_WAREHOUSE = "inventory_warehouse"
    SETTLED = "settled"
    SUSPENDED = "suspended"


@dataclass
class MarketMetadata:
    condition_id: str
    token_id_yes: str
    token_id_no: str
    category: str            # "crypto" | "politics" | "finance" | "sports"
    fee_rate: float          # fetched from getClobMarketInfo
    fee_exponent: int        # 1 for all current categories
    rebate_fraction: float   # ≈ 0.20; validate via API
    sports: bool             # True → use sports fee formula


@dataclass
class PriceLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    market_id: str
    timestamp: datetime
    bids: list[PriceLevel]   # sorted descending by price
    asks: list[PriceLevel]   # sorted ascending by price
    token_side: str = ""     # "YES", "NO", or "" for legacy single-book data

    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    def mid(self) -> Optional[float]:
        bb = self.best_bid()
        ba = self.best_ask()
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2


@dataclass
class Fill:
    fill_id: str
    market_id: str
    side: Side
    price: float
    size: float
    timestamp: datetime
    is_maker: bool
    order_id: str = ""
    token_side: str = ""   # "YES", "NO", or "" for legacy data

    def notional(self) -> float:
        return self.price * self.size


@dataclass
class InventoryState:
    market_id: str
    hedgeable_contracts: float   # contracts with opposing depth available
    skew_contracts: float        # contracts accepted as skew (no hedge available)
    avg_fill_price: float        # weighted average fill price across both buckets

    def total_contracts(self) -> float:
        return self.hedgeable_contracts + self.skew_contracts


@dataclass
class QuoteDecision:
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    regime: Regime
    suspend: bool
    reason: str = ""             # human-readable explanation for monitoring

    def spread(self) -> float:
        return self.ask_price - self.bid_price
