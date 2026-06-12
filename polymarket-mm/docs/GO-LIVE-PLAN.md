# Go-Live Plan — Polymarket Maker-Taker Arb

Drafted 2026-06-11. Owner: Matthew. Status: **Phase 0 (data accumulation)**.

The strategy is structural arbitrage (paired YES+NO at combined cost < $1 /
proceeds > $1, settled at exactly $1), so per-cycle losses are bounded by
construction. The open question is not "does the math work" but **"how much
of the simulated flow do we actually capture live"** — the backtest brackets
this at $18–58/day on $20k (BACK→FRONT queue models, PRO_RATA ≈ $31/day),
and only live fills can collapse that range.

---

## Phase 0 — Data accumulation & stability  (now → ~Jun 24)

Goal: a trustworthy PRO_RATA backtest over ≥14 days of full 26-connection
coverage before committing capital.

**Exit criteria (all must hold):**
- [ ] ≥14 consecutive days of collector data at full coverage
      (~1,000 markets/day; gauge shows MLB/UFC/crypto feeds healthy)
- [ ] PRO_RATA backtest daily PnL positive on ≥90% of days, daily-PnL
      Sharpe ≥ 5 over the window
- [ ] No unexplained drop in $/day as the window grows (regime stability)
- [ ] Collector uptime ≥99% (watchdog log + healthcheck log clean)

**Standing tasks:**
- Weekly: `py -3 scripts/run_live_backtest.py --capital 20000 --queue-model PRO_RATA`
  — record $/day, daily Sharpe, fills by category in a tracking row.
- Monitor EC2: local watchdog (15 min), on-box healthcheck (10 min),
  CloudWatch alarm (see Ops below).
- Upgrade instance to t3.small (911MB RAM OOM'd under 26 connections;
  swap + MemoryMax are mitigations, not fixes).

**Engineering gate — must close before Phase 2 (real orders):**
- [ ] Replace blocking REST `get_book` inside the WS callback with a WS
      subscription for the NO token (review item #5 — a 10s stall blocks
      every market on the feed; unacceptable with live orders resting).
- [ ] Live-path tests: hedge-routing table and `_send_taker` partial-fill
      handling in `quote_loop.py` (currently zero tests on the
      highest-stakes code).
- [ ] Wire `ExitChecker.check()` with own-order stripping into the live
      loop's market-entry decision.
- [ ] Verify order rate limits: reprice interval (30s/slot) and ladder
      churn vs Polymarket API limits at ~20 markets.

## Phase 1 — Dry-run shakedown  (3–5 days, no capital at risk)

Goal: prove the live plumbing end-to-end with real market data and fake
orders.

```
py -3 scripts/run_live.py --universe data/universe.json --total-capital 2000
```
(dry-run is the default; NO --live flag)

**Watch for:**
- Quote computation rate and reprice churn per market
- Fill-poll behavior (no replay of historical fills — fixed, verify anyway)
- Per-market fee schedules fetched correctly (crypto 7%, sports 3%)
- Portfolio caps engaging at quote time (logs show suppression, not blocks
  at fill time)
- Clean shutdown: Ctrl-C cancels all resting orders (verify in logs)
- `stats.unroutable_fills` stays 0

**Exit criteria:** 3+ days without errors/restarts; dry-run fill events
roughly track the same-day backtest's fills for the same markets.

## Phase 2 — Micro pilot  (real money: $1,000–2,000, 2 weeks)

Goal: measure the ONE number simulation cannot give us — the **realized
fill rate vs PRO_RATA prediction** — plus hedge slippage and rebate income.

**Setup:**
- 6–10 markets, hand-picked: 3–4 MLB game lines (cheapest fees, highest
  flow), BTC + ETH daily up/down, one 15m window as a recycling test
- `--live --total-capital 2000 --max-long-term-fraction 0` (short-duration only)
- Per-market notional cap $200 (`MAX_MARKET_NOTIONAL` low for the pilot)
- Quote sizes: let adaptive sizing run, clamp stays 500

**Daily measurements (build a tracking sheet):**
| Metric | Backtest reference | Kill threshold |
|---|---|---|
| Fill rate vs same-day PRO_RATA sim | 100% | n/a (measurement) |
| Maker→hedge slippage (taker px vs book at fill) | 0 | > 1 tick avg |
| Naked-leg incidents (unhedged > 60s) | 0 | any, twice |
| Unroutable fills | 0 | any (investigate) |
| Daily PnL | ~$3/day at $2k scale | -$50 cumulative |
| Maker rebates received (wallet) vs modeled | 20–25% share | n/a |
| Liquidity-rewards income (separate program) | $0 modeled | n/a — pure upside |

**Hard kill-switches (stop trading, keep positions, review):**
- Cumulative PnL below -$50
- Any naked-leg incident lasting > 5 minutes
- Collector or quote-loop crash with orders resting
- Any settlement dispute (UMA) on a held market

## Phase 3 — Scale decision  (after 2 clean pilot weeks)

Compute: `realized_capture = pilot fill rate / PRO_RATA prediction`.

- capture ≥ 70%  → scale to $10k across the full universe, keep caps
  proportional; expected ~$15–25/day initially
- capture 40–70% → scale to $5k, focus on the categories where capture was
  highest (likely MLB — cheapest fees, densest flow)
- capture < 40%  → do not scale; revisit quoting (offset, at-touch quoting
  on low-AS markets) with the live data before adding capital

**Scaling rules:**
- Double capital at most once per 2 weeks, only after a clean window
- Keep long-term cap at 30%; revisit only when short-duration capacity
  is saturated (peak concurrent > 80% of wallet)
- Re-run the backtest weekly against realized results; if live persistently
  underperforms PRO_RATA by >2x, the model is broken — stop and diagnose

## Risk register (top 5)

1. **Fill-rate model risk** — the $18–58/day bracket. Mitigated by pilot
   measurement before scale.
2. **Operational: box death with orders resting** — watchdog + shutdown
   cancellation + (Phase 0 gate) non-blocking book fetch. Worst case:
   paired positions are still bounded-loss; naked legs are not.
3. **Settlement risk** — UMA disputes can delay or flip resolution.
   Bounded by per-market cap ($200 pilot / $2k scaled).
4. **API/ToS risk** — 26 WS connections + order churn; watch for rate-limit
   warnings; keep one IP, no circumvention.
5. **Regime risk** — fee schedule changes (fees only launched 2026), reward
   program changes, or competitors adopting the same ladder. Weekly
   backtest-vs-live tracking catches drift.

## Ops runbook

- **Alerts:** local Windows watchdog (15 min, toast + `ec2_watchdog.log`);
  on-box healthcheck cron (10 min, restarts service);
  **TODO (manual, 5 min):** AWS CloudWatch alarm on `StatusCheckFailed`
  with (a) auto-recover action and (b) SNS email — this is the layer that
  catches a dead box even when this PC is off.
- **EC2 recovery:** reboot from console; if stop/start, the public IP
  changes → update `EC2_HOST` in `run_live_backtest.py`, `run_sensitivity.py`,
  `ec2_watchdog.ps1` (or assign an Elastic IP — recommended).
- **Disk:** ~1–2GB/day at full coverage, 16GB free → prune synced date
  dirs on EC2 monthly (`data/live/` is mirrored locally by every backtest sync).
- **Security:** credentials only via `.env` / `credentials.py`; `--live`
  is opt-in; never log keys; pilot wallet holds pilot capital only.

## World Cup compressed timeline (2026-06-11 revision)

The 2026 FIFA World Cup (Jun 11 - Jul 19) front-loads the best conditions
the strategy will see this year: sports fee tier (3%/25%), ~2h match
markets, peak retail flow. Phases compress to catch the group stage:

| Date | Milestone |
|---|---|
| Jun 11 | DONE: collector covers all WC markets (ser-fifa x3, tag-based, 60s refresh) |
| Jun 11 | DONE: engineering gate — WS-first NO book (blocking REST fetch removed); live status monitor (data/live_status.json) |
| Jun 12-13 | Capture first match days; START dry-run on WC match markets |
| Jun 14 | Backtest first 2-3 match days (PRO_RATA): fills/match, AS around goals, which line types earn |
| Jun 15-16 | Go/no-go: $1-2k pilot on group-stage match markets (Phase 2 rules apply) |
| ~Jun 18 | If pilot clean: scale toward $20k per Phase 3 capture-rate gates |

WC-specific guardrails:
- Match markets ONLY (winner/draw, O/U, halftime). NO Winner outright
  (negRisk, locks capital to Jul 20), no exact-score tails (illiquid).
- In-play goal spikes are the AS stress case — watch unhedged count in
  live_status.json during matches; kill-switch rules unchanged.

## Wallet & platform readiness checklist (before first --live)

Integration that EXISTS and is wired: credential loading (.env via
credentials.py, never logged), py-clob-client L2 auth, order place
(GTC/FAK with explicit order type), cancel, open-orders, positions,
full ladder maintenance (cancel/replace on drift, 30s reprice floor,
300s TTL), immediate taker hedge with retry, shutdown cancel-all,
status monitor. None of it has placed a real order yet.

- [ ] Fund Polymarket account with pilot amount FIRST ($1-2k), not $20k —
      scale funding with the phase gates
- [x] Account type confirmed: MetaMask -> signature_type=2 + funder wired
      (2026-06-12). PREREQ: .env PRIVATE_KEY = exported MetaMask EOA key;
      POLY_ADDRESS = the Polymarket PROXY/deposit address (from your
      polymarket.com profile), NOT the MetaMask address.
- [ ] Run the auth test: py -3 scripts/test_order.py --confirm
      (places ONE ~\$1.50 GTD bid 20c below best, verifies, cancels;
      self-destructs in 2 min even if interrupted)
- [ ] Confirm USDC allowances (UI deposits via proxy normally pre-approve;
      verify the $5 test order fills/cancels cleanly)
- [ ] Derive/refresh API creds if the $5 test 401s (scripts/derive_key.py)
- [ ] Confirm get_positions() matches the UI portfolio page after the test

## Monitoring (live)

- data/live_status.json — refreshed every 30s: mode, total PnL, fills,
  orders, unhedged count, unroutable count, errors, portfolio cap usage,
  per-market table. Watch it, tail the console log, or open the
  Polymarket portfolio page (ground truth for positions/orders/balance).
- 5-minute STATUS line in the console log.
- Alerting stack (CloudWatch + local watchdog + on-box cron) covers the
  data pipeline; the trading process runs on THIS machine under your eyes
  during the pilot.

## Overnight lessons (2026-06-12, opener night)

1. **Session-managed processes die with the session.** The first dry-run was
   launched as an assistant background task and silently terminated at 01:18
   (no crash, no traceback — process lifecycle). Trading processes MUST run
   as detached OS processes (Start-Process / scheduled task). The relaunched
   dry-run is detached; the live pilot must be too.
2. **Exact-score markets slipped into the dry-run universe** — laddering NO
   bids at 0.83-0.86 ($250/level) on illiquid tails. make_wc_universe now
   excludes exact-score / futures / first-to-score lines per the pilot
   guardrails. Watch the next dry-run for any other line types that look
   wrong.
3. **Collector handled match night flawlessly**: 2,315 markets on Jun 11,
   fifa feeds saturated through the match window, healthcheck green hourly,
   memory stable with swap at ~360MB.

## Decision log

| Date | Decision | Basis |
|---|---|---|
| 2026-06-10 | LT cap 80%→30% | Liquidity guard; sweep showed zero PnL cost |
| 2026-06-11 | Plan on PRO_RATA ($31/day @ $20k) not FRONT ($58) | Queue-model bracket |
| 2026-06-11 | Sizing + tighter offset rejected as levers | +2% / -8% experiments |
| | Go/no-go Phase 1 | |
| | Go/no-go Phase 2 | |
| | Scale decision | |
