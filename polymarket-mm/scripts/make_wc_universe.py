#!/usr/bin/env python3
"""Build a World Cup match-market universe file for run_live.

Fetches all events carrying the 2026 FIFA World Cup tag that end within
--hours (default 30 — i.e. today's matches), and writes a universe.json
compatible with `run_live.py --universe`.

Match markets only by design: the Winner outright and other futures lock
capital until July 20 and are excluded by the end-date window.

Usage (rerun each match day):
    py -3 scripts/make_wc_universe.py                       # next 30h
    py -3 scripts/make_wc_universe.py --hours 72            # next 3 days
    py -3 scripts/make_wc_universe.py --min-event-volume 5000
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.universe import MarketUniverse, ScoredMarket

FIFA_TAG_ID = 102232  # Gamma tag: fifa-world-cup
DEFAULT_OUT = Path("data/universe_wc.json")


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=30.0,
                    help="Include events ending within this many hours (default 30)")
    ap.add_argument("--min-event-volume", type=float, default=1000.0,
                    help="Skip events below this 24h volume (default 1000)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=args.hours)
    today = now.strftime("%Y-%m-%d")

    universe = MarketUniverse()
    n_events = n_markets = 0
    for offset in range(0, 500, 100):
        events = _get(
            f"https://gamma-api.polymarket.com/events"
            f"?tag_id={FIFA_TAG_ID}&closed=false&end_date_min={today}"
            f"&limit=100&offset={offset}"
        )
        if not events:
            break
        for ev in events:
            end_raw = ev.get("endDate") or ""
            try:
                end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if end_dt > cutoff:
                continue
            vol = float(ev.get("volume24hr", 0) or 0)
            if vol < args.min_event_volume:
                continue
            n_events += 1
            for m in ev.get("markets", []):
                if not (m.get("active") and not m.get("closed")):
                    continue
                # Pilot guardrail (GO-LIVE-PLAN): match winner/draw, O/U and
                # halftime lines only. Exact-score tails are illiquid one-way
                # books (observed: dry-run laddering NO bids at 0.83-0.86,
                # ~$250/level, on "Exact Score 2-1" markets); futures lock
                # capital to Jul 20.
                q = (m.get("question", "") or "").lower()
                if any(x in q for x in ("exact score", "win the 2026",
                                        "golden boot", "to score first",
                                        "first team to score")):
                    continue
                clob_ids = m.get("clobTokenIds", [])
                if isinstance(clob_ids, str):
                    clob_ids = json.loads(clob_ids)
                if len(clob_ids) != 2:
                    continue
                days_left = max(0.0, (end_dt - now).total_seconds() / 86400)
                universe._markets[m["conditionId"]] = ScoredMarket(
                    condition_id=m["conditionId"],
                    slug=m.get("slug", ""),
                    question=(m.get("question", "") or "")[:120],
                    yes_token=clob_ids[0],
                    no_token=clob_ids[1],
                    score=vol,  # event volume as a rough priority score
                    volatility_std=0.0,
                    volume_24h=float(m.get("volume24hr", 0) or 0),
                    max_quotable=0.0,
                    trades_per_day=0.0,
                    end_date=end_dt.strftime("%Y-%m-%d"),
                    days_to_resolution=days_left,
                    status="active",
                    ingested=True,  # run_live filters on this; no raw-history needed
                    last_scored_at=now.isoformat(),
                )
                n_markets += 1
        if len(events) < 100:
            break

    universe.save(args.out)
    print(f"Wrote {args.out}: {n_markets} match markets from {n_events} events "
          f"(ending within {args.hours:.0f}h, event vol >= ${args.min_event_volume:,.0f})")


if __name__ == "__main__":
    main()
