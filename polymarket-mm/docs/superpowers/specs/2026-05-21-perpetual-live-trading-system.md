# Perpetual Live Trading System — Design Spec

**Date:** 2026-05-21  
**Status:** Approved  

---

## Goal

Build a fully automated, perpetual market-making system for Polymarket that:
1. Discovers and scores all active markets continuously (1,000+ markets across all categories)
2. Batch-ingests historical data to power a comprehensive backtest across 200–300 markets
3. Runs as a live trading daemon that auto-discovers new qualifying markets, starts trading them, and retires expired ones — without manual intervention

---

## Background: What We Know From Current Backtest

- 37 markets, 30 days, 49 fills → too small to be statistically meaningful
- Strategy is structurally correct: 100% win rate on 42 completed cycles
- Key discovery: fills only come from **oscillating markets** (price std > 0.05), not trending ones
- Fill-triggering trades are all ≤100 contracts (small retail), so quote size doesn't scale PnL
- Iran/Hormuz markets (std ~0.03, slow trend) generate almost no fills
- Best performers (sports, crypto): std > 0.05, 1,500+ trades/month
- PnL is flat across half-spread 0.010–0.030 (already at efficiency frontier for these markets)
- Scaling path: **more qualifying markets**, not bigger quote sizes or tighter spreads

---

## Architecture

```
BACKTEST MODE                      LIVE MODE
──────────────────────────────────────────────────────────
Gamma API (1,000+ markets)         Gamma API (1,000+ markets)
     ↓ paginate all (one-shot)           ↓ poll every 4 hours
  Market Scorer                       Market Scorer
  • price std (Data API)               • same scoring
  • exit liquidity (CLOB L2)           • same scoring
  • trade frequency (Data API)         • same scoring
     ↓ top 300 by score                   ↓ qualifying markets
  Batch Ingester                      Auto-Ingester (7-day warm-up)
  • 90 days history                       • then start trading
  • 4 parallel workers                    ↓
     ↓                               Live Quote Loops (N markets)
  Portfolio Backtest                   run_live.py (dynamic universe)
  run_portfolio_analysis.py
```

---

## Scoring Model

### Signals

| Signal | Source | Minimum threshold |
|--------|--------|-------------------|
| Price volatility (std) | Last 200 trades, Data API | std > 0.03 |
| Exit liquidity | Live L2 book, CLOB API | max_quotable > 20 contracts |
| Trade frequency | Trades in last 24h, Data API | > 30 trades/day |
| Time to resolution | Gamma API end_date | > 1.0 days remaining |

### Composite Score

```python
volatility_multiplier = min(std / 0.05, 2.0)
score = log1p(volume_24h) * max_quotable * volatility_multiplier
```

- Markets with std ≥ 0.05 get up to a 2× bonus over baseline
- Markets with std < 0.03 score near zero (filtered out)
- Zero exit liquidity = score of zero regardless of volatility

### Market Categories

All Polymarket categories are included. The scoring model is the filter — no category exclusions. Sports markets (high std, high frequency) are expected to dominate; political trending events (low std) will self-filter.

---

## New Components

### `src/data/universe.py` — MarketUniverse

Manages the scored market list. Persists to `data/universe.json`.

```python
@dataclass
class ScoredMarket:
    condition_id: str
    slug: str
    question: str
    yes_token: str
    no_token: str
    score: float
    volatility_std: float
    volume_24h: float
    max_quotable: float
    trades_per_day: float
    end_date: str
    days_to_resolution: float
    status: str  # "active" | "expired" | "below_threshold"
    last_scored_at: str  # ISO timestamp
    ingested: bool

class MarketUniverse:
    def load(self, path: Path) -> None
    def save(self, path: Path) -> None
    def update(self, market: ScoredMarket) -> None
    def active_markets(self) -> list[ScoredMarket]
    def markets_needing_ingest(self) -> list[ScoredMarket]
```

### `scripts/build_universe.py` — One-Shot Backtest Prep

```
py -3 scripts/build_universe.py [--pages all] [--volatility] [--top 300] [--days 90] [--workers 4]
```

1. Paginates all Gamma API markets (handles all pages, all categories)
2. For each market: fetches exit liquidity (CLOB) + volatility (Data API last 200 trades)
3. Scores and ranks all markets
4. Writes `data/universe.json`
5. Batch-ingests top-N markets with `--days` of history using `--workers` parallel workers
6. Prints a summary: markets scanned, qualifying, ingested, skipped (already have data)

Flags:
- `--pages N` or `--pages all` — how many Gamma pages to scan (100 markets per page)
- `--volatility` — fetch recent trades for price std (slower but essential)
- `--top N` — ingest only the top N markets by score (default 300)
- `--days N` — history window for ingestion (default 90)
- `--workers N` — parallel ingest workers (default 4)
- `--skip-ingest` — score and export only, don't download data
- `--min-std FLOAT` — volatility threshold (default 0.03)
- `--min-quotable FLOAT` — exit liquidity threshold (default 20)

### `scripts/run_discovery.py` — Perpetual Live Daemon

```
py -3 scripts/run_discovery.py [--interval 14400] [--dry-run]
```

Runs forever. Every `--interval` seconds (default 4 hours):
1. Re-scans all Gamma markets (paginated)
2. Re-scores all markets
3. Updates `data/universe.json`:
   - New qualifying markets → status=active, ingest=False
   - Markets dropping below threshold → status=below_threshold
   - Markets past end_date → status=expired
4. For newly active markets: auto-ingests last 7 days of history
5. Rewrites `data/universe.json` — `run_live.py` polls this file

Does NOT place any orders itself. Purely a discovery/data layer.

### Modified: `scripts/ingest_history.py`

Add two new flags:
- `--from-universe FILE` — reads `data/universe.json`, ingests all `ingested=False` markets
- `--workers N` — parallel ingestion with N workers (default 1, max 8)
- `--skip-existing` — don't re-ingest markets that already have a `.jsonl` file (default True)

Rate limiting: 0.5s delay between API calls per worker (existing `--delay` flag extended to parallel case).

### Modified: `scripts/scan_markets.py`

Add:
- `--all` flag — paginate through ALL Gamma markets instead of `--limit N`
- `--volatility` flag — fetch last 200 trades per market for price std (shown as `Std` column)
- `--export FILE` — write scored results to JSON file for use by `build_universe.py`
- `Std` column in output table (hidden if `--volatility` not passed)

### Modified: `scripts/run_live.py`

Add:
- `--universe FILE` — watch `data/universe.json`, trade all active markets dynamically
- Background thread polls `universe.json` every 60 seconds
- New active markets: ingest 7-day warm-up window, then spin up QuoteLoop
- Expired/removed markets: gracefully shut down QuoteLoop, log final position

---

## Data Flow: Backtest Prep

```
1. py -3 scripts/build_universe.py --pages all --volatility --top 300 --days 90
   → Scans 1,000+ markets (~30 min including volatility fetch)
   → Writes data/universe.json
   → Ingests 90 days for top 300 markets (~2-4 hours, parallel)

2. py -3 scripts/run_portfolio_analysis.py --data data/raw --twap-window 3600
   → Runs backtest across all 300 markets
   → Expected: 500-1,500 fills (statistically meaningful)
   → Report shows per-category breakdown
```

## Data Flow: Live Trading

```
1. py -3 scripts/run_discovery.py  (runs forever, updates universe.json every 4h)
   
2. py -3 scripts/run_live.py --universe data/universe.json --dry-run
   (or --live for real orders)
```

---

## universe.json Format

```json
{
  "last_updated": "2026-05-21T14:30:00Z",
  "total_scored": 1247,
  "active_count": 47,
  "markets": [
    {
      "condition_id": "0xabc...",
      "slug": "nba-celtics-heat-2026-05-22",
      "question": "Will the Celtics beat the Heat on May 22?",
      "yes_token": "1234...",
      "no_token": "5678...",
      "score": 847.3,
      "volatility_std": 0.142,
      "volume_24h": 45000.0,
      "max_quotable": 100.0,
      "trades_per_day": 312.0,
      "end_date": "2026-05-22",
      "days_to_resolution": 0.9,
      "status": "active",
      "last_scored_at": "2026-05-21T14:30:00Z",
      "ingested": true
    }
  ]
}
```

---

## Backtest Limitations (Cannot Be Fixed Without Live Data)

| Limitation | Impact on PnL estimate | Mitigation in design |
|-----------|----------------------|---------------------|
| Synthetic NO books (fixed spread around YES price) | Real flatten price may be 10–30% worse | Use `--spread 0.03` for conservative synthetic books |
| FRONT queue assumption in fill model | Real fill rate likely 30–60% of backtest | Run backtest with `--queue-model pro_rata` to get lower bound |
| No capital lock-up modeling | Backtest overstates throughput when many markets fill simultaneously | Portfolio-level capital cap in `PortfolioConfig` |
| AS detection lag | Some adverse fills not caught | The AS threshold tuning in live system is the real fix |

**The 2–4 week dry-run after backtest validation is the only way to quantify these gaps.**

---

## Scope Boundaries (Out of Scope)

- Position management UI / dashboard
- Database storage (flat files are sufficient for validation phase)
- Multi-exchange support
- Order amendment / partial cancel logic
- Sophisticated queue position modeling

---

## Success Criteria for Backtest Validation

The backtest is considered validated when:
1. ≥ 500 total fills across ≥ 150 markets over 90-day window
2. Win rate ≥ 95% (allowing for a few edge cases)
3. ≥ 3 market categories represented (e.g., sports, crypto, politics)
4. Positive PnL in each calendar month of the 90-day window (no single bad month)
5. Fill rate consistent across time (not concentrated in one period)
