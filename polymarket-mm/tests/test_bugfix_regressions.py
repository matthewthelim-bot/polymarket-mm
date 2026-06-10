"""Regression tests for the 2026-06-10 review fixes.

Each test encodes the corrected behavior of a specific confirmed bug so the
fix cannot silently regress. Bug numbers reference the review findings.
"""

import threading
import pytest
from datetime import datetime, timezone, timedelta

from src.data.loader import HistoricalDataLoader
from src.live.credentials import _parse_env_file
from src.live.portfolio_state import PortfolioConstraints
from src.strategy.fair_value import FairValueEstimator, TradeObservation, ExternalSignal

from src.fee_model import FeeModel
from src.data.schemas import MarketMetadata, OrderBook, PriceLevel, Fill, Side
from src.strategy.regime import RegimeClassifier
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig
from src.strategy.quote_engine import QuoteEngine
from src.strategy.inventory import InventoryManager
from src.pnl import PnLEngine
from src.backtest.fill_model import FillModel, FillModelConfig, QueueModel
from src.backtest.simulator import BacktestSimulator, SimulatorConfig


def ts(offset=0):
    return datetime(2026, 1, 1, 12, tzinfo=timezone.utc) + timedelta(seconds=offset)


# ---------------------------------------------------------------------------
# Bug 15 — loader: numeric epoch timestamps must parse, not crash
# ---------------------------------------------------------------------------

def test_parse_ts_accepts_numeric_epoch():
    dt = HistoricalDataLoader._parse_ts(1717977600)
    assert dt == datetime.fromtimestamp(1717977600, tz=timezone.utc)


def test_parse_ts_accepts_float_epoch():
    dt = HistoricalDataLoader._parse_ts(1717977600.5)
    assert dt.tzinfo is not None


def test_parse_ts_accepts_iso_string():
    dt = HistoricalDataLoader._parse_ts("2026-06-10T00:00:00Z")
    assert dt.tzinfo is not None


def test_parse_ts_rejects_unsupported_type():
    # ValueError lands in load_market's catch list → line skipped, no crash
    with pytest.raises(ValueError):
        HistoricalDataLoader._parse_ts(None)


# ---------------------------------------------------------------------------
# Bug 7 — credentials: .env values must survive inline comments and quotes
# ---------------------------------------------------------------------------

def _parse_env_lines(tmp_path, content):
    import os
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")
    # use unique key names so os.environ pollution doesn't break reruns
    _parse_env_file(env_file)
    return os.environ


def test_env_inline_comment_stripped(tmp_path):
    import os
    os.environ.pop("BUGFIX_T1", None)
    _parse_env_lines(tmp_path, "BUGFIX_T1=s3cr3t  # rotated 2026-06\n")
    assert os.environ["BUGFIX_T1"] == "s3cr3t"


def test_env_quoted_value_keeps_hash(tmp_path):
    import os
    os.environ.pop("BUGFIX_T2", None)
    _parse_env_lines(tmp_path, 'BUGFIX_T2="value # with hash"\n')
    assert os.environ["BUGFIX_T2"] == "value # with hash"


def test_env_quotes_inside_secret_survive(tmp_path):
    import os
    os.environ.pop("BUGFIX_T3", None)
    _parse_env_lines(tmp_path, "BUGFIX_T3='it''s'\n")
    # only the single outer quote pair is removed; inner quotes survive
    # (the old strip("'") would have eaten ALL leading/trailing quotes)
    assert os.environ["BUGFIX_T3"] == "it''s"


# ---------------------------------------------------------------------------
# Bug 9 — portfolio: try_open is atomic under concurrency
# ---------------------------------------------------------------------------

def test_try_open_atomic_under_contention():
    p = PortfolioConstraints(
        total_capital=1000.0,
        max_long_term_fraction=0.10,   # $100 headroom
        max_market_notional=0.0,
        max_event_notional=0.0,
    )
    results = []

    def worker():
        results.append(p.try_open("ev", "mkt", 100.0, days_to_resolution=60))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly ONE thread may claim the $100 headroom
    assert sum(results) == 1
    assert p.status()["long_term_notional"] == pytest.approx(100.0)


def test_try_open_rejects_when_capped():
    p = PortfolioConstraints(total_capital=1000.0, max_market_notional=50.0)
    assert p.try_open("ev", "m1", 50.0, 5) is True
    assert p.try_open("ev", "m1", 1.0, 5) is False  # cap reached, state unchanged
    assert p.status()["market_notional"]["m1"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Bug (sweep) — fair value: one signal per source, stale signals expire
# ---------------------------------------------------------------------------

def _feed_trades(est, price=0.50, n=3):
    for i in range(n):
        est.on_trade(TradeObservation(price=price, size=10.0, timestamp=ts(i)))


def test_repeated_signals_from_one_source_count_once():
    est = FairValueEstimator(twap_window_seconds=300, external_weight=0.5)
    _feed_trades(est, price=0.50)
    # Source publishes the same stale view ten times
    for i in range(10):
        est.on_external_signal(ExternalSignal("metaculus", 0.30, ts(i)))
    # Then a second source publishes a fresh different view
    est.on_external_signal(ExternalSignal("manifold", 0.70, ts(20)))
    fv = est.estimate(as_of=ts(30))
    # external average must be (0.30 + 0.70)/2 = 0.50, not (10*0.30+0.70)/11
    assert fv == pytest.approx(0.5 * 0.50 + 0.5 * 0.50)


def test_stale_signals_age_out():
    est = FairValueEstimator(
        twap_window_seconds=300, external_weight=0.5, signal_max_age_seconds=60
    )
    _feed_trades(est, price=0.50)
    est.on_external_signal(ExternalSignal("metaculus", 0.90, ts(0)))
    # 2 minutes later the signal is past max age → pure TWAP
    fv = est.estimate(as_of=ts(120))
    assert fv == pytest.approx(0.50)


def test_trade_list_pruned_to_window():
    est = FairValueEstimator(twap_window_seconds=60)
    for i in range(1000):
        est.on_trade(TradeObservation(price=0.5, size=1.0, timestamp=ts(i)))
    # Only ~60s of trades may remain buffered
    assert len(est._trades) <= 62


# ---------------------------------------------------------------------------
# Bugs 10/11/13 — simulator: hedge depth budget, fee-aware guard,
#                 partial-close fee proration
# ---------------------------------------------------------------------------

def _make_sim(fee_rate=0.04, quote_size=100.0, iceberg=0.0, levels=1,
              max_open_notional=0.0):
    fm = FeeModel()
    meta = MarketMetadata(
        condition_id="test-001", token_id_yes="y", token_id_no="n",
        category="politics", fee_rate=fee_rate, fee_exponent=1,
        rebate_fraction=0.20, sports=False,
    )
    no_skew = SkewConfig(
        skew_tolerance=0.0, skew_edge_premium=0.005,
        skew_hard_limit=0, skew_capital_charge_multiplier=3.0,
        max_skew_notional=0.0, current_skew_notional=0.0,
    )
    return BacktestSimulator(
        metadata=meta,
        fee_model=fm,
        fv_estimator=FairValueEstimator(twap_window_seconds=300),
        regime_classifier=RegimeClassifier(),
        hedgeability_assessor=HedgeabilityAssessor(fm, meta.fee_rate, meta.rebate_fraction),
        quote_engine=QuoteEngine(fm, meta.fee_rate, meta.rebate_fraction),
        inventory_manager=InventoryManager(meta.condition_id),
        pnl_engine=PnLEngine(fm, meta.fee_rate, meta.rebate_fraction),
        fill_model=FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=0)),
        skew_config=no_skew,
        config=SimulatorConfig(
            start_capital=10000.0,
            max_inventory_contracts=500,
            adverse_selection_threshold=0.012,
            time_to_resolution_hours=48.0,
            quote_size=quote_size,
            iceberg_display_size=iceberg,
            ladder_levels=levels,
            max_open_notional=max_open_notional,
        ),
    )


def test_partial_close_prorates_entry_fees():
    """Bug 13: closing half a position must credit half its entry fees."""
    sim = _make_sim()
    # Open a 200-contract short via ask-arb (no longs exist)
    sim._record_ask_arb_cycle(
        maker_price=0.55, taker_price=0.50, size=200.0,
        timestamp=ts(0), maker_token="YES",
    )
    assert len(sim._open_shorts) == 1
    full_entry_fees = sim._open_shorts[0].entry_fees_net

    # Close in two 100-contract bid-arb cycles
    sim._record_bid_arb_cycle(
        maker_price=0.44, taker_price=0.50, size=100.0,
        timestamp=ts(10), maker_token="YES",
    )
    assert len(sim._open_shorts) == 1
    # Remainder must carry exactly half the original entry fees
    assert sim._open_shorts[0].entry_fees_net == pytest.approx(full_entry_fees / 2)

    sim._record_bid_arb_cycle(
        maker_price=0.44, taker_price=0.50, size=100.0,
        timestamp=ts(20), maker_token="YES",
    )
    assert len(sim._open_shorts) == 0


def test_oversized_close_continues_fifo_and_opens_remainder():
    """Bug (Angle E): a cycle bigger than the oldest position must not
    silently drop the excess — it closes FIFO then opens the remainder."""
    sim = _make_sim()
    # Open a 50-contract short
    sim._record_ask_arb_cycle(
        maker_price=0.55, taker_price=0.50, size=50.0,
        timestamp=ts(0), maker_token="YES",
    )
    # Bid-arb of 200: 50 closes the short, 150 opens a new long
    sim._record_bid_arb_cycle(
        maker_price=0.44, taker_price=0.50, size=200.0,
        timestamp=ts(10), maker_token="YES",
    )
    assert len(sim._open_shorts) == 0
    assert len(sim._open_longs) == 1
    assert sim._open_longs[0].size == pytest.approx(150.0)


def test_profitability_guard_rejects_sub_fee_edge():
    """Bug 11: a 1-tick gross edge smaller than the net taker fee must not
    execute as an 'arb'."""
    sim = _make_sim(fee_rate=0.07)
    # gross edge 0.001/contract; taker fee at p≈0.5 ≈ 0.0175 → net negative
    edge = sim._cycle_net_edge_pc(0.50, 0.499, 1.0 - 0.50 - 0.499)
    assert edge < 0

    # A healthy edge clears the guard
    edge_ok = sim._cycle_net_edge_pc(0.45, 0.50, 1.0 - 0.45 - 0.50)
    assert edge_ok > 0


def test_hedge_budget_not_reused_across_chunks():
    """Bug 10: opposing-book depth of 50 cannot hedge 300 contracts."""
    sim = _make_sim(quote_size=300.0, iceberg=50.0, levels=1)
    # Wire dual-book state directly
    sim._ever_seen_tagged_book = True
    sim._current_book = OrderBook(
        market_id="test-001", timestamp=ts(0),
        bids=[PriceLevel(0.45, 500.0)], asks=[PriceLevel(0.55, 500.0)],
        token_side="YES",
    )
    # NO book: best ask has only 50 contracts of hedge depth
    sim._no_book = OrderBook(
        market_id="test-001", timestamp=ts(0),
        bids=[PriceLevel(0.45, 500.0)], asks=[PriceLevel(0.50, 50.0)],
        token_side="NO",
    )
    # Seed FV so _compute_quote returns a decision
    for i in range(5):
        sim.fv_estimator.on_trade(
            TradeObservation(price=0.50, size=10.0, timestamp=ts(i))
        )

    trade = Fill(
        fill_id="t1", market_id="test-001", side=Side.SELL,
        price=0.30, size=300.0, timestamp=ts(10), is_maker=False,
        token_side="YES",
    )
    sim._check_yes_bid_fill(trade, fv=0.50)

    # Total hedged contracts across all cycles must not exceed the 50
    # contracts of NO-ask depth that actually existed.
    total_cycle_contracts = sum(
        p.size for p in sim._open_longs
    )
    assert total_cycle_contracts <= 50.0 + 1e-6
