"""
RegimeClassifier — deterministic 7-state lifecycle machine.

Priority order (highest to lowest):
  SUSPENDED > SETTLED > HEDGE_PENDING > INVENTORY_WAREHOUSE
  > INVENTORY_REDUCED > ONE_SIDE_FILLED > QUOTE_ACTIVE
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from src.data.schemas import Regime, InventoryState


@dataclass
class RegimeInput:
    timestamp: datetime
    inventory: InventoryState
    adverse_selection: float
    adverse_selection_threshold: float
    time_to_resolution_hours: float
    pre_resolution_hours: float
    max_inventory_contracts: float
    warehouse_threshold_fraction: float
    fv: float
    best_bid: float | None
    best_ask: float | None


class RegimeClassifier:
    """
    Stateless classifier. Call classify() on each tick.

    Regime controls quoting behavior:
      QUOTE_ACTIVE        → quote both sides normally
      ONE_SIDE_FILLED     → quote only the unfilled side (hedge leg)
      INVENTORY_REDUCED   → widen spreads, prioritize flatten
      INVENTORY_WAREHOUSE → suspend new quotes, flatten only
      HEDGE_PENDING       → aggressive flatten, no new quotes
      SETTLED             → redemption only, no quoting
      SUSPENDED           → no quoting (adverse selection detected)
    """

    def classify(self, inp: RegimeInput) -> Regime:
        # 1. Settled (resolution has passed)
        if inp.time_to_resolution_hours <= 0.0:
            return Regime.SETTLED

        # 2. Suspended (adverse selection)
        if inp.adverse_selection > inp.adverse_selection_threshold:
            return Regime.SUSPENDED

        # 3. Pre-resolution hedge window
        if inp.time_to_resolution_hours <= inp.pre_resolution_hours:
            if inp.inventory.total_contracts() > 0:
                return Regime.HEDGE_PENDING

        total = inp.inventory.total_contracts()
        fraction = total / inp.max_inventory_contracts if inp.max_inventory_contracts > 0 else 0.0

        # 4. Inventory warehouse (near hard limit)
        if fraction >= inp.warehouse_threshold_fraction:
            return Regime.INVENTORY_WAREHOUSE

        # 5. Inventory reduced (mid-range)
        if fraction >= 0.20:
            return Regime.INVENTORY_REDUCED

        # 6. One side filled (small inventory)
        if total > 0:
            return Regime.ONE_SIDE_FILLED

        # 7. Normal quoting
        return Regime.QUOTE_ACTIVE
