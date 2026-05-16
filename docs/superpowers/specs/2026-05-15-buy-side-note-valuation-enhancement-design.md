# Buy-Side Note Valuation Enhancement — Design Spec

**Date:** 2026-05-15
**Status:** Approved for implementation

---

## Overview

Enhance the existing `buy-side-note` skill with three new analytical capabilities applied across all five note types: probability-weighted scenario analysis, sensitivity tables, and trade construction with position sizing. Also adds asset-type detection (equity vs. crypto) to gate instrument vocabulary in trade construction.

This is an in-place expansion of `skills/buy-side-note/skill.md`. No new files. No new skill registration. The file grows from ~665 lines to ~1,400 lines.

Inspired by: institutional fair value memo format (multi-methodology valuation, 3-way scenario model with multi-horizon FV table, sensitivity matrices, named trade structures with entry/exit conditions, position sizing by price zone).

---

## What Changes

### Stage 1 — Asset Detection (new step)

A single classification step added at the end of Stage 1, after note type is confirmed and before research begins.

**Detection logic:**

| Signal | Classification |
|---|---|
| Ticker: 1–5 uppercase letters, no numeric suffix (NVDA, MSFT, ALAB, JPM) | EQUITY |
| Token name or ticker with on-chain context; or explicit "token", "protocol", "on-chain", "DEX", "L1", "L2" in subject | CRYPTO |
| Ambiguous (sector, theme, no single asset) | EQUITY (default); trade structures use basket/ETF instruments only |

Announced: *"Asset type: [EQUITY / CRYPTO]. Trade construction will use [equity / crypto-native] instrument vocabulary."*

This classification is stored and referenced in Stage 3 trade construction. No other stage behaviour changes based on asset type.

---

### Stage 2 — Research Additions

Each note type's existing checklist gets additional items appended. These run after all existing checklist items complete.

#### Universal Additions (all five note types)

**Comps research:**
Search: "[subject] comparable companies peers valuation multiples 2025 2026"
- EQUITY: EV/Revenue, EV/EBITDA, P/E, P/S vs. 3–5 named peers. Record median and high/low range.
- CRYPTO: P/S on circulating market cap and FDV vs. 3–5 named comparable protocols. Record median and high/low range.
- Gap-log: if fewer than 3 comps found, mark `[DIRECTIONAL ESTIMATE]` on median.

**Scenario parameters:**
Search: "[subject] bear case bull case analyst price targets 2026"
- Extract: what the street's bear assumes (specific — low growth rate, margin level, market share %)
- Extract: what the street's bull assumes (specific — acceleration rate, expansion scenario, new revenue stream)
- These anchor the 3-way scenario model in Stage 3.

**Probability weights (research-derived):**
Do not use fixed defaults. Derive from:
- Positioning signal: crowded consensus → elevated bear probability (35–45%)
- Catalyst proximity: near-term binary event → compress base probability, widen bear/bull spread
- Regulatory environment: active enforcement risk → elevated bear probability
- Probabilities must sum to 100%. State reasoning for each weight in one sentence.

**Sensitivity variable identification:**
At the end of all research, identify the 2 variables that most drive fair value for this subject. These become the axes for the two sensitivity tables in Stage 3.
- EQUITY examples: revenue growth rate × exit multiple; operating margin × P/E
- CRYPTO examples: market share % × token supply inflation; TVL × protocol yield capture rate
- Thematic Rotation examples: rotation speed (weeks) × basket entry price; ETF AUM growth × P/S re-rating
- Record as: "Sensitivity axes: [Variable A] × [Variable B]"

#### Note-Type-Specific Additions

**Thematic Rotation:**
- Search: "[outgoing theme] historical rotation duration weeks months drawdown". Record: how long prior analogous rotations took to play out, typical drawdown in outgoing theme during transition.
- Search: "[candidate themes] basket P/S vs. prior rotation baskets". Record: whether candidate themes are cheap or expensive vs. entry points of prior rotations (e.g., AI vs. cloud SaaS entry in 2019).
- Search: "ETF flows [candidate themes] momentum 2026". Record: flow direction and magnitude as rotation signal.

**Earnings Preview:**
- Search: "[TICKER] historical earnings beat miss rate 2023 2024 2025". Record: beat/miss on EPS and revenue for last 8 quarters. Compute beat rate %.
- Search: "[TICKER] options straddle implied move earnings 2026". Record: ATM straddle cost as % of stock price. Mark [UNFOUND] if unavailable.
- Search: "[TICKER] historical implied vs actual move earnings". Record: whether the stock historically over- or under-moves vs. implied.

**Earnings Flash:**
- Search: "[TICKER] prior quarter guidance [metric]". Record: what management guided to for the just-reported quarter.
- Search: "[TICKER] earnings estimate revisions [date]". Record: direction and magnitude of post-print estimate revisions.
- Note: If no prior scenario framework exists (first time running on this ticker), build a baseline from reported results only.

**Single-Stock Deep Dive:**
- Search: "[TICKER] revenue growth forecast 2026 2027 2028". Record: 3-year revenue CAGR estimate.
- Search: "[TICKER] operating margin EBITDA margin forecast". Record: margin trajectory over 3 years.
- Search: "[TICKER] WACC discount rate comparable". For EQUITY: derive WACC from beta, risk-free rate, market premium. For CRYPTO: use 25% base WACC with stated risk premiums (regulatory, illiquidity, smart contract risk).
- Search: "[TICKER] M&A precedent transactions comparable acquisition multiples" (EQUITY only) OR "[subject] tokenomics buyback yield staking APR unlock schedule" (CRYPTO only).

**Sector Analysis:**
- Search: "[sector] P/E forward 5-year historical average". Record: current vs. historical mean and standard deviation.
- Search: "[sector] factor exposure value growth quality tilt 2026". Record: dominant factor exposure and whether it is in or out of favour.
- Search: "[sector] sub-sector relative performance YTD 2026". Record: which sub-sectors are leading and lagging within the sector.

---

### Stage 3 — New Sections (all note types)

Five new sections appended to every note type's write template, in this order, after the existing content and before TIME-SENSITIVE FLAGS:

---

#### New Section A: VALUATION

Three valuation methodologies per note type, each with explicit stated assumptions, then a weighted blended fair value conclusion.

**Methodology assignments by note type:**

| Note Type | Method 1 | Method 2 | Method 3 |
|---|---|---|---|
| Thematic Rotation | Basket P/S vs. prior rotation entry valuations | ETF flow momentum implied return (AUM growth × re-rating) | Historical rotation duration × current entry timing (early/mid/late cycle) |
| Earnings Preview | Options-implied move pricing (straddle cost as % of stock, annualised) | Historical beat/miss adjusted EPS × forward P/E | P/E re-rating scenario: on beat (multiple expands to [X]), on miss (multiple compresses to [X]) |
| Earnings Flash | Reported results vs. prior scenario framework (which scenario printed) | Post-print estimate revision direction × implied multiple | Guidance change implied re-rating (raised/maintained/cut × historical re-rating magnitude) |
| Single-Stock Deep Dive | DCF: 5-year revenue build, stated WACC, stated terminal multiple, PV of terminal value | Comps: EV/Revenue or P/S vs. peer median (stated peers, stated median) | EQUITY: sum-of-parts or precedent M&A transactions (stated comp set, stated premium). CRYPTO: tokenomics reflexivity (buyback yield + staking APR + net supply deflation/inflation → implied required return) |
| Sector Analysis | Sector forward P/E vs. 5-year historical mean (current discount/premium stated as % and σ) | Sub-sector relative performance implied catch-up return | Factor premium: value/growth/quality tilt historical premium in this macro regime |

**Weighted conclusion format:**
```
Methodology weights: Method 1 [X]% · Method 2 [X]% · Method 3 [X]%
(Weights must sum to 100%. State rationale for weighting in one sentence.)

Blended fair value: $[X] (range: $[low] – $[high])
vs. current spot: +/–[X]%
```

---

#### New Section B: SCENARIO ANALYSIS

3-way model. Probabilities must sum to 100% and must match the research-derived weights from Stage 2.

**Scenario definition format (for each of bear/base/bull):**
- Probability: [X]%
- 2–3 named defining conditions (specific and falsifiable — not "growth slows", but "revenue growth decelerates from 28% to 14%")
- Price targets at 1M / 3M / 6M / 1Y

**Multi-horizon fair value table:**
```
                BEAR ([X]%)    BASE ([X]%)    BULL ([X]%)    BLENDED FV    vs. SPOT
1 Month         $[X]           $[X]           $[X]           $[X]          +/–[X]%
3 Months        $[X]           $[X]           $[X]           $[X]          +/–[X]%
6 Months        $[X]           $[X]           $[X]           $[X]          +/–[X]%
1 Year          $[X]           $[X]           $[X]           $[X]          +/–[X]%
```

Blended FV = (Bear target × bear probability) + (Base target × base probability) + (Bull target × bull probability).

**Note-type scenario anchors:**
- Thematic Rotation: bear = rotation stalls/reverses, base = rotation plays out over [X] weeks, bull = rotation accelerates and basket re-rates
- Earnings Preview: bear = miss on EPS and revenue + guidance cut, base = in-line + maintained guidance, bull = beat on both + raised guidance
- Earnings Flash: bear = results worse than printed (guide-down scenario now embedded), base = results at face value, bull = results better than they look (hidden beat in metrics)
- Single-Stock Deep Dive: bear = [specific named failure condition from bear case], base = consensus plays out, bull = [specific named upside condition]
- Sector Analysis: bear = macro contraction triggers de-rating, base = sector holds current multiple, bull = macro expansion + factor rotation into sector

---

#### New Section C: SENSITIVITY TABLES

Two matrices using the sensitivity axes identified at the end of Stage 2 research. One table per axis pair.

**Table format:**
```
[Variable A] × [Variable B] → Implied Fair Value / Price Target

              [B: Low]    [B: Mid]    [B: High]
[A: Low]      $X          $X          $X
[A: Mid]      $X          $X          $X
[A: High]     $X          $X          $X
```

- Current spot: mark the cell closest to spot with ← SPOT
- Base case: mark the cell representing base case assumptions with ← BASE
- Flag any cell implying >50% upside from spot with ▲ and any cell implying >30% downside with ▼

Both tables required. If data is insufficient to populate a cell, use `[DIRECTIONAL ESTIMATE]` and add to TIME-SENSITIVE FLAGS.

---

#### New Section D: TRADE CONSTRUCTION

3–5 named trade structures. Asset type (EQUITY / CRYPTO) gates instrument vocabulary.

**Required trades (all note types):**
1. **Core directional trade** — the primary expression of the thesis
2. **Event-specific trade** — structured around the nearest dated catalyst from the risk/catalyst section
3. **Hedge trade** — what to own if the thesis is wrong; explicitly named instrument or position

**Additional trades (where applicable):**
4. **Pairs trade** — long subject vs. short named peer or sector ETF/index (EQUITY: named ETF; CRYPTO: named competitor token or L1 index)
5. **Carry trade** (CRYPTO only) — staking yield + option premium selling; stated annualised combined yield

**Trade structure format (each trade):**
```
Trade [N]: [Name]
Instrument: [specific — e.g., "long NVDA calls, 3M tenor, $145 strike" or "long HYPE / short SOL, equal notional"]
Rationale: [one sentence]
Entry: [specific condition — price level, event, or signal]
Exit (profit): [specific condition]
Exit (loss): [specific condition — stop level or invalidating event]
```

**EQUITY instrument vocabulary:** long/short common equity, long/short calls or puts (state tenor and strike), vertical call or put spreads, covered call overwrite, pairs vs. named peer or named sector ETF.

**CRYPTO instrument vocabulary:** long/short spot, long/short calls or puts where liquid (state exchange and tenor), staking + put-selling carry (state combined annualised yield), pairs vs. named competitor token, NAV arb where treasury company structure exists, on-chain yield position.

---

#### New Section E: POSITION SIZING

Price zone table with book weighting guidance. Stated for the primary instrument (common equity or spot token).

**Format:**
```
POSITION SIZING — [SUBJECT]

Price Zone          Weighting       Rationale
[Zone 1 — low]      [X]x book       [one-line reason — e.g., "2–3x risk-reward at bear-case support"]
[Zone 2]            [X]x book       [one-line reason]
[Current spot ~$X]  [X]x book  ← YOU ARE HERE
[Zone 3]            [X]x book       [one-line reason]
[Zone 4 — high]     [X]x book       [one-line reason — e.g., "trim; bull case largely priced"]

Maximum portfolio allocation: [X]% NAV
```

**Risk-adjusted return (stated at two points):**
```
At current spot ($[X]):     Expected return [X]% · Est. volatility [X]% · Implied Sharpe ~[X]
At best-entry zone ($[X]):  Expected return [X]% · Est. volatility [X]% · Implied Sharpe ~[X]
```

Expected return = probability-weighted 1-year blended FV from Section B minus current spot, as %.
Volatility estimate = stated explicitly with source (historical vol, implied vol from options, or directional estimate).

**CRYPTO additions:**
```
Staking/carry yield: [X]% annualised (if applicable)
Total return at current spot (price + carry): [X]%
```

---

### TIME-SENSITIVE FLAGS

No change to existing structure. All `[UNFOUND]` and `[DIRECTIONAL ESTIMATE]` items from both the original research checklist and the new additions flow into this section.

---

### Stage 4 — Chart Additions

Two new charts added to the chart generation table for note types that support them:

| Note Type | New Chart 3 |
|---|---|
| Thematic Rotation | Blended FV by scenario and horizon (grouped bar, 4 time horizons × 3 scenarios) |
| Earnings Preview | Historical implied move vs. actual move — last 8 events (paired bar chart) |
| Earnings Flash | Reported vs. prior scenario framework on key metrics (deviation bar chart) |
| Single-Stock Deep Dive | Sensitivity heatmap: Variable A × Variable B → colour-coded FV matrix |
| Sector Analysis | Scenario probability-weighted return distribution (bar chart with scenario labels) |

Existing chart generation rules apply: never generate with fabricated data; if data unavailable, omit and add to TIME-SENSITIVE FLAGS.

---

## What Is Not In Scope

- No new skill files created — this is an in-place edit of `skills/buy-side-note/skill.md`
- No changes to `package.json` — `buy-side-note` remains the registered skill name
- No changes to the `research-debate` plugin — it continues to call `buy-side-note` sub-agent as before (and will automatically get the enhanced output)
- No persistent storage of prior scenario frameworks between sessions
- No real-time options pricing integration — straddle costs sourced from web search only
- DCF model is narrative/stated-assumptions format, not a spreadsheet or structured model output
