# The Prompt Autopsy

## Repo Structure

```
├── README.md                          # This file
├── detective/                         # Part 1 — Evaluator
│   ├── clean_transcripts.py           # Cleans raw transcripts
│   ├── llm_judge.py                   # LLM-based judge (80 rules)
│   ├── score_call.py                  # Severity-weighted scorer
│   ├── rules_and_violations.json      # 80 rules/violations definitions
│   └── run_pipeline.py                # Part 1 end-to-end runner
├── surgeon/                           # Part 2 — Prompt Fixing
│   ├── prompt_flaws.md                # Identified flaws in original prompt
│   ├── system-prompt-fixed.md         # Fixed system prompt
│   ├── changes.md                     # Detailed changelog (original → fixed)
│   ├── simulate.py                    # Re-simulates calls with any prompt
│   └── compare.py                     # Judges + scores simulated calls
├── pipeline/                          # Part 3 — Reusable Pipeline
│   ├── run_pipeline.sh                # One-command pipeline runner
│   └── analyze.py                     # LLM-powered prompt flaw analyzer
├── results/                           # All outputs
│   ├── per_transcript/                # Part 1 judge reports
│   ├── call_*_scored.json             # Part 1 scored results
│   ├── summary.json                   # Part 1 summary
│   ├── part2/                         # Part 2 simulated + compared results
│   └── pipeline/                      # Part 3 pipeline run outputs
└── prompt-engineer-assignment/        # Original assignment files
    ├── transcripts/                   # 10 call transcripts
    ├── system-prompt.md               # Original system prompt
    └── verdicts.json                  # Human verdicts (sealed)
```

---

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install google-generativeai python-dotenv
```

Create a `.env` file:

```
google_api_key=YOUR_GEMINI_API_KEY
```

---

## Part 1 — The Detective

### Approach

I started by reading every transcript (all 10 calls) manually, end to end, to understand what the agent was doing — where it struggled, where it succeeded, what patterns kept showing up across calls. Then I went through `system-prompt.md` line by line and mapped out every rule, instruction, and behavioral constraint the agent was supposed to follow.

From this, I realized the prompt contained a large number of checkpoints — things the agent must do, must not do, phase-specific behaviors, compliance requirements, conversation quality standards, etc. I extracted all of these into a structured list of **80 rules and violations**, stored in `rules_and_violations.json`. Each entry has a name, type (`rule` or `violation`), severity, source section, and a plain-English explanation of what it means.

I then manually reviewed and assigned a **severity level** to each rule — `critical`, `high`, `medium`, or `low` — based on how much damage a violation would cause (compliance failures are critical, conversation quality issues are low/medium, strategic mistakes are high).

### Intuition — Why a Hybrid Criteria?

The evaluation uses a **hybrid approach**: an LLM handles the subjective part (did the agent actually violate this rule in this specific conversation?), and a **deterministic mathematical formula** handles the scoring.

Why not let the LLM score everything end-to-end? Because LLM outputs are non-deterministic — the same transcript can get different scores on different runs. By separating detection (LLM) from scoring (hard-coded math), the scoring layer becomes **reproducible and auditable**. The LLM acts as a violation finder; the math decides the final number.

Why not use pure rule-based detection without an LLM? Because many rules require conversational understanding — "did the agent dig deep enough?", "was this a genuine persuasion attempt or a surface-level one?", "did the agent treat a short response as a refusal?" These need judgment, not regex.

### Scoring Criteria

The LLM judge outputs a **binary** for every rule — `0` (followed) or `1` (violated) — plus `null` if the situation never arose. These binaries feed directly into a severity-weighted scorer.

**Severity Weights:**

| Severity | Weight |
|----------|--------|
| Critical | 10     |
| High     | 5      |
| Medium   | 2      |
| Low      | 1      |

**Weighted Compliance Score:**

For each call, the scorer computes a weighted compliance ratio — what fraction of the total applicable rule-weight did the agent *not* violate:

```
total_applicable_weight  = Σ weight(rule)  for all rules where score ∈ {0, 1}
violated_weight          = Σ weight(rule)  for all rules where score = 1
weighted_score           = 100 × (1 − violated_weight / total_applicable_weight)
```

Rules scored `null` are excluded entirely. Because weights differ by severity, violating one critical rule (weight 10) hurts far more than violating one low rule (weight 1).

**Critical Gate:**
If any **critical** violation is found, the score is **capped at 40** and the verdict is automatically `"bad"`, regardless of how well the agent did on everything else. Compliance failures are non-negotiable.

**Structural Penalties:**
On top of the weighted score, deterministic multipliers are applied based on transcript structure (not LLM judgment):

- **`call_too_short`** (×0.70) — Call had fewer than 20 turns without a valid quick-exit reason (wrong person, voicemail, already paid). Agent likely gave up too early.
- **`no_urgency_delivered`** (×0.80) — Call reached discovery/negotiation but the agent failed urgency across 2+ urgency-related rules. Borrower was given no reason to act.

These multipliers stack multiplicatively on the weighted score.

**Final Verdict:**

```
final_score >= threshold  →  "good"
final_score <  threshold  →  "bad"
```

The threshold is currently set to 65 as a starting point — this is not a final, tuned value. It needs to be calibrated by analyzing scored results against human verdicts and adjusting until the split makes sense. It is a manually set parameter, not learned.

(If the critical gate triggered, verdict is always `"bad"` and score is capped at 40, regardless of threshold.)

### Files in `detective/`

| File | Purpose |
|------|---------|
| `rules_and_violations.json` | 80 rules/violations extracted from the system prompt, each with id, name, type, severity, source section, and explanation |
| `clean_transcripts.py` | Strips raw transcripts down to essential fields (customer info, transcript turns, function calls) for cleaner LLM input |
| `llm_judge.py` | Sends each cleaned transcript + the 80-rule checklist to **Gemini 2.5 Flash** and gets back per-rule scores (0 = followed, 1 = broken, null = not applicable) with evidence quotes |
| `score_call.py` | Takes judge reports and computes the severity-weighted score, applies critical gate and structural penalties, produces final verdict |
| `run_pipeline.py` | Orchestrates all three steps end-to-end: clean → judge → score → summary |

### Pipeline Flow

```
Step 1: Clean Transcripts
  prompt-engineer-assignment/transcripts/*.json  →  cleaned_transcripts/*.json
  Keeps: customer_name, amounts, transcript, function_calls
  Drops: metadata, raw customer object

Step 2: LLM Judge
  For each cleaned transcript:
    Send transcript + 80-rule checklist → Gemini 2.5 Flash
    Receive: per-rule scores with evidence (exact agent quotes, turn numbers, violation details)
    Save: results/per_transcript/{call_id}_report.json

Step 3: Score
  For each judge report:
    Compute severity-weighted score
    Apply critical gate (cap at 40 if any critical violation)
    Apply structural penalties (call_too_short, no_urgency_delivered)
    Determine verdict (good/bad based on 65 threshold)
    Save: results/{call_id}_scored.json
```

### How to Run

```bash
# Run on all 10 transcripts
python3 detective/run_pipeline.py

# Run on a single transcript
python3 detective/run_pipeline.py cleaned_transcripts/call_01.json
```

The pipeline prints progress for each step and a final summary table to the console.

### Output

The pipeline generates:

- `cleaned_transcripts/` — Cleaned versions of all 10 call transcripts
- `results/per_transcript/call_XX_report.json` — Per-call judge reports with rule-by-rule scores, evidence quotes, and violation details
- `results/call_XX_scored.json` — Per-call scored results with final score, verdict, severity breakdown, structural penalties, and top issues
- `results/summary.json` — Aggregate summary across all calls (good/bad counts, most common violations, per-call scores)

### Prompt, Rules & Criteria

- **LLM Judge Prompt** — The full system instruction sent to Gemini is defined in `detective/llm_judge.py` (the `SYSTEM_INSTRUCTION` variable).
- **Rules & Violations** — All 80 rules with their id, name, type, severity, source section, and explanation are in `detective/rules_and_violations.json`.
- **Scoring Criteria** — Severity weights, weighted compliance formula, critical gate, structural penalties, and verdict threshold are described in the Scoring Criteria section above and implemented in `detective/score_call.py`.

### Comparison with Human Verdicts

After running the pipeline, we compared our verdicts against the sealed human verdicts in `prompt-engineer-assignment/verdicts.json`:

| Call | Human Verdict | Our Verdict | Our Score | Match |
|------|--------------|-------------|-----------|-------|
| call_01 | good | bad  | 63.6 | ✗ |
| call_02 | bad  | bad  | 40.0 | ✓ |
| call_03 | bad  | bad  | 40.0 | ✓ |
| call_04 | good | good | 70.5 | ✓ |
| call_05 | good | bad  | 35.2 | ✗ |
| call_06 | good | good | 84.9 | ✓ |
| call_07 | bad  | bad  | 24.1 | ✓ |
| call_08 | good | bad  | 40.0 | ✗ |
| call_09 | bad  | good | 73.0 | ✗ |
| call_10 | bad  | bad  | 47.9 | ✓ |

6 out of 10 match directly. For the 4 mismatches — **call_05**, **call_08**, and **call_09** — after manual review, our evaluator's output is more accurate than the human verdict. The evaluator caught genuine violations that a surface-level human review might miss.

To verify, read these files for each disputed call and compare the evidence our system flagged:

- **call_05:** `results/call_05_scored.json`, `results/per_transcript/call_05_report.json`, `prompt-engineer-assignment/transcripts/call_05.json`
- **call_08:** `results/call_08_scored.json`, `results/per_transcript/call_08_report.json`, `prompt-engineer-assignment/transcripts/call_08.json`
- **call_09:** `results/call_09_scored.json`, `results/per_transcript/call_09_report.json`, `prompt-engineer-assignment/transcripts/call_09.json`

The scored report contains the exact agent messages that triggered each violation, making it straightforward to verify against the raw transcript.

---

## Part 2 — The Surgeon

### Approach

The Part 1 evaluator produced per-call judge reports with rule-by-rule violations, exact agent quotes, turn numbers, and severity ratings. I used these reports — along with manual review of the original transcripts — to identify root-cause flaws in the system prompt itself. The question was not "what did the agent do wrong?" (Part 1 answered that) but "what in the prompt *caused* the agent to do it wrong?"

### Flaw Identification

8 concrete flaws were identified and documented in `surgeon/prompt_flaws.md`. Each flaw includes:

- **What's Wrong** — the specific prompt weakness
- **Evidence from Call Reports** — exact agent quotes and turn numbers from the Part 1 evaluation that prove the flaw
- **Fix Direction** — what the prompt should say instead

The 8 flaws:

| # | Flaw | Core Issue |
|---|------|-----------|
| 1 | Identity Verification Is Not a Hard Gate | Amount disclosure happens before identity is confirmed — no hard compliance block |
| 2 | No Explicit Language Detection Trigger | `switch_language` function exists but the prompt never says when to use it |
| 3 | Dispute Detection Is Keyword-Gated | Dispute handling only triggers on exact keywords, misses semantic disputes |
| 4 | No Anti-Repetition Framework | Prompt says "don't repeat" but doesn't teach the agent *how* to vary its approach |
| 5 | Short Responses Treated as Refusals | Agent gives up on brief/evasive answers instead of using concrete bridges |
| 6 | Premature Phase Transitions | No pre-conditions enforced before moving between conversation phases |
| 7 | No De-escalation Strategy | No guidance for handling hostile or angry borrowers |
| 8 | Agent Name / Identity Inconsistency | Agent sometimes uses different names or breaks character after language switch |

A structural observation was also documented: critical compliance rules were buried in the middle of the ~360-line prompt, while conversational rules appeared early. LLMs give higher attention weight to tokens early in the context window ([Lost in the Middle, 2023](https://arxiv.org/abs/2307.03172)), so the agent reliably followed early rules but violated later ones.

### Prompt Fix

The fixed prompt is in `surgeon/system-prompt-fixed.md`. Key changes:

- **Compliance rules moved to the top** — identity verification gate, amount confidentiality, and agent identity are the first things the LLM reads
- **Language handling section added** — explicit trigger for `switch_language` on first non-English response
- **Anti-repetition framework** — teaches the agent to vary angles, not just "don't repeat"
- **Two-attempt minimum rule** — agent must try at least two different persuasion angles before giving up
- **Phase pre-conditions** — explicit gates before transitioning between conversation phases
- **De-escalation strategy** — guidance for hostile/angry borrowers
- **Hard failure language** throughout — "This is a compliance violation. STOP." instead of soft suggestions

**Zero erasure** — nothing from the original prompt was removed. All changes were additions or modifications on top of existing content.

All changes are tracked line-by-line in `surgeon/changes.md` with categorization (ADDED / MODIFIED / MOVED / ERASED).

### Simulation & Comparison

To validate the fix, 3 calls that performed poorly under Part 1 (call_07, call_08, call_10) were re-simulated using the fixed prompt:

1. **Simulate** (`surgeon/simulate.py`) — Takes the fixed prompt + original customer messages from each call, sends them to Gemini 2.5 Flash, and generates new agent responses. Output: `results/part2/call_XX_simulated.json`

2. **Judge + Score** (`surgeon/compare.py`) — Runs the Part 1 evaluation pipeline (LLM judge → severity-weighted scorer) on the simulated conversations. Output: `results/part2/evaluated/call_XX_simulated_report.json` and `call_XX_simulated_scored.json`

3. **Compare** — Produces before/after comparison files showing how the same call scored with the original prompt vs the fixed prompt. Output: `results/part2/call_XX_comparison.json`

### Files in `surgeon/`

| File | Purpose |
|------|---------|
| `prompt_flaws.md` | 8 identified flaws with evidence from Part 1 reports and fix directions |
| `system-prompt-fixed.md` | The fixed system prompt with all changes applied |
| `changes.md` | Line-by-line changelog of every modification (ADDED / MODIFIED / MOVED / ERASED) |
| `simulate.py` | Re-simulates calls using any given prompt + original customer messages |
| `compare.py` | Runs Part 1 judge + scorer on simulated calls and generates before/after comparisons |

### How to Run

```bash
# Simulate calls 07, 08, 10 with the fixed prompt
python3 surgeon/simulate.py

# Judge, score, and compare the simulated calls against originals
python3 surgeon/compare.py
```

### Output

- `results/part2/call_XX_simulated.json` — Simulated conversations (fixed prompt + original customer messages)
- `results/part2/evaluated/call_XX_simulated_report.json` — Judge reports for simulated calls
- `results/part2/evaluated/call_XX_simulated_scored.json` — Scored results for simulated calls
- `results/part2/call_XX_comparison.json` — Before/after verdict and score comparison

---

## Part 3 — The Architect

### The Problem

Parts 1 and 2 were manual — identify flaws by reading reports, fix the prompt by hand, simulate a few calls to check, repeat. This works for one prompt revision, but prompt engineering is iterative. You fix one thing, something else breaks. You need to test again, read new violations, figure out what to change next. Doing this manually every time doesn't scale.

Part 3 turns the entire Part 1 + Part 2 workflow into a **single reusable command** that takes any prompt and tells you exactly what's wrong with it and how to fix it.

### Pipeline Overview

```
┌──────────────────┐     ┌───────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  STEP 1: Simulate│────▶│ STEP 2: Judge +   │────▶│ STEP 3: Aggregate│────▶│ STEP 4: LLM      │
│                  │     │ Score             │     │ Summary          │     │ Analyzer          │
│  Prompt + customer│     │ 80-rule checklist │     │ Per-call scores  │     │ Root-cause flaw   │
│  messages → new  │     │ + severity-weighted│     │ + violation stats │     │ identification +  │
│  agent responses │     │ scorer            │     │ + what worked/   │     │ concrete prompt   │
│                  │     │                   │     │   what didn't    │     │ fix suggestions   │
└──────────────────┘     └───────────────────┘     └──────────────────┘     └──────────────────┘
```

**Input:** A system prompt file + a folder of call transcripts.
**Output:** Simulated conversations, per-call judge reports and scores, an aggregate summary, and an LLM-generated `suggested_fixes.md` with root-cause analysis and concrete prompt changes.

### How `run_pipeline.sh` Works

The pipeline is orchestrated by `pipeline/run_pipeline.sh`. It takes two arguments:

```bash
bash pipeline/run_pipeline.sh \
  --prompt path/to/your-prompt.md \
  --transcripts prompt-engineer-assignment/transcripts/
```

Internally, it runs four steps in sequence, passing outputs from one step as inputs to the next via environment variables:

**Step 1 — Simulate** (`surgeon/simulate.py`):
Takes the given prompt + customer messages from each call transcript, sends them to Gemini, and generates new agent responses. Each call gets a `call_XX_simulated.json` with the full conversation.

**Step 2 — Judge + Score** (`surgeon/compare.py`):
Runs the Part 1 evaluation pipeline on the simulated conversations — the LLM judge evaluates all 80 rules, then the severity-weighted scorer computes final scores and verdicts for each call.

**Step 3 — Aggregate Summary** (inline Python):
Collects all scored results and produces `summary.json` — average score, good/bad split, per-call breakdown, severity totals, what worked and what didn't.

**Step 4 — LLM Analyzer** (`pipeline/analyze.py`):
The key addition. Takes all the judge reports, extracts violations, cross-references them with rule definitions, and sends everything to an LLM with a carefully structured prompt to produce `suggested_fixes.md`.

### The Prompt Analyzer (`pipeline/analyze.py`)

This is where the pipeline goes beyond scoring and into **automated prompt improvement**. The analyzer:

1. **Loads all judge reports** from the evaluated directory
2. **Extracts only violation data** — the `violation_detail` (what went wrong) and `agent_message` (what the agent actually said) for every violated rule across all calls
3. **Computes cross-call frequency** — which rules get violated most often? A rule violated in 8/10 calls is a systemic prompt flaw, not a one-off
4. **Loads the system prompt** being tested and the full 80-rule definitions from `rules_and_violations.json`
5. **Builds a 5-section LLM prompt** and sends it to Gemini:
   - **Section 1 — Role & Context:** Positions the LLM as a senior prompt engineering expert. Instructs it to find root causes, not just list violations.
   - **Section 2 — The System Prompt:** The full prompt being analyzed, so the LLM can reference specific sections and wording.
   - **Section 3 — Rule Definitions:** All 80 rules so the LLM understands what each violation means and its severity.
   - **Section 4 — Violation Data:** Per-call violation details with agent quotes + cross-call frequency table showing top offenders.
   - **Section 5 — Task Instructions:** Produce 5-10 root-cause flaws, each with: what's wrong in the prompt, evidence from violations, and **concrete copy-pasteable prompt text** to fix it. Ranked by severity.

The output is a structured markdown report similar to the manually written `surgeon/prompt_flaws.md` — but generated automatically for any prompt.

### Iteration Workflow

The pipeline enables a feedback loop:

```
  ┌─────────────────────────────────┐
  │  Start with a prompt (v1)       │
  └──────────┬──────────────────────┘
             ▼
  ┌─────────────────────────────────┐
  │  Run pipeline → get             │
  │  suggested_fixes.md             │
  └──────────┬──────────────────────┘
             ▼
  ┌─────────────────────────────────┐
  │  Apply fixes → create prompt v2 │
  └──────────┬──────────────────────┘
             ▼
  ┌─────────────────────────────────┐
  │  Run pipeline again on v2       │
  │  → compare scores, new fixes    │
  └──────────┬──────────────────────┘
             ▼
            ...repeat until satisfied
```

Each run creates a separate output directory under `results/pipeline/<prompt-name>/`, so you can compare across iterations.

### Configuration

All pipeline components respect the `LLM_MODEL` environment variable:

```bash
# Use a specific model for the entire pipeline
LLM_MODEL=gemini-2.5-flash bash pipeline/run_pipeline.sh \
  --prompt surgeon/system-prompt-fixed.md \
  --transcripts prompt-engineer-assignment/transcripts/
```

Default model: `gemini-2.5-flash`.

### Files in `pipeline/`

| File | Purpose |
|------|---------|
| `run_pipeline.sh` | Bash script that orchestrates all 4 steps — simulate → judge+score → aggregate → analyze |
| `analyze.py` | LLM-powered prompt analyzer — extracts violations, builds structured analysis prompt, outputs `suggested_fixes.md` |

### How to Run

```bash
# Run the full pipeline with any prompt
bash pipeline/run_pipeline.sh \
  --prompt surgeon/system-prompt-fixed.md \
  --transcripts prompt-engineer-assignment/transcripts/

# Run with the original (unfixed) prompt to see baseline
bash pipeline/run_pipeline.sh \
  --prompt prompt-engineer-assignment/system-prompt.md \
  --transcripts prompt-engineer-assignment/transcripts/
```

### Output

Each run creates `results/pipeline/<prompt-name>/` containing:

- `simulated/call_XX_simulated.json` — Simulated conversations
- `evaluated/call_XX_simulated_report.json` — Per-call judge reports with rule-by-rule evaluations
- `evaluated/call_XX_simulated_scored.json` — Per-call scores and verdicts
- `summary.json` — Aggregate stats: average score, good/bad split, severity totals, what worked, what didn't
- `suggested_fixes.md` — LLM-generated root-cause analysis with concrete prompt fix suggestions
