"""
PnLEngine — realized PnL with two-bucket spread/skew attribution.

All PnL is computed on completed inventory cycles and settled markets.
Mark-to-mid is never used.

Two attribution buckets:
  spread_pnl — PnL from hedged (risk-free) cycles
  skew_pnl   — PnL from unhedged skew cycles (directional exposure)
"""

from __future__ import annotations
from dataclasses import dataclass
from src.fee_model import FeeModel


@dataclass
class CompletedCycle:
    market_id: str
    entry_price: float      # passive fill price (maker)
    entry_size: float       # contracts
    flatten_price: float    # taker flatten price
    flatten_size: float     # contracts flattened (may be < entry_size if partial)
    is_skew: bool           # True → attribute to skew_pnl


@dataclass
class CycleResult:
    spread_pnl: float
    skew_pnl: float
    taker_fee_paid: float
    maker_rebate_received: float

    def total_pnl(self) -> float:
        return self.spread_pnl + self.skew_pnl


class PnLEngine:
    """
    Args:
        fee_model: shared FeeModel instance
        fee_rate: market fee_rate
        rebate_fraction: market rebate_fraction
    """

    def __init__(self, fee_model: FeeModel, fee_rate: float, rebate_fraction: float):
        self.fee_model = fee_model
        self.fee_rate = fee_rate
        self.rebate_fraction = rebate_fraction

    def compute_cycle(self, cycle: CompletedCycle) -> CycleResult:
        """
        Compute realized PnL for one completed entry→flatten cycle.

        Gross cycle PnL = (1 - entry_price - flatten_price) * flatten_size
          (risk-free arb: buy Yes at p_yes, buy No at p_no, payout = 1 - p_yes - p_no)

        Net = gross - taker_fee(flatten) + maker_rebate(entry)
        """
        gross = (1.0 - cycle.entry_price - cycle.flatten_price) * cycle.flatten_size

        taker_fee = self.fee_model.taker_fee(
            size=cycle.flatten_size,
            price=cycle.flatten_price,
            fee_rate=self.fee_rate,
        )
        maker_rebate = self.fee_model.maker_rebate(
            size=cycle.entry_size,
            price=cycle.entry_price,
            fee_rate=self.fee_rate,
            rebate_fraction=self.rebate_fraction,
        )

        net = gross - taker_fee + maker_rebate

        if cycle.is_skew:
            return CycleResult(
                spread_pnl=0.0,
                skew_pnl=net,
                taker_fee_paid=taker_fee,
                maker_rebate_received=maker_rebate,
            )
        return CycleResult(
            spread_pnl=net,
            skew_pnl=0.0,
            taker_fee_paid=taker_fee,
            maker_rebate_received=maker_rebate,
        )

    def compute_settlement(
        self,
        avg_fill_price: float,
        contracts: float,
        resolution: float,   # 1.0 = Yes resolved, 0.0 = No resolved
        is_skew: bool,
    ) -> CycleResult:
        """
        Compute PnL when a market settles with unsold inventory.
        No fees on settlement (on-chain redemption, no taker fee).
        """
        net = (resolution - avg_fill_price) * contracts
        if is_skew:
            return CycleResult(spread_pnl=0.0, skew_pnl=net, taker_fee_paid=0.0, maker_rebate_received=0.0)
        return CycleResult(spread_pnl=net, skew_pnl=0.0, taker_fee_paid=0.0, maker_rebate_received=0.0)
