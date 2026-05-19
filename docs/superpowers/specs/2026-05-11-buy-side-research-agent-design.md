# Buy-Side Research Agent — Design Spec
**Date:** 2026-05-11  
**Status:** Approved for implementation

---

## Overview

A Claude Code skill (`/buy-side-note`) and a set of standalone prompt templates that generate institutional-quality buy-side research notes on demand. The agent uses web search for all data sourcing. Output is a PDF research note with embedded charts, derived from a markdown draft. Structured for position initiation, not commentary.

**Reference artifact:** Thematic rotation note "After Memory/HBM: The Next Thematic Rotation" (May 9, 2026) — this document was reverse-engineered to derive the report DNA encoded in this spec.

---

## Supported Note Types

| Type | When to Use |
|------|-------------|
| Thematic Rotation Note | Identifying what market narrative comes next after a crowded theme |
| Earnings Preview | Pre-print positioning and key debate framing |
| Earnings Flash | Post-print rapid read within hours of results |
| Single-Stock Deep Dive | Full initiation-style analysis on a single name |
| Sector Analysis | Cycle position, macro frame, and stock selection within a sector |

---

## Architecture

Four stages run in sequence for every request.

### Stage 1 — Classify

Parse the user's request for:
- **Note type** — one of the five supported types above
- **Subject** — theme name, ticker(s), or sector
- **Constraints** — time horizon, geography, mandate restrictions (if stated)

If note type is ambiguous, ask exactly one clarifying question before proceeding. Do not begin research until note type and subject are confirmed.

Announce to user: *"Identified: [note type] on [subject]. Beginning research phase."*

---

### Stage 2 — Research

Load the typed checklist for the confirmed note type. Run each search item sequentially using web search. For each checklist item:
- Record what was found with source and approximate date
- Flag items that returned no usable data as `[UNFOUND]`
- Flag items where only a single source was found as `[SINGLE SOURCE]`
- Flag items that are directional estimates as `[DIRECTIONAL ESTIMATE]`

Do not fabricate data to fill gaps. Gaps flow directly into the TIME-SENSITIVE FLAGS section.

Announce on completion: *"Research complete. [N]/[M] checklist items confirmed. [X] flagged as directional, single-source, or unfound."*

#### Research Checklists by Note Type

**Thematic Rotation Note**
1. Crowding signals on the outgoing theme: sell-side coverage count, valuation compression from entry, recent institutional disclosures or letters mentioning the theme
2. 4–6 candidate next themes: one-sentence thesis, near-term named catalysts, listed beneficiary tickers
3. For each candidate: institutional ownership estimates, relevant ETF vehicles, bear case
4. One non-consensus idea absent from standard sell-side rotation lists — why it's non-consensus and why it's real
5. Leading indicators per theme: specific data sources and thresholds that signal rotation is live

**Earnings Preview**
1. Consensus estimates: EPS, revenue, and 2–3 key operating metrics the street tracks for this name
2. Prior quarter results and management guidance into the current quarter
3. Options-implied move into print (nearest ATM straddle as % of stock price)
4. Short interest (% of float) and any recent notable changes in institutional ownership (13F or press)
5. The 2–3 key debates heading into the print: what bulls and bears specifically disagree on
6. Sector peers reporting the same week: read-across risk or confirmation

**Earnings Flash**
1. Actual results vs. consensus on every guided metric (EPS, revenue, key operating lines)
2. Guidance revision vs. prior: raised / lowered / maintained, and specific language changes
3. Management commentary on each of the key debates identified pre-print
4. Stock reaction: % move after-hours or on open, and what that implies about positioning
5. Immediate peer read-across: which other names in the sector are repriced by this print

**Single-Stock Deep Dive**
1. Revenue breakdown by segment, margin structure (gross / operating / FCF), balance sheet health
2. Competitive position: 2–3 real competitive threats, what the moat is and how durable
3. Management track record: beat/miss history on guidance over last 6–8 quarters
4. Valuation: 2–3 relevant multiples vs. direct peers and own 3-year history
5. Short interest (% of float) and institutional ownership concentration (top 5 holders as % of float)
6. Upcoming catalyst calendar: earnings dates, investor days, product launches, regulatory events

**Sector Analysis**
1. Sector performance vs. S&P 500: YTD and 1-year (absolute and relative)
2. Current valuation multiples vs. 5-year history (forward P/E, EV/EBITDA, or sector-appropriate metric)
3. Earnings growth consensus: current year and next year estimates and revision direction
4. 2–3 macro variables most correlated with sector performance and current read on each
5. Sub-sector differentiation: which sub-segments are best/worst positioned and why
6. Top 3 long ideas and 1 avoid with positioning rationale for each

---

### Stage 3 — Write

Apply the note-type template to research findings. Voice rules (see below) enforced globally. TIME-SENSITIVE FLAGS populated from Stage 2 gap log.

Announce on completion: *"Draft complete. Generating charts and PDF."*

### Stage 4 — Render

Generate charts from Stage 2 data using the per-note-type chart set (see Output Format section). Assemble the markdown draft + charts into a PDF using standard clean research note styling. Deliver the PDF to the user.

If a chart cannot be generated due to missing data, omit it silently and add it to TIME-SENSITIVE FLAGS. Do not generate placeholder or illustrative charts with fabricated data.

---

## Templates by Note Type

### Thematic Rotation Note

```
[REPORT TYPE] THEMATIC STRATEGY   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Title: outcome framing, not descriptive]
[One-line subtitle: "structured for position initiation, not commentary"]

---

01 — CYCLE FRAME
[Why the outgoing theme is in late-consensus. Specific crowding signals: 
sell-side coverage proliferation, valuation compression, institutional flow 
data, public letters. Two rotation paths: (a) monetization pivot, (b) 
regime-shock rotation into real-economy beneficiaries. Both paths in play 
simultaneously if applicable.]

02 — CANDIDATE THEMES

## [Theme Name]                                          [TAG]
[One-line framing: what kind of rotation this is]

THESIS       [The investable argument. Bold the single key claim. 2–3 
             paragraphs max.]

CATALYST     (1) [Specific named event with approximate timing]
             (2) [Specific named event]
             (3) [Specific named event]
             (4) [Specific named event]

BENEFICIARIES   [TICK] [TICK] [TICK] [TICK]
             [One sentence rationale per name, grouped by role in the theme]

POSITIONING  [Directional estimate of institutional crowding. Is this 
             under-owned, consensus, or crowded? Name specific funds or 
             ETFs if evidence exists. Distinguish directional estimates 
             from confirmed data explicitly.]

> [Orange callout: positioning caveat or data quality warning on a 
>  specific claim in this theme block]

> [Red callout: Bear case — the specific condition that kills this thesis]

[Repeat theme block for each candidate, A through F]

---

03 — RANKING

## Force-ranked: probability of becoming the next major theme (6–12 months)

Criteria: narrative readiness × fundamental support × positioning asymmetry 
× catalyst proximity. A theme scores high only if it clears all four.

| # | THEME | KEY JUSTIFICATION | FAILURE CONDITION |
|---|-------|-------------------|-------------------|
| 1 | **[Theme Name]** [TICK] [TICK] | [Why it ranks here] | [Specific kill condition] |
| 2 | ... | ... | ... |

---

04 — CONTRARIAN / NON-CONSENSUS PICK

## [Pick name]

[Why this is non-consensus: what structural reason keeps it off sell-side 
rotation lists. Why the thesis is real despite low coverage. Specific 
catalyst clock. Positioning: who owns it, what the free float situation is. 
Bear case.]

[TICK] [TICK] [TICK]

---

05 — TRADEABLE EXPRESSION

## Entry structure for top-ranked theme + contrarian

| DIMENSION | THEME #1: [NAME] | CONTRARIAN: [NAME] |
|-----------|------------------|--------------------|
| **Cleanest expression** | [Core long / picks-and-shovels / ETF] | [Single-name / portfolio entry / ETF proxy if exists] |
| **Entry trigger** | [1–3 named events that confirm the trade] | [1–3 named events] |
| **Hedge / short leg** | [Specific short idea with rationale] | [Macro hedge or thematic short] |
| **Time horizon** | [Months, and why] | [Months, and why] |
| **Sizing logic** | [Pre-catalyst % / post-catalyst % / rationale] | [% and constraints] |

---

06 — WHAT TO MONITOR

[Category label]   [Specific data source + what threshold or language signals 
                   the rotation is live. One row per category.]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS

- [CLAIM]: [Why it's flagged — single source, directional estimate, 
  time-sensitive. What to check and where.]
[One bullet per flagged claim from Stage 2 gap log]

---
Internal research note — not for distribution. All thematic views represent 
forward-looking estimates subject to material revision on catalyst events. [DATE].
```

**Classification tags:** ADJACENT (extension of current theme) / NEXT-LEG (derivative of capex cycle) / MACRO (regime-driven) / ROTATION-OUT (defensive + under-owned)

---

### Earnings Preview

```
[REPORT TYPE] EARNINGS PREVIEW   [TICKER] Q[N] [YEAR]   [DATE]

# [Company Name] ([TICKER]) — Q[N] Preview
[One-line: what is at stake in this print]

---

01 — SETUP
[What is currently priced: valuation, implied move from options market, 
short interest, recent stock performance. What positioning looks like 
heading into the print.]

02 — KEY DEBATES

## Debate 1: [Label]
BULL     [Specific bull argument with data anchor]
BEAR     [Specific bear argument with data anchor]
WATCH    [The specific number or language that resolves this debate on the call]

## Debate 2: [Label]
[Repeat structure]

## Debate 3: [Label]
[Repeat structure]

---

03 — NUMBERS TO WATCH

| METRIC | CONSENSUS | BEAT LOOKS LIKE | MISS LOOKS LIKE |
|--------|-----------|-----------------|-----------------|
| Revenue | $[X]B | >$[X+]B | <$[X-]B |
| EPS | $[X] | >$[X] | <$[X] |
| [Key operating metric] | [X] | [threshold] | [threshold] |

---

04 — TRADEABLE EXPRESSION

[How to position into the print. Entry, sizing pre-print vs. post-print, 
hedge if needed. Time horizon past the print if the thesis is multi-quarter.]

---

05 — WHAT TO MONITOR ON THE CALL

[Specific language, disclosure, or guidance revision to listen for. 
One line per item. These are the signals that confirm or break the thesis.]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
[Flagged items from Stage 2]
```

---

### Earnings Flash

```
[REPORT TYPE] EARNINGS FLASH   [TICKER] Q[N] [YEAR]   [DATE / TIME]

# [TICKER]: [One-line verdict — beat/miss/inline on the metric that matters]

---

01 — THE PRINT

| METRIC | REPORTED | CONSENSUS | DELTA |
|--------|----------|-----------|-------|
| Revenue | $[X]B | $[X]B | [+/-X%] |
| EPS | $[X] | $[X] | [+/-X%] |
| [Key metric] | [X] | [X] | [delta] |

---

02 — GUIDANCE

[Prior guidance vs. new guidance on each metric management guides to. 
Flag language changes — specific wording matters.]

---

03 — KEY DEBATE RESOLUTION

## Debate 1: [Label from preview]
RESOLVED / UNRESOLVED   [What the print said, or didn't say, about this debate]

[Repeat for each debate]

---

04 — POSITIONING READ

[What the stock reaction implies about how investors were positioned. 
A big move on an inline print = positioning was more extreme than consensus. 
A muted move on a beat = the beat was expected.]

---

05 — PEER READ-ACROSS

[Which names in the sector are immediately repriced by this print, and in 
which direction. One line per name.]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
[Flagged items from Stage 2 — note: flash notes decay within 24–48 hours]
```

---

### Single-Stock Deep Dive

```
[REPORT TYPE] SINGLE-STOCK   [TICKER]   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Company Name] ([TICKER])
[One-line: the single thesis sentence]

---

01 — BUSINESS FRAME
[What it does, how it makes money, revenue breakdown by segment, 
TAM and penetration. Keep to what's relevant to the thesis.]

02 — COMPETITIVE POSITION
[The moat: what it is, how durable, stress-tested. 
2–3 real competitive threats with named companies. Where it wins and loses.]

03 — FINANCIALS

| METRIC | [YEAR-1] | [YEAR] | [YEAR+1]E |
|--------|----------|--------|-----------|
| Revenue | $[X]B | $[X]B | $[X]B |
| Gross Margin | [X]% | [X]% | [X]% |
| Operating Margin | [X]% | [X]% | [X]% |
| FCF | $[X]B | $[X]B | $[X]B |

[Balance sheet health: net cash/debt, any leverage concerns]

04 — VALUATION

| MULTIPLE | [TICKER] | PEER AVG | [TICKER] 3YR AVG |
|----------|----------|----------|------------------|
| Fwd P/E | [X]x | [X]x | [X]x |
| EV/EBITDA | [X]x | [X]x | [X]x |
| [Sector metric] | [X] | [X] | [X] |

[What the current multiple implies about expectations. What's priced in.]

05 — THE DEBATE

BULL     [The bull thesis in 2–3 sentences with the key data anchor]
BEAR     [The bear thesis in 2–3 sentences with the key data anchor]
VIEW     [Where you stand and why. Direct, not hedged.]

06 — POSITIONING

[Short interest as % of float. Institutional ownership concentration. 
Any notable recent 13F additions or reductions. Crowded or under-owned?]

07 — TRADEABLE EXPRESSION

[Cleanest long expression. Entry trigger. Catalyst clock. 
Sizing logic. Hedge if applicable. Time horizon.]

08 — WHAT TO MONITOR

[Specific data points, earnings metrics, or events that confirm or 
break the thesis. One line per item with the data source.]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
[Flagged items from Stage 2]
```

---

### Sector Analysis

```
[REPORT TYPE] SECTOR ANALYSIS   [SECTOR]   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Sector Name]: [One-line cycle characterization]

---

01 — CYCLE POSITION
[Where the sector sits in its cycle. What's priced vs. fundamentals. 
Valuation vs. history. Recent performance vs. market.]

02 — MACRO FRAME

## [Macro Driver 1]
[What it is, how it moves this sector, current read]

## [Macro Driver 2]
[Same structure]

## [Macro Driver 3]
[Same structure]

---

03 — SUB-SECTOR DIFFERENTIATION

| SUB-SECTOR | CYCLE POSITION | KEY DRIVER | BEST EXPRESSION |
|------------|---------------|------------|-----------------|
| [Name] | [early/mid/late] | [what drives it] | [TICK] |
| [Name] | ... | ... | ... |

[Narrative on who wins and loses within the sector. Be specific about why.]

---

04 — STOCK SELECTION

## Longs

### [TICKER] — [One-line thesis]
[3–4 sentences: why this name, what's the positioning gap, catalyst clock]

### [TICKER] — [One-line thesis]
[Same structure]

### [TICKER] — [One-line thesis]
[Same structure]

## Avoid

### [TICKER] — [One-line bear thesis]
[3–4 sentences: what's wrong with the consensus view, what kills the bull case]

---

05 — POSITIONING
[Sector flow data: recent ETF inflows/outflows. Crowding: which names are 
over-owned. Where the positioning gaps are relative to fundamental strength.]

06 — WHAT TO MONITOR
[Macro data releases, earnings dates, and events that move this sector. 
Specific data sources and thresholds.]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
[Flagged items from Stage 2]
```

---

## Global Voice Rules

These rules apply to every note type without exception.

1. **Actionable, not descriptive.** Every section answers "so what for positioning." Description without a positioning implication is cut.

2. **Distinguish data quality explicitly.**
   - Confirmed data: state source and date
   - `Directional estimate:` prefix for unconfirmed positioning or ownership claims
   - `Single source —` prefix for claims backed by only one data point
   - Never present an estimate as a fact

3. **Opinions stated directly.** "This is the most asymmetric positioning gap on the list" not "this may represent an asymmetric opportunity." The bear case section carries the hedging function — the main thesis does not hedge itself.

4. **Tickers ALL-CAPS throughout.**

5. **No empty qualifiers.** Cut: "may represent," "could potentially," "might be worth considering," "appears to suggest."

6. **Bear cases are explicit, not buried.** Every theme or stock thesis has a named bear case with a specific failure condition. Not "the trade could go wrong" — "the trade fails if [named event] occurs."

7. **TIME-SENSITIVE FLAGS section is always present.** Populated from Stage 2 gap log. If nothing was flagged, that itself is noted: "All claims confirmed with multi-source data."

8. **Data citations include source and approximate date.** "IEA (2025 report)" not just "IEA." "Third Point Q4 2025 letter" not "a major fund."

---

## File Structure

```
~/.claude/plugins/buy-side-research/
├── skills/
│   └── buy-side-note/
│       └── skill.md          ← Claude Code skill (slash command)
└── templates/
    ├── thematic-rotation.md  ← standalone prompt, no skill required
    ├── earnings-preview.md
    ├── earnings-flash.md
    ├── single-stock.md
    └── sector-analysis.md
```

The skill file encodes all four stages (classify → research → write → render) plus the full template library, chart specs, and voice rules. Each standalone template is self-contained: paste it + your topic into any Claude session to generate a correctly structured report without the skill.

---

## Output Format

Every report is delivered in two forms:
1. **Markdown** — the working draft, inline in the conversation
2. **PDF** — generated after the markdown is approved, using standard clean research note styling

### PDF Style
Standard institutional research note aesthetic:
- Clean serif or sans-serif body font, clear typographic hierarchy
- Section headers clearly delineated (numbered, bold)
- Tables with light borders and alternating row shading
- Callout boxes for bear cases and data caveats (no colored chips or monospace labels)
- Ticker references bold throughout
- Footer with date, classification, and disclaimer

### Charts

Each note type generates a standard set of charts embedded in the PDF. Charts are constructed from data gathered in Stage 2 (web search). If data for a chart is unavailable, the chart is omitted and flagged in TIME-SENSITIVE FLAGS.

| Note Type | Charts Generated |
|-----------|-----------------|
| Thematic Rotation | (1) Outgoing theme vs. S&P YTD performance; (2) Candidate themes relative performance comparison |
| Earnings Preview | (1) Stock vs. sector performance (3-month); (2) Historical EPS beat/miss vs. consensus (last 8 quarters) |
| Earnings Flash | (1) Stock reaction vs. implied move; (2) Reported metrics vs. consensus (bar chart) |
| Single-Stock Deep Dive | (1) Revenue and margin trend (3-year); (2) Valuation multiples vs. peer group (bar chart) |
| Sector Analysis | (1) Sub-sector relative performance YTD; (2) Sector valuation vs. 5-year history |

Charts are simple and data-dense — no decorative elements. Each chart includes a one-line data source note beneath it.

---

## What This Does NOT Do

- No financial data API calls (web search only — data is best-effort and time-sensitive)
- No multi-model routing
- No compliance review — user is responsible for validating all data before use

---

## Out of Scope for v1

- Automated scheduling or monitoring (run on a cron, alert on catalyst events)
- Multi-note linking (e.g., earnings flash auto-references prior preview)
- Collaborative editing or version history
- Non-English output
