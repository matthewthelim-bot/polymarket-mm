# Polymarket Regime-Adaptive Market Maker — Design Spec

**Date:** 2026-05-16
**Status:** Approved for implementation
**Capital:** $50K Phase 1, adapter-ready to scale
**Venue:** Polymarket (Phase 1); VenueAdapter interface designed for Kalshi and future venues

---

## 1. EXECUTIVE SUMMARY

The system is a regime-adaptive binary prediction-market maker targeting Polymarket's CLOB, operating under a commercial liquidity-provision mandate whose economics derive from maker spread capture, Polymarket incentive programs, and future retainer/fee arrangements with venues or clients. The core tradable hypothesis is that quoting both sides of the same binary market — allowing one passive fill, then flattening via the opposite side of the same market — avoids cross-market basis risk because both legs resolve on the identical event, converting the flatten into a synthetic arbitrage rather than a cross-market hedge. This approach generates positive expected edge only when: (a) the half-spread net of adverse selection and fees is positive, (b) opposite-side execution probability is high enough to keep hedge delay cost below the earned spread, and (c) incentive/retainer economics are measured conditional on fill quality rather than counted as pure alpha. The system detects five market lifecycle regimes and adapts quoting aggressively: tightening in stable active periods, widening pre-resolution, suspending on adverse-selection signals, and triggering deterministic inventory flattening when position risk approaches limits. Four Claude agents operate as the research and operations layer above the autonomous Python strategy core; they never touch live order routing. Phase 1 deploys $50K on Polymarket; a VenueAdapter interface stubs Kalshi integration as a 3–4 week bolt-on once the core is validated.

---

## 2. DESIGN PRINCIPLES

1. **Realized edge over mark-to-mid.** Every PnL metric is computed on completed inventory cycles and settled markets. Mark-to-mid is reported for monitoring only, never used to evaluate strategy quality.
2. **FV independence.** Fair value is estimated independently of quoted mid. The system never anchors to the current best bid/ask as a proxy for true probability.
3. **Decomposable and falsifiable.** Every module has defined inputs, outputs, and a falsification test. No black boxes.
4. **Inventory path matters.** Inventory is tracked as signed contracts, state-contingent payout exposure, and capital lock-up simultaneously. Risk limits apply to all three dimensions.
5. **Incentives are conditional revenue.** Incentive payments are modeled subject to uptime, quote-width, minimum-size, and adverse-selection drag. Profitability is always reported with and without incentives.
6. **Regimes govern quoting.** Market lifecycle regime is the primary control variable. The system quotes, widens, suspends, or flattens based on regime, not just price signals.
7. **Adapter-clean.** All venue-specific logic is isolated behind the VenueAdapter interface. Strategy core has zero direct Polymarket dependencies.
8. **Staged deployment.** Backtest → paper → $5K UAT → $50K live. No stage is skipped.
9. **Claude agents observe and recommend; humans approve destructive actions.** No agent submits orders, changes live config, or restarts processes without human approval.
10. **Mandate track record from day one.** Quoting quality metrics (uptime, spread tightness, depth, fill rate) are logged from the first paper trade to build the mandate pitch dataset.

---

## 3. MARKET MICROSTRUCTURE MODEL

### 3.1 Polymarket CLOB Structure

Polymarket operates a Central Limit Order Book per binary market. Each market is a Yes/No question. Yes and No are separate ERC-1155 tokens within the Conditional Token Framework (CTF). A resolved Yes market pays $1 for each Yes token and $0 for each No token; resolution is the inverse for a No outcome.

- **Order book:** Only active when `enableOrderBook=true` on the market object.
- **Token IDs:** Each market has `tokenId_yes` and `tokenId_no` (hex strings). Orders reference token IDs, not market IDs directly.
- **Collateral:** USDC on Polygon. All positions and P&L denominated in USDC.
- **Tick size:** Typically 0.01 (1 cent). Min order size varies by market.
- **Fee structure:** Maker fee = 0 always. Taker fee is parabolic in price:
  `fee = C × feeRate × p × (1-p)` where C is shares, p is price, feeRate is category-specific.
  Category feeRates: Crypto = 0.07, Finance/Politics = 0.04, Sports = 0.03.
  Sports uses an alternate form `C × p × feeRate × (p(1-p))^exponent` with exponent=1,
  which equals `C × feeRate × p²(1-p)` — peaks at p=2/3, not p=0.5 like the standard formula.
  Runtime feeRate and exponent are fetched via `getClobMarketInfo(conditionID)` at market init.
  Makers receive a rebate ≈ rebate_fraction × feeRate × p × (1-p) per contract, where
  rebate_fraction ≈ 20–25% of collected taker fees (assumption; validate via API).
  **Critical implication:** fees peak at p=0.5 (midmarket) and shrink toward 0 or 1. The strategy
  must widen spreads at midmarket and can tighten them for near-resolved markets.
- **Queue model:** Price-time priority. Queue position is unknown post-reconnect.
- **Settlement:** On-chain CTF resolution. Redemption requires explicit on-chain call.

### 3.2 Binary Market Economics

For a Yes position held at price `p`:
- Payout if Yes resolves: `1 - p` (gain)
- Payout if No resolves: `-p` (loss)
- Expected value at FV: `FV×(1-p) + (1-FV)×(-p) = FV - p`

The maker earns positive expected value if `p < FV - AS - fee`.

**Why same-market opposite-side flattening differs from cross-market hedging:**

If the maker buys Yes at `p_yes` and later buys No at `p_no`:
- Combined payout: Yes resolves → `(1-p_yes) + (-p_no)` = `1 - p_yes - p_no`
- No resolves → `(-p_yes) + (1-p_no)` = `1 - p_yes - p_no`
- The payout is identical regardless of outcome: `1 - (p_yes + p_no)`
- This is positive if `p_yes + p_no < 1`, i.e., bought both sides for less than $1

This is risk-free arbitrage if both fills execute at the right prices. There is **no basis risk** because both legs reference the same resolution event. Contrast with cross-market hedging (e.g., hedging a Yes position via a correlated market), where the hedge has independent resolution risk.

The failure mode is not basis risk — it is **hedge delay**: the No side may not fill at an acceptable price before resolution, leaving a naked directional position.

### 3.3 Adverse Selection in Binary Markets

Binary markets have discontinuous payoffs. Informed traders have high conviction on resolution outcomes. Adverse selection in binary markets is therefore:

1. **Higher in absolute terms** than continuous markets — a fill at 46c from an informed trader who knows the answer is worth $0 or $1 implies full loss of $0.46 per contract.
2. **Concentrated near resolution.** Adverse selection intensity spikes as time-to-resolution shortens and as news arrives.
3. **Regime-dependent.** Adverse selection is low in new markets with thin information and high in markets where external events have just resolved or leaked.

**Adverse selection estimator:**

```
AS_t = E[|FV_{t+Δ} - FV_t| | passive fill at t]
     ≈ (1/N) Σ |mid_{t+30s} - mid_t| for fills in rolling window
```

This is re-estimated every 15 minutes per market. If `AS_t > S/2 - fee`, the market is suspended.

### 3.4 Why Mark-to-Mid Is Insufficient

Mark-to-mid PnL measures: `(mid_t - fill_price) × quantity`. It appears profitable whenever the market moves back toward mid after a fill. This is misleading for five reasons:

1. **Mid is not fair value.** In a thin binary book, mid can sit at 50c for a market that is truly 80c. The fill was at a "good" price relative to mid but a terrible price relative to FV.
2. **Opposite-side execution cost is invisible.** The flatten leg has a real cost (taker fee + slippage) not reflected in mark-to-mid.
3. **Hedge delay is not priced.** Inventory held overnight accrues capital charge; mark-to-mid ignores this.
4. **Resolution is binary.** A Yes position marked at 55c can still resolve to $0 with 45% probability. Mark-to-mid has no terminal condition.
5. **Incentives inflate mark-to-mid comparisons.** If the incentive program pays per quote-hour, the "PnL" includes payments that are not repeatable without the mandate.

**All strategy evaluation uses realized cycle PnL:** the sum of fill prices across a complete Yes+No round trip, compared to $1 (the arb target), net of all fees and capital charges.

### 3.5 Thin Book and Queue Position Uncertainty

Polymarket books are often thin (2–5 price levels, $100–$2,000 per level). This creates:

- **Queue position uncertainty:** After a WS reconnect or cancel/replace, the system loses its place in the queue. Model assumes worst-case (back of queue) after any reconnect.
- **Impact of own quotes:** On thin markets, the system's own quotes may constitute a significant fraction of displayed depth. Pulling quotes creates a visible signal.
- **Jump risk:** A single large informed order can move the entire book. The system must detect and respond within one quote cycle (<500ms).

---

## 4. STRATEGY ARCHITECTURES

### Artifact A: Architecture Comparison

| Architecture | Core idea | Edge source | Inventory behavior | Key failure mode | Data requirements | Backtest difficulty | Deployability |
|---|---|---|---|---|---|---|---|
| **A1: Symmetric Passive Spread Maker** | Quote both sides at fixed spread around FV; wait for passive round trip | Half-spread × fill rate + incentives | Accumulates on one-sided flow; mean-reverts only if two-way flow continues | Informed one-side fill; opposite side never fills before resolution; full adverse selection loss | Order book snapshots, trade history | Low — simple fill model | 9/10 |
| **A2: Regime-Adaptive Inventory-Managed MM (chosen)** | A1 core + regime detection + active inventory flattening when threshold breached | Spread capture in stable regimes + active risk control prevents adverse-selection traps + incentive optimization | Actively managed toward zero; aggressive flatten when threshold breached; warehouses only when justified by carry economics | Regime misclassification during news shock; system quotes through adverse selection event | Order book, trade history, time-to-resolution metadata, external FV signals | Medium — requires regime segmentation and hedge delay model | 7/10 |
| **A3: Multi-Market Portfolio MM** | Quote many markets; manage inventory at portfolio level; adverse selection diversified across uncorrelated events | Portfolio diversification + spread + incentives across wide market book | Portfolio-level netting; per-market spikes tolerated if aggregate balanced | Correlated resolution events (election night) break netting assumptions; simultaneous multi-market adverse selection | Full historical order book across 50+ markets, correlation model | High — requires portfolio risk engine and correlated-resolution stress tests | 4/10 |

---

## 5. CHOSEN SYSTEM DESIGN

Architecture 2: Regime-Adaptive Inventory-Managed Market Maker.

### 5.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CLAUDE AGENTS LAYER                       │
│  MarketResearchAgent │ CalibrationAgent │ MonitoringAgent    │
│                      │  IncidentAgent                        │
└──────────────────────┬──────────────────────────────────────┘
                       │ read-only telemetry / write alerts
┌──────────────────────▼──────────────────────────────────────┐
│                    STRATEGY CORE (Python)                     │
│                                                              │
│  MarketDataService ──► RegimeClassifier ──► QuoteEngine     │
│         │                    │                   │           │
│         │       HedgeabilityAssessor ────────────┤           │
│         │                    │                   │           │
│         │              InventoryManager ◄─────── │           │
│         │                    │                   │           │
│         └──► FairValueEstimator ─────────────────┘           │
│                         │                                    │
│                     RiskEngine ──► KillSwitch                │
│                         │                                    │
│                     PnLEngine                                │
└──────────────────────┬──────────────────────────────────────┘
                       │ normalized Order / Cancel objects
┌──────────────────────▼──────────────────────────────────────┐
│                  VENUE ADAPTER LAYER                         │
│    PolymarketAdapter          KalshiAdapter (stub)           │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 VenueAdapter Interface

```python
class VenueAdapter(Protocol):
    def submit_order(self, order: Order) -> OrderAck: ...
    def cancel_order(self, order_id: str) -> CancelAck: ...
    def amend_order(self, order_id: str, new_price: Decimal, new_size: Decimal) -> OrderAck: ...
    def get_order_book(self, market_id: str) -> OrderBook: ...
    def get_open_orders(self, market_id: str) -> list[Order]: ...
    def get_fills(self, since: datetime) -> list[Fill]: ...
    def get_balance(self) -> Balance: ...
    def get_markets(self, filters: MarketFilter) -> list[MarketMetadata]: ...
    def normalize_market(self, raw: dict) -> MarketMetadata: ...
    def subscribe_book(self, market_id: str, callback: Callable[[OrderBook], None]) -> None: ...
    def subscribe_fills(self, callback: Callable[[Fill], None]) -> None: ...
    def unsubscribe(self, market_id: str) -> None: ...
```

Adding Kalshi = implement this interface + market discovery adapter + historical data source. Strategy core is untouched.

### 5.3 HedgeabilityAssessor

The `HedgeabilityAssessor` runs before every quote submission and continuously while inventory is held. It answers two questions: (1) *can this position be economically hedged right now?* and (2) *if not, is the operator willing to hold a skew position and is there sufficient edge to justify it?*

**5.3.1 Net Opposing Depth Calculation**

Before quoting, the assessor strips own resting orders from the opposing side of the book to compute true external liquidity:

```python
def net_opposing_depth(book: OrderBook, own_orders: list[Order], side: Side,
                       max_acceptable_price: float) -> float:
    """
    Returns total external depth available on the opposing side
    within max_acceptable_price, excluding own resting orders.
    side: the side we HOLD (e.g. YES); opposing side is NO.
    """
    opposing_levels = book.asks if side == YES else book.bids
    own_ids = {o.order_id for o in own_orders}
    net = 0.0
    for level in opposing_levels:
        if not acceptable_price(level.price, side, max_acceptable_price):
            break
        external_size = sum(q.size for q in level.quotes if q.order_id not in own_ids)
        net += external_size
    return net
```

**5.3.2 Fee-Adjusted Maximum Acceptable Flatten Price**

The HedgeabilityAssessor calls `FeeModel.max_flatten_price()` directly — the same FeeModel instance used by QuoteEngine and PnLEngine. Fee parameters flow from one source: `getClobMarketInfo(conditionID)` at market init.

The taker fee is **parabolic**, not flat. This makes the breakeven condition a quadratic, not a linear equation. The exact closed-form solution (derived in Section 6.1):

```
max_flatten_price = FeeModel.max_flatten_price(p_fill, feeRate, rebate_fraction, min_edge_floor)

Derivation (reproduced for clarity):
  edge = (1 - p_fill - p_flatten)                              [arb payout]
       + rebate_fraction × feeRate × p_fill × (1-p_fill)       [rebate on maker fill]
       - feeRate × p_flatten × (1-p_flatten)                   [taker fee on flatten]
       - min_edge_floor                                         [required floor]
       ≥ 0

  Let LHS = 1 - p_fill + rebate_fraction × feeRate × p_fill(1-p_fill) - min_edge_floor
  Rearrange: LHS ≥ p_flatten × (1 + feeRate - feeRate × p_flatten)
  Quadratic: feeRate × p_flatten² - (1+feeRate) × p_flatten + LHS = 0
  Solution:  p_flatten_max = [(1+feeRate) - √((1+feeRate)² - 4×feeRate×LHS)] / (2×feeRate)

Numerical example — Finance market (feeRate=0.04), p_fill=0.46:
  rebate = 0.20 × 0.04 × 0.46 × 0.54 = 0.00199
  LHS    = 1 - 0.46 + 0.00199 - 0.005 = 0.53699
  disc   = 1.0816 - 4×0.04×0.53699 = 0.99568
  p_max  = (1.04 - 0.99784) / 0.08 = 0.527

  Interpretation: must buy No for ≤ 52.7c to break even after fees and rebate.
  The old flat-fee approximation (52.4c) understates the allowable price by 0.3c;
  this difference compounds across thousands of fills.

If discriminant < 0: no viable flatten price exists → do not quote on this market.
```

**5.3.3 Pre-Quote Hedgeability Gate**

Run at every quote cycle before submitting or refreshing a bid or ask:

```python
def hedgeability_assessment(
    side_to_quote: Side,          # the side we are about to passively quote
    quote_price: float,           # proposed passive quote price
    quote_size: float,            # proposed size
    book: OrderBook,
    own_orders: list[Order],
    fee_taker: float,
    rebate_maker: float,
    min_edge_floor: float,
    skew_config: SkewConfig,      # operator-configured skew tolerance
    current_skew_inventory: float # existing unhedgeable inventory on this market
) -> HedgeabilityResult:

    p_flatten_max = (1 - quote_price + rebate_maker - min_edge_floor) / (1 + fee_taker)
    net_depth = net_opposing_depth(book, own_orders, side_to_quote, p_flatten_max)

    hedgeable_size = min(quote_size, net_depth)
    unhedgeable_size = quote_size - hedgeable_size

    if unhedgeable_size == 0:
        return HedgeabilityResult(
            mode=FULLY_HEDGEABLE,
            allowed_size=quote_size,
            skew_size=0
        )

    # Check if operator allows skew for the unhedgeable portion
    skew_headroom = skew_config.skew_tolerance - current_skew_inventory
    skew_size = min(unhedgeable_size, skew_headroom)

    if skew_size > 0:
        # Skew is allowed up to tolerance; check edge premium is met
        required_edge = min_edge_floor + skew_config.skew_edge_premium
        expected_edge = (1 - quote_price) * skew_config.fv_estimate - quote_price
        if expected_edge < required_edge:
            skew_size = 0  # Edge premium not met; don't accept skew

    return HedgeabilityResult(
        mode=PARTIAL_SKEW if skew_size > 0 else UNHEDGEABLE_BLOCKED,
        allowed_size=hedgeable_size + skew_size,
        skew_size=skew_size,
        p_flatten_max=p_flatten_max,
        net_opposing_depth=net_depth
    )
```

**5.3.4 Skew Tolerance Configuration**

`SkewConfig` is an operator-level parameter set, configurable per market or globally:

```yaml
skew_config:
  skew_tolerance: 0           # USDC notional of unhedgeable inventory allowed
                              # 0 = strict market maker (default)
                              # e.g. 500 = willing to hold $500 unhedged per market
  skew_edge_premium: 0.02     # additional edge required over min_edge_floor
                              # before accepting unhedgeable fill (compensates
                              # for directional resolution risk)
  skew_hard_limit: 1000       # absolute maximum skew inventory regardless of
                              # edge premium; never exceeded
  skew_capital_charge_multiplier: 3.0
                              # capital charge on skew inventory is this multiple
                              # of standard capital charge (reflects higher risk)
```

**Setting `skew_tolerance = 0`** is the default and restores the strict hedgeability gate: the system will not quote any size it cannot immediately flatten at economic prices, net of fees.

**Setting `skew_tolerance > 0`** allows the system to deliberately hold a directional skew up to that notional, provided the edge premium condition is met. The skew inventory is tracked separately from hedgeable inventory throughout its life.

**5.3.5 Continuous Hedgeability Monitoring for Held Positions**

While inventory is held, the assessor re-evaluates opposing depth on every book update:

```python
def monitor_held_inventory(inventory: InventoryState, book: OrderBook,
                            own_orders: list[Order], skew_config: SkewConfig):
    p_flatten_max = compute_max_flatten_price(inventory)
    net_depth = net_opposing_depth(book, own_orders, inventory.side, p_flatten_max)

    coverage_ratio = net_depth / abs(inventory.hedgeable_notional)

    if coverage_ratio < 0.5:
        emit_alert(WARNING, "HEDGE_DEPTH_INSUFFICIENT",
                   value=coverage_ratio, threshold=0.5)
        # Escalate flatten urgency even if below INV_SOFT
        inventory.flatten_urgency = ELEVATED

    if coverage_ratio < 0.1 and inventory.skew_inventory == 0:
        # Hedgeable position is now effectively un-hedgeable; reclassify
        inventory.reclassify_to_skew(skew_config)
        emit_alert(CRITICAL, "INVENTORY_RECLASSIFIED_TO_SKEW")
```

**5.3.6 Two-Bucket Inventory Accounting**

Once inventory exists, it is classified into two buckets with separate risk limits, capital charges, and PnL attribution:

| Bucket | Definition | Capital charge multiplier | Risk limit | PnL attribution |
|---|---|---|---|---|
| `hedgeable` | Opposing-side depth ≥ position size at `p_flatten_max` | 1× standard | INV_SOFT / INV_HARD as before | Spread PnL |
| `skew` | No economic hedge available; held deliberately within `skew_tolerance` | `skew_capital_charge_multiplier` (default 3×) | `skew_hard_limit` | Directional PnL (reported separately) |

PnL attribution in the `PnLEngine`:
```
spread_pnl   = realized PnL from completed hedged round trips
skew_pnl     = realized PnL from resolved skew positions (settlement-only)
total_pnl    = spread_pnl + skew_pnl
```

Both are always reported separately. The mandate pitch reports `spread_pnl` as the primary metric. `skew_pnl` is disclosed as a separate line with a note that it represents deliberate directional exposure.

### 5.4 PolymarketAdapter Implementation Notes

- Auth: EIP-712 signing with private key; key stored in environment variable, never in config files
- Order submission: POST to Polymarket CLOB API (`/order`); include `tokenId`, `side`, `price`, `size`, `orderType`
- WebSocket: Subscribe to `book` and `trade` channels per `tokenId`
- Queue position: Tracked per resting order; reset to worst-case on reconnect
- Rate limits: Implement token-bucket limiter; default 10 req/s
- Polygon gas: Monitor gas prices; pause order submission if gas > threshold

### 5.4 Market Lifecycle State Machine

#### Artifact C: State Machine

```
                    ┌─────────────────┐
                    │   market_init   │
                    │ (new market     │
                    │  detected)      │
                    └────────┬────────┘
                             │ tradability score ≥ 4
                             ▼
                    ┌─────────────────┐
              ┌────►│  quote_active   │◄──────────────────┐
              │     │ (both sides     │                   │
              │     │  quoted)        │                   │
              │     └────────┬────────┘                   │
              │              │ passive fill               │
              │              ▼                            │
              │     ┌─────────────────┐                   │
              │     │ one_side_filled  │                   │
              │     │ (inventory held, │                   │
              │     │  opp. side order)│                  │
              │     └────────┬────────┘                   │
              │              │                            │
              │    ┌─────────┴──────────┐                 │
              │    │                    │                 │
              │  opp. side         inv > threshold        │
              │  fills             or regime shift        │
              │    │                    │                 │
              │    ▼                    ▼                 │
              │  round trip    ┌─────────────────┐        │
              │  complete      │  hedge_pending   │        │
              │    │           │ (aggressive      │        │
              │    │           │  flatten order   │        │
              │    │           │  submitted)      │        │
              │    │           └────────┬────────┘        │
              │    │                    │ flatten fills    │
              │    │                    ▼                  │
              │    │           ┌──────────────────┐        │
              │    │           │ inventory_reduced │        │
              │    │           │ (partial or full  │        │
              │    │           │  flatten done)    │        │
              │    │           └────────┬──────────┘        │
              │    │                    │                  │
              └────┴────────────────────┘                  │
                             │ if residual inv             │
                             ▼                             │
                    ┌──────────────────┐                   │
                    │inventory_warehouse│                   │
                    │(large inv held,   │                   │
                    │ one side suspended│                   │
                    │ carry assessed)   │                   │
                    └────────┬──────────┘                  │
                             │ carry justified              │
                             └────────────────────────────┘
                             │ carry NOT justified
                             ▼
                    ┌──────────────────┐
               ┌───►│  quote_suspend   │
               │    │ (all quotes      │
               │    │  cancelled,      │
               │    │  no new orders)  │
               │    └────────┬─────────┘
               │             │
               │   AS spike  │  normal conditions
               │   or halt   │  restored
               └─────────────┘
                             │ venue outage / halt
                             ▼
                    ┌──────────────────┐
                    │market_close_or   │
                    │halt              │
                    │(all orders pulled│
                    │ immediately)     │
                    └────────┬─────────┘
                             │ venue restores
                             ▼
                    ┌──────────────────┐
                    │resolution_pending│
                    │(T < T_alert,     │
                    │ all quotes off,  │
                    │ flatten only)    │
                    └────────┬─────────┘
                             │ market resolves
                             ▼
                    ┌──────────────────┐
                    │    settled       │
                    │ (CTF redemption  │
                    │  triggered,      │
                    │  cycle PnL       │
                    │  realized)       │
                    └──────────────────┘
```

**State transition table:**

| From | To | Trigger | Action |
|---|---|---|---|
| market_init | quote_active | Tradability score ≥ 4, book active | Submit initial bid + ask |
| market_init | quote_suspend | Score < 4 or no order book | Log, do not quote |
| quote_active | one_side_filled | Passive fill event received | Cancel filled side, submit opp-side passive order |
| quote_active | quote_suspend | AS spike, regime signal, FV confidence low | Cancel all orders |
| one_side_filled | hedge_pending | `\|inv\|` > INV_HARD or regime = resolution_pending | Submit aggressive flatten order |
| one_side_filled | inventory_reduced | Opposite passive fill | Update inventory, reassess |
| hedge_pending | inventory_reduced | Flatten fill received | Update inventory |
| inventory_reduced | quote_active | `\|inv\|` = 0 | Resume two-sided quoting |
| inventory_reduced | inventory_warehouse | `\|inv\|` > 0 and carry justified | Hold, reassess each cycle |
| inventory_warehouse | quote_active | Inventory cleared or carry no longer justified | Resume quoting |
| quote_active | market_close_or_halt | Venue WebSocket drop or halt signal | Cancel all immediately |
| any | resolution_pending | `time_to_resolution` < T_alert (default 1h) | Cancel all quotes, flatten aggressively |
| resolution_pending | settled | Resolution event received | Trigger CTF redemption |

---

## 6. MATHEMATICAL FRAMEWORK

### Artifact B: Formula Block

**6.1 Fee Model**

All fee and rebate calculations use a single `FeeModel` instance per market, instantiated at market init with parameters fetched from `getClobMarketInfo(conditionID)`. Every downstream component — HedgeabilityAssessor, QuoteEngine, PnLEngine, backtest simulator — uses this shared instance. There is one source of truth for `feeRate`.

```python
class FeeModel:
    """
    Polymarket parabolic fee model. feeRate and exponent fetched from
    getClobMarketInfo(conditionID) at market initialization.
    rebate_fraction is a global config assumption pending API validation.
    """
    CATEGORY_FEE_RATES = {
        'crypto': 0.07, 'politics': 0.04, 'finance': 0.04,
        'sports': 0.03, 'other': 0.04
    }
    DEFAULT_REBATE_FRACTION = 0.20  # assumption; validate via Polymarket LP docs

    def taker_fee(self, size: float, price: float,
                  fee_rate: float, exponent: int = 1) -> float:
        if exponent == 1:
            return size * fee_rate * price * (1 - price)          # standard
        else:
            return size * price * fee_rate * (price * (1-price)) ** exponent  # Sports

    def maker_rebate(self, size: float, price: float,
                     fee_rate: float, rebate_fraction: float) -> float:
        fee_equiv = size * fee_rate * price * (1 - price)
        return rebate_fraction * fee_equiv
        # NOTE: actual rebate = your_fee_equiv / total_market_fee_equiv × rebate_pool
        # The above is an approximation; it converges to the exact value as
        # the strategy's share of market volume stabilises.

    def fee_flatten_expected(self, fv: float,
                             fee_rate: float, exponent: int = 1) -> float:
        """
        Expected taker fee on aggressive flatten, evaluated at current FV.
        Used by QuoteEngine to set the half-spread floor.
        """
        if exponent == 1:
            return fee_rate * fv * (1 - fv)
        else:
            return fee_rate * fv * (fv * (1-fv)) ** exponent

    def max_flatten_price(self, p_fill: float, fee_rate: float,
                          rebate_fraction: float, min_edge_floor: float) -> float:
        """
        Maximum price at which the aggressive flatten still produces positive
        round-trip edge after fees and rebate. Exact quadratic solution.

        Derivation:
          edge = (1 - p_fill - p_flatten) + rebate(p_fill) - fee_taker(p_flatten) - floor ≥ 0
          Let rebate  = rebate_fraction × fee_rate × p_fill × (1-p_fill)
              LHS     = 1 - p_fill + rebate - floor
          Constraint: LHS ≥ p_flatten + fee_rate × p_flatten(1-p_flatten)
                          ≥ p_flatten × (1 + fee_rate - fee_rate × p_flatten)
          Quadratic:  fee_rate × p² - (1+fee_rate) × p + LHS = 0
          Lower root is the binding max price.
        """
        rebate = rebate_fraction * fee_rate * p_fill * (1 - p_fill)
        LHS = 1 - p_fill + rebate - min_edge_floor
        a, b, c = fee_rate, -(1 + fee_rate), LHS
        disc = b**2 - 4*a*c
        if disc < 0:
            return 0.0   # no viable flatten price; do not quote
        return (-b - math.sqrt(disc)) / (2 * a)
```

**Fee breakeven reference table** (min_edge_floor=0.005, rebate_fraction=0.20):

| Category | feeRate | p_fill=0.30 | p_fill=0.46 | p_fill=0.50 | p_fill=0.70 |
|---|---|---|---|---|---|
| Finance/Politics | 0.04 | 0.671 | 0.527 | 0.508 | 0.295 |
| Crypto | 0.07 | 0.657 | 0.521 | 0.503 | 0.289 |
| Sports | 0.03 | 0.677 | 0.531 | 0.512 | 0.299 |

*Read as: if you passively fill Yes at p_fill, you can pay at most p_flatten_max for an aggressive No flatten and still break even. Markets where best No ask exceeds this price must not be quoted (or placed in the skew bucket if within tolerance).*

**Sports formula note:** Sports fee = `C × feeRate × p²(1-p)` (peaks at p=2/3, not p=0.5). The `max_flatten_price` formula uses this via the `exponent` parameter, so Sports markets naturally allow a slightly wider flatten window at mid-prices.

---

**6.2 Fair Value Estimation**

```
FV(t) = w1 × FV_trade(t) + w2 × FV_external(t) + w3 × FV_base(t)

where:
  FV_trade(t)    = TWAP of recent trade prices, adjusted for book imbalance
                 = median(last 10 trade prices) × (1 + λ × book_imbalance)
  FV_external(t) = consensus probability from external source (Metaculus/Manifold)
                   if available, else 0 (w2 = 0)
  FV_base(t)     = historical resolution rate for this market category
  w1 + w2 + w3   = 1; defaults: w1=0.6, w2=0.3, w3=0.1

book_imbalance   = (bid_depth - ask_depth) / (bid_depth + ask_depth), ∈ [-1, 1]
λ                = 0.05 (assumption; calibrate live)

Confidence interval: [FV - 2σ_FV, FV + 2σ_FV]
  σ_FV = rolling std of FV_trade over 30-min window
```

**6.3 Quote Placement**

```
half_spread(t)  = max(S_min, α + β × σ_FV(t) + fee_flatten_expected(t) / 2)

  S_min                  = minimum half-spread floor (controllable; default 0.02)
  α                      = base half-spread (controllable; default 0.015)
  β                      = volatility loading (controllable; default 2.0)
  fee_flatten_expected(t) = FeeModel.fee_flatten_expected(FV(t), feeRate, exponent)
                           = feeRate × FV(t) × (1 - FV(t))   [standard form]

  This replaces the static fee_roundtrip/2 term. The spread floor is now dynamic:
  it widens when FV ≈ 0.5 (fees peak) and tightens when FV approaches 0 or 1
  (fees shrink). At FV=0.5 with feeRate=0.04: fee term = 0.04×0.25/2 = 0.005.
  At FV=0.8 with feeRate=0.04: fee term = 0.04×0.16/2 = 0.0032.
  The QuoteEngine calls FeeModel.fee_flatten_expected() on every quote cycle.

inventory_skew(t) = γ × inventory(t) / INV_MAX
  γ              = risk aversion (controllable; default 0.03)
  INV_MAX        = max inventory in contracts (controllable; default $5,000 notional)

bid(t)  = FV(t) - half_spread(t) - inventory_skew(t)
ask(t)  = FV(t) + half_spread(t) - inventory_skew(t)

Clamp: bid ∈ [0.01, 0.99], ask ∈ [0.01, 0.99], bid < ask
```

**6.4 Expected Edge per Passive Fill**

```
E[edge | fill] = half_spread(t) - AS(t) + expected_rebate(p_fill)

  AS(t)                  = EMA(|FV_{t+30s} - FV_t| for fills in rolling 1h window, α=0.1)
  expected_rebate(p_fill) = FeeModel.maker_rebate(size=1, p_fill, feeRate, rebate_fraction)
                           = rebate_fraction × feeRate × p_fill × (1-p_fill)

  Maker fee = 0 (Polymarket); rebate is positive revenue earned on the maker fill.
  The rebate is parabolic in fill price — highest at p=0.5, lowest near 0 or 1.
  Rebate is reported as a separate line item in PnL attribution, never blended into spread.

Minimum viable condition (S_min floor constraint):
  half_spread > AS - expected_rebate(FV)
  ⟹ S_min ≥ max(0, AS_typical - rebate_fraction × feeRate × FV × (1-FV))

  The rebate lowers the required S_min, making near-midmarket quotes more viable.
  This is the correct behavior: the fee structure subsidizes liquidity at mid.
```

**6.5 Expected Edge per Completed Inventory Cycle**

```
Standard cycle: passive initial fill (maker), aggressive flatten (taker).

E[edge | cycle] = (p_initial + p_flatten - 1) × size
                + rebate_initial × size        [maker rebate on initial fill]
                - fee_flatten × size           [taker fee on aggressive flatten]
                - hedge_slippage
                - capital_charge

  rebate_initial  = FeeModel.maker_rebate(1, p_initial, feeRate, rebate_fraction)
                  = rebate_fraction × feeRate × p_initial × (1-p_initial)

  fee_flatten     = FeeModel.taker_fee(1, p_flatten, feeRate, exponent)
                  = feeRate × p_flatten × (1-p_flatten)   [standard form]

  hedge_slippage  = (p_flatten_actual - p_flatten_expected) × size
                    [positive cost when aggressive fill is worse than mid estimate]

  capital_charge  = |inventory| × FV × r_opp × Δt_held
    r_opp         = 10% annualized (assumption)
    Δt_held       = seconds held / (365.25 × 86400)

Passive-passive cycle (both legs fill passively — best case):
  + rebate_initial + rebate_flatten - hedge_slippage = 0
  E[edge | passive cycle] = (p_initial + p_flatten - 1) × size
                           + (rebate_initial + rebate_flatten) × size
                           - capital_charge

Cycle edge is positive when:
  p_initial + p_flatten < 1                           [bought both for less than $1]
  AND rebate_initial > fee_flatten - (1 - p_initial - p_flatten)
  i.e., the spread plus rebate exceeds the flatten fee plus capital charge.

Note: feeRate and exponent are the SAME values fetched from getClobMarketInfo at
market init. PnLEngine uses FeeModel.taker_fee() and FeeModel.maker_rebate()
directly on every fill event — no approximations.
```

**6.5 All-In Mandate Economics**

```
mandate_economics = Σ_cycles [E[edge | cycle]]
                  + incentive_revenue_conditional
                  + retainer_revenue
                  - operational_costs
                  - capital_charge_total

  incentive_revenue_conditional = incentive_pool × uptime_fraction × depth_score
                                  × (1 - toxic_fill_rate)
    toxic_fill_rate = fills from informed flow / total fills (estimated by post-fill FV move)
    (Reported separately from spread edge; never combined into a single "edge" number)

  retainer_revenue = fixed periodic payment for quoting services (0 in Phase 1)

Profitability is always reported in two columns:
  gross_edge:   spread capture + cycle PnL, no incentives
  net_mandate:  gross_edge + incentive_conditional + retainer - all costs
```

**6.6 Adverse Selection Estimate**

```
AS_t = conditional expected mid-price move after passive fill:

  AS_t = EMA_{fills in rolling 1h window}(|mid_{t+30s} - mid_t|, α=0.1)

Decomposition:
  AS_t = AS_uninformed + AS_informed
  AS_informed / AS_t ≈ kyle_lambda × (fill_size / avg_trade_size)
    kyle_lambda estimated via OLS: Δmid_t = λ × order_flow_imbalance_t + ε

If AS_t > half_spread - fee: suspend quoting on this market
```

**6.7 Capital Usage / Balance-Sheet Charge**

```
capital_charge(position, Δt) = |position_notional| × r_opportunity × Δt

  position_notional = |inventory| × FV     (mark-to-market notional)
  r_opportunity     = 10% annualized (assumption; replace with actual cost of capital)
  Δt                = holding period in years

Portfolio capital utilization:
  util = Σ_markets |position_notional_i| / total_capital
  Target: util < 0.4 in Phase 1 ($50K total → max $20K in positions)
  Hard limit: util > 0.8 → halt new quotes
```

**6.8 Quote Optimization Objective**

```
maximize: E[spread_revenue] - E[adverse_selection_cost] - E[capital_charge] + E[incentive_revenue]

subject to:
  half_spread ≥ S_min
  |inventory| ≤ INV_MAX
  util ≤ 0.8
  regime ∈ {quote_active, inventory_reduced}
  AS_t ≤ half_spread - fee_maker

Simplified per-market objective at each quoting cycle (every 500ms):

  J(S) = S × fill_probability(S) - AS × fill_probability(S) - capital_charge(expected_hold_time)
       + incentive_per_contract × fill_probability(S)

  fill_probability(S) ≈ 1 / (1 + exp(k × (S - S_market)))
    S_market = observed competing spread; k = 5 (assumption; calibrate)

  Optimal S* = argmax J(S) subject to constraints above
```

**6.9 Flatten-or-Hold Decision Rule**

```
decision = flatten_aggressive  if:
    |inventory| > INV_HARD                          # hard limit
    OR regime == resolution_pending                  # time constraint
    OR time_to_resolution < T_alert                  # 1h default
    OR AS_t > AS_CRITICAL                            # toxic flow detected

decision = flatten_passive     if:
    INV_SOFT < |inventory| ≤ INV_HARD              # elevated but manageable
    AND regime ∈ {one_side_filled, inventory_reduced}
    AND time_to_resolution > T_alert

decision = hold                if:
    |inventory| ≤ INV_SOFT                          # within normal range
    AND carry_justified(inventory, FV, time_to_resolution)
    AND regime ∈ {quote_active, inventory_warehouse}

carry_justified(inv, FV, TTR) = True  if:
    E[passive_flatten_edge] > capital_charge(inv, TTR)
    i.e., (FV_opp_side - current_opp_ask) × |inv| > capital_charge

Defaults: INV_SOFT = 0.4 × INV_MAX; INV_HARD = 0.8 × INV_MAX
```

**6.10 Inventory Risk Penalty**

```
inventory_risk_penalty(inv) = ρ × (inv / INV_MAX)²

  ρ = penalty scaling (controllable; default 0.005 per contract-hour)

Applied as: effective_half_spread = half_spread - inventory_risk_penalty(inv)
  → as inventory grows, effective spread earned decreases
  → system naturally incentivized to flatten before hard limits

State-contingent payout exposure:
  payout_if_yes  =  inventory_yes × (1 - avg_fill_yes) + inventory_no × (-avg_fill_no)
  payout_if_no   =  inventory_yes × (-avg_fill_yes) + inventory_no × (1 - avg_fill_no)
  max_loss       =  min(payout_if_yes, payout_if_no)  [should be negative in loss case]
  Risk limit applied to max_loss, not just signed net inventory.
```

**6.11 Incentive-Adjusted Effective Spread**

```
effective_spread = realized_half_spread
                 + incentive_per_contract
                 - fee_roundtrip / 2
                 - AS_t
                 - capital_charge_per_contract

  realized_half_spread  = |fill_price - mid_at_fill| (per fill, averaged over session)
  incentive_per_contract = incentive_pool_payout / total_contracts_quoted

Reported in two modes:
  1. gross_effective_spread:  no incentives
  2. net_effective_spread:    with incentives

Mandate pitch uses net_effective_spread but must disclose both.
```

**6.13 Hedgeability and Skew Tolerance Framework**

All values below are computed using the shared `FeeModel` instance for the market.

```
--- Pre-Quote Hedgeability Gate ---

max_flatten_price = FeeModel.max_flatten_price(p_fill_estimate, feeRate, rebate_fraction,
                                               min_edge_floor)
  [exact quadratic formula — see Section 6.1 and 5.3.2]
  p_fill_estimate = proposed quote price (bid or ask)

net_opposing_depth = Σ sizes at opposing levels where level.price ≤ max_flatten_price,
                     EXCLUDING own resting orders at those levels

hedgeable_size     = min(proposed_quote_size, net_opposing_depth)
unhedgeable_size   = proposed_quote_size - hedgeable_size

--- Skew Acceptance Test (runs only if unhedgeable_size > 0) ---

skew_headroom        = skew_tolerance - current_skew_inventory_notional
allowed_skew_size    = min(unhedgeable_size, skew_headroom)

rebate_on_skew_fill  = FeeModel.maker_rebate(1, p_fill_estimate, feeRate, rebate_fraction)
  [rebate earned on initial fill reduces effective cost basis of the skew position]

effective_cost_basis = p_fill_estimate - rebate_on_skew_fill
  = p_fill_estimate × (1 - rebate_fraction × feeRate × (1-p_fill_estimate))

skew_edge_expected   = FV_opposing_estimate - effective_cost_basis
  [directional EV of holding skew to resolution or eventual passive flatten]

skew_edge_required   = min_edge_floor + skew_edge_premium

if skew_edge_expected < skew_edge_required:
    allowed_skew_size = 0   # edge premium not met even with rebate; block skew

final_quote_size     = hedgeable_size + allowed_skew_size

--- Capital Charges by Bucket (PnLEngine applies these on every inventory tick) ---

capital_charge_hedgeable(pos, Δt) = |pos| × FV × r_opp × Δt
capital_charge_skew(pos, Δt)      = |pos| × FV × r_opp × Δt × skew_capital_charge_multiplier
  skew_capital_charge_multiplier  = 3.0 (default; reflects full directional resolution risk)

--- Skew PnL at Settlement ---

skew_pnl(market) = Σ_skew_positions [payout_at_resolution - effective_cost_basis × size
                                      - capital_charge_skew_accrued]

  payout_at_resolution = size × (1 - effective_cost_basis) if outcome matches position
                       = size × (0 - effective_cost_basis) if outcome opposes position

skew_pnl reported separately from spread_pnl at all times.
Flag if skew_pnl > spread_pnl in any trailing 30-day window.

--- Integration Check ---
The following values must be consistent across all components:
  feeRate          → fetched once via getClobMarketInfo; stored in MarketMetadata
  rebate_fraction  → single global config parameter
  min_edge_floor   → single config parameter
  FeeModel instance → shared between HedgeabilityAssessor, QuoteEngine, PnLEngine, Backtest
Any component that uses a fee approximation instead of FeeModel is a bug.
```

**6.13 Edge Measurement Across Four Dimensions**

| Dimension | Formula | Unit | Why it matters |
|---|---|---|---|
| Per fill | `half_spread - AS - fee_maker` | USDC per contract | Immediate signal on quoting quality; fast feedback loop |
| Per completed round trip | `(p_yes + p_no - 1) × size - all_fees - capital_charge` | USDC per cycle | Only fully realized metric; mandate benchmark |
| Per market-hour | `cycle_edge_sum / total_market_hours_quoted` | USDC / market-hour | Uptime normalization; mandate uptime score |
| Per unit of balance sheet | `cycle_edge_sum / avg_capital_deployed` | USDC / USDC deployed | Capital efficiency; determines scale-up decision |

---

## 7. BACKTEST SPECIFICATION

### Artifact D: Full Backtest Specification

**7.1 Simulator Design: Event-Driven Architecture**

```python
class EventDrivenSimulator:
    event_queue: PriorityQueue[Event]   # ordered by timestamp
    order_book: SimulatedOrderBook
    strategy: RegimeAdaptiveMMStrategy
    fill_model: FillModel
    fee_model: FeeModel
    inventory: InventoryState
    pnl_engine: PnLEngine

    def run(self, events: list[MarketEvent]) -> BacktestResult:
        for event in sorted(events, key=lambda e: e.timestamp):
            self.dispatch(event)
        return self.pnl_engine.finalize()

    def dispatch(self, event: MarketEvent):
        match event.type:
            case BOOK_UPDATE:   self.on_book_update(event)
            case TRADE:         self.on_trade(event)
            case ORDER_FILL:    self.on_fill(event)
            case MARKET_HALT:   self.on_halt(event)
            case RESOLUTION:    self.on_resolution(event)
            case TIMER:         self.on_timer(event)   # quote refresh, regime check
```

Events are replayed in strict timestamp order. Strategy decisions happen at the timestamp of the triggering event plus a simulated latency offset.

**7.2 Historical Data Requirements**

| Data type | Source | Format | Retention | Notes |
|---|---|---|---|---|
| Order book snapshots | Polymarket CLOB API (historical) | L2 book per tokenId | Full history | Min 100ms granularity preferred |
| Trade events | Polymarket trade history | Price, size, timestamp, aggressor | Full history | Required for AS estimation |
| Market metadata | Polymarket markets API | enableOrderBook, tokenIds, resolution date, category | Per market | Required for regime classification |
| Resolution outcomes | Polymarket resolution history | Outcome + timestamp | Full history | Required for settlement simulation |
| External FV signals | Metaculus/Manifold API | Probability time series | Per market | Optional; improves FV estimation |

**7.3 Order Book Replay Assumptions**

- Assumption: Own orders do not appear in historical book. Assumption is clearly labeled; ablation test removes own-order depth effect.
- Own quotes are inserted at their price level with their size, behind existing orders at the same price (worst-case queue position).
- Book state is updated by replaying all historical order events. Snapshots are used to fill gaps.
- Own cancel events are processed immediately (zero latency); opponent orders are replayed as-is.

**7.4 Queue Position Model Options**

Three options; default is Option B:

| Option | Description | Bias | When to use |
|---|---|---|---|
| A: Front of queue | Own orders fill before any others at same price | Optimistic | Upper bound only |
| B: Pro-rata at arrival (default) | Own order fills proportionally to its size / total size at level | Realistic | Primary backtest |
| C: Back of queue | Own orders fill last at any price level | Pessimistic | Conservative bound |

Backtests must report results under all three. Mandate pitch uses Option B; stress-test uses Option C.

**7.5 Fill Model Options**

| Option | Description |
|---|---|
| Passive fill: touch model | Assume fill whenever opposing market order crosses price level |
| Passive fill: volume model | Fill with probability = own_size / total_resting_size_at_level × volume_that_crossed |
| Aggressive fill: immediate | Assume full fill at best available price at submission timestamp + latency |
| Aggressive fill: impact model | Aggressive order walks the book; price impact applied based on own size vs. book depth |

Default: passive = volume model (Option B above); aggressive = impact model.

**7.6 Latency Model**

```
total_latency = network_latency + processing_latency + venue_latency

  network_latency   = sampled from lognormal(μ=50ms, σ=20ms)  [assumption; calibrate with live]
  processing_latency = 10ms fixed [assumption]
  venue_latency      = 20ms fixed [Polymarket CLOB assumption]

Quote decisions are delayed by total_latency before reaching the book.
Order cancels incur full latency; stale quotes may fill during latency window.
```

**7.7 Hedge Delay Model**

```
hedge_delay = time between one_side_filled event and opposite_side_fill event

Modeled as:
  hedge_delay ~ Gamma(shape=k, scale=θ)
  Parameters estimated from historical opposing-side fill time distributions per market category.

  If hedge_delay > resolution_time: position expires unhedged → full adverse-selection scenario
  Probability of unhedged expiry: P(hedge_delay > TTR) estimated per regime/category

Hedge slippage:
  slippage = (aggressive_fill_price - mid_at_hedge_decision) × size
           [negative for buys above mid; positive for sells below mid]
```

**7.8 Partial Fill Handling**

- Partial fills create fractional inventory.
- Remaining open order stays resting; fill events processed incrementally.
- Risk limits apply to total position including partial fills.
- PnL accrual: each partial fill is a separate realized lot for capital charge calculation.
- If partial fill triggers INV_SOFT, system switches to flatten_passive immediately on remaining unfilled quantity.

**7.9 Fee / Rebate / Incentive Model**

The backtest fee model uses the same `FeeModel` class as the live system. There is no separate backtest fee approximation — any divergence between backtest and live fee calculations is a bug.

```python
# Backtest fee model — identical to live FeeModel
class BacktestFeeModel(FeeModel):
    pass   # no overrides; same code path as production

# Applied per simulated fill event:
def on_simulated_fill(fill: Fill, market: MarketMetadata, fee_model: FeeModel):
    if fill.fill_type == TAKER:
        fill.fee_paid = fee_model.taker_fee(fill.size, fill.price,
                                            market.fee_rate, market.fee_exponent)
        fill.rebate_received = 0.0
    else:  # MAKER
        fill.fee_paid = 0.0
        fill.rebate_received = fee_model.maker_rebate(fill.size, fill.price,
                                                       market.fee_rate,
                                                       market.rebate_fraction)
```

```
Category fee rates (from getClobMarketInfo; hardcoded in backtest as defaults):
  crypto:          feeRate = 0.07, exponent = 1
  politics/finance: feeRate = 0.04, exponent = 1
  sports:          feeRate = 0.03, exponent = 1   [NOTE: Sports formula = p²(1-p); peaks at p=2/3]
  other:           feeRate = 0.04, exponent = 1   [default; verify per market]

rebate_fraction = 0.20  [assumption; labeled as such in all backtest outputs]
                         [run sensitivity: rebate_fraction ∈ {0.0, 0.15, 0.20, 0.25}]

incentive_model:
  incentive_per_hour = I_pool × (time_at_top_of_book / total_market_hours)
                     × (1 if quote_width ≤ W_threshold else 0)
                     × (1 if displayed_size ≥ SIZE_threshold else 0)

  I_pool      = 0 for gross backtest; parameterized for net backtest
  W_threshold = 5c default
  SIZE_threshold = $100 default

Backtest parameter sweep must include rebate_fraction sensitivity.
All results reported in three columns:
  gross: no rebate, no incentives
  rebate_only: with rebate, no incentive pool
  net: with rebate and incentive pool
```

**7.10 Retainer Economics Model**

```
retainer_pnl = retainer_monthly / (trading_days × market_hours_per_day)  [per hour allocation]

Phase 1: retainer = 0 (pre-mandate)
Phase 2+: retainer = negotiated amount; allocated pro-rata to market-hours quoted

Retainer is always reported as a separate line item, never blended into spread edge.
```

**7.11 Capital Lock-Up Model**

```
Each open position locks capital:
  locked_capital(position) = position_size × collateral_per_contract

  For Polymarket Yes position: collateral = fill_price × size (USDC locked)
  For Polymarket No position: collateral = (1 - fill_price) × size (USDC locked; Yes+No = $1 total)

Total locked = Σ_markets locked_capital(position_i)
Available capital = total_capital - total_locked
New positions blocked if: available_capital < min_reserve (default: 20% of total_capital)
```

**7.12 Mark-to-Market vs Realization Logic**

```
mark_to_mid_pnl(t) = Σ_positions [(mid_t - avg_fill_price) × size]
  → Reported for monitoring only; not used for strategy evaluation

realized_pnl(cycle) = (p_yes + p_no - 1) × size - all_fees - capital_charge
  → Primary strategy metric

settled_pnl(market) = Σ_cycles realized_pnl(cycle)
                    + settlement_payout                     [on-chain CTF redemption]
                    → Final P&L for the market; logged to mandate track record
```

**7.13 End-of-Market Settlement Logic**

```
On RESOLUTION event:
  1. Cancel all open orders immediately (zero latency in simulation)
  2. For each open position:
     if outcome == YES: payout = inventory_yes × 1.00 + inventory_no × 0.00
     if outcome == NO:  payout = inventory_yes × 0.00 + inventory_no × 1.00
  3. settled_pnl = payout - Σ fill_costs - capital_charges
  4. Log to PnLEngine; update mandate metrics
  5. Transition market to settled state
```

**7.14 Venue Outage / Halt Logic**

```
On HALT event (WS drop or explicit halt signal):
  1. Transition all active markets to market_close_or_halt
  2. Record last known inventory for each market
  3. Resume quoting only after WS reconnect + full book re-sync confirmed
  4. Queue position reset to worst-case (back of queue) after reconnect
  5. Do not submit orders during reconnect window
  6. Log halt duration to mandate uptime metrics
```

**7.15 Parameter Sweep Plan**

```
Parameters to sweep:
  S_min:     [0.01, 0.02, 0.03, 0.04, 0.05]
  α:         [0.01, 0.015, 0.02, 0.025]
  β:         [1.0, 1.5, 2.0, 3.0]
  γ:         [0.01, 0.02, 0.03, 0.05]
  INV_MAX:   [$1K, $2.5K, $5K, $10K] notional
  T_alert:   [30m, 1h, 2h, 4h]
  AS_thresh: [0.01, 0.02, 0.03]

Grid search: 5×4×4×4×4×4×3 = 15,360 combinations
Reduce via Sobol sequence sampling to 500 representative combinations.
Evaluate each on: realized_pnl, cycle_count, capital_efficiency, adverse_selection_rate, uptime.
```

**7.16 Walk-Forward / Regime Segmentation Plan**

```
Time segmentation:
  Train:    first 60% of historical data per market category
  Validate: next 20%
  Test:     final 20% (held out until final evaluation)

Regime segmentation:
  Segment by: market category (politics, sports, crypto, other)
              time-to-resolution at quote initiation (>7d, 1–7d, <1d)
              market activity level (high/medium/low volume)

Report performance separately per segment.
Strategy must show positive realized edge in at least 4 of 6 major segments before live deployment.
```

**7.17 Ablation Study Plan**

Each component is tested by removing it and comparing performance:

| Ablation | What is removed | Hypothesis tested |
|---|---|---|
| No regime detection | All regimes treated as quote_active | Regime detection reduces adverse selection |
| No inventory skew | γ = 0 | Skew reduces inventory accumulation |
| No FV external signal | w2 = 0 | External signal improves FV accuracy |
| No aggressive flatten | Hold inventory passively always | Active flatten reduces resolution exposure |
| No AS detection | Never suspend on AS | AS detection prevents loss-making quoting |
| No capital charge | r_opportunity = 0 | Capital charge correctly penalizes warehousing |

**7.18 Falsification Tests for the Central Hypothesis**

*Central hypothesis: quoting both sides of the same binary market and flattening via the opposite side generates positive realized edge after all costs.*

The hypothesis is **falsified** if any of the following are observed:

1. **Realized cycle PnL is negative** across the full test set after fees and capital charges, even before incentives.
2. **P(p_yes + p_no > 1) > 0.5** across completed cycles: the system routinely paid more than $1 total to flatten, implying structural loss-making.
3. **Hedge delay distribution shows P(hedge_delay > TTR) > 0.1**: more than 10% of filled positions expire unhedged.
4. **Post-fill FV move exceeds half-spread in the same direction in >60% of fills**: adverse selection dominates unconditionally.
5. **Net PnL without incentives is negative** and incentives account for >100% of total net PnL: the strategy is purely an incentive-farming operation with no intrinsic spread edge.
6. **Capital efficiency < 0**: annualized return on deployed capital is negative even including incentives.

---

## 8. DATA MODEL & SCHEMAS

### Artifact E: JSON Schemas

**8.1 Market Metadata**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MarketMetadata",
  "type": "object",
  "required": ["market_id", "question", "token_id_yes", "token_id_no", "enable_order_book",
               "resolution_date", "category", "created_at"],
  "properties": {
    "market_id": { "type": "string", "description": "Polymarket condition ID (hex)" },
    "question": { "type": "string" },
    "token_id_yes": { "type": "string", "description": "ERC-1155 token ID for Yes" },
    "token_id_no": { "type": "string", "description": "ERC-1155 token ID for No" },
    "enable_order_book": { "type": "boolean" },
    "resolution_date": { "type": "string", "format": "date-time" },
    "category": { "type": "string", "enum": ["politics", "sports", "crypto", "economics", "other"] },
    "min_order_size": { "type": "number" },
    "tick_size": { "type": "number" },
    "created_at": { "type": "string", "format": "date-time" },
    "tradability_score": { "type": "number", "minimum": 0, "maximum": 10 },
    "fv_estimate": { "type": "number", "minimum": 0, "maximum": 1 },
    "fv_confidence_lo": { "type": "number" },
    "fv_confidence_hi": { "type": "number" },
    "fee_rate": { "type": "number", "description": "Taker feeRate from getClobMarketInfo; e.g. 0.04 for Finance" },
    "fee_exponent": { "type": "integer", "default": 1, "description": "Fee formula exponent; 1 for standard, >1 alters shape (Sports)" },
    "rebate_fraction": { "type": "number", "description": "Maker rebate as fraction of taker fees; assumed 0.20, override per market" },
    "fee_formula_note": { "type": "string", "description": "Human-readable: 'standard p(1-p)' or 'sports p²(1-p)' etc." }
  }
}
```

**8.2 Order Events**

```json
{
  "title": "OrderEvent",
  "type": "object",
  "required": ["order_id", "market_id", "token_id", "side", "price", "size",
               "order_type", "status", "timestamp"],
  "properties": {
    "order_id": { "type": "string" },
    "market_id": { "type": "string" },
    "token_id": { "type": "string" },
    "side": { "type": "string", "enum": ["BUY", "SELL"] },
    "price": { "type": "number", "minimum": 0.01, "maximum": 0.99 },
    "size": { "type": "number", "exclusiveMinimum": 0 },
    "order_type": { "type": "string", "enum": ["LIMIT", "MARKET", "GTC", "GTD"] },
    "status": { "type": "string", "enum": ["PENDING", "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"] },
    "timestamp": { "type": "string", "format": "date-time" },
    "strategy_regime": { "type": "string", "description": "Regime at time of submission" },
    "intent": { "type": "string", "enum": ["MAKE_BID", "MAKE_ASK", "FLATTEN_PASSIVE", "FLATTEN_AGGRESSIVE"] }
  }
}
```

**8.3 Fill Events**

```json
{
  "title": "FillEvent",
  "type": "object",
  "required": ["fill_id", "order_id", "market_id", "token_id", "side", "fill_price",
               "fill_size", "fill_type", "timestamp", "fee_paid"],
  "properties": {
    "fill_id": { "type": "string" },
    "order_id": { "type": "string" },
    "market_id": { "type": "string" },
    "token_id": { "type": "string" },
    "side": { "type": "string", "enum": ["BUY", "SELL"] },
    "fill_price": { "type": "number" },
    "fill_size": { "type": "number" },
    "fill_type": { "type": "string", "enum": ["MAKER", "TAKER"] },
    "timestamp": { "type": "string", "format": "date-time" },
    "fee_paid": { "type": "number" },
    "fv_at_fill": { "type": "number", "description": "FV estimate at fill timestamp" },
    "mid_at_fill": { "type": "number" },
    "mid_30s_post_fill": { "type": "number", "description": "For AS calculation" },
    "regime_at_fill": { "type": "string" },
    "cycle_id": { "type": "string", "description": "Links to inventory cycle" }
  }
}
```

**8.4 Inventory State**

```json
{
  "title": "InventoryState",
  "type": "object",
  "required": ["market_id", "timestamp", "inventory_yes", "inventory_no",
               "avg_fill_price_yes", "avg_fill_price_no", "locked_capital",
               "payout_if_yes", "payout_if_no", "max_loss"],
  "properties": {
    "market_id": { "type": "string" },
    "timestamp": { "type": "string", "format": "date-time" },
    "inventory_yes": { "type": "number", "description": "Signed Yes position in contracts (total)" },
    "inventory_no": { "type": "number", "description": "Signed No position in contracts (total)" },
    "inventory_yes_hedgeable": { "type": "number", "description": "Yes inventory with opposing depth available at economic price" },
    "inventory_yes_skew": { "type": "number", "description": "Yes inventory held deliberately without hedge; within skew_tolerance" },
    "inventory_no_hedgeable": { "type": "number" },
    "inventory_no_skew": { "type": "number" },
    "avg_fill_price_yes": { "type": "number" },
    "avg_fill_price_no": { "type": "number" },
    "locked_capital": { "type": "number", "description": "USDC locked as collateral" },
    "payout_if_yes": { "type": "number", "description": "Net USDC payout if market resolves Yes" },
    "payout_if_no": { "type": "number", "description": "Net USDC payout if market resolves No" },
    "max_loss": { "type": "number", "description": "min(payout_if_yes, payout_if_no); negative = loss" },
    "regime": { "type": "string" },
    "capital_charge_accrued": { "type": "number", "description": "Standard capital charge on hedgeable inventory" },
    "skew_capital_charge_accrued": { "type": "number", "description": "Elevated capital charge on skew inventory (3× multiplier)" },
    "net_opposing_depth_at_last_check": { "type": "number", "description": "External depth available at max_flatten_price; updated each book tick" },
    "hedge_coverage_ratio": { "type": "number", "description": "net_opposing_depth / hedgeable_inventory; <0.5 triggers WARNING" }
  }
}
```

**8.5 Strategy Decisions**

```json
{
  "title": "StrategyDecision",
  "type": "object",
  "required": ["decision_id", "market_id", "timestamp", "regime", "fv", "half_spread",
               "bid", "ask", "action"],
  "properties": {
    "decision_id": { "type": "string" },
    "market_id": { "type": "string" },
    "timestamp": { "type": "string", "format": "date-time" },
    "regime": { "type": "string" },
    "fv": { "type": "number" },
    "fv_confidence_lo": { "type": "number" },
    "fv_confidence_hi": { "type": "number" },
    "half_spread": { "type": "number" },
    "inventory_skew": { "type": "number" },
    "bid": { "type": "number" },
    "ask": { "type": "number" },
    "action": { "type": "string", "enum": ["QUOTE_BOTH", "QUOTE_ONE_SIDE", "FLATTEN_PASSIVE", "FLATTEN_AGGRESSIVE", "SUSPEND", "HOLD"] },
    "as_estimate": { "type": "number" },
    "rationale": { "type": "string" }
  }
}
```

**8.6 Risk Alerts**

```json
{
  "title": "RiskAlert",
  "type": "object",
  "required": ["alert_id", "timestamp", "severity", "market_id", "alert_type", "value", "threshold"],
  "properties": {
    "alert_id": { "type": "string" },
    "timestamp": { "type": "string", "format": "date-time" },
    "severity": { "type": "string", "enum": ["INFO", "WARNING", "CRITICAL", "KILL"] },
    "market_id": { "type": "string", "description": "null for portfolio-level alerts" },
    "alert_type": { "type": "string", "enum": [
      "INVENTORY_SOFT_BREACH", "INVENTORY_HARD_BREACH",
      "AS_SPIKE", "CAPITAL_UTIL_HIGH", "KILL_SWITCH_TRIGGERED",
      "WS_RECONNECT", "FILL_RATE_ANOMALY", "FV_CONFIDENCE_LOW",
      "RESOLUTION_APPROACHING", "VENUE_HALT",
      "HEDGE_DEPTH_INSUFFICIENT", "SKEW_TOLERANCE_BREACH",
      "INVENTORY_RECLASSIFIED_TO_SKEW", "SKEW_PNL_DOMINATES_SPREAD_PNL"
    ]},
    "value": { "type": "number", "description": "Current value of monitored metric" },
    "threshold": { "type": "number", "description": "Threshold that was breached" },
    "action_taken": { "type": "string" },
    "requires_human_approval": { "type": "boolean" }
  }
}
```

**8.7 Backtest Results**

```json
{
  "title": "BacktestResult",
  "type": "object",
  "required": ["experiment_id", "run_timestamp", "parameters", "metrics", "regime_breakdown"],
  "properties": {
    "experiment_id": { "type": "string" },
    "run_timestamp": { "type": "string", "format": "date-time" },
    "parameters": { "type": "object", "description": "Full parameter set used" },
    "metrics": {
      "type": "object",
      "properties": {
        "total_realized_pnl_gross": { "type": "number" },
        "total_realized_pnl_net": { "type": "number" },
        "total_cycles_completed": { "type": "integer" },
        "avg_edge_per_fill_gross": { "type": "number" },
        "avg_edge_per_cycle_gross": { "type": "number" },
        "avg_edge_per_market_hour": { "type": "number" },
        "capital_efficiency_annualized": { "type": "number" },
        "adverse_selection_rate": { "type": "number" },
        "unhedged_expiry_rate": { "type": "number" },
        "uptime_fraction": { "type": "number" },
        "toxic_fill_rate": { "type": "number" },
        "avg_hedge_delay_seconds": { "type": "number" },
        "max_drawdown": { "type": "number" },
        "capital_efficiency_net": { "type": "number" }
      }
    },
    "regime_breakdown": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "regime": { "type": "string" },
          "cycles": { "type": "integer" },
          "pnl": { "type": "number" },
          "as_rate": { "type": "number" }
        }
      }
    },
    "falsification_tests": {
      "type": "object",
      "properties": {
        "hypothesis_supported": { "type": "boolean" },
        "tests_passed": { "type": "array", "items": { "type": "string" } },
        "tests_failed": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

**8.8 Experiment Manifest**

```json
{
  "title": "ExperimentManifest",
  "type": "object",
  "required": ["experiment_id", "description", "created_at", "parameter_space",
               "markets_included", "data_range", "hypothesis", "acceptance_criteria"],
  "properties": {
    "experiment_id": { "type": "string" },
    "description": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "parameter_space": { "type": "object", "description": "Parameter ranges for sweep" },
    "markets_included": { "type": "array", "items": { "type": "string" } },
    "data_range": {
      "type": "object",
      "properties": {
        "start": { "type": "string", "format": "date-time" },
        "end": { "type": "string", "format": "date-time" }
      }
    },
    "hypothesis": { "type": "string" },
    "acceptance_criteria": { "type": "array", "items": { "type": "string" } },
    "queue_model": { "type": "string", "enum": ["FRONT", "PRO_RATA", "BACK"] },
    "fill_model": { "type": "string", "enum": ["TOUCH", "VOLUME", "IMPACT"] },
    "include_incentives": { "type": "boolean" }
  }
}
```

---

## 9. AGENTIC CLAUDE DEPLOYMENT DESIGN

### Artifact F: Named Agent Specifications

Claude agents operate as the research and operations layer. They read telemetry, write reports and alerts, and surface recommendations. **No agent submits live orders, modifies live configuration, or restarts production processes.** All such actions require human approval.

---

**Agent 1: MarketResearchAgent**

- **Mission:** Assess new Polymarket markets for tradability before capital is committed. Provide FV estimates, identify correlated existing positions, and flag resolution ambiguity.
- **Trigger:** Scheduled daily scan + webhook on new market detection
- **Inputs:**
  - Market metadata JSON (question text, category, resolution date, token IDs, current book state)
  - Existing position inventory (read-only)
  - Historical resolution data for same category (read from database)
- **Outputs:**
  - `MarketAssessment` JSON: tradability score (0–10), estimated FV + CI, recommended initial S_min, correlation flag
  - Written to `data/market_assessments/{market_id}.json`
  - If score ≥ 7: auto-approve for quoting
  - If score 4–6: flag for human review before quoting
  - If score < 4: do not quote; log reason
- **Allowed tools:** `web_search`, `read_file`, `write_file`
- **Forbidden:** Any order submission, balance access, config modification, process interaction
- **Escalation conditions:**
  - Resolution criteria ambiguous or multi-conditional → human review required before quoting
  - Market has >$500K open interest and score < 6 → human review
  - Correlated with existing position >INV_SOFT → flag correlation risk
- **Memory objects:**
  - `category_base_rates`: historical resolution rates per category
  - `assessment_history`: past assessments with accuracy tracking (FV vs. eventual mid)
  - `known_correlated_pairs`: market pairs with observed price correlation > 0.7
- **Success metrics:**
  - FV estimate RMSE vs. eventual settlement price < 0.08
  - Tradability score correctly rejects adverse-selection-dominated markets (retrospective validation quarterly)

---

**Agent 2: ParameterCalibrationAgent**

- **Mission:** Review live and backtest results; propose parameter updates with evidence; run sandbox simulations to quantify expected impact before any change goes live.
- **Trigger:** Weekly scheduled review + on-demand when MonitoringAgent flags degraded performance
- **Inputs:**
  - Last 7-day PnL report (CSV + JSON)
  - Fill log with AS estimates
  - Current live parameter set
  - Backtest simulator access (sandboxed, read-only data)
- **Outputs:**
  - `ParameterProposal` document: proposed values, rationale, before/after simulation comparison
  - Written to `docs/calibration/YYYY-MM-DD-proposal.md`
  - Submitted to human operator for approval; never auto-applied
- **Allowed tools:** `read_file`, `write_file`, `run_backtest` (sandboxed subprocess, no live system access)
- **Forbidden:** Direct live config modification, live order interaction, deploying changes without human sign-off
- **Escalation conditions:**
  - Proposed change to INV_MAX, INV_HARD, or kill-switch thresholds → mandatory human sign-off
  - Simulation shows >10% PnL improvement → flag as potentially overfit; request out-of-sample validation
  - Simulation shows negative expected PnL with proposed parameters → do not submit proposal; flag for human investigation
- **Memory objects:**
  - `parameter_history`: all parameter versions with timestamps, rationale, and performance before/after
  - `calibration_log`: record of proposals, approvals, rejections, and outcomes
- **Success metrics:**
  - Parameter proposals improve 30-day forward PnL in >60% of cases (tracked retrospectively)
  - No proposed change causes a kill-switch trigger within 7 days of deployment

---

**Agent 3: MonitoringAgent**

- **Mission:** Continuous surveillance of live system telemetry. Detect anomalies, generate alerts, produce daily mandate metrics digest.
- **Trigger:** Continuous (poll every 60 seconds) + event-driven on alert webhooks
- **Inputs:**
  - Live metrics stream: fill rate, inventory levels per market, PnL, order latency, WS health, regime state per market, capital utilization
  - RiskAlert stream from RiskEngine
- **Outputs:**
  - `WARNING` alerts: logged to `logs/alerts/` + written to ops Slack channel (or email)
  - `CRITICAL` alerts: above + human page (PagerDuty or equivalent)
  - Daily digest: `reports/daily/YYYY-MM-DD-mandate-metrics.md`
    - Uptime %, spread quality, fill rate, gross PnL, net PnL, incentive revenue, capital efficiency
- **Allowed tools:** `read_metrics` (read-only metrics API), `write_file`, `send_alert`
- **Forbidden:** Order submission, config changes, process restarts, any write to live systems
- **Escalation conditions:**
  - Any KILL severity RiskAlert → immediate human page
  - Inventory > 80% of INV_MAX on any market → WARNING + alert
  - WS disconnected > 30 seconds → WARNING
  - Fill rate drops to 0 for >10 minutes during active market hours → WARNING
  - Daily PnL < -$500 → CRITICAL
  - Portfolio capital utilization > 70% → WARNING
- **Memory objects:**
  - `baseline_distributions`: normal operating ranges for each metric (updated weekly)
  - `alert_history`: deduplicated alert log to prevent spam
  - `known_outage_signatures`: Polymarket-specific outage patterns (WS drop profiles, API error codes)
- **Success metrics:**
  - Zero incidents where CRITICAL condition was not detected within 5 minutes
  - Daily mandate digest delivered by 08:00 UTC every day

---

**Agent 4: IncidentResponseAgent**

- **Mission:** First-responder for system failures, venue outages, and abnormal fill patterns. Diagnoses incidents, drafts recommended actions, and writes post-mortems.
- **Trigger:** Invoked by MonitoringAgent on CRITICAL alert or human operator request
- **Inputs:**
  - Incident alert with severity, market_id, alert_type, value, threshold
  - Last 500 log lines from strategy core
  - Current inventory snapshot
  - Current regime states per market
- **Outputs:**
  - Incident diagnosis report: root cause hypothesis, evidence, confidence level
  - Recommended action: one of [CONTINUE_MONITORING, SUSPEND_MARKET, SUSPEND_ALL, MANUAL_FLATTEN, INVESTIGATE_FURTHER]
  - Post-mortem draft (after resolution): written to `docs/incidents/YYYY-MM-DD-{incident_id}.md`
  - **All recommended actions require human approval before execution**
- **Allowed tools:** `read_logs`, `read_metrics`, `read_file`, `write_file`, `send_alert`
- **Forbidden:** Order submission, live config changes, process kills, any write to live systems
- **Escalation conditions:** Every incident escalates to human for action; agent diagnoses only
- **Memory objects:**
  - `incident_history`: past incidents with root cause, action taken, resolution
  - `failure_pattern_library`: known failure signatures for fast matching (e.g., "Polymarket WS drops every ~4h during high volume")
  - `venue_status_history`: recorded Polymarket API status events
- **Success metrics:**
  - Correct root cause diagnosis in >70% of incidents (validated retrospectively)
  - Post-mortem written within 24h of incident resolution
  - Zero cases where recommended action would have caused additional loss (validated by human review)

---

## 10. RISK, CONTROLS & GOVERNANCE

### 10.1 Risk Limits (Phase 1 / $50K)

| Limit | Value | Breach action |
|---|---|---|
| Per-market INV_SOFT | $2,000 notional | Switch to flatten_passive |
| Per-market INV_HARD | $4,000 notional | Flatten aggressively immediately |
| Portfolio capital utilization soft | 40% ($20K) | No new markets; size down existing |
| Portfolio capital utilization hard | 80% ($40K) | Halt all new quotes |
| Minimum reserve | 20% ($10K) | Hard block on new orders |
| Daily loss limit | -$1,000 | Suspend all quoting; human required to resume |
| Market max_loss threshold | -$500 | Suspend that market |
| AS spike threshold | AS > half_spread - fee | Suspend quoting on market |
| Time-to-resolution alert | < 1 hour remaining | Cancel all quotes; flatten only |
| Skew tolerance (default) | 0 (strict) | No unhedgeable inventory permitted |
| Skew hard limit | $1,000 per market | Hard cap regardless of edge premium; never exceeded |
| Skew capital charge | 3× standard rate | Applied to all skew inventory continuously |
| Hedge coverage ratio warning | < 0.5 (50% of hedgeable inventory covered) | Elevate flatten urgency; emit WARNING |
| Hedge coverage ratio critical | < 0.1 | Reclassify hedgeable inventory as skew; emit CRITICAL |
| Skew PnL dominance | skew_pnl > spread_pnl over trailing 30 days | Flag for mandate review; system may be running directional, not MM |

### 10.2 Kill-Switch Design

Hardware-level kill switch: a separate lightweight process that watches a heartbeat file written by the strategy core. If the heartbeat file is not updated within 30 seconds, the kill process cancels all open orders via a direct API call using its own credentials. This process has no strategy logic and cannot be disabled by the strategy core.

Software kill switch: triggered by RiskEngine on any KILL severity alert. Actions:
1. Cancel all open orders across all markets
2. Write kill_reason and timestamp to kill log
3. Set system state to KILLED (prevents new order submission)
4. Alert human operator via CRITICAL channel
5. Do not attempt to flatten inventory (human decides)

### 10.3 Governance

- Parameter changes: ParameterCalibrationAgent proposes; human approves; changes logged with rationale
- Live capital increases: require backtest evidence for new capital level + human sign-off
- New market onboarding: MarketResearchAgent score ≥ 7 auto-approves; 4–6 requires human review
- Incident response: IncidentResponseAgent diagnoses; human approves all actions
- Mandate pitch: MonitoringAgent generates track record report; human reviews and approves before sharing

### Artifact H: Do Not Deploy If Checklist

The system must not go live if any of the following conditions are true:

1. Backtest realized cycle PnL (gross, no incentives) is negative across the full test set
2. Backtest falsification tests show any failed condition
3. Unhedged expiry rate in backtest > 10% of filled positions
4. Adverse selection rate in backtest > 60% of fills (post-fill FV move exceeds half-spread)
5. Kill-switch process has not been tested independently (manually trigger heartbeat failure; verify all orders cancel within 30s)
6. Private key / wallet credentials are stored anywhere other than environment variables or a secrets manager
7. Paper trading has not run for minimum 7 days with positive realized PnL
8. $5K UAT phase has not completed with zero CRITICAL incidents
9. Capital utilization in paper/UAT phase exceeded 80% and was not properly handled by risk limits
10. Any component lacks a unit test with > 80% line coverage (FairValueEstimator, RegimeClassifier, QuoteEngine, InventoryManager, RiskEngine)
11. MonitoringAgent daily digest has not been verified to deliver correctly for 3 consecutive days
12. No incident response runbook exists (written, reviewed, available to human operator)
13. Order cancellation on WS disconnect has not been tested (simulate disconnect; verify all resting orders are cancelled)
14. Partial fill handling has not been tested (simulate partial fill sequence; verify inventory and risk limits update correctly)
15. The VenueAdapter interface has not been tested with mock implementations to verify contract correctness before PolymarketAdapter goes live
16. Polygon gas price monitoring is not in place (failure to submit cancel orders due to gas exhaustion = unprotected inventory)
17. USDC balance monitoring is not in place (failure to detect insufficient collateral = rejected order silently leaves inventory unhedged)
18. Settlement / CTF redemption has not been tested end-to-end on testnet (or with a $1 live market)
19. No documented rollback procedure exists (how to restore previous parameter set in < 5 minutes)
20. System has not been run for a full 24-hour period without intervention in paper mode
21. HedgeabilityAssessor has not been tested with a book where own orders constitute 100% of opposing depth (must block quote or reduce to zero hedgeable size)
22. `skew_tolerance` is set above 0 in Phase 1 config without explicit human sign-off and documented rationale (default must be 0 for initial live deployment)

---

## 11. IMPLEMENTATION ROADMAP

### Artifact G: Production Build Plan

**11.1 Repo / Module Layout**

```
polymarket-mm/
├── src/
│   ├── adapters/
│   │   ├── base.py              # VenueAdapter Protocol
│   │   ├── polymarket.py        # PolymarketAdapter
│   │   └── kalshi_stub.py       # KalshiAdapter stub (interface only)
│   ├── strategy/
│   │   ├── fair_value.py        # FairValueEstimator
│   │   ├── regime.py            # RegimeClassifier + state machine
│   │   ├── quote_engine.py      # QuoteEngine
│   │   ├── hedgeability.py      # HedgeabilityAssessor + SkewConfig
│   │   ├── inventory.py         # InventoryManager (two-bucket: hedgeable + skew)
│   │   └── pnl.py               # PnLEngine (spread_pnl + skew_pnl attribution)
│   ├── risk/
│   │   ├── engine.py            # RiskEngine
│   │   └── kill_switch.py       # Standalone kill process
│   ├── data/
│   │   ├── market_data.py       # MarketDataService
│   │   └── schemas.py           # Pydantic models for all JSON schemas
│   ├── agents/
│   │   ├── market_research.py   # MarketResearchAgent Claude prompt
│   │   ├── calibration.py       # ParameterCalibrationAgent Claude prompt
│   │   ├── monitoring.py        # MonitoringAgent
│   │   └── incident.py          # IncidentResponseAgent
│   ├── fee_model.py             # FeeModel — single source of truth for all fee/rebate calcs
│   └── backtest/
│       ├── simulator.py         # EventDrivenSimulator
│       ├── fill_model.py        # Fill models (touch, volume, impact)
│       └── runner.py            # Parameter sweep + walk-forward runner
│                                # NOTE: backtest uses src/fee_model.py directly — no copy
├── tests/
│   ├── unit/                    # Per-component unit tests
│   ├── integration/             # Adapter + strategy integration tests
│   └── backtest/                # Backtest regression tests
├── config/
│   ├── base.yaml                # Venue-agnostic defaults
│   ├── polymarket.yaml          # Polymarket-specific overrides
│   └── phase1.yaml              # Phase 1 ($50K) risk limits
├── scripts/
│   ├── ingest_history.py        # Historical data ingestion
│   ├── run_backtest.py          # Backtest runner CLI
│   └── run_paper.py             # Paper trading runner
├── docs/
│   ├── specs/                   # Design specs (this file)
│   ├── calibration/             # Parameter proposals
│   ├── incidents/               # Post-mortems
│   └── mandate/                 # Track record reports
├── infra/
│   ├── docker-compose.yml       # Local dev + paper trading
│   └── systemd/                 # Production service definitions
└── requirements.txt
```

**11.2 Service Boundaries**

| Service | Process | Restart policy | State |
|---|---|---|---|
| strategy_core | Python process, single-threaded event loop | Auto-restart on crash; halt on KILLED state | In-memory + SQLite for persistence |
| kill_switch | Separate Python process, no shared memory | Manual restart only (prevents accidental re-enable) | Stateless |
| monitoring_agent | Claude API process, scheduled + event-driven | Auto-restart | Reads from metrics API; writes to file |
| data_ingestion | Separate process for WS feed | Auto-restart with reconnect backoff | Writes to event queue |

**11.3 Config Hierarchy**

```
base.yaml (venue-agnostic defaults)
  └── polymarket.yaml (venue-specific overrides)
        └── phase1.yaml (capital/risk-level overrides)
              └── ENV VARS (secrets: private key, API keys)
```

No secrets in any YAML file. All credentials via environment variables or AWS Secrets Manager.

**11.4 Test Strategy**

- Unit tests: pytest, per-module, >80% line coverage required. Mock VenueAdapter for strategy tests.
- Integration tests: PolymarketAdapter tested against Polymarket testnet (or recorded HTTP fixtures).
- Backtest regression tests: Reference run stored; new code must produce identical output within tolerance.
- End-to-end paper test: Full system run against live Polymarket book with no real capital; monitored for 7 days.

**11.5 Observability Stack**

- Metrics: Prometheus scrape endpoint on strategy_core; Grafana dashboard for inventory, PnL, uptime, latency
- Logs: Structured JSON logs → file rotation; ingested by MonitoringAgent
- Alerts: RiskEngine writes to alert queue; MonitoringAgent reads and routes to Slack/PagerDuty
- Mandate reporting: Daily cron generates mandate metrics digest via MonitoringAgent

**11.6 Kill-Switch Conditions**

Automatic (no human required):
- Heartbeat file not updated in 30s → kill process cancels all orders
- RiskEngine emits KILL severity alert → strategy_core halts all order submission

Manual (human required to execute):
- Daily loss limit breach (system suspends; human decides whether to resume or fully exit)
- Venue anomaly detected by IncidentResponseAgent

**11.7 Staged Rollout Gates**

| Stage | Duration | Capital | Gate criteria to advance |
|---|---|---|---|
| Backtest | Weeks 1–4 | $0 | All falsification tests pass; parameter sweep complete; walk-forward positive |
| Paper trading | Weeks 5–8 | $0 | 7 consecutive days, positive realized PnL, zero CRITICAL incidents, all kill-switch tests pass |
| UAT live | Weeks 9–10 | $5K | 14 days, positive net PnL, no daily loss limit breach, all components verified in production |
| Phase 1 live | Weeks 11+ | $50K | UAT gate passed; human operator signed off; mandate track record begins |
| Scale | Post-mandate | TBD | 90-day track record, positive capital efficiency, mandate signed |

---

## 12. VALIDATION & ACCEPTANCE TESTS

**12.1 Unit Acceptance Tests (per component)**

| Component | Test | Pass criterion |
|---|---|---|
| FeeModel | taker_fee(size=100, price=0.50, feeRate=0.04) | Returns 1.00 (100×0.04×0.25); Sports exponent=1 returns 0.50 (100×0.03×0.25×0.5) |
| FeeModel | maker_rebate(size=100, price=0.50, feeRate=0.04, rebate_fraction=0.20) | Returns 0.20 (0.20×1.00) |
| FeeModel | max_flatten_price(p_fill=0.46, feeRate=0.04, rebate_fraction=0.20, floor=0.005) | Returns 0.527 ± 0.001 |
| FeeModel | max_flatten_price with discriminant < 0 | Returns 0.0; QuoteEngine does not submit quote |
| FairValueEstimator | FV on known-resolved market | FV within 0.05 of eventual settlement at >72h before resolution |
| RegimeClassifier | Inject all state transition triggers | All transitions fire correctly per state machine table |
| QuoteEngine | Quote with INV > INV_SOFT | Bid/ask skewed correctly away from inventory direction |
| InventoryManager | Sequence of fills including partial | Position, locked capital, payout exposure all correct after each fill |
| RiskEngine | Breach each limit in sequence | Correct action triggered within 100ms of breach |
| HedgeabilityAssessor | Submit quote where own orders constitute 100% of opposing depth | Quote size reduced to 0 (no external depth); skew path activates only if skew_tolerance > 0 |
| HedgeabilityAssessor | Submit quote with fee_taker=0.02; opposing ask at 0.58; p_fill=0.46 | max_flatten_price = (0.535) / 1.02 ≈ 0.524; 0.58 > 0.524 → quote blocked or size capped |
| HedgeabilityAssessor (skew path) | skew_tolerance=500, current_skew=0, edge premium met | Allows up to $500 notional as skew; books to skew bucket; 3× capital charge applied |
| InventoryManager (two-bucket) | Sequence of fills that transitions hedgeable → skew on depth deterioration | hedgeable and skew buckets update correctly; skew capital charge applies from reclassification timestamp |
| Kill switch | Simulate heartbeat failure | All orders cancelled within 30s independently of strategy core |

**12.2 Backtest Acceptance Tests**

- Realized cycle PnL gross > 0 on held-out test set (Option B queue model)
- Realized cycle PnL gross > 0 on Option C (pessimistic queue) — may be smaller but must be positive
- All 6 falsification tests pass
- Walk-forward results consistent across 3 market categories
- Ablation studies show each component contributes positive marginal value

**12.3 Paper Trading Acceptance Tests**

- 7 consecutive calendar days without kill-switch trigger
- Daily mandate digest delivered each day
- No CRITICAL alert that was not detected by MonitoringAgent within 5 minutes
- WS reconnect test passed (manually triggered; all orders cancelled; book re-synced correctly)

**12.4 Central Hypothesis Falsification**

*If after 90 days of live trading (Phase 1) the following conditions hold, the central hypothesis is rejected and the system should be shut down pending redesign:*

- Gross realized cycle PnL (no incentives) is negative on a trailing 30-day basis
- P(p_yes + p_no > 1) > 0.5 across all completed cycles in the trailing 30 days
- Net PnL is positive only due to incentives, and incentive program terms have materially changed

---

## 13. OPEN QUESTIONS & ASSUMPTIONS

**Assumptions (require validation before live deployment):**

1. Taker fee formula: `feeRate × p × (1-p)`; feeRates: Crypto=0.07, Finance/Politics=0.04, Sports=0.03. **Validate per market via `getClobMarketInfo(conditionID)` at market init. Treat Sports exponent as 1 unless API returns otherwise.**
2. Maker rebate = `rebate_fraction × feeRate × p × (1-p)`; rebate_fraction = 0.20. **Validate exact rebate_fraction via Polymarket LP documentation or API before relying on rebate economics in mandate pitch. Run backtest sensitivity: rebate_fraction ∈ {0.0, 0.15, 0.20, 0.25}.**
2. Polymarket CLOB latency = ~20ms. **Measure in paper trading phase.**
3. Opportunity cost rate = 10% annualized. **Replace with actual cost of capital.**
4. Network latency ∼ lognormal(50ms, 20ms). **Calibrate from paper trading logs.**
5. FV external signals available from Metaculus/Manifold for >50% of markets. **Validate during data ingestion phase.**
6. Polymarket testnet exists and is usable for integration testing. **Confirm before beginning adapter work.**

**Estimable quantities (require historical data):**

1. AS distribution per market category and TTR bucket. **Requires historical order book + trade data.**
2. Hedge delay distribution (time from one-side fill to opposite-side fill). **Requires historical fill data.**
3. Optimal parameter set (S_min, α, β, γ). **Requires parameter sweep on historical data.**
4. FV accuracy of external signals vs. internal estimates. **Requires cross-validation on resolved markets.**

**Unknowns requiring live calibration:**

1. Queue position dynamics after reconnect on Polymarket specifically.
2. Incentive program payout formula and qualification thresholds (varies by market and period).
3. Actual gas costs for Polygon order submission during high-volume periods.
4. Market discovery rate (how many new tradeable markets are listed per week).
5. Polymarket API rate limits and burst allowances under production load.

**Open questions:**

1. Should the system quote fractional contract sizes, or round to minimum lot size? (Affects capital efficiency at $50K scale.)
2. Does Polymarket allow order amendment, or cancel-replace only? (Affects queue position management.)
3. Is there a Polymarket market-maker agreement or API SLA available? (Required for mandate pitch.)
4. What is the CTF redemption process latency after resolution? (Affects capital recycling speed.)

---

## 14. FINAL SELF-CRITIQUE

**Overfitting risk:** The parameter sweep covers 500 Sobol-sampled combinations across 7 dimensions. With 500 combinations and a modest historical dataset (say, 200 resolved markets), in-sample overfitting is likely. Mitigation: walk-forward validation with a held-out test set, plus the deliberate constraint that the acceptance criterion requires positive performance on Option C (pessimistic queue) — the most conservative fill assumption. If the strategy only works under optimistic assumptions, it should not be deployed.

**Simulator realism:** The two largest simulator gaps are queue position uncertainty and correlated fill arrival. The queue model options address the first; the fill model volume option partially addresses the second by conditioning on historical volume. However, the model does not capture the impact of own quotes on order flow — a system quoting 20% of book depth at a price level changes what opposing orders arrive. This is labeled as a known gap; the ablation study should test sensitivity to own-quote market-impact assumptions.

**Venue fragility:** The entire Phase 1 system depends on Polymarket's API and CLOB remaining stable. Polymarket has had historical outages, smart contract upgrades, and market policy changes. The kill-switch and halt logic address the immediate financial risk, but a sustained venue outage or policy change (e.g., removing CLOB trading from a category) could make the system unviable. Mitigation: the VenueAdapter interface ensures Kalshi can be added as a fallback within 3–4 weeks.

**Operational burden:** Four Claude agents plus a live trading system require ongoing human attention. For a $50K operation this is a meaningful overhead per dollar deployed. The system is designed to be low-touch (agents surface alerts; humans only approve changes), but the MonitoringAgent and IncidentResponseAgent still require a human who is responsive to CRITICAL alerts within minutes during trading hours. This burden justifies the mandate pitch — moving costs to a client-funded arrangement.

**Hidden directional exposure:** The system explicitly avoids treating mid as fair value and uses an independent FV estimate. However, if the external FV signal (Metaculus/Manifold consensus) is systematically biased in a direction — for example, consistently under-pricing tail outcomes on political markets — the FV estimator will carry that bias into every quote. This is not an inventory risk but a systematic mis-pricing risk. Mitigation: track FV estimate error by category and TTR bucket; if RMSE > 0.10 on any segment, reduce weight on that signal source.

**Skew tolerance as a directional backdoor:** The skew tolerance framework is a controlled and explicit mechanism for holding unhedged inventory, but it creates a meaningful risk: if the operator sets `skew_tolerance` too high or the edge premium is set too low, the system can drift from market making into directional speculation without a clear signal. The two-bucket PnL attribution and the "skew_pnl dominates spread_pnl" alert are the primary safeguards, but they are lagging indicators — the skew position is already held by the time the alert fires. The default `skew_tolerance = 0` is deliberate and should not be increased until the base strategy is validated on live capital with strict mode, and only with a documented rationale and human sign-off. For the mandate pitch, any period where `skew_tolerance > 0` was active must be disclosed and the skew PnL attributed separately.

**Incentive gaming risk:** Incentive programs on Polymarket have historically changed terms, pools, and qualification criteria with short notice. The system is designed to report performance with and without incentives, and to never combine incentive revenue into spread edge metrics. However, if the team optimizes quoting parameters against an incentive program (e.g., tuning to maximize time-at-top-of-book for a specific pool), those parameters may be suboptimal once the program changes. Mitigation: primary parameter optimization always uses gross metrics; incentive-aware parameters are a separate, secondary optimization layer.
