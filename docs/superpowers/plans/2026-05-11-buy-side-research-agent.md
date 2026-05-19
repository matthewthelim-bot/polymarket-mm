# Buy-Side Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill (`/buy-side-note`) and five standalone prompt templates that generate institutional buy-side research notes with charts and PDF output.

**Architecture:** Four-stage pipeline (classify → research → write → render) encoded in a single skill.md. Research phase uses web search with typed checklists per note type. Stage 4 invokes `anthropic-skills:canvas-design` for charts and `anthropic-skills:pdf` for PDF rendering.

**Tech Stack:** Claude Code skills (markdown), built-in WebSearch, `anthropic-skills:canvas-design`, `anthropic-skills:pdf`

---

## File Map

| File | Purpose |
|------|---------|
| `~/.claude/plugins/buy-side-research/package.json` | Plugin metadata, registers the skill |
| `~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md` | Main skill — all 4 stages, all 5 note types, voice rules |
| `~/.claude/plugins/buy-side-research/templates/thematic-rotation.md` | Standalone self-contained prompt for thematic rotation notes |
| `~/.claude/plugins/buy-side-research/templates/earnings-preview.md` | Standalone self-contained prompt for earnings previews |
| `~/.claude/plugins/buy-side-research/templates/earnings-flash.md` | Standalone self-contained prompt for earnings flash notes |
| `~/.claude/plugins/buy-side-research/templates/single-stock.md` | Standalone self-contained prompt for single-stock deep dives |
| `~/.claude/plugins/buy-side-research/templates/sector-analysis.md` | Standalone self-contained prompt for sector analysis notes |

---

## Task 1: Plugin Scaffold

**Files:**
- Create: `C:\Users\matth\.claude\plugins\buy-side-research\package.json`
- Create dirs: `skills\buy-side-note\` and `templates\`

- [ ] **Step 1: Create the plugin directory structure**

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.claude\plugins\buy-side-research\skills\buy-side-note"
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.claude\plugins\buy-side-research\templates"
```

Expected: directories created, no errors.

- [ ] **Step 2: Write package.json**

Create `C:\Users\matth\.claude\plugins\buy-side-research\package.json`:

```json
{
  "name": "buy-side-research",
  "version": "1.0.0",
  "description": "Institutional buy-side research note generator — thematic rotation, earnings, single-stock, sector analysis",
  "skills": [
    {
      "name": "buy-side-note",
      "path": "skills/buy-side-note/skill.md",
      "description": "Generate institutional buy-side research notes with charts and PDF output. Supports: thematic rotation, earnings preview, earnings flash, single-stock deep dive, sector analysis."
    }
  ]
}
```

- [ ] **Step 3: Verify structure**

```powershell
Get-ChildItem -Recurse "$env:USERPROFILE\.claude\plugins\buy-side-research"
```

Expected output:
```
    Directory: C:\Users\matth\.claude\plugins\buy-side-research
Mode  Name
----  ----
d---- skills
d---- templates
-a--- package.json

    Directory: ...\skills
d---- buy-side-note
```

- [ ] **Step 4: Commit**

```powershell
cd "$env:USERPROFILE\.claude\plugins\buy-side-research"
git init
git add package.json
git commit -m "feat: scaffold buy-side-research plugin"
```

---

## Task 2: Core Skill File — Stages 1 & 2 (Classify + Research)

**Files:**
- Create: `C:\Users\matth\.claude\plugins\buy-side-research\skills\buy-side-note\skill.md`

This task writes the first half of the skill: the classify and research stages. The file will be completed in Task 3.

- [ ] **Step 1: Write skill.md with frontmatter, intro, Stage 1, and Stage 2**

Create `C:\Users\matth\.claude\plugins\buy-side-research\skills\buy-side-note\skill.md` with the following content:

```markdown
---
name: buy-side-note
description: Generate institutional buy-side research notes (thematic rotation, earnings preview, earnings flash, single-stock deep dive, sector analysis) with charts and PDF output. Use when asked to write any form of investment research, rotation note, earnings analysis, or stock deep dive.
---

# Buy-Side Research Note Generator

You are an institutional buy-side analyst writing internal research notes. Every note is structured for position initiation, not commentary. Run the four stages below in sequence, announcing each stage transition.

**Invocation examples:**
- "write a thematic rotation note on post-AI-capex rotation"
- "earnings preview for NVDA Q2 2026"
- "quick earnings flash on MSFT"
- "full deep dive on ALAB"
- "sector analysis on US defense"

---

## STAGE 1 — CLASSIFY

Parse the user's request for:
- **Note type** — one of five supported types (see routing table)
- **Subject** — theme name, ticker(s), or sector
- **Constraints** — time horizon, geography, mandate restrictions (if stated)

| User language | Note type |
|---|---|
| "thematic rotation", "what comes next", "after X", "rotation note", "next theme" | Thematic Rotation |
| "earnings preview", "pre-earnings", "into the print", "before earnings", "preview" | Earnings Preview |
| "earnings flash", "post-earnings", "after the print", "quick read on results", "flash" | Earnings Flash |
| "deep dive", "initiation", "single stock", "full analysis on [TICKER]", "cover [TICKER]" | Single-Stock Deep Dive |
| "sector analysis", "sector note", "sector view", "sector on [sector]" | Sector Analysis |

If note type is ambiguous after parsing, ask exactly one clarifying question. Do not begin research until note type and subject are confirmed.

Announce: **"Identified: [note type] on [subject]. Beginning research phase."**

---

## STAGE 2 — RESEARCH

Load the checklist for the confirmed note type. Run each item as a web search. Maintain a gap log as you go:
- Data found with source → record as `[source, date]`
- Only one source found → prefix claim with `Single source —`
- No usable data found → mark item `[UNFOUND]`
- Estimate without hard confirmation → mark `[DIRECTIONAL ESTIMATE]`

Do not fabricate data to fill gaps. Every `[UNFOUND]` or `[DIRECTIONAL ESTIMATE]` item flows directly into the TIME-SENSITIVE FLAGS section of the report.

Announce on completion: **"Research complete. [N]/[M] checklist items confirmed. [X] flagged as directional, single-source, or unfound."**

---

### Thematic Rotation — Research Checklist

Search for each of the following:

1. **Outgoing theme crowding signals** — Search: "[outgoing theme] crowded consensus sell-side coverage 2025 2026". Look for: sell-side coverage proliferation, valuation compression from original entry, institutional letters or public disclosures naming the trade.

2. **Candidate next themes (4–6)** — Search: "thematic rotation after [outgoing theme] investors 2026", "next AI trade after [topic]", "what replaces [outgoing theme] institutional". For each candidate found, record: one-sentence thesis, named near-term catalysts, listed beneficiary tickers.

3. **Institutional ownership + ETF vehicles per candidate** — Search: "[candidate theme] ETF 2025 2026", "[key ticker] institutional ownership hedge fund". Look for ETF tickers, expense ratios, AUM. Directional estimate on crowding is acceptable if hard data unavailable.

4. **Non-consensus contrarian idea** — Search: "[subject area] under-owned non-consensus 2026", "[region or sector] unloved underweight institutional". Goal: find one idea not on standard sell-side rotation lists. Record why it's non-consensus and why the thesis is real.

5. **Leading indicators per candidate theme** — Search: "[candidate theme] leading indicator data source monitor". Record: specific data release, ETF flow source, earnings event, or policy announcement that signals rotation is live.

---

### Earnings Preview — Research Checklist

Search for each of the following (replace [TICKER] with the subject):

1. **Consensus estimates** — Search: "[TICKER] Q[N] earnings estimates consensus EPS revenue 2026". Look for: EPS estimate, revenue estimate, and 2–3 operating metrics (e.g., billings, ARR, units, margins) the street specifically tracks.

2. **Prior quarter + guidance** — Search: "[TICKER] Q[N-1] earnings results guidance 2026". Record: actual prior-quarter EPS and revenue, management guidance for current quarter if given.

3. **Options-implied move** — Search: "[TICKER] options implied move earnings straddle 2026". Record: ATM straddle cost as % of stock price. If unavailable, mark [DIRECTIONAL ESTIMATE].

4. **Short interest + ownership changes** — Search: "[TICKER] short interest float 2026", "[TICKER] 13F institutional ownership changes". Record: short % of float, any notable adds or reductions.

5. **Key debates** — Search: "[TICKER] bull bear thesis 2026", "[TICKER] earnings debate street". Identify the 2–3 things bulls and bears specifically disagree on heading into the print.

6. **Peer reporting calendar** — Search: "[TICKER] sector peers earnings same week Q[N] 2026". Identify names reporting in the same window with potential read-across.

---

### Earnings Flash — Research Checklist

(Used immediately after results are published — prioritize speed.)

1. **Actual results** — Search: "[TICKER] Q[N] earnings results EPS revenue [current date]". Record: reported EPS, reported revenue, and every metric management guided to. Compare to consensus from Step 1.

2. **Guidance revision** — Search: "[TICKER] Q[N] guidance raised lowered maintained 2026". Record: new guidance vs. prior guidance, any specific language changes management made.

3. **Management commentary on key debates** — Search: "[TICKER] earnings call highlights key themes [current date]". Identify what management said (or didn't say) about the 2–3 debates from the preview.

4. **Stock reaction** — Search: "[TICKER] stock after-hours earnings [current date]". Record: % move after-hours or on open, implied move vs. actual move.

5. **Peer read-across** — Search: "[peer tickers] reaction [TICKER] earnings [current date]". Identify which sector names are immediately repriced and in which direction.

---

### Single-Stock Deep Dive — Research Checklist

1. **Business + financials** — Search: "[TICKER] revenue breakdown segments margins FCF 2025 2026", "[TICKER] annual report investor day". Record: revenue by segment, gross margin, operating margin, FCF, net cash/debt.

2. **Competitive position** — Search: "[TICKER] competitive advantages moat threats 2026", "[TICKER] vs [main competitor]". Identify: 2–3 named competitive threats, what the moat is and evidence of its durability.

3. **Management track record** — Search: "[TICKER] earnings beat miss guidance history 2024 2025". Record: beat/miss pattern on EPS and revenue over last 6–8 quarters.

4. **Valuation** — Search: "[TICKER] P/E EV/EBITDA valuation peers 2026", "[TICKER] forward multiple historical". Record: 2–3 relevant multiples vs. named direct peers and own 3-year average.

5. **Short interest + ownership** — Search: "[TICKER] short interest 2026", "[TICKER] top institutional holders 13F". Record: short % of float, top 5 holders as % of float if available.

6. **Catalyst calendar** — Search: "[TICKER] next earnings date investor day conference 2026", "[TICKER] product launch regulatory catalyst". Record: next 3 named catalysts with approximate dates.

---

### Sector Analysis — Research Checklist

1. **Sector performance** — Search: "[sector] ETF performance vs S&P 2026 YTD", "[sector] total return 1 year". Record: YTD performance absolute and relative to S&P 500, 1-year performance.

2. **Valuation vs. history** — Search: "[sector] forward P/E EV/EBITDA valuation 5-year history 2026". Record: current multiple and 5-year average for 1–2 relevant metrics.

3. **Earnings growth consensus** — Search: "[sector] earnings growth consensus 2026 2027 estimates". Record: current-year and next-year EPS growth consensus, revision direction.

4. **Macro drivers** — Search: "[sector] macro drivers interest rates [relevant variable] 2026". Identify 2–3 macro variables most correlated with sector performance and their current direction.

5. **Sub-sector differentiation** — Search: "[sector] sub-sectors outperform underperform 2026". Identify 3–4 sub-segments, their cycle position, and named best expressions.

6. **Stock selection** — Search: "[sector] best stocks 2026 buy-side", "[sector] undervalued under-owned 2026", "[sector] avoid overvalued crowded 2026". Identify top 3 long ideas and 1 avoid with positioning rationale.
```

- [ ] **Step 2: Verify file created and content looks right**

```powershell
(Get-Content "$env:USERPROFILE\.claude\plugins\buy-side-research\skills\buy-side-note\skill.md" | Measure-Object -Line).Lines
```

Expected: 150+ lines.

- [ ] **Step 3: Commit**

```powershell
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" add skills/buy-side-note/skill.md
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" commit -m "feat: add skill Stage 1 (classify) and Stage 2 (research checklists)"
```

---

## Task 3: Core Skill File — Stages 3 & 4 + Voice Rules (Write + Render)

**Files:**
- Modify: `C:\Users\matth\.claude\plugins\buy-side-research\skills\buy-side-note\skill.md` (append)

- [ ] **Step 1: Append Stage 3 (Write), Voice Rules, and Stage 4 (Render) to skill.md**

Append the following to the end of `skill.md`:

```markdown

---

## STAGE 3 — WRITE

Apply the template below for the confirmed note type. Voice Rules (at the end of this skill) apply globally — enforce them throughout without exception.

Announce when writing begins: **"Writing [note type] on [subject]."**

---

### Template: Thematic Rotation Note

```
THEMATIC STRATEGY   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Title: forward call framing — what comes after what]
[One-line subtitle: "structured for position initiation, not commentary"]

---

01 — CYCLE FRAME

[Why the outgoing theme is in late-consensus. Specific crowding signals: sell-side
coverage proliferation, valuation compression, institutional flow data, public letters.
Name the evidence. Two rotation paths in play: (a) monetization pivot — what does all
this [X] produce in revenue? — and (b) regime-shock rotation into real-economy
beneficiaries priced for nothing. State whether both paths are simultaneously live.]

---

02 — CANDIDATE THEMES

## [Theme Name]                                                    [CLASSIFICATION TAG]
[One-line framing: what kind of rotation this is]

THESIS       [The investable argument in 2–3 paragraphs. Bold the single key
             claim. State it directly. No hedge-y qualifiers — those go in the
             bear case box.]

CATALYST     (1) [Specific named event with approximate timing]
             (2) [Specific named event with approximate timing]
             (3) [Specific named event with approximate timing]
             (4) [Specific named event with approximate timing]

BENEFICIARIES   [TICK] [TICK] [TICK] [TICK] [TICK]
             [One sentence per name or group: role in the theme, why this
             name and not another. Group by role (pure-play / picks-and-shovels
             / foundry constraint / etc.)]

POSITIONING  [Directional estimate of institutional crowding. Is this under-owned,
             early-consensus, or crowded? Reference specific funds, ETFs, or
             13F data if available. Prefix unconfirmed estimates with
             "Directional estimate:"]

> [POSITIONING CAVEAT — orange callout: flag any specific claim in this
>  theme block that is a directional estimate or single-sourced. What to
>  check before trading.]

> [BEAR CASE — red callout: the specific named condition that kills this
>  thesis. Not "the trade could go wrong." "The trade fails if [specific
>  event/data point] occurs."]

[Repeat theme block A through F, applying the same structure to each candidate.
Use classification tags: ADJACENT (extension of current AI/capex cycle),
NEXT-LEG (derivative monetization play), MACRO (regime/fiscal driven),
ROTATION-OUT (defensive + genuinely under-owned).]

---

03 — RANKING

## Force-ranked: probability of becoming the next major theme (6–12 months)

Criteria: narrative readiness (story generalists can tell) × fundamental support
(near-term earnings anchor) × positioning asymmetry (under-owned relative to thesis
strength) × catalyst proximity (named events within 6 months). A theme scores high
only if it clears all four.

| # | THEME | KEY JUSTIFICATION | FAILURE CONDITION |
|---|-------|-------------------|-------------------|
| 1 | **[Theme Name]** [TICK] [TICK] | [Why it ranks here against the four criteria] | [The specific named event or data point that kills it] |
| 2 | **[Theme Name]** [TICK] [TICK] | [Justification] | [Kill condition] |
| 3 | ... | ... | ... |

---

04 — CONTRARIAN / NON-CONSENSUS PICK

## [Pick name] (non-consensus, [driver: macro-regime / structural / positioning])

[Why this is absent from standard sell-side rotation lists — structural reason, not
just "overlooked." Why the thesis is real despite low coverage: name the asymmetry.
Positioning: who owns it, what the free float situation is, what foreign/institutional
access looks like. The catalyst clock: specific named event that reprices the group.
Bear case: specific named risk that kills the trade, not generic market risk.]

[TICK] [TICK] [TICK]

---

05 — TRADEABLE EXPRESSION

## Entry structure for top-ranked theme + contrarian

| DIMENSION | THEME #1: [NAME] | CONTRARIAN: [NAME] |
|-----------|------------------|--------------------|
| **Cleanest expression** | Core long: [TICK] + [TICK]. Picks-and-shovels: [TICK]. ETF if sizing efficiency needed: [ETF TICK] ([expense ratio]) | Single-name: [TICK] (most liquid). Portfolio: equal-weight [TICK] + [TICK]. ETF proxy: [ticker or "none — this is the alpha gap"] |
| **Entry trigger** | (1) [Named event]. (2) [Named event]. (3) [Named event] | (1) [Named event]. (2) [Named event] |
| **Hedge / short leg** | Short [TICK] — [one sentence rationale: why this name is the correct expression of the disruption narrative on the short side] | [Macro hedge: e.g., short JGB futures, long USD/JPY, sector put. Or "no clean thematic short"] |
| **Time horizon** | [N] months. [One sentence: why this timeline, what the catalyst clock is] | [N] months. [Why — budget cycles, regulatory events, etc.] |
| **Sizing logic** | [X]% pre-catalyst (narrative risk). [X+Y]% post-catalyst confirmation. [Note on multi-thesis risk in the core long if applicable] | [X]% given [constraint: FX/liquidity/binary risk]. Size conservatively until [named event] confirms |

---

06 — WHAT TO MONITOR

[CATEGORY LABEL IN CAPS]   [Specific data source + named threshold or language that
                           signals rotation is live. One line per category. Be
                           specific: "AVGO Q2 FY2026 results (~June 2026) — look for
                           AI ASIC custom silicon revenue per hyperscaler. If any
                           single customer breaks $4B annual run rate, Theme A
                           gets mainstream." Not: "watch Broadcom earnings."]

[Include 6–8 categories covering: earnings dates, macro data releases, ETF flow
thresholds, policy/regulatory events, short interest flags, and clinical/product
milestones where applicable.]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS

[One bullet per flagged item from Stage 2 gap log. Format:]
- **[CLAIM LABEL IN CAPS]**: [The specific claim.] [Why it's flagged — single source,
  directional estimate, time-sensitive.] [What to check and where before trading.]

[If nothing was flagged: "All claims confirmed with multi-source data as of [date]."]

---
Internal research note — not for distribution. All thematic views represent
forward-looking estimates subject to material revision on catalyst events. [DATE].
```

---

### Template: Earnings Preview

```
EARNINGS PREVIEW   [TICKER] Q[N] [YEAR]   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Company Name] ([TICKER]) — Q[N] [YEAR] Preview
[One-line: what is specifically at stake in this print — the debate the market is
pricing in]

---

01 — SETUP

[What is currently priced: current valuation vs. history and peers, recent stock
performance (1-month, 3-month vs. sector). Options-implied move: [X]% (ATM straddle
as % of stock, source + date). Short interest: [X]% of float (source + date).
Positioning: directional estimate of how institutional books are positioned heading
into the print — long/light/neutral and why.]

---

02 — KEY DEBATES

## Debate 1: [Label — the thing bulls and bears actually disagree on]

**Bull:** [Specific argument with a data anchor. Not "growth is strong" — "NRR held
above 110% for 6 consecutive quarters suggesting the displacement thesis is overpriced."]

**Bear:** [Specific counter-argument with a data anchor.]

**Watch on the call:** [The specific number, disclosure, or management language that
resolves this debate. "If Q[N+1] revenue guidance comes in above $[X]B, the bull case
is confirmed. Below $[X-]B, the bear case accelerates."]

## Debate 2: [Label]
[Same structure]

## Debate 3: [Label]
[Same structure]

---

03 — NUMBERS TO WATCH

| METRIC | CONSENSUS | BEAT LOOKS LIKE | MISS LOOKS LIKE |
|--------|-----------|-----------------|-----------------|
| Revenue | $[X]B | >$[X+delta] | <$[X-delta] |
| EPS (adj.) | $[X] | >$[X+delta] | <$[X-delta] |
| [Key operating metric 1] | [X] | >[threshold] | <[threshold] |
| [Key operating metric 2] | [X] | >[threshold] | <[threshold] |
| Q[N+1] Revenue Guide | $[X]B (street est.) | >$[X+delta] | <$[X-delta] |

---

04 — TRADEABLE EXPRESSION

[How to position into the print. State the specific setup: entry level, sizing rationale
pre-print vs. post-print, hedge if needed. State the time horizon past the print if the
thesis extends beyond the reaction. "This is a 3–6 month thesis, not a day-of trade —
position pre-print at [X]% of book, add to [X+Y]% on a [named catalyst] confirmation.
Hedge with [specific hedge] to limit binary print risk."]

---

05 — WHAT TO MONITOR ON THE CALL

[One line per item — specific language, disclosure, or metric to listen for that
confirms or breaks the thesis. "Listen for management quantifying AI agent
displacement of seat-based users — any disclosure of NRR decline in SMB cohorts
accelerates the bear case." Not: "listen to what management says about AI."]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS

[One bullet per flagged item from Stage 2. At minimum: options-implied move source
and date, short interest data source and date, consensus estimates source and date.]
```

---

### Template: Earnings Flash

```
EARNINGS FLASH   [TICKER] Q[N] [YEAR]   [DATE / TIME of writing]

# [TICKER]: [One-line verdict — beat/miss/inline on the metric that matters most]
[Sub-line: "Initial read — subject to full call transcript review"]

---

01 — THE PRINT

| METRIC | REPORTED | CONSENSUS | DELTA |
|--------|----------|-----------|-------|
| Revenue | $[X]B | $[X]B | [+/-X% vs. est.] |
| EPS (adj.) | $[X] | $[X] | [+/-X% vs. est.] |
| [Key operating metric 1] | [X] | [X] | [delta] |
| [Key operating metric 2] | [X] | [X] | [delta] |

---

02 — GUIDANCE

[Prior guidance vs. new guidance on each metric management guides to. Bold language
changes — exact wording shifts in tone matter as much as number revisions. "FY revenue
guidance raised from $[X]–$[X] to $[X]–$[X]. Management language shifted from 'macro
uncertainty' to 'demand recovery is underway' — a notable tone change."]

---

03 — KEY DEBATE RESOLUTION

## Debate 1: [Label from preview]
**RESOLVED / UNRESOLVED / PARTIALLY RESOLVED**
[What the print said about this debate. Quote management if relevant.
"The [X]% NRR print resolves the bull case — displacement fears were overpriced.
Management guided to further NRR improvement, removing the bear overhang." Or:
"Management did not address the ASIC revenue mix question — unresolved until the call."]

## Debate 2: [Label]
[Same structure]

## Debate 3: [Label]
[Same structure]

---

04 — POSITIONING READ

[What the stock reaction implies about how investors were positioned.
"[TICKER] +[X]% on a [beat/inline] print implies the market was positioned
for a miss — short interest was elevated and options were pricing an [X]% move.
The actual reaction of [X]% exceeds/undershoots the implied move, suggesting
[crowded short covering / longs were already positioned / the miss was worse
than the implied move priced]."]

---

05 — PEER READ-ACROSS

[One line per relevant peer. "[TICK] — [directional implication from this print and
why]. [TICK] — [implication]. Monitor: [TICK] which reports [date] with similar
thesis exposure."]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS

- **ALL DATA IN THIS NOTE**: Flash notes are written within hours of results and
  before full call transcript review. All figures should be confirmed against the
  official 8-K/press release before trading.
[Additional flags from Stage 2 gap log]
```

---

### Template: Single-Stock Deep Dive

```
SINGLE-STOCK   [TICKER]   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Company Name] ([TICKER])
[One-line: the single thesis sentence — what is the core investable argument]

---

01 — BUSINESS FRAME

[What it does in 2–3 sentences. Revenue breakdown by segment as % of total with
growth rates. TAM and current penetration. Keep this section tight — only include
what is directly relevant to the thesis.]

---

02 — COMPETITIVE POSITION

[The moat: what it specifically is, and evidence it is durable (switching costs,
data network effects, regulatory capture, scale). Name 2–3 real competitive threats
with company names — not "competition could intensify." Where it specifically wins
and where it is vulnerable.]

---

03 — FINANCIALS

| METRIC | [YEAR-1]A | [YEAR]A/E | [YEAR+1]E |
|--------|-----------|-----------|-----------|
| Revenue | $[X]B | $[X]B | $[X]B |
| YoY Growth | [X]% | [X]% | [X]% |
| Gross Margin | [X]% | [X]% | [X]% |
| Operating Margin | [X]% | [X]% | [X]% |
| FCF | $[X]B | $[X]B | $[X]B |
| FCF Margin | [X]% | [X]% | [X]% |

Balance sheet: Net cash / (debt) of $[X]B. [One sentence on leverage or liquidity risk
if relevant, otherwise omit.]

---

04 — VALUATION

| MULTIPLE | [TICKER] (current) | PEER AVG | [TICKER] 3YR AVG |
|----------|--------------------|----------|------------------|
| Fwd P/E | [X]x | [X]x | [X]x |
| EV/EBITDA | [X]x | [X]x | [X]x |
| [Sector metric, e.g. EV/Revenue, P/FCF] | [X]x | [X]x | [X]x |

[One paragraph: what the current multiple implies about expectations, what is priced
in, and where the re-rating thesis lives. "At [X]x forward earnings vs. peers at [X]x,
the market is pricing in [X]% growth deceleration. The bull case requires only [Y]%
growth — which [evidence] suggests is achievable."]

---

05 — THE DEBATE

**Bull:** [3–4 sentences. The bull thesis anchored to specific data: margins, TAM
penetration, moat evidence, valuation gap. Lead with the strongest argument.]

**Bear:** [3–4 sentences. The bear thesis anchored to specific risk: competitive
threat, margin compression, execution risk, valuation premium. Be honest about the
strongest bear argument — don't strawman it.]

**View:** [Where you stand and why. Direct. "The bear case underestimates [specific
thing]. At [X]x forward earnings with [evidence] as a floor, the risk/reward is
asymmetric to the upside on a [N]-month horizon." Not: "on balance we lean positive."]

---

06 — POSITIONING

Short interest: [X]% of float (source, date). [Crowded short / neutral / limited
short interest — implication for re-rating velocity if bull thesis plays out.]

Institutional ownership: [Top holder] [X]%, [second holder] [X]%. Top 5 holders
represent [X]% of float — [concentrated / broadly distributed].

Directional estimate: [Under-owned / consensus / crowded]. [Why — which types of
funds own it, which don't, what the natural buyer is if the narrative shifts.]

---

07 — TRADEABLE EXPRESSION

[Cleanest long expression (single-name or paired trade). Entry trigger: the named
event that confirms the thesis has legs. Catalyst clock: next 3 named events with
dates. Sizing: pre-catalyst [X]% of book, post-catalyst [X+Y]%. Time horizon: [N]
months. Hedge: [specific hedge if binary risk warrants it, or "no hedge needed given
[reason]"]. Position exit: what would cause you to close the trade early.]

---

08 — WHAT TO MONITOR

[One line per item — specific data source, specific threshold, specific event.
"[TICKER] Q[N+1] earnings (~[date]) — watch for [specific metric] above [threshold]
as confirmation. Below [threshold] invalidates the margin expansion thesis."]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS

[One bullet per flagged item from Stage 2 gap log. At minimum: valuation data source
and date, short interest source and date, any directional estimates in the positioning
section.]
```

---

### Template: Sector Analysis

```
SECTOR ANALYSIS   [SECTOR]   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Sector Name]: [One-line cycle characterization]
[Sub-line: structured for sector allocation and stock selection]

---

01 — CYCLE POSITION

[Where the sector sits in its cycle relative to fundamentals. What is currently priced
vs. the earnings and macro reality. Recent performance: [X]% YTD vs. S&P [X]% YTD.
Current valuation: [X]x forward P/E vs. 5-year average of [X]x — [premium/discount]
and why. Whether the sector is early-cycle, mid-cycle, or late-cycle and the evidence.]

---

02 — MACRO FRAME

## [Macro Driver 1]
[What it is, how it mechanically moves this sector (direction and magnitude), current
read as of [date]. "10-year Treasury yields at [X]% — [implication for sector
multiples or earnings]. The relationship holds unless [named exception]."]

## [Macro Driver 2]
[Same structure]

## [Macro Driver 3]
[Same structure]

---

03 — SUB-SECTOR DIFFERENTIATION

| SUB-SECTOR | CYCLE POSITION | KEY DRIVER | BEST EXPRESSION |
|------------|----------------|------------|-----------------|
| [Name] | [early / mid / late / crowded] | [What specifically drives this sub-segment] | [TICK] |
| [Name] | ... | ... | ... |
| [Name] | ... | ... | ... |

[2–3 sentences of narrative: the key differentiation within the sector. Which
sub-segments benefit from which macro scenario, and why the allocation matters now.]

---

04 — STOCK SELECTION

## Longs

### [TICKER] — [One-line thesis]
[3–5 sentences: why this name specifically, what the positioning gap is, what
catalyst closes the gap, sizing rationale. "Directional estimate: under-owned in
generalist books because [reason]. The catalyst is [named event ~date]."]

### [TICKER] — [One-line thesis]
[Same structure]

### [TICKER] — [One-line thesis]
[Same structure]

## Avoid

### [TICKER] — [One-line bear thesis]
[3–5 sentences: what is wrong with the consensus bull view, what the specific
failure condition is, what the crowding dynamic looks like on the short side.
"The consensus sees [bull argument]. This underestimates [specific risk].
The trade fails if [named event/data point] confirms it."]

---

05 — POSITIONING

[Sector ETF flows: recent inflow/outflow trend and what it signals about where
generalist money is positioned. Which names are over-owned vs. where the gaps are.
"[TICK] is in every thematic basket — not a positioning gap. [TICK] is largely absent
from US institutional books because [specific structural reason] — that is the gap."]

---

06 — WHAT TO MONITOR

[One line per category — specific data release, earnings event, or policy announcement
with named source and threshold. 5–7 items.]

---

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS

[One bullet per flagged item from Stage 2 gap log.]
```

---

## VOICE RULES

Enforce these globally across all note types. No exceptions.

1. **Actionable, not descriptive.** Every section answers "so what for positioning." Description with no positioning implication is cut.

2. **Distinguish data quality explicitly.**
   - Confirmed with source → state source and approximate date
   - Directional estimate → prefix: `Directional estimate:`
   - Single source → prefix: `Single source —`
   - Never present an estimate as confirmed fact

3. **Opinions stated directly.** "This is the most asymmetric positioning gap on the list" — not "this may represent an asymmetric opportunity." The bear case carries the hedging function.

4. **Tickers ALL-CAPS throughout.** No exceptions.

5. **No empty qualifiers.** Cut: "may represent," "could potentially," "might be worth considering," "appears to suggest."

6. **Bear cases are explicit, not buried.** Named failure condition. Not "the trade could go wrong" — "the trade fails if [named event] occurs."

7. **TIME-SENSITIVE FLAGS is always present.** Populated from Stage 2 gap log. If all items confirmed: state it explicitly.

8. **Data citations include source and approximate date.** "IEA (2025 electricity demand report)" not "IEA." "Third Point Q4 2025 letter" not "a major fund."

---

## STAGE 4 — RENDER

After the markdown draft is complete, generate charts and produce a PDF.

Announce: **"Draft complete. Generating charts and rendering PDF."**

### Chart Generation

Generate the following charts from Stage 2 research data. For each chart:
1. Prepare the data points gathered in Stage 2
2. Invoke `anthropic-skills:canvas-design` to generate the chart as a PNG with clean styling (white background, minimal gridlines, labeled axes, source note at bottom)
3. Insert the PNG at the relevant section in the final PDF

| Note Type | Chart 1 | Chart 2 |
|-----------|---------|---------|
| Thematic Rotation | Outgoing theme vs. S&P 500 YTD (line chart) | Candidate themes relative performance comparison (bar chart) |
| Earnings Preview | Stock vs. sector 3-month performance (line chart) | Historical EPS beat/miss vs. consensus — last 8 quarters (bar chart) |
| Earnings Flash | Reported vs. consensus on key metrics (bar chart) | Stock reaction % vs. options-implied move (single-bar comparison) |
| Single-Stock Deep Dive | Revenue and operating margin trend — 3 years (dual-axis line/bar) | Valuation multiples vs. peer group (grouped bar chart) |
| Sector Analysis | Sub-sector relative performance YTD (bar chart) | Sector forward P/E vs. 5-year historical average (line chart with mean line) |

**If data for a chart is unavailable:** omit the chart silently and add it to TIME-SENSITIVE FLAGS. Never generate charts with fabricated or illustrative data.

### PDF Rendering

After all charts are generated, invoke `anthropic-skills:pdf` to render the complete note as a PDF. Provide the following styling instructions to the pdf skill:

- Font: clean sans-serif (Inter, Helvetica, or system default), 10–11pt body
- Section headers: bold, numbered, clearly delineated with spacing
- Tables: light 1pt borders, alternating row shading (#F7F7F7 / white)
- Callout boxes: light gray border, slightly indented, for bear cases and caveats
- Tickers: bold throughout
- Charts: embedded at the relevant section, full-width with source note beneath
- Header: report type + ticker/subject + date, right-aligned
- Footer: "Internal research note — not for distribution. [DATE]." centered, small text
- Page margins: 1.25" left/right, 1" top/bottom
```

- [ ] **Step 2: Verify final skill.md line count**

```powershell
(Get-Content "$env:USERPROFILE\.claude\plugins\buy-side-research\skills\buy-side-note\skill.md" | Measure-Object -Line).Lines
```

Expected: 400+ lines.

- [ ] **Step 3: Commit**

```powershell
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" add skills/buy-side-note/skill.md
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" commit -m "feat: add skill Stage 3 (write templates), voice rules, Stage 4 (render)"
```

---

## Task 4: Standalone Template — Thematic Rotation

**Files:**
- Create: `C:\Users\matth\.claude\plugins\buy-side-research\templates\thematic-rotation.md`

Standalone templates are self-contained — they include the research checklist, the write template, and the voice rules for one note type. Paste the entire file as a user prompt in any Claude session.

- [ ] **Step 1: Write thematic-rotation.md**

Create `C:\Users\matth\.claude\plugins\buy-side-research\templates\thematic-rotation.md`:

```markdown
# Standalone Prompt: Thematic Rotation Note

Paste this entire file as a prompt in Claude, then append your topic at the end.
Example: paste this file, then add "Topic: what comes after the AI capex / HBM theme in mid-2026"

---

You are an institutional buy-side analyst writing an internal thematic rotation note.
The note is structured for position initiation, not commentary. Follow the three phases
below in sequence.

## PHASE 1 — RESEARCH

Search for each of the following before writing a single line of the report:

1. **Crowding signals on the outgoing theme** — Search: "[outgoing theme] crowded consensus sell-side coverage". Look for: sell-side coverage count, valuation compression from entry, institutional letters naming the trade publicly.

2. **4–6 candidate next themes** — Search: "thematic rotation after [outgoing theme] investors 2026", "next trade after [topic]". For each candidate: one-sentence thesis, named near-term catalysts, listed beneficiary tickers.

3. **Institutional ownership + ETF vehicles per candidate** — Search: "[candidate theme] ETF 2025 2026", "[key ticker] institutional ownership". Record ETF tickers, AUM, expense ratios. Mark ownership estimates as `Directional estimate:` if unconfirmed.

4. **Non-consensus contrarian idea** — Search: "[subject area] under-owned non-consensus 2026". Find one idea absent from standard sell-side rotation lists.

5. **Leading indicators per theme** — Search: "[candidate theme] leading indicator data source". Record specific data releases or events that signal rotation is live.

Track gaps: `[UNFOUND]` = no data found. `[DIRECTIONAL ESTIMATE]` = unconfirmed estimate. `[SINGLE SOURCE]` = one source only. These flow into the caveats section.

---

## PHASE 2 — WRITE

Apply this template using the research above. Voice rules (Phase 3) apply throughout.

```
THEMATIC STRATEGY   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Title: forward call framing]
[Subtitle: "structured for position initiation, not commentary"]

01 — CYCLE FRAME
[Why the outgoing theme is in late-consensus. Specific crowding signals.
Two rotation paths: (a) monetization pivot, (b) regime-shock real-economy rotation.]

02 — CANDIDATE THEMES

## [Theme Name]                                              [CLASSIFICATION TAG]
[One-line framing]

THESIS       [The investable argument. Bold the key claim.]

CATALYST     (1) [Named event + timing]
             (2) [Named event + timing]
             (3) [Named event + timing]
             (4) [Named event + timing]

BENEFICIARIES   [TICK] [TICK] [TICK] [TICK]
             [Role per name or group]

POSITIONING  [Directional estimate of crowding. Prefix unconfirmed with
             "Directional estimate:"]

> [POSITIONING CAVEAT: specific data quality flag]

> [BEAR CASE: named failure condition — "the trade fails if [X] occurs"]

[Repeat for each candidate A–F. Tags: ADJACENT / NEXT-LEG / MACRO / ROTATION-OUT]

03 — RANKING

## Force-ranked (6–12 months)
Criteria: narrative readiness × fundamental support × positioning asymmetry × catalyst proximity.

| # | THEME | KEY JUSTIFICATION | FAILURE CONDITION |
|---|-------|-------------------|-------------------|
| 1 | **[Name]** [TICK] | [Against all four criteria] | [Named kill condition] |

04 — CONTRARIAN / NON-CONSENSUS PICK

## [Pick name]
[Why non-consensus. Why real. Catalyst clock. Positioning. Bear case.]
[TICK] [TICK] [TICK]

05 — TRADEABLE EXPRESSION

| DIMENSION | THEME #1 | CONTRARIAN |
|-----------|----------|------------|
| **Cleanest expression** | [Long + ETF] | [Single-name or portfolio] |
| **Entry trigger** | [Named events] | [Named events] |
| **Hedge / short leg** | [Specific short + rationale] | [Macro hedge or "none"] |
| **Time horizon** | [N months + why] | [N months + why] |
| **Sizing logic** | [Pre/post-catalyst %] | [% + constraints] |

06 — WHAT TO MONITOR
[CATEGORY]   [Specific data source + threshold that signals rotation is live]
[6–8 categories]

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
- [CLAIM]: [Why flagged. What to check before trading.]
```

---

## PHASE 3 — VOICE RULES

1. Every section answers "so what for positioning." No description without implication.
2. `Directional estimate:` prefix for unconfirmed positioning. `Single source —` for single-sourced claims.
3. Opinions stated directly. Hedging lives in the bear case box, not the thesis.
4. Tickers ALL-CAPS throughout.
5. No empty qualifiers: cut "may represent," "could potentially," "might be worth."
6. Bear cases name a specific failure condition. Not "risk exists" — "fails if [X]."
7. TIME-SENSITIVE FLAGS always present.
8. Data citations include source + approximate date.

---

**Topic:** [Append your topic here before sending]
```

- [ ] **Step 2: Commit**

```powershell
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" add templates/thematic-rotation.md
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" commit -m "feat: add standalone thematic-rotation template"
```

---

## Task 5: Standalone Template — Earnings Preview

**Files:**
- Create: `C:\Users\matth\.claude\plugins\buy-side-research\templates\earnings-preview.md`

- [ ] **Step 1: Write earnings-preview.md**

Create `C:\Users\matth\.claude\plugins\buy-side-research\templates\earnings-preview.md`:

```markdown
# Standalone Prompt: Earnings Preview

Paste this entire file as a prompt in Claude, then append your ticker and quarter.
Example: paste this file, then add "Ticker: NVDA. Quarter: Q2 FY2026 (reports ~late May 2026)."

---

You are an institutional buy-side analyst writing an internal earnings preview.
The note is structured for position initiation before the print. Follow three phases.

## PHASE 1 — RESEARCH

Search for each item before writing:

1. **Consensus estimates** — Search: "[TICKER] Q[N] earnings estimates consensus EPS revenue [year]". Record: EPS estimate, revenue estimate, 2–3 key operating metrics the street tracks.

2. **Prior quarter + guidance** — Search: "[TICKER] Q[N-1] earnings results guidance". Record: prior-quarter actuals, current-quarter guidance from management if given.

3. **Options-implied move** — Search: "[TICKER] options implied move earnings straddle". Record ATM straddle as % of stock price. Mark `[DIRECTIONAL ESTIMATE]` if unavailable.

4. **Short interest + ownership** — Search: "[TICKER] short interest float", "[TICKER] 13F institutional ownership changes". Record: short % of float, notable adds/reductions.

5. **Key debates** — Search: "[TICKER] bull bear thesis [year]", "[TICKER] earnings debate". Identify the 2–3 things bulls and bears specifically disagree on.

6. **Peer reporting calendar** — Search: "[TICKER] sector peers earnings same week". Identify names reporting in the same window.

Track gaps with `[UNFOUND]`, `[DIRECTIONAL ESTIMATE]`, `[SINGLE SOURCE]`.

---

## PHASE 2 — WRITE

```
EARNINGS PREVIEW   [TICKER] Q[N] [YEAR]   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Company] ([TICKER]) — Q[N] [YEAR] Preview
[One-line: the specific debate the market is pricing into this print]

01 — SETUP
[Current valuation vs. history + peers. Recent stock performance vs. sector.
Implied move: [X]% (source, date). Short interest: [X]% of float (source, date).
Positioning: directional estimate of institutional positioning heading into print.]

02 — KEY DEBATES

## Debate 1: [Label]
**Bull:** [Specific argument with data anchor]
**Bear:** [Specific counter-argument with data anchor]
**Watch on the call:** [The specific number or language that resolves this debate.
"If Q[N+1] guide comes in above $[X]B, bull confirmed. Below $[X-], bear accelerates."]

## Debate 2: [Label]
[Same structure]

## Debate 3: [Label]
[Same structure]

03 — NUMBERS TO WATCH

| METRIC | CONSENSUS | BEAT | MISS |
|--------|-----------|------|------|
| Revenue | $[X]B | >$[X+] | <$[X-] |
| EPS (adj.) | $[X] | >$[X+] | <$[X-] |
| [Key metric 1] | [X] | >[threshold] | <[threshold] |
| [Key metric 2] | [X] | >[threshold] | <[threshold] |
| Q[N+1] Guide | $[X]B est. | >$[X+] | <$[X-] |

04 — TRADEABLE EXPRESSION
[Entry, sizing pre vs. post-print, hedge, time horizon. Specific, not generic.]

05 — WHAT TO MONITOR ON THE CALL
[Specific language or disclosure to listen for. One line per item.]

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
[One bullet per flagged item. At minimum: estimates source+date, implied move source+date.]
```

---

## PHASE 3 — VOICE RULES

1. Every section answers "so what for positioning."
2. `Directional estimate:` prefix for unconfirmed. `Single source —` for single-sourced.
3. Direct opinions. Hedging in the bear/caveat sections only.
4. Tickers ALL-CAPS.
5. Cut empty qualifiers.
6. Named failure conditions in bear/caveat sections.
7. TIME-SENSITIVE FLAGS always present.
8. Source + approximate date on all data citations.

---

**Ticker and quarter:** [Append here before sending]
```

- [ ] **Step 2: Commit**

```powershell
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" add templates/earnings-preview.md
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" commit -m "feat: add standalone earnings-preview template"
```

---

## Task 6: Standalone Templates — Earnings Flash + Single-Stock

**Files:**
- Create: `C:\Users\matth\.claude\plugins\buy-side-research\templates\earnings-flash.md`
- Create: `C:\Users\matth\.claude\plugins\buy-side-research\templates\single-stock.md`

- [ ] **Step 1: Write earnings-flash.md**

Create `C:\Users\matth\.claude\plugins\buy-side-research\templates\earnings-flash.md`:

```markdown
# Standalone Prompt: Earnings Flash

Paste this entire file as a prompt in Claude, then append ticker + "results just published."
Example: paste this file, then add "Ticker: MSFT. Q3 FY2026 results just published. Date: [today]."

---

You are an institutional buy-side analyst writing an earnings flash note immediately
after results are published. Speed and accuracy on the key metrics matter most.
Follow three phases.

## PHASE 1 — RESEARCH

Search quickly for each item:

1. **Actual results** — Search: "[TICKER] Q[N] earnings results EPS revenue [today's date]". Record: reported EPS, reported revenue, every metric management guided to previously.

2. **Guidance revision** — Search: "[TICKER] Q[N] guidance [today's date]". Record new guidance vs. prior guidance. Note exact language changes.

3. **Management commentary** — Search: "[TICKER] earnings call highlights [today's date]". Identify what was said about the 2–3 key pre-print debates.

4. **Stock reaction** — Search: "[TICKER] stock after hours [today's date]". Record % move and compare to options-implied move if known.

5. **Peer read-across** — Search: "[peer tickers] reaction [TICKER] earnings [today's date]". Identify which sector names are repriced and in which direction.

Track gaps with `[UNFOUND]`, `[DIRECTIONAL ESTIMATE]`, `[SINGLE SOURCE]`.

---

## PHASE 2 — WRITE

```
EARNINGS FLASH   [TICKER] Q[N] [YEAR]   [DATE / TIME]

# [TICKER]: [One-line verdict on the metric that matters most]
Initial read — subject to full call transcript review

01 — THE PRINT

| METRIC | REPORTED | CONSENSUS | DELTA |
|--------|----------|-----------|-------|
| Revenue | $[X]B | $[X]B | [+/-X%] |
| EPS (adj.) | $[X] | $[X] | [+/-X%] |
| [Key metric 1] | [X] | [X] | [delta] |
| [Key metric 2] | [X] | [X] | [delta] |

02 — GUIDANCE
[Prior vs. new guidance on each metric. Bold language changes. One paragraph.]

03 — KEY DEBATE RESOLUTION

## Debate 1: [Label]
**RESOLVED / UNRESOLVED / PARTIALLY RESOLVED**
[What the print said. Quote management if relevant.]

## Debate 2: [Label]
[Same structure]

04 — POSITIONING READ
[What the [X]% stock reaction implies about how the market was positioned.
Compare actual move to implied move.]

05 — PEER READ-ACROSS
[One line per peer. "[TICK] — implication. [TICK] — implication."]

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
- **ALL DATA**: Flash note written before full transcript review. Confirm figures
  against official 8-K/press release before trading.
[Additional flags from research phase]
```

---

## PHASE 3 — VOICE RULES

1. Speed and accuracy. Every section answers "so what for positioning."
2. `Directional estimate:` prefix for unconfirmed. `Single source —` for single-sourced.
3. Direct. Hedging in caveats section only.
4. Tickers ALL-CAPS.
5. Cut empty qualifiers.
6. TIME-SENSITIVE FLAGS always present and prominent — flash notes decay fast.
7. Source + time on all data (hour-level precision matters for flash notes).

---

**Ticker and context:** [Append here — e.g., "MSFT Q3 FY2026, results published 30 minutes ago"]
```

- [ ] **Step 2: Write single-stock.md**

Create `C:\Users\matth\.claude\plugins\buy-side-research\templates\single-stock.md`:

```markdown
# Standalone Prompt: Single-Stock Deep Dive

Paste this entire file as a prompt in Claude, then append your ticker.
Example: paste this file, then add "Ticker: ALAB (Astera Labs). Date: [today]."

---

You are an institutional buy-side analyst writing an internal single-stock deep dive,
structured for position initiation. Follow three phases.

## PHASE 1 — RESEARCH

Search for each item before writing:

1. **Business + financials** — Search: "[TICKER] revenue segments margins FCF [year] annual report". Record: revenue by segment, gross margin, operating margin, FCF, net cash/debt.

2. **Competitive position** — Search: "[TICKER] competitive moat threats [year]", "[TICKER] vs [main competitor]". Record: 2–3 named threats, moat evidence.

3. **Management track record** — Search: "[TICKER] earnings beat miss guidance history 2024 2025". Record: beat/miss pattern on EPS and revenue, last 6–8 quarters.

4. **Valuation** — Search: "[TICKER] P/E EV/EBITDA peers valuation [year]". Record: 2–3 multiples vs. named peers and own 3-year average.

5. **Short interest + ownership** — Search: "[TICKER] short interest float", "[TICKER] top institutional holders 13F". Record: short % of float, top holders.

6. **Catalyst calendar** — Search: "[TICKER] next earnings investor day 2026", "[TICKER] product launch regulatory". Record: next 3 named catalysts with approximate dates.

Track gaps with `[UNFOUND]`, `[DIRECTIONAL ESTIMATE]`, `[SINGLE SOURCE]`.

---

## PHASE 2 — WRITE

```
SINGLE-STOCK   [TICKER]   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Company] ([TICKER])
[One-line thesis sentence]

01 — BUSINESS FRAME
[What it does. Revenue by segment with growth rates. TAM + penetration.
Only what is directly relevant to the thesis.]

02 — COMPETITIVE POSITION
[The moat and evidence of durability. 2–3 named threats. Where it wins and
where it is vulnerable. Specific, not generic.]

03 — FINANCIALS

| METRIC | [YEAR-1]A | [YEAR]A/E | [YEAR+1]E |
|--------|-----------|-----------|-----------|
| Revenue | $[X]B | $[X]B | $[X]B |
| YoY Growth | [X]% | [X]% | [X]% |
| Gross Margin | [X]% | [X]% | [X]% |
| Operating Margin | [X]% | [X]% | [X]% |
| FCF | $[X]B | $[X]B | $[X]B |

Balance sheet: Net cash/(debt) $[X]B.

04 — VALUATION

| MULTIPLE | [TICKER] | PEER AVG | [TICKER] 3YR AVG |
|----------|----------|----------|------------------|
| Fwd P/E | [X]x | [X]x | [X]x |
| EV/EBITDA | [X]x | [X]x | [X]x |
| [Sector metric] | [X]x | [X]x | [X]x |

[What current multiple implies about expectations. Where re-rating thesis lives.]

05 — THE DEBATE
**Bull:** [3–4 sentences. Strongest argument anchored to data.]
**Bear:** [3–4 sentences. Strongest counter. Don't strawman it.]
**View:** [Where you stand and why. Direct.]

06 — POSITIONING
Short interest: [X]% of float (source, date).
Institutional: [Top holder] [X]%, top 5 = [X]% of float.
Directional estimate: [Under-owned / consensus / crowded] — [why].

07 — TRADEABLE EXPRESSION
[Cleanest long. Entry trigger. Catalyst clock: 3 named events + dates.
Sizing: pre/post-catalyst %. Time horizon. Hedge if needed. Exit condition.]

08 — WHAT TO MONITOR
[One line per item — specific data, specific threshold, specific event.]

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
[One bullet per flag. At minimum: valuation data date, short interest date.]
```

---

## PHASE 3 — VOICE RULES

1. Every section answers "so what for positioning."
2. `Directional estimate:` prefix for unconfirmed. `Single source —` for single-sourced.
3. Direct opinions. Bear case carries the hedging function.
4. Tickers ALL-CAPS.
5. Cut empty qualifiers.
6. Named failure condition in bear case and exit condition.
7. TIME-SENSITIVE FLAGS always present.
8. Source + approximate date on all data citations.

---

**Ticker:** [Append here]
```

- [ ] **Step 3: Commit**

```powershell
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" add templates/earnings-flash.md templates/single-stock.md
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" commit -m "feat: add standalone earnings-flash and single-stock templates"
```

---

## Task 7: Standalone Template — Sector Analysis

**Files:**
- Create: `C:\Users\matth\.claude\plugins\buy-side-research\templates\sector-analysis.md`

- [ ] **Step 1: Write sector-analysis.md**

Create `C:\Users\matth\.claude\plugins\buy-side-research\templates\sector-analysis.md`:

```markdown
# Standalone Prompt: Sector Analysis

Paste this entire file as a prompt in Claude, then append your sector.
Example: paste this file, then add "Sector: US Defense & Aerospace. Date: [today]."

---

You are an institutional buy-side analyst writing an internal sector analysis note,
structured for sector allocation and stock selection. Follow three phases.

## PHASE 1 — RESEARCH

Search for each item before writing:

1. **Sector performance** — Search: "[sector] ETF performance vs S&P 2026 YTD", "[sector] total return 1 year". Record: YTD and 1-year performance, absolute and vs. S&P 500.

2. **Valuation vs. history** — Search: "[sector] forward P/E EV/EBITDA 5-year history 2026". Record: current multiple and 5-year average for 1–2 sector-appropriate metrics.

3. **Earnings growth consensus** — Search: "[sector] earnings growth consensus 2026 2027". Record: current-year and next-year EPS growth estimate, revision direction.

4. **Macro drivers** — Search: "[sector] macro drivers [relevant variable: rates / oil / defense budget / etc.] 2026". Identify 2–3 correlated macro variables and current read on each.

5. **Sub-sector differentiation** — Search: "[sector] sub-sectors outperform underperform 2026". Identify 3–4 sub-segments with cycle position and best expression per sub-sector.

6. **Stock selection** — Search: "[sector] best stocks 2026 buy-side undervalued under-owned", "[sector] avoid overvalued crowded". Identify top 3 longs and 1 avoid.

Track gaps with `[UNFOUND]`, `[DIRECTIONAL ESTIMATE]`, `[SINGLE SOURCE]`.

---

## PHASE 2 — WRITE

```
SECTOR ANALYSIS   [SECTOR]   [DATE]   INTERNAL / BUY-SIDE ONLY

# [Sector Name]: [One-line cycle characterization]

01 — CYCLE POSITION
[Where the sector sits in its cycle. What is currently priced vs. fundamentals.
Performance: [X]% YTD vs. S&P [X]%. Valuation: [X]x fwd P/E vs. 5yr avg [X]x.
Early / mid / late cycle — evidence.]

02 — MACRO FRAME

## [Macro Driver 1]
[What it is, mechanical relationship to sector, current read as of [date].]

## [Macro Driver 2]
[Same structure]

## [Macro Driver 3]
[Same structure]

03 — SUB-SECTOR DIFFERENTIATION

| SUB-SECTOR | CYCLE POSITION | KEY DRIVER | BEST EXPRESSION |
|------------|----------------|------------|-----------------|
| [Name] | [early/mid/late/crowded] | [specific driver] | [TICK] |
| [Name] | ... | ... | ... |
| [Name] | ... | ... | ... |

[2–3 sentences: key differentiation. Which sub-segments win in which scenario.]

04 — STOCK SELECTION

## Longs

### [TICKER] — [One-line thesis]
[3–5 sentences: why this name, positioning gap, named catalyst, sizing rationale.
"Directional estimate: under-owned because [reason]. Catalyst: [event ~date]."]

### [TICKER] — [One-line thesis]
[Same structure]

### [TICKER] — [One-line thesis]
[Same structure]

## Avoid

### [TICKER] — [One-line bear thesis]
[3–5 sentences: what is wrong with the consensus bull view, specific failure
condition, crowding dynamic. "Fails if [named event/data point] confirms [risk]."]

05 — POSITIONING
[ETF flow trend and implication. Which names are over-owned. Where the gaps are.
"[TICK] is in every thematic basket — not a gap. [TICK] is absent from US books
because [structural reason] — that is the gap."]

06 — WHAT TO MONITOR
[One line per category: specific data release, earnings event, policy announcement.
Named source + threshold. 5–7 items.]

TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
[One bullet per flag from research phase.]
```

---

## PHASE 3 — VOICE RULES

1. Every section answers "so what for sector allocation and stock selection."
2. `Directional estimate:` prefix for unconfirmed. `Single source —` for single-sourced.
3. Direct opinions. Hedging in bear case and caveats only.
4. Tickers ALL-CAPS.
5. Cut empty qualifiers.
6. Named failure conditions. Not "risk exists" — "fails if [X]."
7. TIME-SENSITIVE FLAGS always present.
8. Source + approximate date on all data citations.

---

**Sector:** [Append here]
```

- [ ] **Step 2: Commit**

```powershell
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" add templates/sector-analysis.md
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" commit -m "feat: add standalone sector-analysis template"
```

---

## Task 8: End-to-End Validation

Validate each note type by running the skill with a test prompt and checking the output against a structural and voice checklist.

- [ ] **Step 1: Test Thematic Rotation**

Invoke the skill with:
> `/buy-side-note write a thematic rotation note on what comes after the AI inference / custom silicon theme in late 2026`

Check output against this list:
- [ ] Header includes date and "INTERNAL / BUY-SIDE ONLY"
- [ ] Section 01 names specific crowding signals (not generic statements)
- [ ] At least 4 candidate themes (A–D minimum), each with THESIS / CATALYST / BENEFICIARIES / POSITIONING blocks
- [ ] Each theme has a bear case callout with a named failure condition
- [ ] Section 03 ranking table has # / THEME / KEY JUSTIFICATION / FAILURE CONDITION columns
- [ ] Section 04 contrarian pick explains why it's non-consensus (structural reason, not just "overlooked")
- [ ] Section 05 tradeable expression table has all 5 rows (cleanest expression / entry trigger / hedge / time horizon / sizing)
- [ ] TIME-SENSITIVE FLAGS section present with at least one flagged item
- [ ] No tickers in lowercase
- [ ] No sentences containing "may represent," "could potentially," or "might be worth"

- [ ] **Step 2: Test Earnings Preview**

Invoke the skill with:
> `/buy-side-note earnings preview for NVDA heading into Q2 FY2027 results`

Check output:
- [ ] Implied move stated with source
- [ ] Short interest stated with source
- [ ] At least 2 key debates, each with Bull / Bear / Watch structure
- [ ] Numbers to Watch table has Beat and Miss thresholds for each metric
- [ ] Tradeable Expression section states specific entry, sizing, and time horizon
- [ ] TIME-SENSITIVE FLAGS present

- [ ] **Step 3: Test Single-Stock Deep Dive**

Invoke the skill with:
> `/buy-side-note full deep dive on ALAB`

Check output:
- [ ] Business frame names specific revenue segments with %
- [ ] Competitive position names 2–3 specific competitor companies
- [ ] Financials table has at least 2 years of data
- [ ] Valuation table compares to named peers (not "sector average")
- [ ] THE DEBATE section has distinct bull and bear theses with data anchors, plus a View that takes a side
- [ ] Catalyst calendar names 3 events with approximate dates
- [ ] TIME-SENSITIVE FLAGS present

- [ ] **Step 4: Fix any structural failures**

If any checklist item fails, identify which section of skill.md produced the gap and correct it. Re-run the affected note type after fixing.

- [ ] **Step 5: Final commit**

```powershell
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" add -A
git -C "$env:USERPROFILE\.claude\plugins\buy-side-research" commit -m "chore: validation complete, buy-side-research plugin v1.0 ready"
```

---

## Self-Review Notes

**Spec coverage check:**
- Stage 1 (classify) → Task 2 ✓
- Stage 2 (research, all 5 checklists) → Task 2 ✓
- Stage 3 (write, all 5 templates) → Task 3 ✓
- Stage 4 (render: charts + PDF) → Task 3 ✓
- Voice rules → Task 3 ✓
- Standalone templates (all 5) → Tasks 4–7 ✓
- PDF style (standard clean) → Task 3 Stage 4 instructions ✓
- Chart specs per note type → Task 3 Stage 4 table ✓
- package.json plugin scaffold → Task 1 ✓

**Placeholder scan:** No TBDs or incomplete steps. All steps contain actual file content or specific commands with expected output.

**Type consistency:** Templates use consistent field names throughout (THESIS / CATALYST / BENEFICIARIES / POSITIONING in thematic; Debate 1/2/3 structure in preview/flash). Stage 4 render instructions reference `anthropic-skills:canvas-design` and `anthropic-skills:pdf` consistently.
