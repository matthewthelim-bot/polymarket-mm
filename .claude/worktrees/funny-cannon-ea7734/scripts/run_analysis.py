#!/usr/bin/env python3
"""
Polymarket Market Making Analysis

Fetches 30-day price history from Polymarket CLOB API, generates synthetic
order-book + trade events, runs the full backtest engine, and reports:

  1. Hedge accessibility  - fraction of quoting opportunities with hedgeable depth
  2. PnL                  - spread + skew attribution, total
  3. Win rate             - profitable cycles / total cycles
  4. Risk level           - max drawdown, daily PnL volatility
  5. Runway               - how long $50k lasts at observed PnL rate

Usage:
    python scripts/run_analysis.py
    python scripts/run_analysis.py --capital 50000 --quote-size 100
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# Make src importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fee_model import FeeModel
from src.data.schemas import MarketMetadata, OrderBook, Fill, PriceLevel, Side
from src.strategy.fair_value import FairValueEstimator, TradeObservation
from src.strategy.regime import RegimeClassifier
from src.strategy.hedgeability import HedgeabilityAssessor, SkewConfig
from src.strategy.quote_engine import QuoteEngine
from src.strategy.inventory import InventoryManager
from src.pnl import PnLEngine
from src.backtest.fill_model import FillModel, FillModelConfig, QueueModel
from src.backtest.simulator import BacktestSimulator, SimulatorConfig

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"

# Markets to analyse: near-50c, high liquidity, using confirmed token IDs and fee params
CANDIDATE_MARKETS = [
    {
        "name": "OKC Thunder NBA Finals",
        "condition_id": "0x22e7b5e35423e76842dd3a5e1a21d13793811080d5e7b2896d0c001bd5e97d54",
        "token_id": "49500299856831034491021962156746701298730459370557900271970866855042624695770",
        "fee_rate": 0.03,
        "fee_exponent": 1,
        "rebate_fraction": 0.25,
        "sports": True,
    },
    {
        "name": "Jesus Christ before GTA VI",
        "condition_id": "0x32b09f6390252b37d674501527e709016d55581b2c1e544bd4b8167f5f732f4c",
        "token_id": "90435811253665578014957380826505992530054077692143838383981805324273750424057",
        "fee_rate": 0.05,
        "fee_exponent": 1,
        "rebate_fraction": 0.25,
        "sports": False,
    },
    {
        "name": "Bitcoin $1M before GTA VI",
        "condition_id": "0xbb57ccf5853a85487bc3d83d04d669310d28c6c810758953b9d9b91d1aee89d2",
        "token_id": "105267568073659068217311993901927962476298440625043565106676088842803600775810",
        "fee_rate": 0.05,
        "fee_exponent": 1,
        "rebate_fraction": 0.25,
        "sports": False,
    },
    {
        "name": "Trump out as President before GTA VI",
        "condition_id": "0x84f8b70331323c2fba97d7ceaa9a35fb645a0770d0dbff169d07f24f376766e9",
        "token_id": "108999723207897941876452935557011604067917389120996960199512481363958770540884",
        "fee_rate": 0.05,
        "fee_exponent": 1,
        "rebate_fraction": 0.25,
        "sports": False,
    },
]


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_price_history(token_id: str, interval: str = "1m") -> list[dict]:
    """Fetch hourly price history from CLOB API. Returns list of {t, p} dicts."""
    url = f"{CLOB_BASE}/prices-history?market={token_id}&interval={interval}&fidelity=60"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json().get("history", [])


def fetch_current_spread(token_id: str) -> float:
    """Fetch current bid-ask spread for a token."""
    try:
        r = requests.get(f"{CLOB_BASE}/spread?token_id={token_id}", timeout=10)
        r.raise_for_status()
        return float(r.json().get("spread", 0.01))
    except Exception:
        return 0.01


# ---------------------------------------------------------------------------
# Synthetic event generation
# ---------------------------------------------------------------------------

def precompute_bid_prices(
    history: list[dict],
    fee_model: FeeModel,
    fee_rate: float,
    half_spread_base: float,
    min_edge_floor: float,
    twap_window: int,
) -> list[Optional[float]]:
    """
    Pre-run FairValueEstimator on price history to compute what bid price the
    strategy would quote at each time step. Returns None when insufficient data.
    """
    fv_est = FairValueEstimator(twap_window_seconds=twap_window, external_weight=0.0)
    bid_prices: list[Optional[float]] = []

    for point in history:
        ts = datetime.fromtimestamp(point["t"], tz=timezone.utc)
        price = float(point["p"])
        # Feed midpoint trade so FV converges to market price
        fv_est.on_trade(TradeObservation(price=price, size=50.0, timestamp=ts))
        fv = fv_est.estimate(as_of=ts)
        if fv is None:
            bid_prices.append(None)
        else:
            fee_cost = fee_model.fee_flatten_expected(fv, fee_rate)
            half_spread = max(half_spread_base, fee_cost + min_edge_floor)
            bid = round(fv - half_spread, 2)
            bid_prices.append(bid)

    return bid_prices


def generate_synthetic_events(
    history: list[dict],
    bid_prices: list[Optional[float]],
    market_id: str,
    no_ask_half_spread: float,
    quote_size: float,
) -> list:
    """
    Build a stream of synthetic OrderBook + Fill events from price history.

    For each time step:
      - OrderBook: bids at [p - half], asks (No side) at [1 - p + half]
      - Warmup trade at midpoint p (drives FV estimator)
      - Fill-trigger trade at bid_price (simulates a market sell hitting our resting bid)

    The No ask price is 1 - p + small_offset, reflecting the complementary
    binary token. For our Yes buy to be hedgeable, we need No_ask <= max_flatten_price.
    """
    events = []

    for i, (point, bid) in enumerate(zip(history, bid_prices)):
        t_base = point["t"]
        p = float(point["p"])
        ts_book = datetime.fromtimestamp(t_base, tz=timezone.utc)
        ts_warmup = ts_book + timedelta(seconds=1)

        # Synthetic order book
        yes_bid = round(p - no_ask_half_spread, 3)
        no_ask = round(1.0 - p + no_ask_half_spread, 3)
        book = OrderBook(
            market_id=market_id,
            timestamp=ts_book,
            bids=[PriceLevel(max(0.01, yes_bid), 100_000.0)],
            asks=[PriceLevel(min(0.99, no_ask), 100_000.0)],
        )
        events.append(book)

        # Warmup trade at midpoint (updates FV estimator inside simulator)
        warmup = Fill(
            fill_id=f"wm_{i}",
            market_id=market_id,
            side=Side.SELL,
            price=p,
            size=50.0,
            timestamp=ts_warmup,
            is_maker=False,
        )
        events.append(warmup)

        # Fill-trigger trade at our computed bid price (if available)
        if bid is not None:
            ts_fill = ts_book + timedelta(seconds=2)
            fill_trigger = Fill(
                fill_id=f"ft_{i}",
                market_id=market_id,
                side=Side.SELL,    # market participant sells Yes at our bid
                price=bid,
                size=quote_size,
                timestamp=ts_fill,
                is_maker=False,
            )
            events.append(fill_trigger)

    # Final sort by timestamp (should already be ordered but be safe)
    events.sort(key=lambda e: e.timestamp)
    return events


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

@dataclass
class MarketAnalysisConfig:
    start_capital: float = 50_000.0
    quote_size: float = 100.0
    half_spread_base: float = 0.015
    min_edge_floor: float = 0.005
    twap_window_seconds: int = 300
    no_ask_half_spread: float = 0.001    # tight: 0.2c each side
    max_inventory_contracts: float = 500.0
    adverse_selection_threshold: float = 0.012
    time_to_resolution_hours: float = 2160.0  # far-future markets: 90 days


def run_market_analysis(market_def: dict, cfg: MarketAnalysisConfig):
    """Fetch data, build events, run simulation, return result."""
    print(f"\nFetching price history for {market_def['name']}...")
    history = fetch_price_history(market_def["token_id"])
    if not history:
        print("  No history found.")
        return None

    current_spread = fetch_current_spread(market_def["token_id"])
    print(f"  {len(history)} hourly points | current spread: {current_spread:.4f}")

    fm = FeeModel()
    fee_rate = market_def["fee_rate"]
    rebate_fraction = market_def["rebate_fraction"]

    # Pre-compute bid prices
    bid_prices = precompute_bid_prices(
        history=history,
        fee_model=fm,
        fee_rate=fee_rate,
        half_spread_base=cfg.half_spread_base,
        min_edge_floor=cfg.min_edge_floor,
        twap_window=cfg.twap_window_seconds,
    )

    # Sample representative bid price and hedgeability check
    valid_bids = [b for b in bid_prices if b is not None]
    if valid_bids:
        sample_bid = valid_bids[len(valid_bids) // 2]  # median sample
        sample_p = float(history[bid_prices.index(sample_bid)]["p"])
        p_max = fm.max_flatten_price(
            p_fill=sample_bid,
            fee_rate=fee_rate,
            rebate_fraction=rebate_fraction,
            min_edge_floor=cfg.min_edge_floor,
        )
        no_ask_sample = round(1.0 - sample_p + cfg.no_ask_half_spread, 3)
        print(f"  Sample: p={sample_p:.3f}, bid={sample_bid:.3f}, max_flatten={p_max:.4f}, "
              f"no_ask={no_ask_sample:.3f}, hedgeable={no_ask_sample <= p_max}")

    # Generate synthetic events
    events = generate_synthetic_events(
        history=history,
        bid_prices=bid_prices,
        market_id=market_def["condition_id"],
        no_ask_half_spread=cfg.no_ask_half_spread,
        quote_size=cfg.quote_size,
    )
    print(f"  Generated {len(events)} synthetic events")

    # Build components
    metadata = MarketMetadata(
        condition_id=market_def["condition_id"],
        token_id_yes=market_def["token_id"],
        token_id_no=market_def["token_id"],
        category="sports" if market_def["sports"] else "general",
        fee_rate=fee_rate,
        fee_exponent=market_def["fee_exponent"],
        rebate_fraction=rebate_fraction,
        sports=market_def["sports"],
    )
    skew_config = SkewConfig(
        skew_tolerance=0.0,
        skew_edge_premium=0.005,
        skew_hard_limit=0,
        skew_capital_charge_multiplier=3.0,
        max_skew_notional=0.0,
        current_skew_notional=0.0,
        current_skew_contracts=0.0,
    )
    fv_estimator = FairValueEstimator(cfg.twap_window_seconds, 0.0)
    regime_classifier = RegimeClassifier()
    hedgeability_assessor = HedgeabilityAssessor(fm, fee_rate, rebate_fraction, cfg.min_edge_floor)
    quote_engine = QuoteEngine(fm, fee_rate, rebate_fraction, cfg.half_spread_base, cfg.min_edge_floor)
    inventory_manager = InventoryManager(market_def["condition_id"], 0.0003)
    pnl_engine = PnLEngine(fm, fee_rate, rebate_fraction)
    fill_model = FillModel(FillModelConfig(queue_model=QueueModel.FRONT, latency_ms=50))
    sim_config = SimulatorConfig(
        start_capital=cfg.start_capital,
        max_inventory_contracts=cfg.max_inventory_contracts,
        adverse_selection_threshold=cfg.adverse_selection_threshold,
        time_to_resolution_hours=cfg.time_to_resolution_hours,
        quote_size=cfg.quote_size,
    )
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
        config=sim_config,
    )
    result = simulator.run(events)
    return result, history, current_spread


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(result, history: list[dict], capital: float, market_name: str):
    """Compute and return the 5 analysis metrics."""
    from src.backtest.simulator import SimulationResult

    days = (history[-1]["t"] - history[0]["t"]) / 86400 if len(history) > 1 else 1.0

    # 1. Hedge accessibility
    hedge_access = result.hedge_accessibility()

    # 2. PnL breakdown
    total_pnl = result.total_pnl()
    daily_pnl = total_pnl / days if days > 0 else 0.0

    # 3. Win rate
    win_rate = result.win_rate()

    # 4. Risk level
    if len(result.per_cycle_pnl) >= 2:
        pnl_std = statistics.stdev(result.per_cycle_pnl)
        pnl_mean = statistics.mean(result.per_cycle_pnl)
        # Sharpe-like: mean / std (per-cycle)
        sharpe = pnl_mean / pnl_std if pnl_std > 0 else 0.0
    else:
        pnl_std = 0.0
        pnl_mean = 0.0
        sharpe = 0.0

    # Max drawdown from cumulative PnL series
    max_drawdown = 0.0
    if result.per_cycle_pnl:
        cum = 0.0
        peak = 0.0
        for pnl in result.per_cycle_pnl:
            cum += pnl
            if cum > peak:
                peak = cum
            dd = peak - cum
            if dd > max_drawdown:
                max_drawdown = dd

    # 5. Runway
    if daily_pnl > 0:
        runway_days = None  # Profitable — no depletion
        runway_label = "Indefinite (profitable)"
    elif daily_pnl < 0:
        runway_days = capital / abs(daily_pnl)
        runway_label = f"{runway_days:.0f} days ({runway_days / 30:.1f} months)"
    else:
        runway_days = None
        runway_label = "Break-even"

    return {
        "name": market_name,
        "days": days,
        "num_events": None,  # filled by caller
        "hedge_accessibility": hedge_access,
        "hedge_checks_total": result.hedge_checks_total,
        "hedge_accessible_count": result.hedge_accessible_count,
        "total_pnl": total_pnl,
        "spread_pnl": result.total_spread_pnl,
        "skew_pnl": result.total_skew_pnl,
        "fees_paid": result.total_fees_paid,
        "rebates_received": result.total_rebates_received,
        "daily_pnl": daily_pnl,
        "num_fills": result.num_fills,
        "num_cycles": result.num_cycles_completed,
        "num_profitable_cycles": result.num_profitable_cycles,
        "win_rate": win_rate,
        "pnl_per_cycle_mean": pnl_mean,
        "pnl_per_cycle_std": pnl_std,
        "sharpe_per_cycle": sharpe,
        "max_drawdown": max_drawdown,
        "runway_label": runway_label,
    }


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------

def print_report(metrics_list: list[dict], capital: float):
    sep = "=" * 70
    thin = "-" * 70

    print(f"\n{sep}")
    print(f"  POLYMARKET MARKET MAKING ANALYSIS  |  Capital: ${capital:,.0f}")
    print(sep)

    for m in metrics_list:
        print(f"\n  Market: {m['name']}")
        print(thin)

        # 1. Hedge Accessibility
        pct = m["hedge_accessibility"] * 100
        print(f"  1. HEDGE ACCESSIBILITY")
        print(f"     Accessible: {pct:.1f}%  "
              f"({m['hedge_accessible_count']} of {m['hedge_checks_total']} checks)")
        if pct < 30:
            print(f"     !! Low — market spread too wide vs fee threshold")
        elif pct > 70:
            print(f"     [OK] Good depth available for hedging")
        else:
            print(f"     [OK] Moderate — some price levels not hedgeable")

        # 2. PnL
        print(f"\n  2. PnL  (over {m['days']:.0f} days)")
        print(f"     Total PnL    : ${m['total_pnl']:+,.4f}")
        print(f"       Spread PnL : ${m['spread_pnl']:+,.4f}")
        print(f"       Skew PnL   : ${m['skew_pnl']:+,.4f}")
        print(f"     Fees paid    : ${m['fees_paid']:,.4f}")
        print(f"     Rebates recv : ${m['rebates_received']:,.4f}")
        print(f"     Daily PnL    : ${m['daily_pnl']:+,.4f}/day")
        print(f"     Fills: {m['num_fills']}  |  Cycles: {m['num_cycles']}")

        # 3. Win Rate
        print(f"\n  3. WIN RATE")
        print(f"     {m['win_rate']*100:.1f}%  ({m['num_profitable_cycles']} profitable "
              f"of {m['num_cycles']} cycles)")
        if m['num_cycles'] > 0:
            print(f"     Mean cycle PnL: ${m['pnl_per_cycle_mean']:+,.4f}  |  "
                  f"Std: ${m['pnl_per_cycle_std']:,.4f}")

        # 4. Risk Level
        print(f"\n  4. RISK LEVEL")
        print(f"     Max drawdown : ${m['max_drawdown']:,.4f}")
        if m['pnl_per_cycle_std'] > 0:
            print(f"     Sharpe ratio : {m['sharpe_per_cycle']:+.3f}  (per-cycle)")
        else:
            print(f"     Sharpe ratio : N/A  (insufficient data)")

        # 5. Runway
        print(f"\n  5. RUNWAY  (${capital:,.0f} capital)")
        print(f"     {m['runway_label']}")
        if m['daily_pnl'] != 0:
            annualized = m['daily_pnl'] * 365
            roi = (annualized / capital) * 100
            print(f"     Annualized PnL: ${annualized:+,.0f}  ({roi:+.1f}% ROI)")

        print(thin)

    print(f"\n{sep}")
    print("  NOTE: Simulation uses synthetic order-book events from CLOB price history.")
    print("  Fill rate reflects strategy fill logic. Actual live fill rates may differ.")
    print(f"{sep}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Polymarket MM analysis")
    parser.add_argument("--capital", type=float, default=50_000.0,
                        help="Starting capital in USDC (default: 50000)")
    parser.add_argument("--quote-size", type=float, default=100.0,
                        help="Quote size in contracts per fill (default: 100)")
    parser.add_argument("--half-spread", type=float, default=0.015,
                        help="Half-spread base in price units (default: 0.015)")
    parser.add_argument("--no-ask-offset", type=float, default=0.001,
                        help="Synthetic No-ask offset above complement (default: 0.001)")
    args = parser.parse_args()

    cfg = MarketAnalysisConfig(
        start_capital=args.capital,
        quote_size=args.quote_size,
        half_spread_base=args.half_spread,
        no_ask_half_spread=args.no_ask_offset,
    )

    all_metrics = []
    for market_def in CANDIDATE_MARKETS:
        try:
            out = run_market_analysis(market_def, cfg)
            if out is None:
                continue
            result, history, current_spread = out
            m = compute_metrics(result, history, args.capital, market_def["name"])
            all_metrics.append(m)
        except Exception as exc:
            print(f"  ERROR on {market_def['name']}: {exc}")

    if all_metrics:
        print_report(all_metrics, args.capital)
    else:
        print("No results obtained.")


if __name__ == "__main__":
    main()
