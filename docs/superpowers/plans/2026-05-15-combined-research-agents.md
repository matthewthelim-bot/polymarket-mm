# Combined Research Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy two new agent suites: (1) the research-debate plugin (short-thesis, devils-advocate, research-debate orchestrator) and (2) enhance buy-side-note with probability-weighted scenario analysis, sensitivity tables, and trade construction across all five note types.

**Architecture:** Research-debate adds three new skill files and registers one new slash command. Buy-side-note enhancement is a single in-place edit of the existing skill.md, adding asset detection to Stage 1, new research items to Stage 2, five new write sections to Stage 3, and one new chart per note type to Stage 4.

**Tech Stack:** Markdown skill files, Claude Code Agent tool for sub-agent dispatch, `anthropic-skills:pdf`, `anthropic-skills:canvas-design`.

---

## File Map

```
~/.claude/plugins/buy-side-research/
  package.json                                    ← MODIFY: add research-debate entry
  skills/
    buy-side-note/skill.md                        ← MODIFY: asset detection + 5 new Stage 3 sections + Stage 2 additions + Stage 4 chart update
    short-thesis/skill.md                         ← CREATE
    devils-advocate/skill.md                      ← CREATE
    research-debate/skill.md                      ← CREATE

~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/
  package.json                                    ← SYNC after Task 4
  skills/
    buy-side-note/skill.md                        ← SYNC after Task 9
    short-thesis/skill.md                         ← SYNC after Task 1
    devils-advocate/skill.md                      ← SYNC after Task 2
    research-debate/skill.md                      ← SYNC after Task 3
```

---

### Task 1: Short Thesis Skill File

**Files:**
- Create: `~/.claude/plugins/buy-side-research/skills/short-thesis/skill.md`
- Sync: `~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/short-thesis/skill.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p ~/.claude/plugins/buy-side-research/skills/short-thesis
```

- [ ] **Step 2: Write the skill file**

Create `~/.claude/plugins/buy-side-research/skills/short-thesis/skill.md` with exactly this content:

````markdown
---
name: short-thesis
description: Write a short analyst thesis on a stock, theme, or sector. Sub-agent persona used by research-debate. Adversarial bear perspective with sourced evidence.
---

# Short Analyst — Thesis Writer

You are a dedicated short-side analyst. You have a position. Your job is to make the strongest possible case that the consensus bull thesis on [SUBJECT] is wrong. You are not balanced. You are adversarial-but-sourced.

You are operating as a sub-agent. Your only output is the completed short thesis in markdown. Do not ask clarifying questions. Do not produce a PDF. Return markdown when finished.

---

## RESEARCH PHASE

Run web searches to build the bear case. Maintain a gap log as you go:
- Data found with source → record as `[source, date]`
- Only one source found → prefix claim with `Single source —`
- No usable data found → mark item `[UNFOUND]`
- Estimate without hard confirmation → mark `[DIRECTIONAL ESTIMATE]`

Do not fabricate data to fill gaps.

Search for each of the following:

1. **Bull case assumptions** — Search: "[subject] bull case thesis consensus 2025 2026", "[subject] buy rating analyst price target". Extract: what multiple expansion, revenue growth, or margin improvement the bull case requires. These are your targets.

2. **Structural headwinds** — Search: "[subject] risks headwinds 2025 2026", "[subject] competition threat market share loss". Look for: regulatory exposure, competitive dynamics, secular declines, or cost structure problems the consensus minimises.

3. **Selective data / omitted data** — Search: "[subject] revenue decline margin compression 2025", "[subject] customer concentration churn". Look for: trends the bull note would omit — narrowing cohorts, slowing growth in core segments, rising capex vs. falling returns.

4. **Short catalysts** — Search: "[subject] earnings risk catalyst 2026", "[subject] contract expiry regulatory risk lock-up expiry". Find three specific, dated events that would force a negative reprice.

5. **Who is short and why** — Search: "[subject] short seller report 2025 2026", "[subject] short interest rising". Record: any named short sellers, their stated thesis, short % of float trend.

6. **Bear-case valuation** — Search: "[subject] bear case valuation downside scenario". If unavailable, build a simple bear case: apply a multiple compression scenario and state the implied price.

---

## WRITE PHASE

Write the short thesis using this exact structure. Do not add sections. Do not remove sections.

```
SHORT THESIS — [SUBJECT IN ALL CAPS]
[Date]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. THE CASE IN ONE LINE

[One sentence. Any PM should be able to repeat it verbatim.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2. WHAT THE BULLS ARE MISSING

Assumption A: [Name the assumption] — [Dispute it with a specific number or named fact]
Assumption B: [Name the assumption] — [Dispute it with a specific number or named fact]
Assumption C: [Name the assumption] — [Dispute it with a specific number or named fact]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3. THE DATA THEY'RE NOT SHOWING YOU

[3–5 bullet points. Specific numbers, comparisons, or trends omitted from the consensus view.
Each bullet: [data point] — [source, date] — [why it matters for the bear case]]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

4. SHORT CATALYSTS

Catalyst 1: [Name] — [Date or expected window] — [What happens to the thesis if this prints]
Catalyst 2: [Name] — [Date or expected window] — [What happens to the thesis if this prints]
Catalyst 3: [Name] — [Date or expected window] — [What happens to the thesis if this prints]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

5. WHAT WOULD MAKE ME COVER

[3 explicit conditions. Each must be falsifiable — a named event, a specific print, or a
price level that would invalidate this thesis. Format: "Cover if [named condition]."]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

6. PRICE TARGET / DOWNSIDE SCENARIO

Bear-case price target: $[X] ([Y]% downside)
Method: [valuation approach]
Key assumptions: [2–3 stated assumptions]

[If bear-case valuation data is [UNFOUND]: state it explicitly and provide a directional
estimate with stated assumptions, prefixed DIRECTIONAL ESTIMATE:]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOW-CONFIDENCE FLAGS

[One bullet per [UNFOUND] or [DIRECTIONAL ESTIMATE] item from the research phase.
If all items confirmed, state: "All data points confirmed with sources."]
```

---

## VOICE RULES

1. **Adversarial but sourced.** Every claim needs a number or a named fact.
2. **No weasel words.** "Could", "might", "potentially", "may" are banned.
3. **Opinions are stated as opinions, not hedged as possibilities.**
4. **ALL-CAPS tickers throughout.**
5. **Gap-log protocol.** Every research gap flows into LOW-CONFIDENCE FLAGS.
````

- [ ] **Step 3: Validate frontmatter**

```bash
head -5 ~/.claude/plugins/buy-side-research/skills/short-thesis/skill.md
```

Expected:
```
---
name: short-thesis
description: Write a short analyst thesis on a stock, theme, or sector. Sub-agent persona used by research-debate. Adversarial bear perspective with sourced evidence.
---
```

- [ ] **Step 4: Sync to cache and verify**

```bash
mkdir -p ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/short-thesis
cp ~/.claude/plugins/buy-side-research/skills/short-thesis/skill.md \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/short-thesis/skill.md
diff ~/.claude/plugins/buy-side-research/skills/short-thesis/skill.md \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/short-thesis/skill.md
```

Expected: no output (files identical)

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add skills/short-thesis/skill.md
git commit -m "feat: add short-thesis sub-agent skill"
```

---

### Task 2: Devil's Advocate Skill File

**Files:**
- Create: `~/.claude/plugins/buy-side-research/skills/devils-advocate/skill.md`
- Sync: `~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/devils-advocate/skill.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p ~/.claude/plugins/buy-side-research/skills/devils-advocate
```

- [ ] **Step 2: Write the skill file**

Create `~/.claude/plugins/buy-side-research/skills/devils-advocate/skill.md` with exactly this content:

````markdown
---
name: devils-advocate
description: Synthesise a bull note and short thesis into a one-page "State of the Debate." Sub-agent persona used by research-debate. Has no position — referee only.
---

# Devil's Advocate — Debate Synthesiser

You have no position. You are a referee, not a participant. You will receive two documents: a bull research note and a short thesis on the same subject. Read both in full. Your job is to find where both sides are overconfident, surface the questions neither answered, and deliver a verdict on which side has the structurally stronger argument.

You are operating as a sub-agent. Your only output is the "State of the Debate" section in markdown. Maximum one page. Do not ask clarifying questions. Do not produce a PDF. Return markdown when finished.

---

## YOUR MANDATE

Before writing, work through these questions internally:

1. **Core disagreement** — What is the fundamental underlying assumption the two sides actually disagree on? Not the surface claims — the deeper structural assumption.

2. **Unresolved questions** — What are the three most consequential questions that, if answered, would resolve the debate? Neither side has answered them.

3. **Shared data, opposite conclusions** — Is either side using the same data points to reach opposite conclusions? Why is that possible?

4. **Empirically unverifiable claims** — Did either side make claims that cannot currently be verified? Flag as "we cannot know," not "we disagree."

5. **Blind spots** — What is the single biggest risk the bull case ignored? The bear case ignored? Not the stated risks — the unstated ones.

6. **Verdict** — Which side has the structurally stronger argument? Strong argument = internally consistent, grounded in verifiable data, falsifiable thesis, explicit assumptions.

---

## WRITE PHASE

Write the State of the Debate using this exact structure. Maximum one page.

```
STATE OF THE DEBATE — [SUBJECT IN ALL CAPS]
[Date]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. CORE DISAGREEMENT

[One paragraph. Name the fundamental underlying assumption — not the surface claims.
What does each side believe to be true that the other denies? Be specific.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2. THREE OPEN QUESTIONS

Q1: [Specific, answerable question. Neither side has answered it.]
Q2: [Specific, answerable question. Neither side has answered it.]
Q3: [Specific, answerable question. Neither side has answered it.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3. WHERE BOTH SIDES HAVE BLIND SPOTS

Bull blind spot: [One named risk or assumption the bull case does not address.]
Bear blind spot: [One named risk or assumption the bear case does not address.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

4. VERDICT

Stronger structural argument: [BULL / BEAR]

[2–3 sentences. State which side and why — not who will be right, but whose argument
is better constructed. Written as a recommendation to a PM: "Spend time on this if X.
Pass if Y."]

[If unresolvable with available public information: "This debate cannot be resolved
with available information. It would require [named data or event]."]
```

---

## VOICE RULES

1. **No position, no hedging.** State which side is structurally stronger and why.
2. **"It depends" is banned** unless immediately completed: "It depends on whether [specific condition]."
3. **Unresolvable is a valid verdict.** Name what would resolve it.
4. **One page maximum.** Every sentence must earn its place.
````

- [ ] **Step 3: Validate frontmatter**

```bash
head -5 ~/.claude/plugins/buy-side-research/skills/devils-advocate/skill.md
```

Expected:
```
---
name: devils-advocate
description: Synthesise a bull note and short thesis into a one-page "State of the Debate." Sub-agent persona used by research-debate. Has no position — referee only.
---
```

- [ ] **Step 4: Sync to cache and verify**

```bash
mkdir -p ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/devils-advocate
cp ~/.claude/plugins/buy-side-research/skills/devils-advocate/skill.md \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/devils-advocate/skill.md
diff ~/.claude/plugins/buy-side-research/skills/devils-advocate/skill.md \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/devils-advocate/skill.md
```

Expected: no output

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add skills/devils-advocate/skill.md
git commit -m "feat: add devils-advocate sub-agent skill"
```

---

### Task 3: Research Debate Orchestrator Skill File

**Files:**
- Create: `~/.claude/plugins/buy-side-research/skills/research-debate/skill.md`
- Sync: `~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/research-debate/skill.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p ~/.claude/plugins/buy-side-research/skills/research-debate
```

- [ ] **Step 2: Write the skill file**

Create `~/.claude/plugins/buy-side-research/skills/research-debate/skill.md` with exactly this content:

````markdown
---
name: research-debate
description: Run a full investment debate on a stock, theme, or sector. Dispatches a bull analyst and short analyst in parallel, synthesises with a devil's advocate, and assembles a single combined PDF. Use when asked to debate, stress-test, or get both sides on any investment topic.
---

# Research Debate Orchestrator

You are an orchestrator. Your job is to coordinate three sub-agents and assemble their outputs into a single combined document. You do not write the research — your sub-agents do. You classify, dispatch, collect, and assemble.

**Invocation examples:**
- `/research-debate NVDA Q2 earnings`
- `/research-debate thematic rotation after HBM`
- `/research-debate US defense sector`
- `/research-debate deep dive on ALAB`

Run the four stages below in sequence. Announce each stage transition to the user.

---

## STAGE 1 — CLASSIFY

Parse the user's request for:
- **Subject** — ticker(s), theme name, or sector
- **Note type** — determines how sub-agents frame their research

| User language | Note type |
|---|---|
| "thematic rotation", "after X", "next theme", "rotation note" | Thematic Rotation |
| "earnings preview", "pre-earnings", "into the print", "preview" | Earnings Preview |
| "earnings flash", "post-earnings", "after the print", "flash" | Earnings Flash |
| "deep dive", "full analysis", "initiate", "single stock" | Single-Stock Deep Dive |
| "sector", "industry" | Sector Analysis |

If subject or note type is ambiguous, ask exactly one clarifying question. Do not begin dispatch until both are confirmed.

Announce: **"Identified: [note type] on [subject]. Dispatching bull and bear agents in parallel — this will take several minutes."**

---

## STAGE 2 — PARALLEL DISPATCH

Use the Agent tool to spawn two sub-agents simultaneously. Dispatch both in the same tool call batch.

**Bull sub-agent prompt:**

```
You are an institutional buy-side analyst writing a [NOTE TYPE] on [SUBJECT].

Run through Stages 1–3 of the buy-side-note skill: classify, research, and write.
DO NOT render a PDF. DO NOT invoke anthropic-skills:pdf or anthropic-skills:canvas-design.
Return the completed research note as markdown only.

Use the full research checklist and write template for [NOTE TYPE] from the buy-side-note skill.
Apply all voice rules. Include TIME-SENSITIVE FLAGS populated from your gap log.

When done, return ONLY the markdown document with no preamble.
```

**Bear sub-agent prompt:**

```
You are a short-side analyst writing a short thesis on [SUBJECT].

Follow the short-thesis skill: research the bear case independently, then write the short thesis.
You have no visibility into any bull research on this subject — do not reference or assume what
a bull analyst might say. Build your case from your own research only.

Return the completed short thesis as markdown only. Do not produce a PDF.

When done, return ONLY the markdown document with no preamble.
```

**Wait for both agents to complete.** If either agent returns an error or an empty response, announce the failure, report what succeeded, and halt. Do not attempt partial assembly.

Announce on completion: **"Both sides complete. Running devil's advocate synthesis."**

---

## STAGE 3 — DEVIL'S ADVOCATE SYNTHESIS

Use the Agent tool to spawn the devil's advocate sub-agent. Pass both completed documents.

**Devil's advocate sub-agent prompt:**

```
You are the devil's advocate synthesiser. You have no position.

You have received two documents on [SUBJECT]:

---BULL CASE---
[INSERT FULL BULL MARKDOWN HERE]
---END BULL CASE---

---BEAR CASE---
[INSERT FULL BEAR MARKDOWN HERE]
---END BEAR CASE---

Follow the devils-advocate skill: read both documents in full, work through your mandate
questions internally, then write the State of the Debate using the exact four-section
structure from the skill (CORE DISAGREEMENT, THREE OPEN QUESTIONS, WHERE BOTH SIDES HAVE
BLIND SPOTS, VERDICT).

Maximum one page. Return ONLY the markdown State of the Debate with no preamble.
```

Wait for the devil's advocate to complete.

Announce: **"Synthesis complete. Assembling final document."**

---

## STAGE 4 — ASSEMBLE AND RENDER

Assemble the combined document in this exact order:

```markdown
# RESEARCH DEBATE — [SUBJECT IN ALL CAPS]
[Today's date]

**Contents:** State of the Debate · Bull Case · Bear Case

---

## STATE OF THE DEBATE

[Devil's advocate output — full text]

---

---

# BULL CASE

[Full bull markdown — complete, unedited]

---

---

# BEAR CASE

[Full bear markdown — complete, unedited]
```

Do not edit, summarise, or shorten any of the three documents. Insert them verbatim.

**File naming:** `[subject-slug]-debate-[YYYY-MM-DD].pdf`
- Subject slug: lowercase, hyphens for spaces, no special characters
- Example: `nvda-q2-earnings-debate-2026-05-15.pdf`

**Render to PDF:** Invoke `anthropic-skills:pdf` with the following styling:
- Font: clean sans-serif (Inter, Helvetica, or system default), 10–11pt body
- Section headers: bold, clearly delineated with spacing
- Tables: light 1pt borders, alternating row shading (#F7F7F7 / white)
- Callout boxes: light gray border, slightly indented
- Section dividers between the three documents: bold full-width horizontal rule with section name centred
- Cover page: Title "Research Debate — [Subject]", date, contents list

Announce on completion: **"Debate complete. PDF saved as [filename]."**
````

- [ ] **Step 3: Validate all four stage headers exist**

```bash
grep "^## STAGE" ~/.claude/plugins/buy-side-research/skills/research-debate/skill.md
```

Expected:
```
## STAGE 1 — CLASSIFY
## STAGE 2 — PARALLEL DISPATCH
## STAGE 3 — DEVIL'S ADVOCATE SYNTHESIS
## STAGE 4 — ASSEMBLE AND RENDER
```

- [ ] **Step 4: Sync to cache and verify**

```bash
mkdir -p ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/research-debate
cp ~/.claude/plugins/buy-side-research/skills/research-debate/skill.md \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/research-debate/skill.md
diff ~/.claude/plugins/buy-side-research/skills/research-debate/skill.md \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/research-debate/skill.md
```

Expected: no output

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add skills/research-debate/skill.md
git commit -m "feat: add research-debate orchestrator skill"
```

---

### Task 4: Register research-debate in package.json

**Files:**
- Modify: `~/.claude/plugins/buy-side-research/package.json`
- Sync: `~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/package.json`

- [ ] **Step 1: Overwrite package.json**

Write `~/.claude/plugins/buy-side-research/package.json` with exactly this content:

```json
{
  "name": "buy-side-research",
  "version": "1.1.0",
  "description": "Institutional buy-side research note generator — thematic rotation, earnings, single-stock, sector analysis, and structured debate",
  "skills": [
    {
      "name": "buy-side-note",
      "path": "skills/buy-side-note/skill.md",
      "description": "Generate institutional buy-side research notes with charts and PDF output. Supports: thematic rotation, earnings preview, earnings flash, single-stock deep dive, sector analysis."
    },
    {
      "name": "research-debate",
      "path": "skills/research-debate/skill.md",
      "description": "Run a full investment debate on any stock, theme, or sector. Bull analyst and short analyst run in parallel; devil's advocate synthesises both. Outputs a combined PDF with State of the Debate, Bull Case, and Bear Case."
    }
  ]
}
```

- [ ] **Step 2: Validate JSON and skill list**

```bash
cat ~/.claude/plugins/buy-side-research/package.json | python3 -m json.tool > /dev/null && echo "Valid JSON"
cat ~/.claude/plugins/buy-side-research/package.json | python3 -c "import sys,json; d=json.load(sys.stdin); print([s['name'] for s in d['skills']])"
```

Expected:
```
Valid JSON
['buy-side-note', 'research-debate']
```

- [ ] **Step 3: Sync to cache and verify**

```bash
cp ~/.claude/plugins/buy-side-research/package.json \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/package.json
diff ~/.claude/plugins/buy-side-research/package.json \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/package.json
```

Expected: no output

- [ ] **Step 4: Verify all four skill directories exist in cache**

```bash
ls ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/
```

Expected:
```
buy-side-note  devils-advocate  research-debate  short-thesis
```

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add package.json
git commit -m "feat: register research-debate slash command, bump to v1.1.0"
```

---

### Task 5: buy-side-note — Stage 1 Asset Detection

**Files:**
- Modify: `~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md`

This task inserts one new block into Stage 1, immediately after the existing announce line.

- [ ] **Step 1: Locate the insertion point**

Find this exact text in the file:
```
Announce: **"Identified: [note type] on [subject]. Beginning research phase."**
```

- [ ] **Step 2: Insert asset detection block immediately after that line**

After the announce line and before the `---` separator that opens Stage 2, insert:

```markdown

**ASSET TYPE DETECTION**

Before beginning research, classify the subject as EQUITY or CRYPTO:

| Signal | Classification |
|---|---|
| Ticker: 1–5 uppercase letters, no numeric suffix (NVDA, MSFT, ALAB, JPM) | EQUITY |
| Token name or ticker with on-chain context; or "token", "protocol", "on-chain", "DEX", "L1", "L2" in subject | CRYPTO |
| Ambiguous (sector note, theme, no single asset) | EQUITY (default) — trade structures use basket/ETF instruments only |

Announce: **"Asset type: [EQUITY / CRYPTO]. Trade construction will use [equity / crypto-native] instrument vocabulary."**

Store this classification. It is referenced in Stage 3 trade construction. No other stage behaviour changes based on asset type.
```

- [ ] **Step 3: Verify the announce line and asset detection block appear in sequence**

```bash
grep -A 20 "Beginning research phase" ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md | head -25
```

Expected: the announce line followed immediately by the "ASSET TYPE DETECTION" header.

- [ ] **Step 4: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add skills/buy-side-note/skill.md
git commit -m "feat: add asset detection (equity/crypto) to buy-side-note Stage 1"
```

---

### Task 6: buy-side-note — Stage 2 Research Additions

**Files:**
- Modify: `~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md`

Append new research items to each of the five note type checklists, and add a universal block after all five checklists. The additions go after the last numbered item in each checklist, before the `---` separator.

- [ ] **Step 1: Add universal research additions block**

Find this exact text (the end of the Sector Analysis checklist, last item before Stage 3):
```
6. **Stock selection** — Search: "[sector] best stocks 2026 buy-side", "[sector] undervalued under-owned 2026", "[sector] avoid overvalued crowded 2026". Identify top 3 long ideas and 1 avoid with positioning rationale.
```

After that line and before `---`, insert:

```markdown

---

### Universal Stage 2 Additions — All Note Types

After completing the note-type-specific checklist above, run these additional research items for every note type:

**Comps research:**
Search: "[subject] comparable companies peers valuation multiples 2025 2026"
- EQUITY: EV/Revenue, EV/EBITDA, P/E, P/S vs. 3–5 named peers. Record median and high/low range.
- CRYPTO: P/S on circulating market cap and FDV vs. 3–5 named comparable protocols. Record median and range.
- Gap-log: if fewer than 3 comps found, mark `[DIRECTIONAL ESTIMATE]` on median.

**Scenario parameters:**
Search: "[subject] bear case bull case analyst targets 2026"
- Extract: what the street's bear assumes (specific — low growth rate %, margin level %, market share %)
- Extract: what the street's bull assumes (specific — acceleration rate, expansion scenario, new revenue stream name)
- These anchor the 3-way scenario model in Stage 3.

**Probability weights (research-derived — do not use fixed defaults):**
Derive from evidence:
- Positioning signal: crowded consensus → elevated bear probability (35–45%)
- Catalyst proximity: near-term binary event → compress base probability, widen bear/bull spread
- Regulatory environment: active enforcement risk → elevated bear probability
- Probabilities must sum to 100%. State one-sentence reasoning for each weight.

**Note-type-specific valuation research:**

*Thematic Rotation:*
- Search: "[outgoing theme] historical rotation duration weeks drawdown". Record: how long prior analogous rotations ran, typical drawdown in outgoing theme during transition.
- Search: "[candidate themes] basket P/S vs. prior rotation entry". Record: whether candidates are cheap or expensive vs. prior rotation entry points.
- Search: "ETF flows [candidate themes] momentum 2026". Record: flow direction and magnitude as rotation signal.

*Earnings Preview:*
- Search: "[TICKER] historical earnings beat miss rate 2023 2024 2025". Record: beat/miss on EPS and revenue last 8 quarters. Compute beat rate %.
- Search: "[TICKER] options straddle implied move earnings 2026". Record: ATM straddle cost as % of stock. Mark [UNFOUND] if unavailable.
- Search: "[TICKER] historical implied vs actual move earnings". Record: whether stock historically over- or under-moves vs. implied.

*Earnings Flash:*
- Search: "[TICKER] prior quarter guidance [metric]". Record: what management guided for the just-reported quarter.
- Search: "[TICKER] earnings estimate revisions [date]". Record: direction and magnitude of post-print revisions.
- Note: if no prior scenario framework exists (first time on this ticker), build baseline from reported results only.

*Single-Stock Deep Dive:*
- Search: "[TICKER] revenue growth forecast 2026 2027 2028". Record: 3-year revenue CAGR estimate.
- Search: "[TICKER] operating margin EBITDA margin forecast". Record: margin trajectory over 3 years.
- For EQUITY: derive WACC from beta, risk-free rate (~4.3%), market premium (~5.5%). For CRYPTO: use 25% base WACC, state component risk premiums (regulatory, illiquidity, smart contract).
- EQUITY only: Search: "[TICKER] M&A precedent transactions comparable acquisition multiples".
- CRYPTO only: Search: "[subject] tokenomics buyback yield staking APR unlock schedule vesting".

*Sector Analysis:*
- Search: "[sector] P/E forward 5-year historical average standard deviation". Record: current vs. mean and σ.
- Search: "[sector] factor exposure value growth quality tilt 2026". Record: dominant factor and whether in/out of favour.
- Search: "[sector] sub-sector relative performance YTD 2026". Record: leading and lagging sub-sectors.

**Sensitivity variable identification (all note types):**
At end of all research, identify the 2 variables that most drive fair value for this subject. Record as:
"Sensitivity axes: [Variable A] × [Variable B]"

Examples by type:
- Thematic Rotation: rotation speed (weeks) × basket entry P/S
- Earnings Preview: EPS beat magnitude × forward P/E re-rating
- Earnings Flash: estimate revision % × multiple change
- Single-Stock EQUITY: revenue growth CAGR × exit EV/Revenue multiple
- Single-Stock CRYPTO: market share % × token net supply inflation
- Sector: forward P/E × earnings growth CAGR
```

- [ ] **Step 2: Also append checklist-specific additions to each note type checklist**

For each of the five checklists, append the note-type-specific comps and valuation search items listed above as additional numbered items. This ensures they appear in context within each checklist, not only in the universal block.

Find the end of the **Thematic Rotation checklist** (after item 5 "Leading indicators...") and append:

```markdown

7. **Basket comps** — Search: "[candidate themes] comparable rotation basket P/S 2025". For each candidate theme, find analogous prior rotation basket entry valuation. Mark [DIRECTIONAL ESTIMATE] if fewer than 2 comparable rotations found.

8. **ETF flow data** — Search: "[candidate themes ETF tickers] AUM flow momentum 2026". Record monthly AUM change direction and magnitude.

9. **Historical rotation duration** — Search: "[outgoing theme] rotation duration 2019 2020 2021 analogous". Record: how long comparable rotations took from crowding signal to new theme dominance (in weeks/months).
```

Find the end of the **Earnings Preview checklist** (after item 6 "Peer reporting calendar...") and append:

```markdown

7. **Historical beat/miss rate** — Search: "[TICKER] earnings beat miss history 2023 2024 2025 quarterly". Record: beat/miss on EPS and revenue for last 8 quarters. Compute: beat rate on EPS (%), average beat magnitude ($).

8. **Implied vs. actual move history** — Search: "[TICKER] implied move vs actual move earnings history". Record: does this stock historically over- or under-move vs. options-implied? By how much on average?
```

Find the end of the **Earnings Flash checklist** (after item 5 "Peer read-across...") and append:

```markdown

6. **Post-print estimate revisions** — Search: "[TICKER] estimate revision [current date] EPS revenue 2026". Record: direction and magnitude of first-wave analyst revisions following the print.

7. **Prior scenario check** — If a prior Earnings Preview was written for this ticker, note which scenario (bear/base/bull) the reported results most closely match.
```

Find the end of the **Single-Stock Deep Dive checklist** (after item 6 "Catalyst calendar...") and append:

```markdown

7. **DCF inputs** — Search: "[TICKER] revenue growth 2026 2027 2028 consensus", "[TICKER] operating margin expansion forecast". Record: 3-year revenue CAGR, margin trajectory. For EQUITY: derive WACC from beta and market inputs. For CRYPTO: use 25% base WACC with stated component premiums.

8. **Third valuation lens** — EQUITY: Search: "[TICKER] M&A comparable transactions acquisition premium EV/Revenue". Record: comparable deal multiples and implied premium. CRYPTO: Search: "[subject] tokenomics buyback program staking APR unlock vesting schedule". Record: buyback yield on market cap, staking APR, net annual supply change.
```

Find the end of the **Sector Analysis checklist** (after item 6 "Stock selection...") and append:

```markdown

7. **Sector valuation vs. history** — Search: "[sector] forward P/E 5-year historical mean standard deviation". Record: current multiple, 5-year mean, premium/discount in % and σ terms.

8. **Factor tilt** — Search: "[sector] factor exposure value growth quality momentum 2026". Record: dominant factor tilt and whether that factor is in or out of favour in the current macro regime.

9. **Sub-sector catch-up** — Search: "[sector] sub-sector relative performance YTD 2026 leading lagging". Record: YTD gap between leading and lagging sub-sectors in percentage points.
```

- [ ] **Step 3: Verify all five checklists have at least 7 items**

```bash
grep -c "^\d\." ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md
```

Expected: at least 40 (5 checklists × ~8 items each = ~40+)

- [ ] **Step 4: Verify universal additions block exists**

```bash
grep "Universal Stage 2 Additions" ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md
```

Expected: `### Universal Stage 2 Additions — All Note Types`

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add skills/buy-side-note/skill.md
git commit -m "feat: add Stage 2 valuation/scenario/comps research items to buy-side-note"
```

---

### Task 7: buy-side-note — Stage 3 Sections A (Valuation) and B (Scenario Analysis)

**Files:**
- Modify: `~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md`

Insert two new sections (VALUATION and SCENARIO ANALYSIS) into each of the five note type write templates, immediately before each template's `TIME-SENSITIVE FLAGS` section.

The insertion marker for each template is the text `TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS` within that template's code block.

- [ ] **Step 1: Insert into Thematic Rotation template**

Find inside the Thematic Rotation template code block:
```
TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
```

Insert immediately before it:

```
VAL — VALUATION

Method 1 — Basket P/S vs. prior rotation entry valuations ([X]% weight):
Basket average P/S: [X]x. Prior rotation analogues (name them): entered at [X]x avg.
Current basket is [expensive/cheap/in-line] vs. prior rotation entry. [source, date]

Method 2 — ETF flow momentum implied return ([X]% weight):
ETF AUM trend: [X]% monthly inflow. At current P/S, a re-rating to [X]x on [X]% AUM
growth implies [X]% return over [X] months. [source, date]

Method 3 — Historical rotation duration × entry timing ([X]% weight):
Prior analogous rotations ran [X]–[X] months. Current rotation appears [early/mid/late]
cycle based on [evidence]. Time-weighted return at duration midpoint: [X]%.

Methodology weights: Method 1 [X]% · Method 2 [X]% · Method 3 [X]%
Weight rationale: [one sentence]

Blended fair value: [X]x P/S implied for basket (range: [X]x – [X]x)
Top theme implied return (1 year): +/–[X]%

---

SCENARIOS — SCENARIO ANALYSIS

Bear ([X]%): [2 named conditions e.g. "Rotation stalls — outgoing theme P/E re-rates to [X]x as earnings miss consensus; candidate themes fail to attract ETF inflows above $[X]M/month"]
Base ([X]%): [2 named conditions e.g. "Rotation plays out over [X] weeks; basket re-rates from [X]x to [X]x P/S as first earnings catalysts confirm theme"]
Bull ([X]%): [2 named conditions e.g. "Rotation accelerates — macro regime shift pulls [X]% of institutional flows into basket within [X] months"]

                BEAR ([X]%)    BASE ([X]%)    BULL ([X]%)    BLENDED FV    vs. SPOT
1 Month         [X]% return    [X]% return    [X]% return    [X]% return   [+/-X]%
3 Months        [X]% return    [X]% return    [X]% return    [X]% return   [+/-X]%
6 Months        [X]% return    [X]% return    [X]% return    [X]% return   [+/-X]%
1 Year          [X]% return    [X]% return    [X]% return    [X]% return   [+/-X]%

Blended = (Bear × bear prob) + (Base × base prob) + (Bull × bull prob).

---

```

- [ ] **Step 2: Insert into Earnings Preview template**

Find inside the Earnings Preview template code block:
```
TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
```

Insert immediately before it:

```
VAL — VALUATION

Method 1 — Options-implied move pricing ([X]% weight):
ATM straddle: [X]% of stock (annualised: [X]%). [source, date. If [UNFOUND]: flag.]
Beat scenario re-rates to [X]x P/E → FV $[X]. Miss compresses to [X]x → FV $[X].

Method 2 — Historical beat/miss adjusted EPS × forward P/E ([X]% weight):
Beat rate: [X]% on EPS last 8 quarters. Avg beat magnitude: [X]%.
Adjusted consensus EPS assuming beat: $[X]. At [X]x P/E: FV $[X].
At miss (–[X]%): EPS $[X]. At [X]x: FV $[X].

Method 3 — P/E re-rating scenarios ([X]% weight):
Beat + raised guidance → multiple expands to [X]x → FV $[X].
In-line + maintained → holds at [X]x → FV $[X].
Miss + guidance cut → compresses to [X]x → FV $[X].

Methodology weights: Method 1 [X]% · Method 2 [X]% · Method 3 [X]%
Weight rationale: [one sentence]

Blended fair value: $[X] (range: $[X] – $[X])
vs. current spot: +/–[X]%

---

SCENARIOS — SCENARIO ANALYSIS

Bear ([X]%): Miss on EPS ([X]% below consensus) AND revenue ([X]% below). Guide cut: [X]% below street for next Q. Named condition: [what specifically drives the miss]
Base ([X]%): In-line EPS (±[X]%) and revenue (±[X]%). Guidance maintained within [X]% of street.
Bull ([X]%): Beat EPS by [X]%+ AND revenue by [X]%+. Raised guidance: [X]% above street for next Q.

              BEAR ([X]%)    BASE ([X]%)    BULL ([X]%)    BLENDED FV    vs. SPOT
1 Month       $[X]           $[X]           $[X]           $[X]          +/–[X]%
3 Months      $[X]           $[X]           $[X]           $[X]          +/–[X]%
6 Months      $[X]           $[X]           $[X]           $[X]          +/–[X]%
1 Year        $[X]           $[X]           $[X]           $[X]          +/–[X]%

---

```

- [ ] **Step 3: Insert into Earnings Flash template**

Find inside the Earnings Flash template code block:
```
TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
```

Insert immediately before it:

```
VAL — VALUATION

Method 1 — Reported vs. prior scenario framework ([X]% weight):
[Prior scenarios: bear $[X] / base $[X] / bull $[X]. The [bear/base/bull] scenario has printed.
Updated FV given what reported: $[X]. If no prior framework: revenue run-rate $[X]M × [X]x fwd multiple = $[X].]

Method 2 — Post-print estimate revision implied FV ([X]% weight):
Estimates revised [up/down] by [X]% EPS, [X]% revenue. At [X]x current multiple
on revised estimates: FV $[X]. [source, date]

Method 3 — Guidance change implied re-rating ([X]% weight):
Guidance [raised/maintained/cut]. Historical multiple change on same guidance action: [X]x move.
Applied to current [X]x multiple: new implied multiple [X]x → FV $[X].

Methodology weights: Method 1 [X]% · Method 2 [X]% · Method 3 [X]%
Weight rationale: [one sentence]

Blended fair value (updated): $[X] (range: $[X] – $[X])
vs. current spot: +/–[X]%

---

SCENARIOS — SCENARIO ANALYSIS

Bear ([X]%): Results worse than they look — guide-down embedded in Q+1 setup. [Named condition that triggers further compression.]
Base ([X]%): Results at face value. Estimates revised [X]%. Stock settles near print reaction level.
Bull ([X]%): Hidden beat — [named metric] better than it appears. Upgrades incoming from [X] analysts.

              BEAR ([X]%)    BASE ([X]%)    BULL ([X]%)    BLENDED FV    vs. SPOT
1 Month       $[X]           $[X]           $[X]           $[X]          +/–[X]%
3 Months      $[X]           $[X]           $[X]           $[X]          +/–[X]%
6 Months      $[X]           $[X]           $[X]           $[X]          +/–[X]%
1 Year        $[X]           $[X]           $[X]           $[X]          +/–[X]%

---

```

- [ ] **Step 4: Insert into Single-Stock Deep Dive template**

Find inside the Single-Stock Deep Dive template code block:
```
TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
```

Insert immediately before it:

```
VAL-DEEP — VALUATION (THREE METHODOLOGIES)

Method 1 — DCF ([X]% weight):
Revenue: $[X]B ([YEAR]) → $[X]B ([YEAR+4]) at [X]% CAGR.
Operating margin: [X]% → [X]% by [YEAR+4].
EQUITY — WACC: [X]% (beta [X]x, risk-free [X]%, market premium [X]%).
CRYPTO — WACC: 25% (regulatory [X]%, illiquidity [X]%, smart contract [X]%).
Terminal multiple: [X]x [EBITDA/Revenue].
Enterprise value: $[X]B → $[X] per share/token (circulating).

Method 2 — Comps ([X]% weight):
Peers: [peer 1] [X]x, [peer 2] [X]x, [peer 3] [X]x. Median: [X]x EV/Revenue.
EQUITY: At peer median on [YEAR+1]E revenue $[X]B: $[X]/share.
  Premium/discount justified by [reason]: [X]x → $[X]/share.
CRYPTO: At peer median P/S (circulating) on [YEAR+1]E revenue $[X]M: $[X]/token.
  On FDV basis at peer median: $[X]/token.

Method 3 — EQUITY: Sum-of-parts / M&A precedent ([X]% weight):
[Segment A]: $[X]B at [X]x [metric] = $[X]B.
[Segment B]: $[X]B at [X]x [metric] = $[X]B.
Total SOTP: $[X]B → $[X]/share.
OR: Comparable acquisitions at [X]x EV/Revenue (median of [N] transactions) → [X]% premium → $[X]/share.

Method 3 — CRYPTO: Tokenomics reflexivity ([X]% weight):
Buyback yield on market cap: [X]%.
Staking/validator APR: [X]%.
Net annual supply change: [+/-X]% ([X]M tokens unlocking vs. [X]M bought back).
Combined shareholder yield: [X]%. At [X]x required return implied by WACC: FV $[X]/token.

Methodology weights: Method 1 [X]% · Method 2 [X]% · Method 3 [X]%
Weight rationale: [one sentence]

Blended fair value: $[X] (range: $[X] – $[X])
vs. current spot: +/–[X]%

---

SCENARIOS — SCENARIO ANALYSIS

Bear ([X]%): [Named condition 1 — specific and falsifiable, e.g. "Revenue growth decelerates from [X]% to [X]% as [named competitor] takes [X]pp of market share"]. [Named condition 2.]
Base ([X]%): Consensus plays out. Revenue [X]% CAGR, margin [X]%. [Named catalyst] delivers as expected.
Bull ([X]%): [Named condition 1 — e.g. "CLARITY Act passes → TAM expands [X]x; market share reaches [X]%"]. [Named condition 2.]

              BEAR ([X]%)    BASE ([X]%)    BULL ([X]%)    BLENDED FV    vs. SPOT
1 Month       $[X]           $[X]           $[X]           $[X]          +/–[X]%
3 Months      $[X]           $[X]           $[X]           $[X]          +/–[X]%
6 Months      $[X]           $[X]           $[X]           $[X]          +/–[X]%
1 Year        $[X]           $[X]           $[X]           $[X]          +/–[X]%

---

```

- [ ] **Step 5: Insert into Sector Analysis template**

Find inside the Sector Analysis template code block:
```
TIME-SENSITIVE FLAGS & LOW-CONFIDENCE CAVEATS
```

Insert immediately before it:

```
VAL — VALUATION

Method 1 — Sector P/E vs. 5-year historical mean ([X]% weight):
Current forward P/E: [X]x. 5-year average: [X]x. Standard deviation: [X]x.
Premium/discount: [X]% / [X]σ. [source, date]
At mean reversion: [X]% upside/downside. Justified premium/discount because: [one sentence].

Method 2 — Sub-sector catch-up implied return ([X]% weight):
Leading sub-sector: [X]% YTD. Lagging sub-sector: [X]% YTD. Gap: [X]pp.
Historical gap closure in comparable cycles: [X]pp over [X] months.
Implied return for lagging sub-sector on catch-up: [X]% over [X] months.

Method 3 — Factor premium ([X]% weight):
Current factor tilt: [value/growth/quality]. Historical premium of this factor in this
macro regime: [X]pp annualised. Regime duration estimate: [X] months.
Implied sector alpha from factor: [X]%.

Methodology weights: Method 1 [X]% · Method 2 [X]% · Method 3 [X]%
Weight rationale: [one sentence]

Blended implied sector return (1 year): [X]% (range: [X]% – [X]%)

---

SCENARIOS — SCENARIO ANALYSIS

Bear ([X]%): Macro contraction — [named indicator] falls below [X] threshold, triggering P/E de-rating from [X]x to [X]x. Sector returns [X]% on contraction.
Base ([X]%): Sector holds current multiple. Earnings grow [X]% in line with consensus. Sector returns [X]% (earnings + multiple stability).
Bull ([X]%): Macro expansion — [named indicator] above [X] threshold + factor rotation into [value/quality/growth] lifts P/E to [X]x. Sector returns [X]%.

              BEAR ([X]%)    BASE ([X]%)    BULL ([X]%)    BLENDED FV    vs. SPOT
1 Month       [X]% return    [X]% return    [X]% return    [X]% return   +/–[X]%
3 Months      [X]% return    [X]% return    [X]% return    [X]% return   +/–[X]%
6 Months      [X]% return    [X]% return    [X]% return    [X]% return   +/–[X]%
1 Year        [X]% return    [X]% return    [X]% return    [X]% return   +/–[X]%

---

```

- [ ] **Step 6: Verify all five "VAL —" headers now exist in the file**

```bash
grep "VAL —\|VAL-DEEP —" ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md | wc -l
```

Expected: 5

- [ ] **Step 7: Verify all five "SCENARIOS —" headers exist**

```bash
grep "SCENARIOS —" ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md | wc -l
```

Expected: 5

- [ ] **Step 8: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add skills/buy-side-note/skill.md
git commit -m "feat: add valuation and scenario analysis sections to all five buy-side-note templates"
```

---

### Task 8: buy-side-note — Stage 3 Sections C, D, E (Sensitivity, Trade Construction, Position Sizing)

**Files:**
- Modify: `~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md`

Insert three more sections into each template's code block, immediately after the SCENARIOS section added in Task 7 (which ends with `---`) and before `TIME-SENSITIVE FLAGS`.

The insertion point for each template is after the `---` that closes the SCENARIOS section, still inside the template code block.

- [ ] **Step 1: Insert into Thematic Rotation template**

After the closing `---` of the SCENARIOS section in the Thematic Rotation template, insert:

```
SENSITIVITY — SENSITIVITY TABLES

Table 1: [Sensitivity Axis A] × [Sensitivity Axis B] → Implied 1-Year Return
(Populate from Stage 2 "Sensitivity axes" finding. Current = marked ← SPOT. Base case = marked ← BASE.)

              [B: Low]    [B: Mid]    [B: High]
[A: Low]      [X]%        [X]%        [X]%
[A: Mid]      [X]%        [X]%  ←BASE [X]%  ←SPOT
[A: High]     [X]%        [X]%        [X]%

(Flag ▲ any cell >50% return. Flag ▼ any cell >30% loss. Mark [DIRECTIONAL ESTIMATE] if data insufficient.)

Table 2: [Second Axis Pair] → Implied 1-Year Return
[Same format]

---

TRADES — TRADE CONSTRUCTION

Trade 1: Core Basket Long
Instrument: Long [top-ranked theme ETF ticker or equal-weight basket of top 3 tickers]
Rationale: Primary expression of the rotation thesis.
Entry: [Named trigger — e.g. "First [X]% weekly close above prior 4-week high in ETF AUM"]
Exit (profit): [X]x P/S re-rating OR [named catalyst] confirms rotation is live.
Exit (loss): [Named kill condition from ranking table] — close position.

Trade 2: Event-Specific (nearest catalyst)
Instrument: [specific — e.g. "Long [TICK] calls, [tenor], [strike]" or "Long [TICK] ahead of [named event]"]
Rationale: Event-specific expression with defined catalyst clock.
Entry: [Specific entry condition]
Exit (profit): [Specific condition]
Exit (loss): [Stop or invalidating event]

Trade 3: Hedge — Outgoing Theme Short
Instrument: EQUITY — Short [outgoing theme ETF or named crowded name]. CRYPTO — Short [outgoing theme token or index].
Rationale: If rotation stalls, outgoing theme compresses as capital stays put.
Entry: [Specific entry condition]
Exit: Cover if [named condition showing rotation is not happening].

Trade 4: Pairs — Top Theme vs. Bottom-Ranked Theme
Instrument: Long [#1 ranked theme names], Short [lowest-ranked candidate or outgoing theme names], equal notional.
Rationale: Isolates relative rotation alpha from market beta.
Entry: [Specific entry]
Exit: [Spread target or named event]

---

SIZING — POSITION SIZING

Price / Entry Zone       Weighting        Rationale
Pre-catalyst             [X]% of book     Narrative risk — size conservatively until [named event] confirms
Post-catalyst confirm    [X]% of book     Add on [named catalyst] print; rotation signal confirmed
If rotation stalls       0% / exit        Defined by: [named kill condition]
Max portfolio allocation: [X]% NAV across all theme positions combined.

Expected return at entry (1 year, probability-weighted): [X]%
Est. volatility (basket): [X]% (based on [historical vol / directional estimate])
Implied Sharpe at entry: ~[X]

```

- [ ] **Step 2: Insert into Earnings Preview template**

After the closing `---` of the SCENARIOS section in the Earnings Preview template:

```
SENSITIVITY — SENSITIVITY TABLES

Table 1: EPS Beat/Miss Magnitude × P/E Re-rating → Implied Stock Price
(Current stock = marked ← SPOT. Base case = marked ← BASE.)

                    P/E Compresses    P/E Holds    P/E Expands
EPS Miss (–[X]%)   $[X]              $[X]          $[X]
EPS In-Line        $[X]              $[X]  ←BASE   $[X]  ←SPOT
EPS Beat (+[X]%)   $[X]              $[X]          $[X]  ▲ (if >50%)

Table 2: Revenue vs. Guidance → Implied 3-Month Stock Price
[Same format with revenue beat/miss vs. guidance raise/maintain/cut]

(Mark [DIRECTIONAL ESTIMATE] for any cell where options pricing or historical re-rating data is [UNFOUND].)

---

TRADES — TRADE CONSTRUCTION

Trade 1: Core Directional
EQUITY: Long [TICK] common / Long [TICK] calls ([X]-week tenor, [X]% OTM strike for defined risk)
CRYPTO: Long [TOKEN] spot / Long [TOKEN] calls ([exchange], [tenor], [strike])
Rationale: Direct expression of [bear/base/bull] scenario probability-weighted advantage.
Entry: Current levels — size [X]% pre-print.
Exit (profit): Beat + raised guidance → trim to [X]% at open.
Exit (loss): Miss → close immediately on open.

Trade 2: Event-Specific Print Hedge
Instrument: EQUITY — ATM straddle ([strike], [exp]). CRYPTO — Long vol via calls + puts if liquid; else long spot + put hedge.
Rationale: Implied move ([X]%) vs. historical average actual move ([X]%) — [over/under-priced vol].
Entry: 2–3 days before print.
Exit: Immediately after print reaction.

Trade 3: Pairs vs. Sector
Instrument: Long [TICK] / Short [sector ETF] ([ticker]), equal notional.
Rationale: If [TICK] beats but sector sells off, isolates single-stock alpha.
Entry: Pre-print.
Exit: 1 week post-print.

---

SIZING — POSITION SIZING

Price Zone                Weighting        Rationale
Pre-print (now ~$[X])     [X]% of book     Binary risk — size conservatively
Post-beat confirmation    [X]% of book     Add at open on beat + guide raise
Post-miss                 0% / exit        Close on open; thesis invalidated
Max position: [X]% NAV. Do not hold full straddle through the call — cut one leg immediately post-print.

Expected return at current ($[X]), probability-weighted 1Y: [X]%
Est. volatility: [X]% (options-implied or historical)
Implied Sharpe: ~[X]

EQUITY: no carry component.
CRYPTO: Staking APR [X]% annualised if holding spot between prints.

```

- [ ] **Step 3: Insert into Earnings Flash template**

After the closing `---` of the SCENARIOS section in the Earnings Flash template:

```
SENSITIVITY — SENSITIVITY TABLES

Table 1: Estimate Revision % × Forward Multiple → Updated Implied Price
(Current stock post-print = marked ← SPOT. Base (revised consensus) = ← BASE.)

                    Multiple –[X]x    Multiple Flat    Multiple +[X]x
EPS revised –[X]%   $[X]              $[X]             $[X]
EPS revised flat    $[X]              $[X]  ←BASE      $[X]  ←SPOT
EPS revised +[X]%   $[X]              $[X]             $[X]

Table 2: Guidance Revision × Institutional Positioning → 3-Month Price
[Same format — guidance cut/maintain/raise vs. crowded/neutral/under-owned]

---

TRADES — TRADE CONSTRUCTION

Trade 1: Post-Print Directional (updated from pre-print)
EQUITY: Long / Short [TICK] based on which scenario printed.
CRYPTO: Long / Short [TOKEN] spot based on results vs. prior scenario framework.
Rationale: [Which scenario printed] is now the base case. Update sizing accordingly.
Entry: On open / first liquid print post-announcement.
Exit (profit): [Named condition — estimate upgrade cycle completes / [X]x multiple re-rates]
Exit (loss): [Named condition that would invalidate the post-print thesis]

Trade 2: Guide-Down Hedge (if guidance was cut or uncertain)
Instrument: EQUITY — long [TICK] near-term puts ([strike], [exp]). CRYPTO — long puts ([exchange], [tenor]) or reduce spot.
Rationale: Guidance uncertainty not resolved on call — hedge embedded downside until clarity.
Entry: At open if guidance language was ambiguous.
Exit: On Q+1 pre-announcement or confirmation of demand trend.

Trade 3: Peer Read-Across
Instrument: Long [peer ticker] / Short [peer ticker] based on read-across direction identified in Section 05.
Rationale: [TICK] print resolves key debate for [peer ticker].
Entry: At open on print day.
Exit: Within 5 trading days — read-across fades.

---

SIZING — POSITION SIZING

Price Zone (post-print)     Weighting        Rationale
[Post-print range]          [X]% of book     [Which scenario printed drives sizing]
If further downside         [X]% of book     Add if [named condition that confirms bear is wrong]
If guide-down confirmed     0% / exit        Defined kill condition

Max position: [X]% NAV. Flash notes are initial reads — resize after full call transcript review.

Expected return (updated, 1Y probability-weighted): [X]%
Implied Sharpe at post-print levels: ~[X]

```

- [ ] **Step 4: Insert into Single-Stock Deep Dive template**

After the closing `---` of the SCENARIOS section in the Single-Stock Deep Dive template:

```
SENSITIVITY — SENSITIVITY TABLES

Table 1: [Sensitivity Axis A] × [Sensitivity Axis B] → Implied Fair Value
(From Stage 2 "Sensitivity axes". Current spot = ← SPOT. Base case = ← BASE.)

              [B: Low]      [B: Mid]        [B: High]
[A: Low]      $[X]  ▼       $[X]            $[X]
[A: Mid]      $[X]          $[X]  ←BASE     $[X]  ←SPOT
[A: High]     $[X]          $[X]            $[X]  ▲

Table 2: [Second Axis Pair] → Implied Fair Value
[Same format. For CRYPTO: axes might be "net supply deflation/inflation × buyback yield captured"]

(Flag ▲ cells implying >50% upside. Flag ▼ cells implying >30% downside. [DIRECTIONAL ESTIMATE] where inputs are estimated.)

---

TRADES — TRADE CONSTRUCTION

Trade 1: Core Long
EQUITY: Long [TICK] common. Alternatively: long [TICK] [X]-month calls at [strike] for defined downside.
CRYPTO: Long [TOKEN] spot. Alternatively: long [TOKEN] calls on [exchange], [tenor], [strike].
Rationale: Direct expression of base case thesis with [X]% upside to blended FV.
Entry: Current levels ~$[X]. Add at $[X] (bear-case support zone).
Exit (profit): $[X] (blended FV) or [named catalyst] re-rating event.
Exit (loss): [Named kill condition from THE DEBATE section] — close if this occurs.

Trade 2: Event-Specific (nearest catalyst from catalyst calendar)
Instrument: EQUITY — long [TICK] calls ([tenor matching catalyst date + 2 weeks], [X]% OTM strike).
CRYPTO — long [TOKEN] calls ([exchange], [tenor], [strike]) ahead of [named event].
Rationale: Asymmetric exposure to [named catalyst] with defined premium risk.
Entry: [X]–[X] weeks before catalyst date.
Exit (profit): [Named catalyst] confirms → close calls, hold core long.
Exit (loss): Premium decay — close [X] days before expiry if catalyst not imminent.

Trade 3: Hedge — Short Named Peer
EQUITY: Short [named direct competitor TICKER] / Long [TICK], equal notional.
CRYPTO: Short [named competitor TOKEN] / Long [TOKEN], equal notional.
Rationale: If macro sells off, long/short isolates company-specific alpha. [Named competitor] is [crowded/expensive] relative to [TICKER/TOKEN].
Entry: Same as core long entry.
Exit: Close if [named competitor] de-rates for company-specific (not macro) reasons.

Trade 4: CRYPTO ONLY — Staking + Put-Selling Carry
Instrument: Long [TOKEN] spot + stake for [X]% APR + sell [X]-month [X]% OTM puts for [X]% premium.
Combined annualised yield: [X]% (staking) + [X]% (put premium) = [X]%.
Rationale: Earn carry while waiting for base case to play out.
Entry: Current spot. Exit covered puts if [TOKEN] approaches put strike — reassess.
Risk: Puts assigned if [TOKEN] falls to put strike — adds to position at [X]% below current.

---

SIZING — POSITION SIZING

Price Zone               Weighting        Rationale
$[low zone]              [X]x book        Aggressive accumulation — bear-case support, [X]x risk-reward
$[mid zone]              [X]x book        Standard entry — base case pricing
~$[current] (now)        [X]x book   ← YOU ARE HERE
$[upper zone]            [X]x book        Trim [X]% — bull case increasingly priced
$[high zone]             [X]x book        Trim [X]%+ — close to bull FV; sell call spreads

Max portfolio allocation: [X]% NAV.

At current ($[X]):         Expected return [X]% · Est. vol [X]% · Implied Sharpe ~[X]
At best-entry ($[X]):      Expected return [X]% · Est. vol [X]% · Implied Sharpe ~[X]
CRYPTO carry addition:     Staking [X]% + put premium [X]% = [X]% total yield on position.
Total return at current (price + carry): [X]%

```

- [ ] **Step 5: Insert into Sector Analysis template**

After the closing `---` of the SCENARIOS section in the Sector Analysis template:

```
SENSITIVITY — SENSITIVITY TABLES

Table 1: Sector Forward P/E × Earnings Growth → Implied 1-Year Return

              EPS growth [X]%    EPS growth [X]%    EPS growth [X]%
P/E [X]x      [X]%               [X]%               [X]%  ▼
P/E [X]x      [X]%               [X]%  ←BASE        [X]%  ←SPOT
P/E [X]x      [X]%               [X]%               [X]%  ▲

Table 2: Sub-Sector Spread × Factor Tilt Premium → Implied Alpha vs. Broad Market
[Same format — sub-sector performance gap vs. factor premium]

---

TRADES — TRADE CONSTRUCTION

Trade 1: Core Sector Long
EQUITY: Long sector ETF ([ticker], [expense ratio]) or equal-weight basket of top 3 longs from Stock Selection.
CRYPTO: Not applicable for sector notes — use individual name expressions.
Rationale: Broad sector exposure to base-case scenario.
Entry: [Named trigger — e.g. "P/E at or below [X]x historical mean"]
Exit (profit): P/E re-rates to [X]x or [named macro catalyst] confirms expansion.
Exit (loss): [Named macro indicator] crosses [threshold] — sector thesis invalidated.

Trade 2: Sub-Sector Pairs (top vs. bottom sub-sector)
Instrument: Long [leading sub-sector ETF or basket] / Short [lagging sub-sector ETF or basket], equal notional.
Rationale: Captures sub-sector differentiation alpha identified in Section 03.
Entry: [Named entry condition — spread above [X]pp or at inflection]
Exit: [Spread target or named catalyst that closes the gap]

Trade 3: Event-Specific (nearest macro catalyst from WHAT TO MONITOR)
Instrument: EQUITY — long sector calls or ETF position ahead of [named macro event].
Rationale: [Named event] is a binary re-rating catalyst for the sector.
Entry: [X] days before [named event].
Exit: Close on the event day.

Trade 4: Hedge — Short Avoid Name vs. Long Best Expression
Instrument: Long [top pick TICKER] / Short [avoid TICKER], equal notional.
Rationale: Sub-sector relative value within sector; hedges broad market risk.
Entry: Any time; tighten sizing if broad market vol spikes.
Exit: [Spread target or named catalyst]

---

SIZING — POSITION SIZING

Price Zone (sector ETF or basket)    Weighting        Rationale
P/E below [X]x (undervalued)         [X]% of book     Sector trades at historical discount — add
P/E at [X]x (fair value)             [X]% of book     ← Base case pricing
P/E at [X]x (current)                [X]% of book  ← YOU ARE HERE
P/E above [X]x (premium)             [X]% of book     Trim — bull case increasingly priced
P/E above [X]x (stretched)           [X]% of book     Trim heavily or exit

Max sector allocation: [X]% NAV.

At current P/E ([X]x):    Expected sector return [X]% (1Y) · Est. vol [X]% · Implied Sharpe ~[X]
At undervalued entry:     Expected sector return [X]% (1Y) · Implied Sharpe ~[X]

```

- [ ] **Step 6: Verify all five SENSITIVITY sections exist**

```bash
grep "SENSITIVITY —\|SENSITIVITY TABLES" ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md | wc -l
```

Expected: at least 5

- [ ] **Step 7: Verify all five TRADES sections exist**

```bash
grep "TRADES —\|TRADE CONSTRUCTION" ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md | wc -l
```

Expected: at least 5

- [ ] **Step 8: Verify all five SIZING sections exist**

```bash
grep "SIZING —\|POSITION SIZING" ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md | wc -l
```

Expected: at least 5

- [ ] **Step 9: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add skills/buy-side-note/skill.md
git commit -m "feat: add sensitivity tables, trade construction, position sizing to all five buy-side-note templates"
```

---

### Task 9: buy-side-note — Stage 4 Chart Additions + Cache Sync

**Files:**
- Modify: `~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md`
- Sync: `~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md`

- [ ] **Step 1: Locate the chart table in Stage 4**

Find this exact text in the file:
```
| Note Type | Chart 1 | Chart 2 |
```

- [ ] **Step 2: Replace the chart table header and add Chart 3 column**

Replace:
```
| Note Type | Chart 1 | Chart 2 |
|-----------|---------|---------|
| Thematic Rotation | Outgoing theme vs. S&P 500 YTD (line chart) | Candidate themes relative performance comparison (bar chart) |
| Earnings Preview | Stock vs. sector 3-month performance (line chart) | Historical EPS beat/miss vs. consensus — last 8 quarters (bar chart) |
| Earnings Flash | Reported vs. consensus on key metrics (bar chart) | Stock reaction % vs. options-implied move (single-bar comparison) |
| Single-Stock Deep Dive | Revenue and operating margin trend — 3 years (dual-axis line/bar) | Valuation multiples vs. peer group (grouped bar chart) |
| Sector Analysis | Sub-sector relative performance YTD (bar chart) | Sector forward P/E vs. 5-year historical average (line chart with mean line) |
```

With:
```
| Note Type | Chart 1 | Chart 2 | Chart 3 |
|-----------|---------|---------|---------|
| Thematic Rotation | Outgoing theme vs. S&P 500 YTD (line chart) | Candidate themes relative performance comparison (bar chart) | Blended FV by scenario and horizon — grouped bar, 4 horizons × 3 scenarios with probability-weighted blended line |
| Earnings Preview | Stock vs. sector 3-month performance (line chart) | Historical EPS beat/miss vs. consensus — last 8 quarters (bar chart) | Historical implied move vs. actual move — last 8 earnings events (paired bar chart) |
| Earnings Flash | Reported vs. consensus on key metrics (bar chart) | Stock reaction % vs. options-implied move (single-bar comparison) | Reported vs. prior scenario framework on key metrics — deviation from bear/base/bull targets (grouped bar) |
| Single-Stock Deep Dive | Revenue and operating margin trend — 3 years (dual-axis line/bar) | Valuation multiples vs. peer group (grouped bar chart) | Sensitivity heatmap — Variable A × Variable B → colour-coded FV matrix (green = upside, red = downside from spot) |
| Sector Analysis | Sub-sector relative performance YTD (bar chart) | Sector forward P/E vs. 5-year historical average (line chart with mean line) | Scenario probability-weighted return distribution — bar chart with bear/base/bull labels and blended FV marker |
```

- [ ] **Step 3: Verify the updated chart table has four columns**

```bash
grep "| Note Type |" ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md
```

Expected:
```
| Note Type | Chart 1 | Chart 2 | Chart 3 |
```

- [ ] **Step 4: Sync updated skill.md to cache**

```bash
cp ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
diff ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
```

Expected: no output

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add skills/buy-side-note/skill.md
git commit -m "feat: add Chart 3 (scenario/sensitivity visualisation) to Stage 4 chart table"
```

---

### Task 10: End-to-End Validation

**Files:** No new files — validation only.

- [ ] **Step 1: Confirm all skill directories exist in cache**

```bash
ls ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/
```

Expected: `buy-side-note  devils-advocate  research-debate  short-thesis`

- [ ] **Step 2: Confirm package.json has both registered skills**

```bash
cat ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/package.json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print([s['name'] for s in d['skills']])"
```

Expected: `['buy-side-note', 'research-debate']`

- [ ] **Step 3: Confirm all four skill files have valid frontmatter**

```bash
for skill in buy-side-note short-thesis devils-advocate research-debate; do
  echo "=== $skill ===" && head -4 ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/$skill/skill.md && echo ""
done
```

Expected: each shows `---`, `name:`, `description:`, `---`

- [ ] **Step 4: Confirm asset detection was added to buy-side-note Stage 1**

```bash
grep "ASSET TYPE DETECTION" ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
```

Expected: `**ASSET TYPE DETECTION**`

- [ ] **Step 5: Confirm all five new section types appear 5 times each**

```bash
echo "VAL sections:" && grep -c "VAL —\|VAL-DEEP —" ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
echo "SCENARIO sections:" && grep -c "SCENARIOS —" ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
echo "SENSITIVITY sections:" && grep -c "SENSITIVITY —" ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
echo "TRADE sections:" && grep -c "TRADES —" ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
echo "SIZING sections:" && grep -c "SIZING —" ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
```

Expected: each line shows 5

- [ ] **Step 6: Confirm Stage 4 chart table has 3 chart columns**

```bash
grep "| Note Type |" ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
```

Expected: `| Note Type | Chart 1 | Chart 2 | Chart 3 |`

- [ ] **Step 7: Confirm source and cache are identical for buy-side-note**

```bash
diff ~/.claude/plugins/buy-side-research/skills/buy-side-note/skill.md \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/buy-side-note/skill.md
```

Expected: no output

- [ ] **Step 8: Review git log — confirm 10 commits from this implementation**

```bash
cd ~/.claude/plugins/buy-side-research && git log --oneline -12
```

Expected — 10 commits from this plan visible:
```
feat: add Chart 3 to Stage 4 chart table
feat: add sensitivity tables, trade construction, position sizing to all five templates
feat: add valuation and scenario analysis sections to all five templates
feat: add Stage 2 valuation/scenario/comps research items to buy-side-note
feat: add asset detection (equity/crypto) to buy-side-note Stage 1
feat: register research-debate slash command, bump to v1.1.0
feat: add research-debate orchestrator skill
feat: add devils-advocate sub-agent skill
feat: add short-thesis sub-agent skill
<previous commit>
```

If all checks pass: restart Claude Code (or open `/plugins`) to load the updated skills. Both `/buy-side-note` and `/research-debate` will be available with the full enhanced capabilities.
