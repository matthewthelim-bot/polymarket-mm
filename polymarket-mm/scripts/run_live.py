#!/usr/bin/env python3
# scripts/run_live.py
"""
Live market making runner.

Discovers markets from data/raw (or --markets flag), starts WebSocket book feed,
and runs a QuoteLoop per market.

SECURITY:
  - Loads credentials from environment / .env file — never prints them
  - --dry-run is the DEFAULT — pass --live to actually place orders
  - All credential loading goes through src.live.credentials

Usage:
    # Dry run (default — no orders placed):
    py -3 scripts/run_live.py

    # Specific markets:
    py -3 scripts/run_live.py --markets data/raw/1116682...jsonl data/raw/2700472...jsonl

    # Live trading (opt-in):
    py -3 scripts/run_live.py --live

    # Parameters:
    py -3 scripts/run_live.py --half-spread 0.030 --quote-size 100 --max-concurrent 1

Ctrl-C for graceful shutdown.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests as _requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fee_model import FeeModel
from src.live.credentials import load_credentials, CredentialError
from src.live.clob_client import ClobClient
from src.live.book_feed import BookFeed
from src.live.portfolio_state import PortfolioConstraints
from src.live.quote_loop import QuoteLoop, QuoteLoopConfig
from src.strategy.fair_value import TradeObservation


DATA_API = "https://data-api.polymarket.com"


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def discover_markets(data_dir: Path) -> list[Path]:
    """Return all .jsonl files in data_dir, sorted."""
    return sorted(data_dir.glob("*.jsonl"))


def load_sidecar(jsonl_path: Path) -> dict:
    """Load sidecar .json for a market (contains condition_id, token IDs, etc.)."""
    sidecar = jsonl_path.with_suffix(".json")
    if sidecar.exists():
        with sidecar.open() as f:
            return json.load(f)
    return {}


def resolve_market_tokens(
    jsonl_path: Path,
    client: ClobClient,
) -> tuple[str, str, str, str] | None:
    """
    Return (yes_token_id, no_token_id, condition_id, market_question) for a market.

    Tries sidecar first, then CLOB API. Returns None on failure.
    """
    log = logging.getLogger("run_live")
    market_id = jsonl_path.stem
    sidecar = load_sidecar(jsonl_path)

    yes_token = sidecar.get("yes_token_id")
    condition_id = sidecar.get("condition_id")
    title = sidecar.get("title", market_id[:40])

    if not yes_token and not condition_id:
        if market_id.isdigit() and len(market_id) > 30:
            # data/raw format: filename IS the YES token ID (long integer)
            yes_token = market_id
        elif market_id.startswith("0x") and len(market_id) > 30:
            # data/live format: filename IS the condition_id (0x hex)
            condition_id = market_id
        else:
            log.warning("Cannot determine YES token or condition_id for %s", market_id[:40])
            return None

    # Get condition_id from CLOB /book if not in sidecar
    if not condition_id:
        try:
            condition_id = client.get_condition_id_for_token(yes_token)
        except Exception as exc:
            log.warning("Cannot resolve condition_id for %s: %s", market_id[:40], exc)
            return None

    # Get YES and NO tokens from CLOB /markets/{condition_id}
    try:
        yes_token_resolved, no_token = client.get_market_tokens(condition_id)
        # Prefer resolved YES token (may differ from filename in edge cases)
        yes_token = yes_token_resolved
    except Exception as exc:
        log.warning("Cannot resolve tokens for %s: %s", condition_id[:20], exc)
        return None

    # Try to get market question if not in sidecar
    if title == market_id[:40]:
        try:
            import requests as _req
            r = _req.get(f"https://clob.polymarket.com/markets/{condition_id}", timeout=5)
            if r.ok:
                title = r.json().get("question", title)[:80]
        except Exception:
            pass

    return yes_token, no_token, condition_id, title


def fetch_market_resolution(condition_id: str) -> tuple[str, int]:
    """Return (end_date_str, days_to_resolution) for a market.

    Uses the CLOB REST API path lookup. The Gamma /markets?condition_id=
    query filter is broken server-side (ignores the filter and returns an
    unrelated market), so it must not be used here.

    The end-date string doubles as the event_key for PortfolioConstraints,
    grouping markets that resolve on the same day. Returns ("unknown", 9999)
    on any error so the caps degrade gracefully (unknown = treated long-term).
    """
    import urllib.request as _ur, json as _json
    url = f"https://clob.polymarket.com/markets/{condition_id}"
    try:
        req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _ur.urlopen(req, timeout=8) as resp:
            m = _json.loads(resp.read())
        end_str = m.get("end_date_iso") or ""
        if end_str:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            days_left = (end_dt - datetime.now(timezone.utc)).days
            return end_dt.strftime("%Y-%m-%d"), max(0, days_left)
    except Exception:
        pass
    return "unknown", 9999


def resolution_from_universe_entry(entry: dict) -> tuple[str, int]:
    """Like fetch_market_resolution() but reads the universe entry's stored
    end_date — no network call. Recomputes days-left from today since the
    stored days_to_resolution goes stale between universe rebuilds."""
    end_str = entry.get("end_date") or ""
    if end_str:
        try:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            days_left = (end_dt - datetime.now(timezone.utc)).days
            return end_dt.strftime("%Y-%m-%d"), max(0, days_left)
        except ValueError:
            pass
    return fetch_market_resolution(entry.get("condition_id", ""))


def build_quote_loop(
    yes_token: str,
    no_token: str,
    condition_id: str,
    title: str,
    client: ClobClient,
    fee_model: FeeModel,
    args: argparse.Namespace,
    portfolio: PortfolioConstraints | None = None,
    days_to_resolution: int = 9999,
    event_key: str = "",
) -> QuoteLoop:
    """Construct a QuoteLoop for one market from CLI args."""
    config = QuoteLoopConfig(
        market_id=title,
        yes_token_id=yes_token,
        no_token_id=no_token,
        condition_id=condition_id,
        fee_rate=args.fee_rate,
        rebate_fraction=args.rebate,
        half_spread_base=args.half_spread,
        min_edge_floor=args.min_edge,
        quote_size=args.quote_size,
        max_open_positions=args.max_open_positions,
        time_to_resolution_hours=args.time_to_resolution,
        max_loss_fraction=args.max_loss,
        min_viable_size=1.0,
        price_tolerance=0.005,
        order_ttl_seconds=args.order_ttl,
        adverse_selection_threshold=0.012,
        daily_capital_charge_rate=0.0003,
        dry_run=not args.live,
        days_to_resolution=days_to_resolution,
        event_key=event_key,
    )
    return QuoteLoop(config=config, clob_client=client, fee_model=fee_model, portfolio=portfolio)


def seed_fv_from_recent_trades(
    loop: QuoteLoop,
    condition_id: str,
    yes_token_id: str,
    n_trades: int = 50,
) -> int:
    """
    Fetch recent trades from the Data API and seed the QuoteLoop's FV estimator.

    Returns the number of trades seeded.
    """
    log = logging.getLogger("run_live")
    try:
        resp = _requests.get(
            f"{DATA_API}/trades",
            params={"market": condition_id, "limit": n_trades, "takerOnly": "false"},
            timeout=10,
        )
        resp.raise_for_status()
        trades = resp.json()
    except Exception as exc:
        log.warning("FV seed failed for %s: %s", loop.config.market_id[:40], exc)
        return 0

    count = 0
    # Trades come newest-first; feed oldest-first for TWAP to be correct
    yes_trades = [
        t for t in trades
        if str(t.get("asset", t.get("token_id", ""))) == str(yes_token_id)
    ]
    for trade in reversed(yes_trades):
        try:
            ts = datetime.fromtimestamp(
                float(trade.get("timestamp", 0)), tz=timezone.utc
            )
            obs = TradeObservation(
                price=float(trade.get("price", 0)),
                size=float(trade.get("size", 0)),
                timestamp=ts,
            )
            loop._fv_estimator.on_trade(obs)
            count += 1
        except Exception:
            pass

    if count:
        fv = loop._fv_estimator.estimate(as_of=datetime.now(timezone.utc))
        log.info(
            "  FV seeded: %d trades, current FV=%.3f (%s)",
            count, fv or 0.0, loop.config.market_id[:50],
        )
    return count


def load_active_from_universe(universe_path: Path) -> list[dict]:
    """
    Return list of dicts with keys: condition_id, yes_token, no_token, question.
    Only returns active, ingested markets from universe.json.
    """
    from src.data.universe import MarketUniverse
    u = MarketUniverse()
    u.load(universe_path)
    return [
        {
            "condition_id": m.condition_id,
            "yes_token": m.yes_token,
            "no_token": m.no_token,
            "question": m.question,
        }
        for m in u.active_markets()
        if m.ingested
    ]


def _universe_watcher(
    universe_path: Path,
    loops: list,
    token_to_loop: dict,
    client,
    fee_model,
    args: argparse.Namespace,
    stop_event,
    poll_interval: float = 60.0,
) -> None:
    # NOTE: This function is NOT called. The actual watcher is the inline _watch_thread
    # closure defined in main_async(). Kept as a standalone reference implementation.
    """
    Background thread: polls universe.json every poll_interval seconds.
    Adds QuoteLoops for newly active+ingested markets.
    Does not remove loops for expired markets (let them drain naturally).
    """
    import threading
    log = logging.getLogger("universe_watcher")
    known_condition_ids: set[str] = {loop.config.condition_id for loop in loops}

    while not stop_event.is_set():
        stop_event.wait(timeout=poll_interval)
        if stop_event.is_set():
            break
        try:
            entries = load_active_from_universe(universe_path)
            for entry in entries:
                cid = entry["condition_id"]
                if cid in known_condition_ids:
                    continue
                # New market — spin up a QuoteLoop
                yes_token = entry["yes_token"]
                no_token = entry["no_token"]
                question = entry["question"][:80]
                log.info("New market detected: %s", question[:60])

                loop = build_quote_loop(
                    yes_token=yes_token,
                    no_token=no_token,
                    condition_id=cid,
                    title=question,
                    client=client,
                    fee_model=fee_model,
                    args=args,
                )
                seed_fv_from_recent_trades(loop, cid, yes_token)

                loops.append(loop)
                token_to_loop[yes_token] = loop
                known_condition_ids.add(cid)
                log.info("QuoteLoop started for %s", question[:60])
        except Exception as exc:
            log.warning("Universe watcher error: %s", exc)


def print_startup_banner(loops: list[QuoteLoop], dry_run: bool) -> None:
    log = logging.getLogger("run_live")
    mode = "DRY-RUN (no orders will be placed)" if dry_run else "*** LIVE TRADING ***"
    log.info("=" * 60)
    log.info("Polymarket Market Maker — %s", mode)
    log.info("=" * 60)
    log.info("Markets (%d):", len(loops))
    for loop in loops:
        log.info("  %s", loop.config.market_id[:70])
    log.info("=" * 60)


def print_stats(loops: list[QuoteLoop]) -> None:
    log = logging.getLogger("run_live")
    log.info("--- STATS ---")
    total_pnl = 0.0
    for loop in loops:
        s = loop.stats
        log.info(
            "  %-40s updates=%d quotes=%d fills=%d takers=%d mm_cycles=%d open=%d pnl=%.4f errors=%d",
            loop.config.market_id[:40],
            s.book_updates, s.quotes_computed, s.fills_received,
            s.takers_filled, s.maker_maker_cycles, s.open_positions,
            s.total_pnl, s.errors,
        )
        total_pnl += s.total_pnl
    log.info("  TOTAL PnL (approx): %.4f", total_pnl)


async def _poll_fills_loop(
    client: ClobClient,
    loops: list[QuoteLoop],
    token_to_loop: dict[str, QuoteLoop],
    stop_event: asyncio.Event,
    poll_interval_seconds: float = 15.0,
) -> None:
    """
    Periodically poll the CLOB for new fills (live mode only).
    Routes fill events to the appropriate QuoteLoop.
    """
    log = logging.getLogger("run_live")
    from src.data.schemas import Fill, Side

    seen_fill_ids: set[str] = set()

    while not stop_event.is_set():
        await asyncio.sleep(poll_interval_seconds)
        if stop_event.is_set():
            break
        try:
            # Get recent trades for the account
            py_client = client._get_py_client()
            raw_trades = py_client.get_trades() or []

            for trade in raw_trades:
                trade_id = trade.get("id", trade.get("transactionHash", ""))
                if not trade_id or trade_id in seen_fill_ids:
                    continue
                seen_fill_ids.add(trade_id)

                token_id = trade.get("asset_id", "")
                loop = token_to_loop.get(token_id)
                if loop is None:
                    continue

                try:
                    # Determine YES/NO token_side from which token was traded
                    token_side = "YES" if token_id == loop.config.yes_token_id else "NO"
                    trade_side = trade.get("side", "").upper()
                    fill = Fill(
                        fill_id=trade_id,
                        market_id=loop.config.condition_id,
                        side=Side.BUY if trade_side == "BUY" else Side.SELL,
                        price=float(trade.get("price", 0)),
                        size=float(trade.get("size", 0)),
                        timestamp=datetime.fromtimestamp(
                            float(trade.get("match_time", trade.get("timestamp", 0))),
                            tz=timezone.utc,
                        ),
                        is_maker=trade.get("maker_order_id") is not None,
                        token_side=token_side,
                    )
                    # Only route our maker fills — taker fills are the hedge we placed
                    if fill.is_maker:
                        log.info(
                            "[%s] MAKER FILL via poll: %s %s price=%.3f size=%.1f",
                            loop.config.market_id[:40], token_side,
                            fill.side.value, fill.price, fill.size,
                        )
                        loop.on_fill(fill)
                except Exception as exc:
                    log.warning("Fill parse error: %s | trade=%s", exc, str(trade)[:100])
        except Exception as exc:
            log.warning("Fill poll error: %s", exc)


async def main_async(args: argparse.Namespace) -> None:
    log = logging.getLogger("run_live")

    # Load credentials (required even for dry-run to test connection)
    if args.live:
        try:
            creds = load_credentials()
            client = ClobClient(credentials=creds)
            log.info("Credentials loaded (LIVE mode)")
        except CredentialError as exc:
            log.error("Cannot start live trading: %s", exc)
            sys.exit(1)
    else:
        client = ClobClient()   # no auth needed for dry-run (public endpoints)
        log.info("No credentials loaded (dry-run mode)")

    fee_model = FeeModel()

    # Shared portfolio constraints (enforced across all active QuoteLoops)
    portfolio = PortfolioConstraints(
        total_capital=getattr(args, "total_capital", 10_000.0),
        max_long_term_fraction=getattr(args, "max_long_term_fraction", 0.80),
        max_event_notional=getattr(args, "max_event_notional", 3_000.0),
    )
    log.info(
        "Portfolio caps: long-term <=%.0f%% of $%.0f (<=$%.0f), event <=$%.0f",
        portfolio.max_long_term_fraction * 100,
        portfolio.total_capital,
        portfolio.max_long_term_notional,
        portfolio.max_event_notional,
    )

    # Discover markets
    if args.universe:
        entries = load_active_from_universe(Path(args.universe))
        if not entries:
            log.error("No active+ingested markets found in %s", args.universe)
            sys.exit(1)
        log.info("Universe mode: %d active markets from %s", len(entries), args.universe)
        market_paths = None
    elif args.markets:
        market_paths = [Path(m) for m in args.markets]
        entries = None
    else:
        data_dir = Path(args.data)
        if not data_dir.exists():
            log.error("Data directory %s not found", data_dir)
            sys.exit(1)
        market_paths = discover_markets(data_dir)
        entries = None

    if not args.universe and not market_paths:
        log.error("No markets found. Use --universe, --data, or --markets.")
        sys.exit(1)

    loops: list[QuoteLoop] = []
    token_ids: list[str] = []

    if args.universe:
        # Universe mode: tokens come directly from universe.json
        for entry in entries:
            yes_token = entry["yes_token"]
            no_token = entry["no_token"]
            condition_id = entry["condition_id"]
            title = entry["question"][:80]
            event_key, days_left = resolution_from_universe_entry(entry)
            loop = build_quote_loop(
                yes_token, no_token, condition_id, title, client, fee_model, args,
                portfolio=portfolio, days_to_resolution=days_left, event_key=event_key,
            )
            loops.append(loop)
            token_ids.extend([yes_token, no_token])
            time.sleep(0.05)
    else:
        # Existing path: resolve from .jsonl files
        log.info("Resolving %d markets...", len(market_paths))
        for path in market_paths:
            result = resolve_market_tokens(path, client)
            if result is None:
                log.warning("Skipping unresolvable market: %s", path.stem[:40])
                continue
            yes_token, no_token, condition_id, title = result
            event_key, days_left = fetch_market_resolution(condition_id)
            loop = build_quote_loop(
                yes_token, no_token, condition_id, title, client, fee_model, args,
                portfolio=portfolio, days_to_resolution=days_left, event_key=event_key,
            )
            loops.append(loop)
            token_ids.extend([yes_token, no_token])
            time.sleep(0.1)

    if not loops:
        log.error("No markets could be resolved. Exiting.")
        sys.exit(1)

    # Seed fair-value estimators with recent trade history so quotes start immediately
    log.info("Seeding fair-value estimators from recent trades...")
    for loop in loops:
        seed_fv_from_recent_trades(
            loop,
            condition_id=loop.config.condition_id,
            yes_token_id=loop.config.yes_token_id,
        )
        time.sleep(0.15)  # rate limit

    print_startup_banner(loops, dry_run=not args.live)

    # Build token→loop mapping for callbacks.
    # Both YES and NO tokens map to the same loop — routing is done by token_id.
    token_to_loop: dict[str, QuoteLoop] = {}
    for loop in loops:
        token_to_loop[loop.config.yes_token_id] = loop
        token_to_loop[loop.config.no_token_id] = loop

    # Set up book feed
    feed = BookFeed(token_ids=token_ids)

    def on_book_update(token_id: str, book):
        loop = token_to_loop.get(token_id)
        if loop is None:
            return
        if token_id == loop.config.yes_token_id:
            loop.on_yes_book_update(token_id, book)
        else:
            loop.on_no_book_update(token_id, book)

    def on_trade_update(token_id: str, price: float, size: float):
        loop = token_to_loop.get(token_id)
        if loop is None:
            return
        loop.on_trade(token_id, price, size)

    feed.on_any_book_update(on_book_update)
    feed.on_any_trade(on_trade_update)

    # Graceful shutdown
    stop_event = asyncio.Event()
    import threading as _threading
    _thread_stop = _threading.Event()

    def _signal_handler(sig, frame):
        log.info("Shutdown signal received, stopping...")
        stop_event.set()
        _thread_stop.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Run feed until stop, with periodic fill polling for live mode
    feed_task = asyncio.create_task(feed.run())

    if args.live:
        fill_poll_task = asyncio.create_task(
            _poll_fills_loop(client, loops, token_to_loop, stop_event)
        )
    else:
        fill_poll_task = None

    # Universe watcher: polls universe.json for new markets every 60s
    watcher_thread = None
    if args.universe:
        import threading

        def _watch_thread():
            import time as _time
            log_w = logging.getLogger("universe_watcher")
            known_condition_ids: set[str] = {loop.config.condition_id for loop in loops}
            while not _thread_stop.is_set():
                _time.sleep(60)
                if _thread_stop.is_set():
                    break
                try:
                    entries_new = load_active_from_universe(Path(args.universe))
                    for entry in entries_new:
                        cid = entry["condition_id"]
                        if cid in known_condition_ids:
                            continue
                        yes_token = entry["yes_token"]
                        no_token = entry["no_token"]
                        question = entry["question"][:80]
                        log_w.info("New market detected: %s", question[:60])
                        ev_key, d_left = resolution_from_universe_entry(entry)
                        loop = build_quote_loop(
                            yes_token, no_token, cid, question, client, fee_model, args,
                            portfolio=portfolio, days_to_resolution=d_left, event_key=ev_key,
                        )
                        seed_fv_from_recent_trades(loop, cid, yes_token)
                        loops.append(loop)
                        token_to_loop[yes_token] = loop
                        known_condition_ids.add(cid)
                        feed.add_token(yes_token)
                        feed.add_token(no_token)
                        log_w.info(
                            "QuoteLoop started for %s (will subscribe on next WS reconnect)",
                            question[:60],
                        )
                except Exception as exc:
                    log_w.warning("Watcher error: %s", exc)

        watcher_thread = threading.Thread(target=_watch_thread, daemon=True, name="universe-watcher")
        watcher_thread.start()
        log.info("Universe watcher started (polling every 60s)")

    log.info("Book feed started. Waiting for market data...")
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        _thread_stop.set()
        feed.stop()
        feed_task.cancel()
        if fill_poll_task:
            fill_poll_task.cancel()
        for task in [feed_task, fill_poll_task]:
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    print_stats(loops)
    log.info("Shutdown complete.")


def main():
    parser = argparse.ArgumentParser(description="Polymarket live market maker")
    parser.add_argument(
        "--live", action="store_true", default=False,
        help="Enable live order placement (default: dry-run, no orders placed)"
    )
    parser.add_argument(
        "--data", default="data/raw",
        help="Directory with .jsonl market data (default: data/raw)"
    )
    parser.add_argument(
        "--markets", nargs="+",
        help="Specific .jsonl paths to trade (overrides --data)"
    )
    parser.add_argument(
        "--universe", type=str, default=None,
        help="Path to universe.json — trade all active+ingested markets dynamically"
    )
    parser.add_argument("--quote-size", type=float, default=100.0)
    parser.add_argument("--half-spread", type=float, default=0.030)
    parser.add_argument("--fee-rate", type=float, default=0.07)
    parser.add_argument("--rebate", type=float, default=0.5)
    parser.add_argument("--min-edge", type=float, default=0.005)
    parser.add_argument("--max-open-positions", type=int, default=4,
                        help="Pause new quotes when this many unhedged fills exist (default 4)")
    parser.add_argument("--time-to-resolution", type=float, default=720.0,
                        help="Hours to resolution (default 720 = 30 days)")
    parser.add_argument("--max-loss", type=float, default=0.10,
                        help="Max taker hedge loss fraction tolerated before parking fill (default 0.10)")
    parser.add_argument("--order-ttl", type=float, default=300.0,
                        help="Seconds before a resting order is cancelled and re-quoted (default 300)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--total-capital", type=float, default=10_000.0,
                        help="Total wallet capital in USDC (default 10000)")
    parser.add_argument("--max-long-term-fraction", type=float, default=0.80,
                        help="Max fraction of capital in >30-day positions (default 0.80)")
    parser.add_argument("--max-event-notional", type=float, default=0.0,
                        help="Max USDC per event group (default 0=disabled). "
                             "CAUTION: events are currently grouped by resolution "
                             "DATE, so this caps ALL markets resolving the same "
                             "day collectively — only enable if that is intended.")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.live:
        log = logging.getLogger("run_live")
        log.warning("=" * 60)
        log.warning("LIVE MODE ENABLED — orders WILL be placed on Polymarket")
        log.warning("Press Ctrl-C within 5 seconds to abort...")
        log.warning("=" * 60)
        time.sleep(5)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
