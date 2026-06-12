# Project Handoff — Polymarket LP/MM Bot

Last updated: 2026-06-12. Read this first when picking up on a new device or
in a new session. It captures both what's **built** (in the repo) and what was
**discussed** (decisions, blockers, venue research) that isn't obvious from code.

---

## 1. What this is

A market-making / liquidity-provision bot for binary prediction markets.
Core strategy: **dual-book maker-taker arbitrage** — rest passive ladders on
both the YES and NO order books; when a maker order fills, immediately hedge
with a taker order on the opposite token, locking in a sub-$1 paired position
that settles at exactly $1.00. Per-cycle losses are bounded by construction;
the edge is harvesting uninformed retail flow for the bid-ask spread + maker
rebates.

Built and validated against **Polymarket**. ~191 tests passing. The full
engineering, backtesting, risk, monitoring, and ops stack is done.

## 2. CURRENT STATUS — read before doing anything

**The project is blocked at the live-trading step by a jurisdiction wall.**

- **Polymarket is illegal in Singapore** (banned Jan 2025 by the Gambling
  Regulatory Authority under the Gambling Control Act 2022; **user-side fines
  up to SGD 10,000**). The owner is Singapore-based.
- Polymarket's CLOB API **geoblocks** the account: order placement returns
  `403 Trading restricted in your region`. Tested from a Singapore IP and an
  Indonesia VPN exit — both blocked. The UK is also a Polymarket-restricted
  jurisdiction (FCA).
- **Do not attempt to circumvent the geoblock** (VPN/proxy to a permitted
  region). It violates Polymarket ToS, may breach Singapore law, and routinely
  gets accounts frozen with funds inside. This boundary was held throughout.
- **$1,999 USDC is parked** in the Polymarket wallet (proxy address
  `0xB67580583331B626CC6DD286C305cE293888F39f`, account "garydegensler").
  **Action: withdraw it** — it's safe but sits at a venue that can't be traded
  from the owner's location.

**Net:** the strategy, code, and infra are sound and **venue-portable**. The
blocker is venue access, not engineering. The only Polymarket-coupled file is
`src/live/clob_client.py`.

## 3. Venue research (2026-06-12) — where to go instead

| Venue | API/CLOB fit | Singapore access | Flow / notes |
|---|---|---|---|
| Polymarket | excellent (built for it) | **BANNED, user fines** | best flow, proven — but unusable |
| Kalshi | good | blocked (SG on restricted list) | US-regulated |
| Crypto.com Predict | no public API found | blocked (US-only) | CFTC entity |
| **IBKR ForecastEx** | good (TWS API; read book, limit orders, maker+taker) | **clean & legal (account opening)** | BUY-ONLY (exit = buy opposite, IB nets); $0.01/contract spread; no rebate; no soccer. Re-derive edge for buy-only before capital. |
| HIP-4 / Hyperliquid | excellent, permissionless | grey (crypto deriv) | API-only, no UI/breadth yet — too early |
| **Predict.fun** (Binance BNB-chain integration) | good; REST+WS, Python/TS SDKs, `x-api-key` reads + JWT-sign orders | grey (crypto deriv, Binance-SG history) | **STRUCTURAL FINDING: single merged Yes-denominated orderbook, NOT two separate YES/NO books.** The dual-book arb likely COLLAPSES into single-book spread-making — a different, harder strategy. Has SPORTS_MATCH + CRYPTO_UP_DOWN variants, a rewards program (`hourlyRate`), and cross-refs `polymarketConditionIds`. Volume much lower than Polymarket. |

**Recommended next move (if continuing):** build a *read-only* Predict.fun
collector (no capital, no legal exposure), bank a few days of native
microstructure, and **verify the single-book finding + measure whether any
edge exists** before rewriting strategy. Needs a Predict.fun `x-api-key`.
A Predict.fun collector was proposed but NOT built (no code written).

**Grey-zone caveat:** HIP-4 and Predict.fun are crypto derivatives; their
legality for a Singapore retail user is unresolved. Get proper guidance
before committing capital. IBKR ForecastEx is the clean-legal path.

## 4. What's built (in this repo)

- `src/data/` — schemas, JSONL loader, MarketUniverse
- `src/strategy/` — fair value, regime classifier, hedgeability, quote engine, inventory
- `src/backtest/` — dual-book simulator, fill/queue models (FRONT/PRO_RATA/BACK),
  adverse-selection tracker, shared `live_harness.py`
- `src/live/` — `BookFeed` (WS), `clob_client.py` (Polymarket; sig_type=2 MetaMask),
  `quote_loop.py` (ladders, hedge, partial fills, kill-switch, GTD dead-man,
  rate limiter), `portfolio_state.py` (caps), `credentials.py`
- `scripts/` — `collect_books.py` (EC2 collector, 29 WS connections),
  `run_live_backtest.py`, `run_live.py`, `dashboard.py`, `test_order.py`,
  `make_wc_universe.py`, watchdog/alert scripts
- `docs/` — `GO-LIVE-PLAN.md` (phased pilot plan), `REVIEW-2026-06-10.md`
  (multi-agent bug review), `README.md` (architecture + API quirks)

Key honest results: daily-PnL Sharpe ~11 (not the flattering per-cycle 48);
PRO_RATA backtest ~$31/day on $20k; peak concurrent capital ~43% of wallet
(capital is NOT the binding constraint — fill opportunity is).

## 5. External infrastructure (lives outside the repo)

- **GitHub**: `https://github.com/matthewthelim-bot/polymarket-mm.git` (private origin)
- **EC2 collector**: `ubuntu@100.52.215.239` (us-east-1, instance
  `i-047f1ad7256084171`, t3.micro). Runs `polymarket-collector` systemd
  service recording market data 24/7. SSH key: `polymarket-key.pem`.
  NOTE: EC2 is in us-east — fine for read-only data collection (public),
  but it CANNOT place orders (US geoblock). Keep trading off the box.
- **CloudWatch alarms** (account-level, follow AWS login): system-check
  auto-recover, instance-check auto-reboot, CPU-credits-low — all email
  matthewthelim@gmail.com via SNS topic `polymarket-ec2-alerts`.
- **Data**: ~12GB in `data/live/` locally; canonical copy on EC2. Re-syncable.

## 6. TRANSFER RUNBOOK (this device → new device)

**A. Code (via GitHub — clean, no secrets):**
1. On THIS device: `git push origin master` (publishes all commits).
2. On NEW device: `git clone https://github.com/matthewthelim-bot/polymarket-mm.git`

**B. Secrets (BY HAND — never via git, email, or chat):**
Move these two files over an encrypted channel (password manager, encrypted
USB, age/gpg). They are gitignored and must stay that way.
1. `Code/.env` → place at `<parent-of-repo>/.env` on the new device
   (contains PRIVATE_KEY, POLY_ADDRESS, POLY_API_KEY/SECRET/PASSPHRASE).
2. `polymarket-mm/polymarket-key.pem` → place in the repo root, then
   `chmod 600 polymarket-key.pem` (Linux/Mac) so SSH accepts it.

**C. Data (optional — don't copy 12GB):**
- The new device re-syncs from EC2 automatically on first
  `py -3 scripts/run_live_backtest.py` (pulls date dirs it lacks).
- Or `scp -r` specific `data/live/YYYY-MM-DD` dirs if you want a head start.

**D. Python env on the new device:**
```
cd polymarket-mm
python -m venv .venv && . .venv/bin/activate   # or py -3 -m venv on Windows
pip install -r requirements.txt
py -3 -m pytest -q        # expect ~191 passing — confirms a clean transfer
```

**E. Device-specific infra to recreate (not in git):**
- EC2 watchdog scheduled task: re-register `scripts/ec2_watchdog.ps1`
  (Windows) — see the schtasks command in that file's header.
- Disable sleep on AC during any live session.
- CloudWatch alarms: already account-level, nothing to do — they follow the
  AWS login, not the device.

**F. Verify the transfer worked:**
- `git log --oneline -1` matches on both devices
- `py -3 -m pytest -q` green on the new device
- `ssh -i polymarket-key.pem ubuntu@100.52.215.239 "echo ok"` reaches EC2
- (Trading stays blocked until a permitted venue is set up — see §2/§3)

## 7. Open decisions for the owner

1. **Withdraw the $1,999** from Polymarket.
2. **Pick a venue** you can legally use: IBKR ForecastEx (clean, account
   opening) and/or measure Predict.fun with the read-only collector.
3. Get **regulatory guidance** on crypto-derivative prediction venues for a
   Singapore retail user before any capital.
4. Whichever venue: the engineering ports; budget for a new exchange adapter
   (`*_client.py`) and — for single-book venues like Predict.fun — a
   re-architected strategy (spread-making, not dual-book arb).
