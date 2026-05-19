"""
BacktestRunner — constructs all components from config and runs a single backtest.

Orchestrates: load config → load data → construct components → run simulator → return results.

Usage:
    config = RunConfig(market_id="abc123", data_dir="data/raw", fee_rate=0.04, ...)
    result = BacktestRunner(config).run()
"""

from __future__ import annotations
from dataclasses import dataclass

from src.fee_model import FeeModel
from src.data.schemas import MarketMetadata
from src.data.loader import HistoricalDataLoader, LoaderConfig
from src.strategy.fair_value import FairValueEstimator
from src.strategy.regime import RegimeClassifier
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig
from src.strategy.quote_engine import QuoteEngine
from src.strategy.inventory import InventoryManager
from src.pnl import PnLEngine
from src.backtest.fill_model import FillModel, FillModelConfig, QueueModel
from src.backtest.simulator import BacktestSimulator, SimulatorConfig, SimulationResult


@dataclass
class RunConfig:
    """Configuration for a single backtest run."""
    market_id: str
    data_dir: str
    fee_rate: float
    fee_exponent: int
    rebate_fraction: float
    sports: bool
    start_capital: float = 50000.0
    quote_size: float = 100.0
    queue_model: str = "FRONT"
    latency_ms: int = 50
    twap_window_seconds: int = 300
    external_weight: float = 0.0
    min_edge_floor: float = 0.005
    half_spread_base: float = 0.015
    max_inventory_contracts: float = 500.0
    adverse_selection_threshold: float = 0.012
    time_to_resolution_hours: float = 48.0
    pre_resolution_hours: float = 4.0
    warehouse_threshold_fraction: float = 0.80
    daily_capital_charge_rate: float = 0.0003
    skew_tolerance: float = 0.0
    skew_edge_premium: float = 0.005
    skew_hard_limit: int = 0
    skew_capital_charge_multiplier: float = 3.0
    max_skew_notional: float = 0.0


class BacktestRunner:
    """
    Orchestrates a full single-market backtest run.

    Constructs all strategy and simulator components from a RunConfig,
    loads event data, and runs the simulation.
    """

    def __init__(self, config: RunConfig):
        self.config = config

    def run(self) -> SimulationResult:
        """
        Execute the backtest and return aggregated results.

        Pipeline:
          1. Instantiate FeeModel (stateless)
          2. Create MarketMetadata from RunConfig
          3. Create SkewConfig
          4. Instantiate all strategy components (FV, Regime, Hedgeability, etc.)
          5. Create BacktestSimulator with all components
          6. Load events from data_dir for the market
          7. Run simulator on events
          8. Return SimulationResult
        """
        cfg = self.config

        # 1. FeeModel (stateless, shared by all components)
        fm = FeeModel()

        # 2. MarketMetadata from RunConfig
        metadata = MarketMetadata(
            condition_id=cfg.market_id,
            token_id_yes=cfg.market_id,   # in backtest, market_id serves as token_id
            token_id_no=cfg.market_id,
            category="unknown",
            fee_rate=cfg.fee_rate,
            fee_exponent=cfg.fee_exponent,
            rebate_fraction=cfg.rebate_fraction,
            sports=cfg.sports,
        )

        # 3. SkewConfig
        skew_config = SkewConfig(
            skew_tolerance=cfg.skew_tolerance,
            skew_edge_premium=cfg.skew_edge_premium,
            skew_hard_limit=cfg.skew_hard_limit,
            skew_capital_charge_multiplier=cfg.skew_capital_charge_multiplier,
            max_skew_notional=cfg.max_skew_notional,
            current_skew_notional=0.0,
        )

        # 4. Instantiate strategy components
        fv_estimator = FairValueEstimator(cfg.twap_window_seconds, cfg.external_weight)
        regime_classifier = RegimeClassifier()
        hedgeability_assessor = HedgeabilityAssessor(
            fm, cfg.fee_rate, cfg.rebate_fraction, cfg.min_edge_floor
        )
        quote_engine = QuoteEngine(
            fm, cfg.fee_rate, cfg.rebate_fraction,
            cfg.half_spread_base, cfg.min_edge_floor
        )
        inventory_manager = InventoryManager(cfg.market_id, cfg.daily_capital_charge_rate)
        pnl_engine = PnLEngine(fm, cfg.fee_rate, cfg.rebate_fraction)

        # 5. Create BacktestSimulator
        try:
            queue_model_enum = QueueModel[cfg.queue_model]
        except KeyError:
            raise ValueError(
                f"Invalid queue_model {cfg.queue_model!r}. "
                f"Valid values: {[m.name for m in QueueModel]}"
            ) from None

        fill_model = FillModel(FillModelConfig(
            queue_model=queue_model_enum,
            latency_ms=cfg.latency_ms,
        ))

        simulator = BacktestSimulator(
            metadata=metadata,
            fee_model=fm,
            fv_estimator=fv_estimator,
            regime_classifier=regime_classifier,
            hedgeability_assessor=hedgeability_assessor,
            quote_engine=quote_engine,
            inventory_manager=inventory_manager,
            pnl_engine=pnl_engine,
            fill_model=fill_model,
            skew_config=skew_config,
            config=SimulatorConfig(
                start_capital=cfg.start_capital,
                max_inventory_contracts=cfg.max_inventory_contracts,
                adverse_selection_threshold=cfg.adverse_selection_threshold,
                time_to_resolution_hours=cfg.time_to_resolution_hours,
                quote_size=cfg.quote_size,
                pre_resolution_hours=cfg.pre_resolution_hours,
                warehouse_threshold_fraction=cfg.warehouse_threshold_fraction,
                daily_capital_charge_rate=cfg.daily_capital_charge_rate,
            ),
        )

        # 6. Load events from data
        loader = HistoricalDataLoader(LoaderConfig(data_dir=cfg.data_dir))
        events = list(loader.load_market(cfg.market_id))

        # 7. Run simulator
        return simulator.run(events)
