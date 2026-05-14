# Research Debate Agent — Design Spec

**Date:** 2026-05-15
**Status:** Approved for implementation

---

## Overview

A `/research-debate` skill that runs a structured investment debate on any topic. Three agents run in two phases: a bull analyst and a short analyst work independently in parallel, then a devil's advocate synthesises both into a "State of the Debate." The final output is a single PDF combining the synthesis and both full documents.

This extends the existing `buy-side-research` plugin. The `buy-side-note` skill is reused as-is for the bull agent.

---

## Invocation

```
/research-debate NVDA Q2 earnings
/research-debate thematic rotation after HBM
/research-debate US defense sector
```

Same subject syntax as `/buy-side-note`. The orchestrator infers note type using the same routing table.

---

## File Structure

New files added to the `buy-side-research` plugin:

```
skills/
  buy-side-note/skill.md       ← existing, unchanged
  short-thesis/skill.md        ← new — short analyst persona
  devils-advocate/skill.md     ← new — devil's advocate persona
  research-debate/skill.md     ← new — orchestrator
```

Only `research-debate` is registered as a slash command in `package.json`. The `short-thesis` and `devils-advocate` skill files exist as sub-agent prompts but are not exposed as standalone slash commands.

---

## Execution Flow

### Phase 1 — Parallel (Bull + Bear)

Two sub-agents are dispatched simultaneously using the `dispatching-parallel-agents` pattern.

**Bull sub-agent** runs the full `buy-side-note` pipeline through Stage 3 only:
- Stage 1: Classify
- Stage 2: Research (independent web search)
- Stage 3: Write
- Stage 4: **Skipped** — the orchestrator instructs the bull sub-agent to return markdown, not render a PDF. PDF rendering happens once at the end by the orchestrator.

**Bear sub-agent** runs the `short-thesis` pipeline on the same subject:
- Stage 1: Research (independent web search — not shown the bull's sources or conclusions)
- Stage 2: Write short thesis
- Stage 3: Return markdown

The two agents have no visibility into each other's work. They research independently.

### Phase 2 — Sequential (Devil's Advocate)

After both Phase 1 agents complete, the devil's advocate sub-agent receives:
- The complete bull note (markdown)
- The complete short thesis (markdown)
- The subject/topic

It reads both in full and produces the "State of the Debate" section.

### Phase 3 — Assembly + Render

The orchestrator assembles the combined document in this order:

```
Cover Page
  Title: "Research Debate: [Subject]"
  Date: [today]
  Sections: State of the Debate | Bull Case | Bear Case

State of the Debate
  (devil's advocate output — full text)

─── BULL CASE ───────────────────────────────
  (full buy-side note)

─── BEAR CASE ───────────────────────────────
  (full short thesis)
```

Renders to PDF via `anthropic-skills:pdf`. Single file output named `[subject]-debate-[date].pdf`.

**Error handling:** If either the bull or bear agent returns an error or incomplete output, the orchestrator reports what succeeded and halts. It does not attempt partial assembly.

---

## Short Analyst Persona (`short-thesis/skill.md`)

### Role

A dedicated bear with a position. Not a balanced commentator. Makes the strongest possible case that the bull thesis is wrong.

### Research Focus

- What is the bull case *assuming* that isn't proven? (multiple expansion, TAM realisation, margin improvement)
- What are the structural headwinds the consensus minimises or omits?
- Where does the data trail get selective? (cherry-picked windows, survivorship bias, comp set manipulation)
- What are the short catalysts — dated events that would force a reprice?
- Who is on the other side of this trade and why are they credible?

### Output Structure

1. **THE CASE IN ONE LINE** — one sentence any PM could repeat
2. **WHAT THE BULLS ARE MISSING** — 3 named assumptions the bull case requires, each disputed with evidence
3. **THE DATA THEY'RE NOT SHOWING YOU** — specific numbers, comparisons, or trends omitted from the consensus view
4. **SHORT CATALYSTS** — 3 dated events that would prove the bear right
5. **WHAT WOULD MAKE ME COVER** — explicit conditions that would invalidate this short thesis
6. **PRICE TARGET / DOWNSIDE SCENARIO** — bear-case valuation with stated assumptions

### Voice Rules

- Adversarial but sourced — every claim needs a number or a named fact
- No weasel words: no "could", "might", "potentially" — either it's true or it isn't
- Direct opinions stated as opinions, not hedged as possibilities
- ALL-CAPS tickers
- Same gap-log protocol as buy-side-note: `[UNFOUND]`, `[DIRECTIONAL ESTIMATE]`, `Single source —`

---

## Devil's Advocate Persona (`devils-advocate/skill.md`)

### Role

Has no position. Reads both the bull note and the short thesis in full. Finds where both sides are overconfident and surfaces the questions neither answered. Not a bear, not a bull — a referee.

### Mandate

- Identify the 3 most consequential unresolved disagreements between the two sides
- Find where both sides use the same data to reach opposite conclusions, and explain why that's possible
- Flag claims either side made that are empirically unverifiable — not "we disagree" but "we cannot know"
- Name the single biggest risk the bull ignored AND the single biggest risk the bear ignored
- Deliver a verdict: which side has the structurally stronger argument, independent of whether they're right

### Output Structure — "State of the Debate"

1. **CORE DISAGREEMENT** — one paragraph naming the fundamental underlying assumption both sides actually disagree on (not the surface claims)
2. **THREE OPEN QUESTIONS** — questions that, if answered, would resolve the debate; neither side has answered them
3. **WHERE BOTH SIDES HAVE BLIND SPOTS** — one named weakness in the bull case, one named weakness in the bear case
4. **VERDICT** — which side has the stronger structural argument and why, written as a recommendation to a PM deciding whether to spend further time on this name

### Voice Rules

- Neutral and clinical — no position, no hedging
- Refuses to say "it depends" without immediately specifying what it depends on
- If the debate is genuinely unresolvable with available information, says so explicitly and names what information would resolve it
- Maximum 1 page — the synthesis must be skimmable in under 2 minutes

---

## Orchestrator Design (`research-debate/skill.md`)

### Stage 1 — Classify

Parse the invocation for subject and note type. Use the same routing table as `buy-side-note`:

| User language | Note type applied |
|---|---|
| thematic rotation, after X, next theme | Thematic Rotation |
| earnings preview, pre-earnings, into the print | Earnings Preview |
| earnings flash, post-earnings, after the print | Earnings Flash |
| deep dive, full analysis, initiate | Single-Stock Deep Dive |
| sector, industry | Sector Analysis |

### Stage 2 — Dispatch (Parallel)

Announce: *"Dispatching bull and bear agents in parallel — this will take several minutes."*

Spawn two sub-agents simultaneously:
- Bull: full `buy-side-note` pipeline, returns markdown
- Bear: `short-thesis` pipeline, returns markdown

Wait for both to complete before proceeding.

### Stage 3 — Synthesis

Announce: *"Both sides complete. Running devil's advocate synthesis."*

Spawn devil's advocate sub-agent with both documents. Wait for State of the Debate.

### Stage 4 — Assemble + Render

Announce: *"Assembling final document."*

Combine in order: cover → State of the Debate → Bull Note → Bear Note. Render to PDF.

Output: single PDF file at current working directory.

---

## Output Format

**PDF styling:** Same clean research note style as `buy-side-note`. Section dividers between the three documents (cover/state-of-debate, bull case, bear case) to make navigation clear.

**Cover page fields:**
- Title: "Research Debate"
- Subject: [ticker/theme/sector]
- Date: [today]
- Contents: State of the Debate · Bull Case · Bear Case

**File naming:** `[subject-slug]-debate-[YYYY-MM-DD].pdf`

---

## What Is Not In Scope

- The short analyst and devil's advocate do not produce charts (charts are the buy-side analyst's output only)
- No iterative back-and-forth between agents (the bull does not see the bear's response)
- No standalone `/short-thesis` or `/devils-advocate` slash commands registered (the skill files exist and can be read, but are not registered as top-level skills in `package.json` — only `/research-debate` is)
- No caching of prior debate runs
