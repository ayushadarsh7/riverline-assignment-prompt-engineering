#!/usr/bin/env bash
#
# Part 3 — Prompt Iteration Pipeline
#
# Simulates calls with a given system prompt, scores them, and
# generates an aggregate report with LLM-suggested prompt fixes.
#
# Usage:
#   bash pipeline/run_pipeline.sh --prompt path/to/prompt.md --transcripts path/to/transcripts/
#
# Example:
#   bash pipeline/run_pipeline.sh \
#     --prompt surgeon/system-prompt-fixed.md \
#     --transcripts prompt-engineer-assignment/transcripts/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BASE_DIR"

# ── Activate venv if available ──
if [ -f "$BASE_DIR/venv/bin/activate" ]; then
    source "$BASE_DIR/venv/bin/activate"
fi

PYTHON="${PYTHON:-python3}"

# ── Parse arguments ──
PROMPT_PATH=""
TRANSCRIPTS_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prompt)
            PROMPT_PATH="$2"; shift 2 ;;
        --transcripts)
            TRANSCRIPTS_DIR="$2"; shift 2 ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: bash pipeline/run_pipeline.sh --prompt <path> --transcripts <dir>"
            exit 1 ;;
    esac
done

if [ -z "$PROMPT_PATH" ] || [ -z "$TRANSCRIPTS_DIR" ]; then
    echo "ERROR: --prompt and --transcripts are required."
    echo "Usage: bash pipeline/run_pipeline.sh --prompt <path> --transcripts <dir>"
    exit 1
fi

if [ ! -f "$PROMPT_PATH" ]; then
    echo "ERROR: Prompt file not found: $PROMPT_PATH"
    exit 1
fi

if [ ! -d "$TRANSCRIPTS_DIR" ]; then
    echo "ERROR: Transcripts directory not found: $TRANSCRIPTS_DIR"
    exit 1
fi

# ── Set up output directory ──
PROMPT_BASENAME="$(basename "$PROMPT_PATH" .md)"
OUTPUT_DIR="results/pipeline/${PROMPT_BASENAME}"
SIM_DIR="${OUTPUT_DIR}/simulated"
EVAL_DIR="${OUTPUT_DIR}/evaluated"

mkdir -p "$SIM_DIR" "$EVAL_DIR"

# ── Discover calls ──
CALL_LIST=$(ls "$TRANSCRIPTS_DIR"/call_*.json 2>/dev/null | xargs -I{} basename {} .json | sort)
CALL_COUNT=$(echo "$CALL_LIST" | wc -l | tr -d ' ')

if [ -z "$CALL_LIST" ]; then
    echo "ERROR: No call_*.json files found in $TRANSCRIPTS_DIR"
    exit 1
fi

CALL_CSV=$(echo "$CALL_LIST" | paste -sd',' -)

echo "============================================================"
echo "  PROMPT ITERATION PIPELINE"
echo "============================================================"
echo "  Prompt:       $PROMPT_PATH"
echo "  Transcripts:  $TRANSCRIPTS_DIR"
echo "  Calls found:  $CALL_COUNT"
echo "  Output:       $OUTPUT_DIR/"
echo "============================================================"
echo ""

# ── Step A: Simulate ──
echo "============================================================"
echo "  STEP 1/4: Simulating calls with provided prompt"
echo "============================================================"

SIM_PROMPT_PATH="$PROMPT_PATH" \
SIM_TRANSCRIPTS_DIR="$TRANSCRIPTS_DIR" \
SIM_OUTPUT_DIR="$SIM_DIR" \
SIM_CALLS="$CALL_CSV" \
    $PYTHON surgeon/simulate.py

echo ""

# ── Step B: Judge + Score + Compare ──
echo "============================================================"
echo "  STEP 2/4: Running LLM judge + scorer on simulated calls"
echo "============================================================"

CMP_INPUT_DIR="$SIM_DIR" \
CMP_EVAL_DIR="$EVAL_DIR" \
CMP_CALLS="all" \
    $PYTHON surgeon/compare.py

echo ""

# ── Step C: Aggregate Summary ──
echo "============================================================"
echo "  STEP 3/4: Generating aggregate summary"
echo "============================================================"

$PYTHON -c "
import json, glob, os

eval_dir = '$EVAL_DIR'
output_dir = '$OUTPUT_DIR'
prompt_name = '$PROMPT_BASENAME'

scored_files = sorted(glob.glob(os.path.join(eval_dir, '*_scored.json')))
results = []
for f in scored_files:
    with open(f) as fh:
        results.append(json.load(fh))

if not results:
    print('  WARNING: No scored files found')
    summary = {'prompt': prompt_name, 'total_calls': 0, 'per_call': []}
else:
    scores = [r['final_score'] for r in results]
    good = [r for r in results if r['verdict'] == 'good']
    bad = [r for r in results if r['verdict'] == 'bad']
    avg = round(sum(scores) / len(scores), 1)

    from collections import Counter
    all_violations = Counter()
    for r in results:
        sb = r.get('severity_breakdown', {})
        for sev, cnt in sb.items():
            all_violations[sev] += cnt

    what_worked = []
    what_didnt = []
    for r in results:
        if r['verdict'] == 'good':
            what_worked.append(f\"{r['file']}: score {r['final_score']}, {r['total_violations']} violations\")
        else:
            what_didnt.append(f\"{r['file']}: score {r['final_score']}, {r['total_violations']} violations — {r.get('reason', '')[:120]}\")

    summary = {
        'prompt': prompt_name,
        'total_calls': len(results),
        'good_calls': len(good),
        'bad_calls': len(bad),
        'average_score': avg,
        'severity_totals': dict(all_violations),
        'per_call': [
            {'file': r['file'], 'score': r['final_score'], 'verdict': r['verdict'],
             'violations': r['total_violations']}
            for r in results
        ],
        'what_worked': what_worked,
        'what_didnt': what_didnt,
    }

    print(f'  Calls scored: {len(results)}')
    print(f'  Average score: {avg}')
    print(f'  Good: {len(good)} | Bad: {len(bad)}')
    for r in results:
        tag = 'GOOD' if r['verdict'] == 'good' else 'BAD '
        print(f\"    {r['file']:>30}  {tag}  {r['final_score']:5.1f}/100  ({r['total_violations']} violations)\")

out_path = os.path.join(output_dir, 'summary.json')
with open(out_path, 'w') as fh:
    json.dump(summary, fh, indent=2)
print(f'  Saved: {out_path}')
"

echo ""

# ── Step D: LLM Analyzer ──
echo "============================================================"
echo "  STEP 4/4: Running LLM analyzer for prompt improvement suggestions"
echo "============================================================"

$PYTHON pipeline/analyze.py \
    --reports-dir "$EVAL_DIR" \
    --prompt "$PROMPT_PATH" \
    --output "${OUTPUT_DIR}/suggested_fixes.md"

echo ""

# ── Final Summary ──
echo "============================================================"
echo "  PIPELINE COMPLETE"
echo "============================================================"
echo ""
echo "  Output directory: $OUTPUT_DIR/"
echo ""
echo "  Files:"
echo "    simulated/        — Simulated transcripts"
echo "    evaluated/        — Judge reports + scored results"
echo "    summary.json      — Aggregate scores and stats"
echo "    suggested_fixes.md — LLM-suggested prompt improvements"
echo ""
echo "  To compare with a different prompt, run:"
echo "    bash pipeline/run_pipeline.sh --prompt <new-prompt.md> --transcripts $TRANSCRIPTS_DIR"
echo ""
