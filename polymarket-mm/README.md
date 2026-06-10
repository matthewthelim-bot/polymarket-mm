# polymarket-mm

Market-making system for Polymarket binary markets. Rests passive maker orders
on both books (YES and NO), hedges each maker fill with an immediate taker IOC
on the opposite token, and earns the spread plus maker rebates when the
combined cost of the two legs is below $1.00 (long) or the combined proceeds
above $1.00 (short).

The repo contains three layers that share the same strategy code:

1. **Data pipeline** — discovers markets, downloads history, records live books
2. **Backtester** — replays recorded books/trades through the simulator
3. **Live trading** — same quoting logic against the real CLOB

```
                Gamma API / Data API            CLOB WebSocket
                       │                              │
   scan_markets ──► universe.json ◄── run_discovery   │
        │                  │                          │
   ingest_history     run_live ──► QuoteLoop     collect_books (EC2)
        │                  │                          │
   data/raw/*.jsonl   real orders               data/live/DATE/*.jsonl
        │                                             │
        └────────────► BacktestSimulator ◄────────────┘
```

## Layout

| Path | Purpose |
|------|---------|
| `src/data/` | Schemas (`OrderBook`, `Fill`, `Side`), JSONL loader, `MarketUniverse` |
| `src/strategy/` | Fair value estimator, regime classifier, hedgeability, quote engine, inventory |
| `src/backtest/` | `BacktestSimulator` (dual-book maker-taker), fill/queue models, adverse-selection tracker, portfolio sim, sweep |
| `src/live/` | `BookFeed` (WS), `ClobClient`, `QuoteLoop`, `PortfolioConstraints`, credentials, exit checker |
| `src/fee_model.py` | Maker rebates and taker fees |
| `src/pnl.py` | PnL engine |
| `scripts/` | Entry points (below) |
| `data/raw/` | Ingested trade history + synthetic books (one `.jsonl` per market) |
| `data/live/` | Collector output, `YYYY-MM-DD/{condition_id}.jsonl` |
| `data/universe.json` | Scored market universe (input to live trading and ingestion) |

## Scripts

### Pipeline (run in this order for a fresh setup)

| Script | What it does |
|--------|-------------|
| `build_universe.py` | One shot: scan all Gamma markets → score → write `universe.json` → bulk ingest history |
| `scan_markets.py` | Scan/score markets (`--all`, `--volatility`, `--export universe.json`) |
| `ingest_history.py` | Download trade history per market (`--from-universe`, `--workers N`) |
| `run_discovery.py` | Perpetual daemon: re-score every 4 h, promote/demote universe entries |
| `collect_books.py` | Record live books + trades over WebSocket (runs on EC2, see Ops) |

### Analysis

| Script | What it does |
|--------|-------------|
| `run_backtest.py` | Single-market backtest from `data/raw` |
| `run_live_backtest.py` | Backtest against `data/live` collector data (syncs from EC2 first; `--no-sync` to skip; `--capital N`) |
| `run_portfolio_analysis.py` | Portfolio-level backtest across markets |
| `run_sensitivity.py` | Sweeps total capital × long-term cap fraction over live data |
| `run_sweep.py` | Sobol parameter sweep (spread, edge floor) on one market |
| `check_exit_liquidity.py` | Diagnostic: can a position be exited at acceptable cost? |
| `filter_untagged_books.py` | One-time repair tool for JSONL files contaminated by overlapping collectors |

### Live trading

```
py -3 scripts/run_live.py --universe data/universe.json            # DRY RUN (default)
py -3 scripts/run_live.py --universe data/universe.json --live    # real orders
```

`--dry-run` is the default; real orders require the explicit `--live` flag.
Useful flags: `--total-capital`, `--max-long-term-fraction`,
`--max-event-notional` (see caveat in `--help`), `--quote-size`, `--order-ttl`.

## Strategy summary

- **Quoting**: a 5-level ladder per side, offsets `0.030 + n*0.010` from fair
  value, size ratios `[1.0, 1.5, 2.0, 2.5, 3.0]` scaled by half the market's
  average trade size (clamped to [5, 500] contracts).
- **Cycle**: maker fill → immediate taker IOC hedge on the opposite token.
  Bid-arb (cost < $1) opens/closes longs; ask-arb (proceeds > $1)
  opens/closes shorts. Round-trip PnL is finalised on close; unclosed
  positions settle at $1.00 at resolution.
- **Risk caps** (`PortfolioConstraints`, shared across all markets):
  - Long-term cap: ≤ 30 % of capital in positions resolving > 30 days out
    (liquidity guard — keeps the wallet free for fast-recycling short-duration
    markets). Short-duration positions (< 30 days) are uncapped by this rule.
  - Per-market notional cap, and an optional per-event cap.
  - Caps are enforced **at quote time** (suppression), never at fill time —
    a fill that lands is always recorded.
- **Fees**: maker rebates accrue, taker fees are paid on the hedge leg; both
  are modelled in backtests via `FeeModel`.

## Data formats

One JSON event per line, two event types, identical in `data/raw` and `data/live`:

```json
{"event_type":"book","market_id":"0x…","token_side":"YES","timestamp":"…","bids":[{"price":0.52,"size":120}],"asks":[…]}
{"event_type":"trade","market_id":"0x…","timestamp":"…","side":"YES","price":0.53,"size":40,"is_maker":false}
```

The backtester requires a **dual book** (YES and NO snapshots plus at least
one trade) to simulate a market.

## EC2 collector ops

The collector runs as a systemd service on the EC2 box (`/opt/polymarket-mm`):

```
sudo systemctl status polymarket-collector
sudo journalctl -u polymarket-collector -n 50 --no-pager
```

Service flags: `--min-volume 1000 --refresh-interval 60 --stats-interval 300`
(plus `--std-shards 3` default).

**Multiple WebSocket connections** (important): Polymarket's WS pushes events
for only ~50 active markets per connection, no matter how many tokens you
subscribe. The collector therefore runs five connections:

- 3 standard-market shards, split by 24 h-volume tier (`--std-shards`)
- high-frequency series (5 m/15 m BTC/ETH/SOL/XRP up-or-down)
- low-frequency series (daily up-or-down, MLB, UFC, weekly strikes)

Each connection captures its own top-50, so series markets are not crowded
out by global-volume leaders, and standard coverage scales with shard count.
New series windows are discovered by the refresh thread (60 s) and subscribed
on the next WS reconnect (~5 min).

A health-check cron (`collector_healthcheck.sh`, every 10 min) restarts the
service if today's data dir has no writes for 10 minutes; it logs to
`/var/log/polymarket-healthcheck.log`.

To deploy a collector change: copy `scripts/collect_books.py` to the box,
`sudo systemctl restart polymarket-collector`, then confirm all five
"Subscribed to book channel" lines appear in the journal.

## Known API quirks (hard-won — do not rediscover)

- **Gamma `?condition_id=` filter is broken server-side**: it ignores the
  filter and returns an unrelated market. Look markets up by condition id via
  CLOB REST instead: `https://clob.polymarket.com/markets/{condition_id}`.
- **Gamma pagination 422s** beyond `offset=10100`; treat it as end-of-pages.
- **CLOB REST book arrays are unsorted** — `bids[0]` is *not* the best bid.
  Sort descending (bids) / ascending (asks) first. The WS feed has the same
  property; `BookFeed` sorts on ingest.
- **WS per-connection market throttle** (~50): see EC2 ops above.
- **Series markets never appear in the volume scan** — each 5-minute window
  is a brand-new market with no volume history. They must be discovered via
  `?series_slug=` queries (see `TRACKED_SERIES` in `collect_books.py`), with
  `end_date_min=today` to exclude stale never-closed windows.

## Credentials & safety

- All secrets live in `Code/.env` and are loaded only through
  `src/live/credentials.py`. Never log or commit `PRIVATE_KEY`,
  `POLY_ADDRESS`, `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE`.
- `run_live.py` defaults to dry-run; `--live` is required for real orders.

## Tests

```
py -3 -m pytest -q          # full suite
```

Strategy and simulator logic is unit-tested; the network-heavy scripts
(scan/ingest/collect) are integration-tested by use.
