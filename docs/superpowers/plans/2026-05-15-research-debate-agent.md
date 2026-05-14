# Research Debate Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three skill files and update `package.json` to give the `buy-side-research` plugin a `/research-debate` command that runs a bull analyst and short analyst in parallel, synthesises with a devil's advocate, and renders a combined PDF.

**Architecture:** Hub-and-spoke — a thin orchestrator skill (`research-debate/skill.md`) dispatches two parallel sub-agents (bull via buy-side-note logic, bear via short-thesis/skill.md), then sequentially runs the devil's advocate (devils-advocate/skill.md) on both outputs, and assembles a PDF. The two sub-skill files exist as prompt libraries but are not registered as slash commands.

**Tech Stack:** Markdown skill files, Claude Code Agent tool for sub-agent dispatch, `anthropic-skills:pdf` for final rendering, `anthropic-skills:canvas-design` for charts (bull agent only).

---

## File Map

```
~/.claude/plugins/buy-side-research/
  package.json                                    ← MODIFY: add research-debate entry
  skills/
    buy-side-note/skill.md                        ← UNCHANGED
    short-thesis/skill.md                         ← CREATE
    devils-advocate/skill.md                      ← CREATE
    research-debate/skill.md                      ← CREATE

~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/
  package.json                                    ← SYNC from source after each task
  skills/
    buy-side-note/skill.md                        ← UNCHANGED
    short-thesis/skill.md                         ← SYNC from source
    devils-advocate/skill.md                      ← SYNC from source
    research-debate/skill.md                      ← SYNC from source
```

**Why two locations?** Claude Code reads skills from the cache path. The source path at `~/.claude/plugins/buy-side-research/` is the authoritative version. Every task ends with a sync step to keep them identical.

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

4. **Short catalysts** — Search: "[subject] earnings risk catalyst 2026", "[subject] contract expiry regulatory risk lock-up expiry". Find three specific, dated events (earnings date, product launch, regulatory decision, lock-up expiry) that would force a negative reprice.

5. **Who is short and why** — Search: "[subject] short seller report 2025 2026", "[subject] short interest rising". Record: any named short sellers, their stated thesis, short % of float trend.

6. **Bear-case valuation** — Search: "[subject] bear case valuation downside scenario". If unavailable, build a simple bear case: take consensus revenue, apply a compression scenario (e.g., multiple contracts to trough), state the implied price.

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
Method: [valuation approach — e.g., "X turns EV/EBITDA on bear-case EBITDA of $Y"]
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

Enforce globally. No exceptions.

1. **Adversarial but sourced.** Every claim needs a number or a named fact. Opinion without evidence is not a short thesis — it is noise.
2. **No weasel words.** "Could", "might", "potentially", "may" are banned. Either the fact is true or it is not. If uncertain, use `[DIRECTIONAL ESTIMATE]`.
3. **Opinions are stated as opinions, not hedged as possibilities.** "This is a structurally broken business" — not "this may represent a challenged business model."
4. **ALL-CAPS tickers throughout.** No exceptions.
5. **Gap-log protocol.** Every research gap flows into LOW-CONFIDENCE FLAGS. Never present an estimate as a confirmed fact.
````

- [ ] **Step 3: Validate the file has correct frontmatter**

```bash
head -5 ~/.claude/plugins/buy-side-research/skills/short-thesis/skill.md
```

Expected output:
```
---
name: short-thesis
description: Write a short analyst thesis on a stock, theme, or sector. Sub-agent persona used by research-debate. Adversarial bear perspective with sourced evidence.
---
```

- [ ] **Step 4: Sync to cache**

```bash
mkdir -p ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/short-thesis
cp ~/.claude/plugins/buy-side-research/skills/short-thesis/skill.md \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/short-thesis/skill.md
```

- [ ] **Step 5: Verify cache copy is identical**

```bash
diff ~/.claude/plugins/buy-side-research/skills/short-thesis/skill.md \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/short-thesis/skill.md
```

Expected output: (no output — files are identical)

- [ ] **Step 6: Commit**

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

1. **Core disagreement** — What is the fundamental underlying assumption the two sides actually disagree on? Not the surface claims (bull says growth accelerates, bear says it decelerates) — the deeper structural assumption that makes one side right and the other wrong.

2. **Unresolved questions** — What are the three most consequential questions that, if answered, would resolve the debate? Neither side has answered them. These are not rhetorical — they are specific, answerable questions the market is currently pricing without information.

3. **Shared data, opposite conclusions** — Is either side using the same data points to reach opposite conclusions? If so, why is that possible? What interpretive assumption creates the divergence?

4. **Empirically unverifiable claims** — Did either side make claims that cannot currently be verified with available public data? Flag these explicitly — not as "we disagree" but as "we cannot know."

5. **Blind spots** — What is the single biggest risk the bull case ignored? What is the single biggest risk the bear case ignored? These are not the stated risks — they are the unstated ones.

6. **Verdict** — Which side has the structurally stronger argument? Independent of whether they turn out to be right. Strong argument = internally consistent, grounded in verifiable data, falsifiable thesis, explicit assumptions. Weak argument = requires multiple unproven assumptions, cherry-picks data, or cannot be falsified.

---

## WRITE PHASE

Write the State of the Debate using this exact structure. It must fit on one page — be ruthlessly concise.

```
STATE OF THE DEBATE — [SUBJECT IN ALL CAPS]
[Date]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. CORE DISAGREEMENT

[One paragraph. Name the fundamental underlying assumption — not the surface claims.
What does each side believe to be true that the other denies? Be specific.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2. THREE OPEN QUESTIONS

Q1: [Specific, answerable question. Neither side has answered it. If answered, it resolves the debate.]
Q2: [Specific, answerable question. Neither side has answered it.]
Q3: [Specific, answerable question. Neither side has answered it.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3. WHERE BOTH SIDES HAVE BLIND SPOTS

Bull blind spot: [One named risk or assumption the bull case does not address. Be specific.]
Bear blind spot: [One named risk or assumption the bear case does not address. Be specific.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

4. VERDICT

Stronger structural argument: [BULL / BEAR]

[2–3 sentences. State which side and why — not who will be right, but whose argument is
better constructed. Written as a recommendation to a PM deciding whether to spend analyst
time on this name: "Spend time on this if X. Pass if Y."]

[If the debate is genuinely unresolvable with available public information, say so
explicitly: "This debate cannot be resolved with available information. It would require
[named data or event] to determine which side is correct."]
```

---

## VOICE RULES

Enforce globally. No exceptions.

1. **No position, no hedging.** You are a referee. No phrases like "I lean toward" or "I find the bull case more compelling personally." State which side is structurally stronger and why.
2. **"It depends" is banned** unless you immediately complete the sentence: "It depends on whether [specific condition], which would be resolved by [specific data or event]."
3. **Unresolvable is a valid verdict.** If the debate cannot be resolved with available public information, say so and name what would resolve it. This is more honest and more useful than picking a side when the evidence is insufficient.
4. **One page maximum.** Every sentence must earn its place. If a sentence does not directly advance the analysis, cut it.
````

- [ ] **Step 3: Validate the file has correct frontmatter**

```bash
head -5 ~/.claude/plugins/buy-side-research/skills/devils-advocate/skill.md
```

Expected output:
```
---
name: devils-advocate
description: Synthesise a bull note and short thesis into a one-page "State of the Debate." Sub-agent persona used by research-debate. Has no position — referee only.
---
```

- [ ] **Step 4: Sync to cache**

```bash
mkdir -p ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/devils-advocate
cp ~/.claude/plugins/buy-side-research/skills/devils-advocate/skill.md \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/devils-advocate/skill.md
```

- [ ] **Step 5: Verify cache copy is identical**

```bash
diff ~/.claude/plugins/buy-side-research/skills/devils-advocate/skill.md \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/devils-advocate/skill.md
```

Expected output: (no output — files are identical)

- [ ] **Step 6: Commit**

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

Use the Agent tool to spawn two sub-agents simultaneously. Do not wait for one to finish before starting the other — dispatch both in the same tool call batch.

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

**Render to PDF:** Invoke `anthropic-skills:pdf` to render the assembled markdown as a PDF with the following styling:
- Font: clean sans-serif (Inter, Helvetica, or system default), 10–11pt body
- Section headers: bold, clearly delineated with spacing
- Tables: light 1pt borders, alternating row shading (#F7F7F7 / white)
- Callout boxes: light gray border, slightly indented, for bear cases and verdicts
- Section dividers between the three documents (State of the Debate / Bull Case / Bear Case): bold full-width horizontal rule with the section name centred
- Cover page: Title "Research Debate — [Subject]", date, contents list

Announce on completion: **"Debate complete. PDF saved as [filename]."**
````

- [ ] **Step 3: Validate the file has correct frontmatter**

```bash
head -5 ~/.claude/plugins/buy-side-research/skills/research-debate/skill.md
```

Expected output:
```
---
name: research-debate
description: Run a full investment debate on a stock, theme, or sector. Dispatches a bull analyst and short analyst in parallel, synthesises with a devil's advocate, and assembles a single combined PDF. Use when asked to debate, stress-test, or get both sides on any investment topic.
---
```

- [ ] **Step 4: Verify all three section headers are present**

```bash
grep "^## STAGE" ~/.claude/plugins/buy-side-research/skills/research-debate/skill.md
```

Expected output:
```
## STAGE 1 — CLASSIFY
## STAGE 2 — PARALLEL DISPATCH
## STAGE 3 — DEVIL'S ADVOCATE SYNTHESIS
## STAGE 4 — ASSEMBLE AND RENDER
```

- [ ] **Step 5: Sync to cache**

```bash
mkdir -p ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/research-debate
cp ~/.claude/plugins/buy-side-research/skills/research-debate/skill.md \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/research-debate/skill.md
```

- [ ] **Step 6: Verify cache copy is identical**

```bash
diff ~/.claude/plugins/buy-side-research/skills/research-debate/skill.md \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/research-debate/skill.md
```

Expected output: (no output — files are identical)

- [ ] **Step 7: Commit**

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

- [ ] **Step 1: Update package.json**

Edit `~/.claude/plugins/buy-side-research/package.json` to add the `research-debate` skill entry. The file should read exactly:

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

Note: version bumped from `1.0.0` to `1.1.0` to reflect the new skill.

- [ ] **Step 2: Validate JSON is valid**

```bash
cat ~/.claude/plugins/buy-side-research/package.json | python3 -m json.tool > /dev/null && echo "Valid JSON"
```

Expected output: `Valid JSON`

- [ ] **Step 3: Verify both skills are listed**

```bash
cat ~/.claude/plugins/buy-side-research/package.json | python3 -c "import sys,json; d=json.load(sys.stdin); print([s['name'] for s in d['skills']])"
```

Expected output: `['buy-side-note', 'research-debate']`

- [ ] **Step 4: Sync package.json to cache**

```bash
cp ~/.claude/plugins/buy-side-research/package.json \
   ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/package.json
```

- [ ] **Step 5: Verify cache package.json is identical**

```bash
diff ~/.claude/plugins/buy-side-research/package.json \
     ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/package.json
```

Expected output: (no output — files are identical)

- [ ] **Step 6: Commit**

```bash
cd ~/.claude/plugins/buy-side-research
git add package.json
git commit -m "feat: register research-debate as slash command, bump to v1.1.0"
```

---

### Task 5: End-to-End Validation

**Files:** No new files — validation only.

- [ ] **Step 1: Verify all four skill files exist in source**

```bash
ls ~/.claude/plugins/buy-side-research/skills/
```

Expected output (four directories):
```
buy-side-note
devils-advocate
research-debate
short-thesis
```

- [ ] **Step 2: Verify all four skill files exist in cache**

```bash
ls ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/
```

Expected output (four directories):
```
buy-side-note
devils-advocate
research-debate
short-thesis
```

- [ ] **Step 3: Check all skill.md files have valid frontmatter**

```bash
for skill in buy-side-note short-thesis devils-advocate research-debate; do
  echo "=== $skill ==="
  head -4 ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/$skill/skill.md
  echo ""
done
```

Expected output — each skill shows `---`, `name: <name>`, `description: ...`, `---`:
```
=== buy-side-note ===
---
name: buy-side-note
description: Generate institutional buy-side research notes ...
---

=== short-thesis ===
---
name: short-thesis
description: Write a short analyst thesis ...
---

=== devils-advocate ===
---
name: devils-advocate
description: Synthesise a bull note and short thesis ...
---

=== research-debate ===
---
name: research-debate
description: Run a full investment debate ...
---
```

- [ ] **Step 4: Verify research-debate is the only new registered slash command**

```bash
cat ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/package.json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print([s['name'] for s in d['skills']])"
```

Expected output: `['buy-side-note', 'research-debate']`

`short-thesis` and `devils-advocate` must NOT appear in this list — they are sub-agent prompts, not registered slash commands.

- [ ] **Step 5: Trace the execution flow against the spec**

Read `~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/research-debate/skill.md` and verify:

- Stage 1 contains the routing table with all five note types
- Stage 2 contains both bull and bear sub-agent prompts with explicit instructions to return markdown only (not PDF)
- Stage 3 contains the devil's advocate prompt with placeholders for inserting both documents
- Stage 4 contains the assembly order: cover → State of the Debate → Bull Case → Bear Case
- Stage 4 instructs `anthropic-skills:pdf` invocation with file naming pattern `[subject-slug]-debate-[YYYY-MM-DD].pdf`

- [ ] **Step 6: Check short-thesis has all six output sections**

```bash
grep -n "^\d\." ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/short-thesis/skill.md
```

Expected output (six numbered items in the write template):
```
1. THE CASE IN ONE LINE
2. WHAT THE BULLS ARE MISSING
3. THE DATA THEY'RE NOT SHOWING YOU
4. SHORT CATALYSTS
5. WHAT WOULD MAKE ME COVER
6. PRICE TARGET / DOWNSIDE SCENARIO
```

- [ ] **Step 7: Check devils-advocate has all four output sections**

```bash
grep -n "^\d\." ~/.claude/plugins/cache/superpowers-marketplace/buy-side-research/1.0.0/skills/devils-advocate/skill.md
```

Expected output (four numbered items in the write template):
```
1. CORE DISAGREEMENT
2. THREE OPEN QUESTIONS
3. WHERE BOTH SIDES HAVE BLIND SPOTS
4. VERDICT
```

- [ ] **Step 8: Final commit with summary**

```bash
cd ~/.claude/plugins/buy-side-research
git log --oneline -5
```

Expected output — five commits visible, with the four from this implementation:
```
<sha> feat: register research-debate as slash command, bump to v1.1.0
<sha> feat: add research-debate orchestrator skill
<sha> feat: add devils-advocate sub-agent skill
<sha> feat: add short-thesis sub-agent skill
<sha> <previous commit>
```

If all checks pass, implementation is complete. Restart Claude Code (or open `/plugins`) to load the new `/research-debate` slash command.
