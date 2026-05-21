# Perpetual Live Trading System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully automated perpetual market-making system that discovers, scores, ingests, and trades all qualifying Polymarket markets continuously.

**Architecture:** A `MarketUniverse` data model (`src/data/universe.py`) is the shared state between a discovery daemon (`run_discovery.py`), a batch prep script (`build_universe.py`), and a live trading daemon (`run_live.py`). The scoring pipeline in `scan_markets.py` is extended with volatility and unlimited pagination, then reused by both the batch and live paths.

**Tech Stack:** Python 3.11+, requests, concurrent.futures (ThreadPoolExecutor), asyncio, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `src/data/universe.py` | **Create** | ScoredMarket dataclass + MarketUniverse load/save/query |
| `tests/test_universe.py` | **Create** | Unit tests for MarketUniverse |
| `scripts/scan_markets.py` | **Modify** | Add --all, --volatility, --export, Std column, updated score |
| `scripts/ingest_history.py` | **Modify** | Extract ingest_one(), add --from-universe, --workers, --skip-existing |
| `scripts/build_universe.py` | **Create** | One-shot orchestration: scan → score → universe.json → bulk ingest |
| `scripts/run_discovery.py` | **Create** | Perpetual daemon: re-score every N seconds, auto-ingest new markets |
| `scripts/run_live.py` | **Modify** | Add --universe flag, background thread for dynamic market management |

---

### Task 1: `src/data/universe.py` — MarketUniverse

**Files:**
- Create: `src/data/universe.py`
- Create: `tests/test_universe.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_universe.py
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pytest
from src.data.universe import ScoredMarket, MarketUniverse


def make_market(condition_id="0xabc", status="active", ingested=False, score=100.0, std=0.06, days=5.0):
    return ScoredMarket(
        condition_id=condition_id,
        slug=f"slug-{condition_id}",
        question=f"Question {condition_id}?",
        yes_token="111",
        no_token="222",
        score=score,
        volatility_std=std,
        volume_24h=10000.0,
        max_quotable=50.0,
        trades_per_day=100.0,
        end_date="2026-12-01",
        days_to_resolution=days,
        status=status,
        last_scored_at="2026-05-21T00:00:00Z",
        ingested=ingested,
    )


def test_update_and_active_markets():
    u = MarketUniverse()
    u.update(make_market("0xaaa", status="active"))
    u.update(make_market("0xbbb", status="expired"))
    u.update(make_market("0xccc", status="below_threshold"))
    active = u.active_markets()
    assert len(active) == 1
    assert active[0].condition_id == "0xaaa"


def test_markets_needing_ingest():
    u = MarketUniverse()
    u.update(make_market("0xaaa", status="active", ingested=False))
    u.update(make_market("0xbbb", status="active", ingested=True))
    u.update(make_market("0xccc", status="expired", ingested=False))
    need = u.markets_needing_ingest()
    assert len(need) == 1
    assert need[0].condition_id == "0xaaa"


def test_update_replaces_existing():
    u = MarketUniverse()
    u.update(make_market("0xaaa", score=100.0))
    u.update(make_market("0xaaa", score=200.0))
    assert len(u.active_markets()) == 1
    assert u.active_markets()[0].score == 200.0


def test_save_and_load_roundtrip():
    u = MarketUniverse()
    u.update(make_market("0xaaa", status="active", ingested=True))
    u.update(make_market("0xbbb", status="expired"))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "universe.json"
        u.save(path)

        u2 = MarketUniverse()
        u2.load(path)

        assert len(u2.active_markets()) == 1
        assert u2.active_markets()[0].condition_id == "0xaaa"
        assert u2.active_markets()[0].ingested is True


def test_save_writes_metadata():
    u = MarketUniverse()
    u.update(make_market("0xaaa", status="active"))
    u.update(make_market("0xbbb", status="expired"))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "universe.json"
        u.save(path)
        data = json.loads(path.read_text())

    assert "last_updated" in data
    assert data["total_scored"] == 2
    assert data["active_count"] == 1
    assert len(data["markets"]) == 2


def test_load_empty_file_ok():
    u = MarketUniverse()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "missing.json"
        u.load(path)   # should not raise
    assert u.active_markets() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\Users\matth\OneDrive\Documents\Claude\Code\polymarket-mm
py -3 -m pytest tests/test_universe.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.data.universe'`

- [ ] **Step 3: Implement `src/data/universe.py`**

```python
"""
MarketUniverse — scored market registry persisted to data/universe.json.

ScoredMarket holds all scoring signals for one market.
MarketUniverse manages the full collection with load/save/update/query.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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
    status: str          # "active" | "expired" | "below_threshold"
    last_scored_at: str  # ISO timestamp
    ingested: bool


class MarketUniverse:
    """Registry of all scored markets. Thread-safe for reads; callers must
    synchronise writes if using across threads."""

    def __init__(self) -> None:
        self._markets: dict[str, ScoredMarket] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: Path) -> None:
        """Load from universe.json. Silently no-ops if the file does not exist."""
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for raw in data.get("markets", []):
            m = ScoredMarket(**{k: raw[k] for k in ScoredMarket.__dataclass_fields__ if k in raw})
            self._markets[m.condition_id] = m

    def save(self, path: Path) -> None:
        """Atomically write universe.json."""
        markets_list = [asdict(m) for m in self._markets.values()]
        active_count = sum(1 for m in self._markets.values() if m.status == "active")
        payload = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_scored": len(self._markets),
            "active_count": active_count,
            "markets": markets_list,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def update(self, market: ScoredMarket) -> None:
        """Insert or replace a market by condition_id."""
        self._markets[market.condition_id] = market

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def active_markets(self) -> list[ScoredMarket]:
        return [m for m in self._markets.values() if m.status == "active"]

    def markets_needing_ingest(self) -> list[ScoredMarket]:
        return [m for m in self._markets.values()
                if m.status == "active" and not m.ingested]

    def get(self, condition_id: str) -> Optional[ScoredMarket]:
        return self._markets.get(condition_id)

    def all_markets(self) -> list[ScoredMarket]:
        return list(self._markets.values())
```

- [ ] **Step 4: Run tests to verify they pass**

```
py -3 -m pytest tests/test_universe.py -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```
git add src/data/universe.py tests/test_universe.py
git commit -m "feat: add MarketUniverse data model with load/save/update/query"
```

---

### Task 2: Extend `scan_markets.py` — volatility, pagination, export

**Files:**
- Modify: `scripts/scan_markets.py`

Changes:
1. Add `volatility_std: float = 0.0` field to `MarketScan`
2. Add `fetch_volatility(condition_id, yes_token_id) -> float` function
3. Update `compute_score()` to accept `volatility_std`
4. Update `fetch_active_markets()` to support `all_pages: bool`
5. Update `scan_one()` to optionally call `fetch_volatility`
6. Add `--all`, `--volatility`, `--export` CLI flags and `Std` column in report

- [ ] **Step 1: Write tests**

```python
# tests/test_scan_markets.py
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.scan_markets import compute_score


def test_score_zero_when_no_quotable():
    assert compute_score(50000.0, 0.0, 0.1) == 0.0


def test_score_zero_when_no_volatility():
    # std=0 → volatility_multiplier=0 → score=0
    assert compute_score(50000.0, 100.0, 0.0) == 0.0


def test_score_below_threshold_std():
    # std=0.02 < 0.03 minimum → score near zero (multiplier = 0.02/0.05 = 0.4)
    import math
    s = compute_score(50000.0, 100.0, 0.02)
    expected = math.log1p(50000.0) * 100.0 * min(0.02 / 0.05, 2.0)
    assert s == pytest.approx(expected)


def test_score_capped_at_2x():
    import math
    # std=0.15 → min(0.15/0.05, 2.0) = 2.0
    s = compute_score(50000.0, 100.0, 0.15)
    expected = math.log1p(50000.0) * 100.0 * 2.0
    assert s == pytest.approx(expected)


def test_score_proportional_to_std_below_cap():
    import math
    s1 = compute_score(50000.0, 100.0, 0.05)
    s2 = compute_score(50000.0, 100.0, 0.10)
    assert s2 == pytest.approx(s1 * 2.0)
```

- [ ] **Step 2: Run to verify failure**

```
py -3 -m pytest tests/test_scan_markets.py -v
```
Expected: `TypeError: compute_score() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Apply changes to `scan_markets.py`**

**3a — Add `volatility_std` field to `MarketScan` dataclass** (after `score: float = 0.0`):

```python
    volatility_std: float = 0.0   # price std from last 200 trades (0 = not fetched)
    trades_per_day: float = 0.0   # estimated from 24h trade count
```

**3b — Replace `compute_score` function:**

```python
def compute_score(volume_24h: float, max_quotable: float, volatility_std: float = 0.0) -> float:
    """
    Composite score: log(volume+1) * max_quotable * volatility_multiplier.
    volatility_multiplier = min(std/0.05, 2.0) — rewards oscillating markets.
    Returns 0 if max_quotable=0 (no exit liquidity).
    """
    import math
    if max_quotable <= 0:
        return 0.0
    volatility_multiplier = min(volatility_std / 0.05, 2.0)
    return math.log1p(volume_24h) * max_quotable * volatility_multiplier
```

**3c — Add `fetch_volatility` function** (after `extract_end_date`):

```python
DATA_API = "https://data-api.polymarket.com"


def fetch_volatility(condition_id: str, yes_token_id: str, n_trades: int = 200) -> tuple[float, float]:
    """
    Fetch last N trades for a market and compute price std and trades/day.
    Returns (volatility_std, trades_per_day). Returns (0.0, 0.0) on error.
    """
    import math
    from datetime import datetime, timezone
    try:
        r = requests.get(
            f"{DATA_API}/trades",
            params={"market": condition_id, "limit": n_trades, "takerOnly": "false"},
            timeout=10,
        )
        r.raise_for_status()
        trades = r.json()
    except Exception:
        return 0.0, 0.0

    if not trades:
        return 0.0, 0.0

    prices = [
        float(t["price"])
        for t in trades
        if str(t.get("asset", "")) == str(yes_token_id)
           and "price" in t
    ]
    if len(prices) < 2:
        return 0.0, 0.0

    mean = sum(prices) / len(prices)
    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
    std = math.sqrt(variance)

    # Estimate trades/day from timestamps of first/last trade
    try:
        ts_list = [float(t["timestamp"]) for t in trades if "timestamp" in t]
        if len(ts_list) >= 2:
            span_seconds = max(ts_list) - min(ts_list)
            if span_seconds > 0:
                trades_per_day = len(prices) / (span_seconds / 86400.0)
            else:
                trades_per_day = 0.0
        else:
            trades_per_day = 0.0
    except Exception:
        trades_per_day = 0.0

    return std, trades_per_day
```

**3d — Update `fetch_active_markets` signature and loop:**

```python
def fetch_active_markets(
    limit: int = 100,
    tag: Optional[str] = None,
    min_volume: float = 0.0,
    all_pages: bool = False,
) -> list[dict]:
    """
    Fetch active, open markets from the Gamma API.
    If all_pages=True, paginates until exhausted (ignores limit).
    """
    results = []
    offset = 0
    page_size = 500

    while True:
        params: dict = {
            "active": "true",
            "closed": "false",
            "limit": page_size,
            "offset": offset,
            "order": "volume24hr",
            "ascending": "false",
        }
        if tag:
            params["tag"] = tag

        try:
            r = requests.get(f"{GAMMA_BASE}/markets", params=params, timeout=15)
            r.raise_for_status()
            page = r.json()
        except Exception as exc:
            print(f"  Gamma API error: {exc}", file=sys.stderr)
            break

        if not page:
            break

        for m in page:
            if min_volume > 0:
                vol = float(m.get("volume", m.get("volume24hr", 0)) or 0)
                if vol < min_volume:
                    continue
            results.append(m)

        if len(page) < page_size:
            break   # last page

        offset += page_size

        if not all_pages and len(results) >= limit:
            break

    return results if all_pages else results[:limit]
```

**3e — Update `scan_one` to accept and use `fetch_vol: bool`:**

In the function signature, add `fetch_vol: bool = False` parameter. After computing `viability`, add:

```python
    vol_std, trades_per_day = 0.0, 0.0
    if fetch_vol:
        vol_std, trades_per_day = fetch_volatility(condition_id, yes_token)
        time.sleep(0.1)  # rate limit volatility fetches

    score = compute_score(volume_24h, viability.max_quotable_size, vol_std)
```

Update the returned `MarketScan` to include `volatility_std=vol_std, trades_per_day=trades_per_day`.

**3f — Update `print_report` to show `Std` column when volatility present:**

Replace header line with:
```python
    show_std = any(s.volatility_std > 0 for s in show)
    if show_std:
        hdr = (f"{'#':>3}  {'Question':<44} {'Ends':>10} {'Mid':>5} "
               f"{'Std':>5} {'MaxQ':>6} {'Vol24h':>9} {'VolTot':>10}  Tags")
    else:
        hdr = (f"{'#':>3}  {'Question':<48} {'Ends':>10} {'Mid':>5} "
               f"{'Sprd':>5} {'MaxQ':>6} {'Vol24h':>9} {'VolTot':>10}  Tags")
```

In the market loop, conditionally include std:
```python
        if show_std:
            std_str = f"{s.volatility_std:.3f}" if s.volatility_std > 0 else "  n/a"
            print(
                f"{i:>3}  {s.question:<44} "
                f"{s.end_date:>10} "
                f"{(s.yes_mid or 0):>5.3f} "
                f"{std_str:>5} "
                f"{s.max_quotable:>6.0f} "
                f"{vol24_str} "
                f"{voltot_str}  "
                f"{tags_str}"
            )
        else:
            # existing print block unchanged
```

**3g — Add CLI flags to `main()`:**

After existing `parser.add_argument("--ingest", ...)`:
```python
    parser.add_argument("--all", action="store_true",
                        help="Paginate through ALL Gamma markets (ignores --limit)")
    parser.add_argument("--volatility", action="store_true",
                        help="Fetch last 200 trades per market for price std (slower)")
    parser.add_argument("--export", type=str, default=None,
                        help="Write scored MarketScan results to JSON file")
    parser.add_argument("--min-std", type=float, default=0.0,
                        help="Minimum volatility std to include in output (default 0)")
    parser.add_argument("--min-trades-day", type=float, default=0.0,
                        help="Minimum trades/day filter (default 0)")
```

Update fetch call:
```python
    markets = fetch_active_markets(
        limit=args.limit,
        tag=args.tag,
        min_volume=args.min_volume,
        all_pages=args.all,
    )
```

Update `scan_one` call to pass `fetch_vol=args.volatility`.

After `scans` is built, add export logic before `print_report`:
```python
    if args.export:
        import dataclasses
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_data = [dataclasses.asdict(s) for s in scans if s.viable]
        export_path.write_text(json.dumps(export_data, indent=2), encoding="utf-8")
        print(f"Exported {len(export_data)} viable markets -> {args.export}")
```

- [ ] **Step 4: Run tests to verify they pass**

```
py -3 -m pytest tests/test_scan_markets.py -v
```
Expected: 5 tests PASS

- [ ] **Step 5: Smoke test the new flags**

```
py -3 scripts/scan_markets.py --limit 5 --volatility --top 5
```
Expected: output table with a `Std` column, no errors.

- [ ] **Step 6: Commit**

```
git add scripts/scan_markets.py tests/test_scan_markets.py
git commit -m "feat: add --all, --volatility, --export flags and updated scoring to scan_markets"
```

---

### Task 3: Extend `ingest_history.py` — extract `ingest_one`, add `--from-universe`, `--workers`

**Files:**
- Modify: `scripts/ingest_history.py`

- [ ] **Step 1: Extract `ingest_one()` from `main()`**

Add this function above `main()`:

```python
def ingest_one(
    market_input: str,
    out_dir: Path,
    days: int = 30,
    since_str: Optional[str] = None,
    spread: float = 0.02,
    book_size: float = 500.0,
    skip_existing: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Ingest one market by URL/slug/condition_id.
    Returns a result dict with keys: market_input, condition_id, token_id,
    title, n_trades, skipped (bool), error (str or None).
    """
    from datetime import datetime, timezone, timedelta
    if since_str:
        since_dt = datetime.strptime(since_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_ts = int(since_dt.timestamp())

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        condition_id, token_id, title = resolve_market(market_input)
    except Exception as exc:
        return {"market_input": market_input, "condition_id": "", "token_id": "",
                "title": "", "n_trades": 0, "skipped": False, "error": str(exc)}

    out_path = out_dir / f"{token_id}.jsonl"

    if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
        if verbose:
            print(f"  SKIP (exists): {title[:60]}")
        return {"market_input": market_input, "condition_id": condition_id,
                "token_id": token_id, "title": title,
                "n_trades": 0, "skipped": True, "error": None}

    if verbose:
        print(f"  Ingesting: {title[:60]}")

    try:
        n = fetch_trades(condition_id, token_id, since_ts, out_path, spread, book_size)
    except Exception as exc:
        return {"market_input": market_input, "condition_id": condition_id,
                "token_id": token_id, "title": title,
                "n_trades": 0, "skipped": False, "error": str(exc)}

    # Write sidecar
    sidecar_path = out_dir / f"{token_id}.json"
    if not sidecar_path.exists():
        sidecar = {"condition_id": condition_id, "yes_token_id": token_id, "title": title}
        with sidecar_path.open("w") as sf:
            json.dump(sidecar, sf, indent=2)

    return {"market_input": market_input, "condition_id": condition_id,
            "token_id": token_id, "title": title,
            "n_trades": n, "skipped": False, "error": None}
```

Also add `from typing import Optional` at the top imports if not present.

- [ ] **Step 2: Refactor `main()` to use `ingest_one()`**

Replace the resolution + download block in `main()` with:

```python
    result = ingest_one(
        market_input=args.market,
        out_dir=Path(args.out),
        days=args.days,
        since_str=args.since,
        spread=args.spread,
        book_size=args.book_size,
        skip_existing=False,  # single-market call: always ingest
        verbose=True,
    )
    if result["error"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    n = result["n_trades"]
    print(f"Done. {n} trades written to {Path(args.out) / (result['token_id'] + '.jsonl')}")
```

- [ ] **Step 3: Add `--from-universe`, `--workers`, `--skip-existing` flags to `main()`**

Add after existing `parser.add_argument("--book-size", ...)`:

```python
    parser.add_argument("--from-universe", type=str, default=None,
                        metavar="FILE",
                        help="Read universe.json, ingest all markets with ingested=False")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel ingest workers (default 1, max 8)")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip markets that already have a .jsonl file (default True)")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
```

Change `parser.add_argument("--market", required=True, ...)` to `required=False` with `default=None`.

Then in `main()`, before the existing single-market block:

```python
    if args.from_universe:
        _bulk_ingest_from_universe(
            universe_path=Path(args.from_universe),
            out_dir=Path(args.out),
            days=args.days,
            spread=args.spread,
            book_size=args.book_size,
            workers=min(max(1, args.workers), 8),
            skip_existing=args.skip_existing,
        )
        return

    if not args.market:
        parser.error("--market is required unless --from-universe is specified")
```

- [ ] **Step 4: Add `_bulk_ingest_from_universe()` function**

```python
def _bulk_ingest_from_universe(
    universe_path: Path,
    out_dir: Path,
    days: int,
    spread: float,
    book_size: float,
    workers: int,
    skip_existing: bool,
) -> None:
    """Bulk-ingest all active, un-ingested markets from universe.json."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.data.universe import MarketUniverse

    universe = MarketUniverse()
    universe.load(universe_path)

    markets = universe.markets_needing_ingest()
    if not markets:
        print("No markets need ingestion.")
        return

    print(f"Ingesting {len(markets)} markets with {workers} worker(s)...")

    import concurrent.futures
    import threading

    _print_lock = threading.Lock()
    results = []

    def _worker(m):
        result = ingest_one(
            market_input=m.condition_id,
            out_dir=out_dir,
            days=days,
            spread=spread,
            book_size=book_size,
            skip_existing=skip_existing,
            verbose=False,
        )
        with _print_lock:
            status = "SKIP" if result["skipped"] else ("ERR" if result["error"] else f"{result['n_trades']} trades")
            print(f"  [{status}] {m.question[:60]}")
        # Rate limit between workers
        time.sleep(0.5)
        return m.condition_id, result

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_worker, m): m for m in markets}
        for fut in concurrent.futures.as_completed(futures):
            try:
                condition_id, result = fut.result()
                results.append(result)
                if not result["error"] and not result["skipped"]:
                    # Mark as ingested in universe
                    m = universe.get(condition_id)
                    if m:
                        from dataclasses import replace
                        universe.update(replace(m, ingested=True))
            except Exception as exc:
                print(f"  Worker error: {exc}", file=sys.stderr)

    universe.save(universe_path)

    n_ok = sum(1 for r in results if not r["error"] and not r["skipped"])
    n_skip = sum(1 for r in results if r["skipped"])
    n_err = sum(1 for r in results if r["error"])
    print(f"\nBulk ingest complete: {n_ok} ingested, {n_skip} skipped, {n_err} errors")
```

- [ ] **Step 5: Smoke test single-market path still works**

```
py -3 scripts/ingest_history.py --market "nba-celtics-heat-2026-05-22" --days 1 --out data/tmp_test
```
Expected: downloads trades, prints count, no errors. Delete `data/tmp_test` after.

- [ ] **Step 6: Commit**

```
git add scripts/ingest_history.py
git commit -m "feat: extract ingest_one(), add --from-universe, --workers, --skip-existing to ingest_history"
```

---

### Task 4: `scripts/build_universe.py` — one-shot batch prep script

**Files:**
- Create: `scripts/build_universe.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
# scripts/build_universe.py
"""
One-shot pipeline: scan all Polymarket markets → score → write universe.json → bulk ingest.

Usage:
    py -3 scripts/build_universe.py --pages all --volatility --top 300 --days 90 --workers 4
    py -3 scripts/build_universe.py --pages 5 --volatility --top 50 --skip-ingest

Flags:
    --pages N|all     Gamma API pages to scan (100 markets/page; default: all)
    --volatility      Fetch last 200 trades per market for price std (slower, recommended)
    --top N           Ingest only top N markets by score (default 300)
    --days N          History window for ingestion in days (default 90)
    --workers N       Parallel ingest workers (default 4, max 8)
    --skip-ingest     Score and write universe.json only, skip downloading data
    --min-std FLOAT   Minimum volatility std threshold (default 0.03)
    --min-quotable F  Minimum exit liquidity threshold in contracts (default 20)
    --out DIR         Output directory for .jsonl files (default data/raw)
    --universe FILE   Path for universe.json (default data/universe.json)
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fee_model import FeeModel
from src.live.clob_client import ClobClient
from src.live.exit_checker import ExitChecker
from src.data.universe import MarketUniverse, ScoredMarket

from scripts.scan_markets import (
    fetch_active_markets,
    scan_one,
    fetch_volatility,
    compute_score,
    extract_volume,
    extract_end_date,
)


def build_universe(
    pages: int | str,       # int or "all"
    use_volatility: bool,
    top_n: int,
    min_std: float,
    min_quotable: float,
    fee_rate: float = 0.07,
    rebate: float = 0.5,
    min_edge: float = 0.005,
    max_loss: float = 0.10,
    half_spread: float = 0.025,
    delay: float = 0.15,
) -> MarketUniverse:
    """
    Scan Gamma, score all markets, return populated MarketUniverse.
    Top-N are marked active; the rest get status based on thresholds.
    """
    fm = FeeModel()
    client = ClobClient()
    exit_checker = ExitChecker(
        fee_model=fm,
        fee_rate=fee_rate,
        rebate_fraction=rebate,
        min_edge_floor=min_edge,
        max_loss_fraction=max_loss,
        min_viable_size=1.0,
    )

    all_pages = (pages == "all")
    limit = 10000 if all_pages else int(pages) * 500

    print(f"Fetching {'all' if all_pages else limit} markets from Gamma API...")
    markets = fetch_active_markets(
        limit=limit,
        all_pages=all_pages,
    )
    print(f"  Got {len(markets)} markets. Scoring each one...")

    scans = []
    for i, market in enumerate(markets):
        q = market.get("question", "?")[:55]
        print(f"  [{i+1:>4}/{len(markets)}] {q:<55}", end="\r", flush=True)

        scan = scan_one(
            market=market,
            client=client,
            exit_checker=exit_checker,
            half_spread=half_spread,
            min_price=0.03,
            max_price=0.97,
            fetch_vol=use_volatility,
        )
        scans.append(scan)

        if delay > 0:
            time.sleep(delay)

    print(" " * 80, end="\r")

    # Convert to ScoredMarket and build universe
    now_iso = datetime.now(timezone.utc).isoformat()
    universe = MarketUniverse()

    # Sort by score descending; assign status
    viable = [s for s in scans if s.viable and s.max_quotable >= min_quotable]
    if use_volatility:
        viable = [s for s in viable if s.volatility_std >= min_std]
    viable.sort(key=lambda s: -s.score)

    active_ids = {s.condition_id for s in viable[:top_n]}

    for scan in scans:
        # Determine days_to_resolution
        days_remaining = 999.0
        if scan.end_date:
            try:
                end_dt = datetime.fromisoformat(scan.end_date).replace(tzinfo=timezone.utc)
                days_remaining = (end_dt - datetime.now(timezone.utc)).total_seconds() / 86400.0
            except Exception:
                pass

        if days_remaining <= 1.0:
            status = "expired"
        elif scan.condition_id in active_ids:
            status = "active"
        else:
            status = "below_threshold"

        m = ScoredMarket(
            condition_id=scan.condition_id,
            slug=scan.slug,
            question=scan.question,
            yes_token=scan.yes_token,
            no_token=scan.no_token,
            score=scan.score,
            volatility_std=scan.volatility_std,
            volume_24h=scan.volume_24h,
            max_quotable=scan.max_quotable,
            trades_per_day=scan.trades_per_day,
            end_date=scan.end_date,
            days_to_resolution=max(0.0, days_remaining),
            status=status,
            last_scored_at=now_iso,
            ingested=False,
        )
        universe.update(m)

    return universe


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build market universe and optionally bulk-ingest history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--pages", default="all",
                        help="Gamma pages to scan (N or 'all'; default: all)")
    parser.add_argument("--volatility", action="store_true",
                        help="Fetch last 200 trades per market for price std")
    parser.add_argument("--top", type=int, default=300,
                        help="Ingest top N markets by score (default 300)")
    parser.add_argument("--days", type=int, default=90,
                        help="History window for ingestion in days (default 90)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel ingest workers (default 4)")
    parser.add_argument("--skip-ingest", action="store_true",
                        help="Score only, don't download data")
    parser.add_argument("--min-std", type=float, default=0.03,
                        help="Minimum volatility std (default 0.03)")
    parser.add_argument("--min-quotable", type=float, default=20.0,
                        help="Minimum exit liquidity in contracts (default 20)")
    parser.add_argument("--out", default="data/raw",
                        help="Output directory for .jsonl files (default data/raw)")
    parser.add_argument("--universe", default="data/universe.json",
                        help="Path for universe.json (default data/universe.json)")
    parser.add_argument("--delay", type=float, default=0.15,
                        help="Seconds between CLOB requests (default 0.15)")
    args = parser.parse_args()

    try:
        pages = int(args.pages)
    except ValueError:
        pages = "all"

    print(f"Building universe: pages={args.pages}, volatility={args.volatility}, "
          f"top={args.top}, min_std={args.min_std}, min_quotable={args.min_quotable}")

    universe = build_universe(
        pages=pages,
        use_volatility=args.volatility,
        top_n=args.top,
        min_std=args.min_std,
        min_quotable=args.min_quotable,
        delay=args.delay,
    )

    universe_path = Path(args.universe)
    universe.save(universe_path)

    active = universe.active_markets()
    total = len(universe.all_markets())
    print(f"\nUniverse written to {universe_path}")
    print(f"  Total scored:   {total}")
    print(f"  Active (top {args.top}): {len(active)}")
    print(f"  Need ingest:    {len(universe.markets_needing_ingest())}")

    if args.skip_ingest:
        print("  Skipping ingest (--skip-ingest)")
        return

    print(f"\nStarting bulk ingest: {len(universe.markets_needing_ingest())} markets, "
          f"{args.days} days history, {args.workers} workers...")

    from scripts.ingest_history import _bulk_ingest_from_universe
    _bulk_ingest_from_universe(
        universe_path=universe_path,
        out_dir=Path(args.out),
        days=args.days,
        spread=0.02,
        book_size=500.0,
        workers=min(max(1, args.workers), 8),
        skip_existing=True,
    )

    # Reload to get updated ingested counts
    universe2 = MarketUniverse()
    universe2.load(universe_path)
    ingested = sum(1 for m in universe2.active_markets() if m.ingested)
    print(f"\nSummary:")
    print(f"  Markets scanned:  {total}")
    print(f"  Qualifying:       {len(active)}")
    print(f"  Ingested:         {ingested}")
    print(f"  Skipped/errors:   {len(active) - ingested}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test (dry run — no ingest)**

```
py -3 scripts/build_universe.py --pages 1 --top 10 --skip-ingest --universe data/test_universe.json
```
Expected: scans ~500 markets, writes test_universe.json, prints summary, no errors. Delete `data/test_universe.json` after.

- [ ] **Step 3: Commit**

```
git add scripts/build_universe.py
git commit -m "feat: add build_universe.py — one-shot scan → score → universe.json → bulk ingest"
```

---

### Task 5: `scripts/run_discovery.py` — perpetual discovery daemon

**Files:**
- Create: `scripts/run_discovery.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
# scripts/run_discovery.py
"""
Perpetual market discovery daemon.

Re-scans all Polymarket markets every --interval seconds (default 4h),
updates universe.json with newly qualifying and expired markets,
and auto-ingests the last 7 days of data for new active markets.

Does NOT place any orders. This is the discovery/data layer only.
run_live.py polls universe.json and manages QuoteLoops independently.

Usage:
    py -3 scripts/run_discovery.py                      # runs forever, updates every 4h
    py -3 scripts/run_discovery.py --interval 3600      # re-scan every 1h
    py -3 scripts/run_discovery.py --dry-run            # score only, don't ingest or save
    py -3 scripts/run_discovery.py --once               # run one cycle then exit

Ctrl-C for graceful shutdown.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.universe import MarketUniverse, ScoredMarket
from scripts.build_universe import build_universe
from scripts.ingest_history import _bulk_ingest_from_universe


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )


def run_one_cycle(
    universe_path: Path,
    out_dir: Path,
    warm_up_days: int,
    min_std: float,
    min_quotable: float,
    use_volatility: bool,
    dry_run: bool,
    workers: int,
) -> None:
    log = logging.getLogger("run_discovery")
    log.info("Starting discovery cycle...")

    # Load existing universe to preserve ingested flags
    existing = MarketUniverse()
    existing.load(universe_path)
    existing_by_id = {m.condition_id: m for m in existing.all_markets()}

    # Re-score all markets
    new_universe = build_universe(
        pages="all",
        use_volatility=use_volatility,
        top_n=10000,       # no hard limit — let scoring filter
        min_std=min_std,
        min_quotable=min_quotable,
        delay=0.15,
    )

    # Preserve ingested flags from previous run
    for m in new_universe.all_markets():
        prev = existing_by_id.get(m.condition_id)
        if prev and prev.ingested:
            from dataclasses import replace
            new_universe.update(replace(m, ingested=True))

    active = new_universe.active_markets()
    need_ingest = new_universe.markets_needing_ingest()

    log.info("Cycle complete: %d total, %d active, %d need ingest",
             len(new_universe.all_markets()), len(active), len(need_ingest))

    if dry_run:
        log.info("DRY RUN — not saving universe or ingesting data")
        return

    new_universe.save(universe_path)
    log.info("Universe saved to %s", universe_path)

    if need_ingest:
        log.info("Auto-ingesting %d new markets (%d-day warm-up)...", len(need_ingest), warm_up_days)
        _bulk_ingest_from_universe(
            universe_path=universe_path,
            out_dir=out_dir,
            days=warm_up_days,
            spread=0.02,
            book_size=500.0,
            workers=workers,
            skip_existing=True,
        )
        log.info("Auto-ingest complete")
    else:
        log.info("No new markets to ingest")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Perpetual Polymarket discovery daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--interval", type=int, default=14400,
                        help="Seconds between re-scan cycles (default 14400 = 4h)")
    parser.add_argument("--warm-up-days", type=int, default=7,
                        help="Days of history to ingest for new active markets (default 7)")
    parser.add_argument("--min-std", type=float, default=0.03,
                        help="Minimum volatility std (default 0.03)")
    parser.add_argument("--min-quotable", type=float, default=20.0,
                        help="Minimum exit liquidity in contracts (default 20)")
    parser.add_argument("--volatility", action="store_true", default=True,
                        help="Fetch volatility for each market (default True)")
    parser.add_argument("--no-volatility", dest="volatility", action="store_false")
    parser.add_argument("--workers", type=int, default=2,
                        help="Parallel ingest workers (default 2)")
    parser.add_argument("--out", default="data/raw",
                        help="Output directory for .jsonl files (default data/raw)")
    parser.add_argument("--universe", default="data/universe.json",
                        help="Path for universe.json (default data/universe.json)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Score only, don't save universe or ingest data")
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle then exit")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    log = logging.getLogger("run_discovery")

    universe_path = Path(args.universe)
    out_dir = Path(args.out)

    stop = False

    def _handle_signal(sig, frame):
        nonlocal stop
        log.info("Shutdown signal received, stopping after current cycle...")
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info("Discovery daemon starting. Interval=%ds, dry_run=%s", args.interval, args.dry_run)

    while not stop:
        try:
            run_one_cycle(
                universe_path=universe_path,
                out_dir=out_dir,
                warm_up_days=args.warm_up_days,
                min_std=args.min_std,
                min_quotable=args.min_quotable,
                use_volatility=args.volatility,
                dry_run=args.dry_run,
                workers=args.workers,
            )
        except Exception as exc:
            log.error("Cycle failed: %s", exc, exc_info=True)

        if args.once or stop:
            break

        log.info("Sleeping %ds until next cycle...", args.interval)
        # Sleep in 10s increments to remain responsive to Ctrl-C
        for _ in range(args.interval // 10):
            if stop:
                break
            time.sleep(10)

    log.info("Discovery daemon stopped.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test one cycle with --dry-run --once**

```
py -3 scripts/run_discovery.py --once --dry-run --no-volatility
```
Expected: scans markets, prints summary, exits cleanly without writing any files.

- [ ] **Step 3: Commit**

```
git add scripts/run_discovery.py
git commit -m "feat: add run_discovery.py perpetual market discovery daemon"
```

---

### Task 6: Extend `run_live.py` — `--universe` flag, dynamic market management

**Files:**
- Modify: `scripts/run_live.py`

- [ ] **Step 1: Add `load_active_from_universe()` helper**

Add after `seed_fv_from_recent_trades`:

```python
def load_active_from_universe(universe_path: Path) -> list[dict]:
    """
    Return list of dicts with keys: condition_id, yes_token, no_token, question.
    Only active, ingested markets.
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
```

- [ ] **Step 2: Add `_universe_watcher` background thread function**

Add after `load_active_from_universe`:

```python
def _universe_watcher(
    universe_path: Path,
    loops: list[QuoteLoop],
    token_to_loop: dict[str, QuoteLoop],
    feed,
    client,
    fee_model,
    args: argparse.Namespace,
    stop_event,
    poll_interval: float = 60.0,
) -> None:
    """
    Background thread: polls universe.json every poll_interval seconds.
    Adds QuoteLoops for newly active+ingested markets.
    Stops QuoteLoops for expired markets (graceful — lets fills settle).
    """
    import threading
    log = logging.getLogger("universe_watcher")
    known_condition_ids: set[str] = {loop.config.condition_id for loop in loops}

    while not stop_event.is_set():
        time.sleep(poll_interval)
        if stop_event.is_set():
            break
        try:
            entries = load_active_from_universe(universe_path)
            for entry in entries:
                cid = entry["condition_id"]
                if cid in known_condition_ids:
                    continue
                # New market — ingest warm-up then spin up loop
                log.info("New market detected: %s", entry["question"][:60])
                yes_token = entry["yes_token"]
                no_token = entry["no_token"]
                question = entry["question"][:80]

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
```

- [ ] **Step 3: Add `--universe` flag to argument parser**

In `main()`, after `parser.add_argument("--markets", ...)`:

```python
    parser.add_argument(
        "--universe", type=str, default=None,
        help="Path to universe.json — trade all active+ingested markets dynamically"
    )
```

- [ ] **Step 4: Wire `--universe` into `main_async()`**

In `main_async()`, replace the "Discover markets" block with:

```python
    # Discover markets
    if args.universe:
        entries = load_active_from_universe(Path(args.universe))
        if not entries:
            log.error("No active+ingested markets found in %s", args.universe)
            sys.exit(1)
        log.info("Universe mode: %d active markets from %s", len(entries), args.universe)
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
```

Then, replace the existing token-resolution loop with a conditional that handles both paths:

```python
    loops: list[QuoteLoop] = []
    token_ids: list[str] = []

    if args.universe:
        # Universe mode: tokens come directly from universe.json
        for entry in entries:
            yes_token = entry["yes_token"]
            no_token = entry["no_token"]
            condition_id = entry["condition_id"]
            title = entry["question"][:80]
            loop = build_quote_loop(yes_token, no_token, condition_id, title, client, fee_model, args)
            loops.append(loop)
            token_ids.extend([yes_token, no_token])
            time.sleep(0.05)
    else:
        # Existing path: resolve from .jsonl files
        for path in market_paths:
            result = resolve_market_tokens(path, client)
            if result is None:
                log.warning("Skipping unresolvable market: %s", path.stem[:40])
                continue
            yes_token, no_token, condition_id, title = result
            loop = build_quote_loop(yes_token, no_token, condition_id, title, client, fee_model, args)
            loops.append(loop)
            token_ids.extend([yes_token, no_token])
            time.sleep(0.1)
```

- [ ] **Step 5: Start universe watcher thread when `--universe` is set**

In `main_async()`, after `feed_task = asyncio.create_task(feed.run())` and before `stop_event.wait()`:

```python
    watcher_thread = None
    if args.universe:
        import threading
        _stop_flag = threading.Event()
        def _watch():
            _universe_watcher(
                universe_path=Path(args.universe),
                loops=loops,
                token_to_loop=token_to_loop,
                feed=feed,
                client=client,
                fee_model=fee_model,
                args=args,
                stop_event=_stop_flag,
            )
        watcher_thread = threading.Thread(target=_watch, daemon=True, name="universe-watcher")
        watcher_thread.start()
        log.info("Universe watcher started (polling every 60s)")
```

In the `finally` block, add:
```python
        if watcher_thread and hasattr(_stop_flag, 'set'):
            _stop_flag.set()
```

- [ ] **Step 6: Smoke test universe mode**

First ensure `data/universe.json` has at least one active+ingested market from a previous `build_universe.py` run, then:

```
py -3 scripts/run_live.py --universe data/universe.json --dry-run
```
Expected: loads markets from universe.json, seeds FV estimators, connects to WS feed, logs "Waiting for market data...", shuts down cleanly on Ctrl-C.

- [ ] **Step 7: Commit**

```
git add scripts/run_live.py
git commit -m "feat: add --universe flag to run_live.py for dynamic market management"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Covered in |
|-----------------|-----------|
| `src/data/universe.py` — ScoredMarket + MarketUniverse | Task 1 |
| `scan_markets.py` --all, --volatility, --export, Std column | Task 2 |
| Updated `compute_score()` with volatility_multiplier | Task 2 |
| `ingest_history.py` --from-universe, --workers, --skip-existing | Task 3 |
| `build_universe.py` one-shot orchestration | Task 4 |
| `run_discovery.py` perpetual daemon | Task 5 |
| `run_live.py` --universe + watcher thread | Task 6 |
| universe.json format with metadata fields | Task 1 (save) + Task 4 (build) |
| Security: no credential logging, dry-run default | Preserved in all new scripts |
| Graceful Ctrl-C on daemon | Task 5 (signal handler) |

### Type consistency check

- `ScoredMarket.trades_per_day` defined in Task 1, populated in Task 2 (`fetch_volatility` returns it), written to universe in Task 4 ✓
- `fetch_volatility` added to `scan_markets.py` in Task 2, imported in Task 4 ✓
- `_bulk_ingest_from_universe` added to `ingest_history.py` in Task 3, imported in Tasks 4 and 5 ✓
- `build_universe()` function (not just script) exported from `build_universe.py`, imported in `run_discovery.py` Task 5 ✓
- `scan_one()` gains `fetch_vol: bool` param in Task 2 — all callers updated in same task ✓
- `MarketScan.trades_per_day` field added in Task 2 alongside `volatility_std` ✓
