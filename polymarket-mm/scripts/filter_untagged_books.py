#!/usr/bin/env python3
"""
filter_untagged_books.py — surgical repair of JSONL files contaminated by two simultaneous collectors.

Two problems this fixes:
  1. Untagged book events (token_side="") written by the old collector into files that
     also have tagged events from the new collector.
  2. Duplicate trade events — both collectors wrote the same last_trade_price WS event
     to the same file, so every trade appears twice.

Rules:
  - If a file has NO tagged book events → leave it completely alone (legacy data)
  - If a file HAS tagged book events:
      - Drop any book event where token_side is "" or missing
      - Deduplicate trade events: keep first occurrence of each
        (timestamp, side, price, size) tuple

Usage:
    py -3 scripts/filter_untagged_books.py data/live/2026-05-22
    py -3 scripts/filter_untagged_books.py data/live/2026-05-22 --dry-run
    py -3 scripts/filter_untagged_books.py data/live --recursive
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

# Two trade events with the same (side, price, size) within this window are duplicates.
# Two collectors writing datetime.now() for the same WS event differ by 2–15ms.
TRADE_DEDUP_WINDOW_MS = 200


def is_tagged_book(event: dict) -> bool:
    return event.get("event_type") == "book" and event.get("token_side", "") in ("YES", "NO")


def is_untagged_book(event: dict) -> bool:
    return event.get("event_type") == "book" and event.get("token_side", "") not in ("YES", "NO")


def _parse_ts_ms(ts: str) -> int | None:
    """Parse ISO timestamp → milliseconds since epoch, or None on failure."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def filter_file(path: Path, dry_run: bool) -> tuple[int, int, int]:
    """
    Returns (kept, books_dropped, trades_dropped).
    Does nothing if the file has no tagged book events.

    Trade deduplication: two trades with the same (side, price, size) within
    TRADE_DEDUP_WINDOW_MS of each other are treated as the same underlying WS event.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[tuple[str, dict]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append((line, json.loads(line)))
        except json.JSONDecodeError:
            events.append((line, {}))  # keep malformed lines as-is

    has_tagged = any(is_tagged_book(e) for _, e in events)
    if not has_tagged:
        return len(events), 0, 0  # pure legacy — leave alone

    kept_lines: list[str] = []
    books_dropped = 0
    trades_dropped = 0
    # recent_trades: (side, price, size) -> last_seen_ms
    recent_trades: dict[tuple, int] = {}

    for raw, event in events:
        if is_untagged_book(event):
            books_dropped += 1
            continue

        if event.get("event_type") == "trade":
            side  = event.get("side", "")
            price = event.get("price")
            size  = event.get("size")
            ts_ms = _parse_ts_ms(event.get("timestamp", ""))
            key   = (side, price, size)

            if ts_ms is not None and key in recent_trades:
                last_ms = recent_trades[key]
                if abs(ts_ms - last_ms) <= TRADE_DEDUP_WINDOW_MS:
                    trades_dropped += 1
                    continue  # drop duplicate

            if ts_ms is not None:
                recent_trades[key] = ts_ms

        kept_lines.append(raw)

    if books_dropped == 0 and trades_dropped == 0:
        return len(events), 0, 0  # already clean

    if not dry_run:
        path.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")

    return len(kept_lines), books_dropped, trades_dropped


def main():
    parser = argparse.ArgumentParser(
        description="Remove untagged book events and duplicate trades from contaminated JSONL files"
    )
    parser.add_argument("dirs", nargs="+", help="Directories containing .jsonl files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without writing")
    parser.add_argument("--recursive", action="store_true", help="Recurse into subdirectories")
    args = parser.parse_args()

    total_files = 0
    total_modified = 0
    total_books_dropped = 0
    total_trades_dropped = 0

    for dir_arg in args.dirs:
        base = Path(dir_arg)
        if not base.exists():
            print(f"[WARN] {base} does not exist, skipping")
            continue
        pattern = "**/*.jsonl" if args.recursive else "*.jsonl"
        files = sorted(base.glob(pattern))

        for path in files:
            kept, books_dropped, trades_dropped = filter_file(path, dry_run=args.dry_run)
            total_files += 1
            if books_dropped > 0 or trades_dropped > 0:
                total_modified += 1
                total_books_dropped += books_dropped
                total_trades_dropped += trades_dropped
                action = "would remove" if args.dry_run else "removed"
                parts = []
                if books_dropped:
                    parts.append(f"{books_dropped} untagged books")
                if trades_dropped:
                    parts.append(f"{trades_dropped} duplicate trades")
                print(f"  {path.name}: {action} {' + '.join(parts)}, {kept} kept")

    verb = "would be " if args.dry_run else ""
    print(
        f"\nSummary: {total_files} files scanned, {total_modified} modified — "
        f"{total_books_dropped} untagged books {verb}removed, "
        f"{total_trades_dropped} duplicate trades {verb}removed"
    )
    if args.dry_run:
        print("(dry run — no files written)")


if __name__ == "__main__":
    main()
