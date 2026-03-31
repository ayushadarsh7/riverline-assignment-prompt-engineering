#!/usr/bin/env python3
"""
Part 2 — Compare: Runs the full Part 1 evaluation pipeline (LLM judge + scorer)
on simulated transcripts, then generates before/after comparison JSONs.

Usage:
  python surgeon/compare.py                     # all 3 simulated calls
  python surgeon/compare.py call_10             # single call
"""

import json
import os
import sys
import time
import glob
from dotenv import load_dotenv
import google.generativeai as genai

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, ".env"))

from detective.llm_judge import (
    load_rules, load_full_rules, evaluate_transcript,
    build_per_transcript_report, SYSTEM_INSTRUCTION,
)
from detective.score_call import score_report

GOOGLE_API_KEY = os.getenv("google_api_key")
MODEL_NAME = os.getenv("LLM_MODEL", "gemini-2.5-flash")

RULES_FILE = os.path.join(BASE_DIR, "detective", "rules_and_violations.json")
PART2_DIR = os.getenv("CMP_INPUT_DIR",
                      os.path.join(BASE_DIR, "results", "part2"))
EVAL_DIR = os.getenv("CMP_EVAL_DIR",
                     os.path.join(PART2_DIR, "evaluated"))
ORIG_REPORTS_DIR = os.path.join(BASE_DIR, "results", "per_transcript")
ORIG_SCORED_DIR = os.path.join(BASE_DIR, "results")
ORIG_TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "prompt-engineer-assignment", "transcripts")

_cmp_calls_env = os.getenv("CMP_CALLS", "")
if _cmp_calls_env.lower() == "all":
    _cmp_dir = PART2_DIR
    TARGET_CALLS = sorted(
        f.replace("_simulated.json", "") for f in os.listdir(_cmp_dir)
        if f.startswith("call_") and f.endswith("_simulated.json")
    ) if os.path.isdir(_cmp_dir) else []
elif _cmp_calls_env:
    TARGET_CALLS = [c.strip() for c in _cmp_calls_env.split(",") if c.strip()]
else:
    TARGET_CALLS = ["call_07", "call_08", "call_10"]


def load_original_data(call_id):
    """Load original report, scored result, and transcript for a call."""
    report_path = os.path.join(ORIG_REPORTS_DIR, f"{call_id}_report.json")
    scored_path = os.path.join(ORIG_SCORED_DIR, f"{call_id}_scored.json")
    transcript_path = os.path.join(ORIG_TRANSCRIPTS_DIR, f"{call_id}.json")

    report = scored = transcript = None
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)
    if os.path.exists(scored_path):
        with open(scored_path) as f:
            scored = json.load(f)
    if os.path.exists(transcript_path):
        with open(transcript_path) as f:
            transcript = json.load(f)

    return report, scored, transcript


def build_comparison(call_id, orig_report, orig_scored, sim_report, sim_scored,
                     orig_transcript_data, sim_transcript_data):
    """Build a before/after comparison JSON."""
    orig_violations = orig_report.get("violations", [])
    sim_violations = sim_report.get("violations", [])

    orig_vids = {v["rule_id"] for v in orig_violations}
    sim_vids = {v["rule_id"] for v in sim_violations}

    fixed = orig_vids - sim_vids
    new_issues = sim_vids - orig_vids
    persistent = orig_vids & sim_vids

    orig_score = orig_scored.get("final_score", orig_report.get("score", "N/A"))
    orig_verdict = orig_scored.get("verdict", orig_report.get("verdict", "N/A"))
    sim_score = sim_scored.get("final_score", sim_report.get("score", "N/A"))
    sim_verdict = sim_scored.get("verdict", sim_report.get("verdict", "N/A"))

    # Side-by-side of first turns
    orig_turns = orig_transcript_data.get("transcript", [])
    sim_turns = sim_transcript_data.get("transcript", [])
    max_show = min(12, max(len(orig_turns), len(sim_turns)))

    side_by_side = []
    for i in range(max_show):
        entry = {"turn": i + 1}
        if i < len(orig_turns):
            entry["original"] = f"[{orig_turns[i]['speaker'].upper()}] {orig_turns[i]['text'][:250]}"
        if i < len(sim_turns):
            entry["simulated"] = f"[{sim_turns[i]['speaker'].upper()}] {sim_turns[i]['text'][:250]}"
        side_by_side.append(entry)

    score_delta = 0
    if isinstance(sim_score, (int, float)) and isinstance(orig_score, (int, float)):
        score_delta = round(sim_score - orig_score, 1)

    return {
        "call_id": call_id,
        "original": {
            "score": orig_score,
            "verdict": orig_verdict,
            "total_violations": orig_scored.get("total_violations", len(orig_violations)),
            "severity_breakdown": orig_scored.get("severity_breakdown", {}),
        },
        "simulated": {
            "score": sim_score,
            "verdict": sim_verdict,
            "total_violations": sim_scored.get("total_violations", len(sim_violations)),
            "severity_breakdown": sim_scored.get("severity_breakdown", {}),
        },
        "improvement": {
            "score_delta": score_delta,
            "violations_fixed": len(fixed),
            "new_issues": len(new_issues),
            "persistent_issues": len(persistent),
        },
        "fixed_violations": [
            {"rule_id": v["rule_id"], "rule_name": v["rule_name"], "severity": v["severity"]}
            for v in sorted(orig_violations, key=lambda x: x["rule_id"])
            if v["rule_id"] in fixed
        ],
        "new_violations": [
            {"rule_id": v["rule_id"], "rule_name": v.get("rule_name", ""), "severity": v.get("severity", "")}
            for v in sorted(sim_violations, key=lambda x: x["rule_id"])
            if v["rule_id"] in new_issues
        ],
        "persistent_violations": [
            {"rule_id": v["rule_id"], "rule_name": v.get("rule_name", ""), "severity": v.get("severity", "")}
            for v in sorted(sim_violations, key=lambda x: x["rule_id"])
            if v["rule_id"] in persistent
        ],
        "side_by_side_first_turns": side_by_side,
    }


def main():
    if not GOOGLE_API_KEY:
        print("ERROR: google_api_key not found in .env")
        return

    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=SYSTEM_INSTRUCTION,
    )

    rules = load_rules(RULES_FILE)
    full_rules = load_full_rules(RULES_FILE)
    os.makedirs(EVAL_DIR, exist_ok=True)

    if len(sys.argv) > 1:
        calls = [sys.argv[1]]
    else:
        calls = TARGET_CALLS

    # Collect simulated files
    sim_files = []
    for call_id in calls:
        path = os.path.join(PART2_DIR, f"{call_id}_simulated.json")
        if os.path.exists(path):
            sim_files.append((call_id, path))
        else:
            print(f"  WARNING: {path} not found, skipping {call_id}")

    print(f"Found {len(sim_files)} simulated transcripts to evaluate.")
    print(f"Model: {MODEL_NAME}\n")

    for i, (call_id, sim_path) in enumerate(sim_files):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(sim_files)}] Evaluating {call_id} (simulated)")
        print(f"{'='*60}")

        # --- Step 1: Load simulated transcript ---
        with open(sim_path) as f:
            sim_transcript_data = json.load(f)

        # --- Step 2: Run LLM Judge ---
        print(f"  Running LLM judge...")
        evaluations = evaluate_transcript(model, sim_transcript_data, rules)

        if evaluations is None:
            print(f"  FAILED — LLM judge returned no results for {call_id}")
            continue

        sim_filename = f"{call_id}_simulated.json"
        sim_report = build_per_transcript_report(
            sim_filename, sim_transcript_data, evaluations, full_rules
        )

        report_path = os.path.join(EVAL_DIR, f"{call_id}_simulated_report.json")
        with open(report_path, "w") as f:
            json.dump(sim_report, f, indent=2, ensure_ascii=False)
        print(f"  Judge report: {report_path}")
        print(f"  Judge score: {sim_report['score']} | Violations: {sim_report['total_violations']}")

        # --- Step 3: Run Scorer ---
        print(f"  Running scorer...")
        sim_scored = score_report(sim_report, sim_transcript_data)

        scored_path = os.path.join(EVAL_DIR, f"{call_id}_simulated_scored.json")
        with open(scored_path, "w") as f:
            json.dump(sim_scored, f, indent=2)
        print(f"  Scored: {scored_path}")
        print(f"  Final score: {sim_scored['final_score']} | Verdict: {sim_scored['verdict']}")

        # --- Step 4: Load original data and build comparison ---
        orig_report, orig_scored, orig_transcript = load_original_data(call_id)

        if orig_report and orig_scored:
            comparison = build_comparison(
                call_id, orig_report, orig_scored, sim_report, sim_scored,
                orig_transcript or {}, sim_transcript_data,
            )

            comp_path = os.path.join(PART2_DIR, f"{call_id}_comparison.json")
            with open(comp_path, "w") as f:
                json.dump(comparison, f, indent=2, ensure_ascii=False)

            delta = comparison["improvement"]["score_delta"]
            arrow = "+" if delta > 0 else ""
            print(f"\n  COMPARISON: {call_id}")
            print(f"    Original:  {comparison['original']['score']}/100 ({comparison['original']['verdict']})"
                  f"  — {comparison['original']['total_violations']} violations")
            print(f"    Simulated: {comparison['simulated']['score']}/100 ({comparison['simulated']['verdict']})"
                  f"  — {comparison['simulated']['total_violations']} violations")
            print(f"    Delta:     {arrow}{delta} points")
            print(f"    Fixed:     {comparison['improvement']['violations_fixed']} violations")
            print(f"    New:       {comparison['improvement']['new_issues']} violations")
            print(f"    Persistent:{comparison['improvement']['persistent_issues']} violations")
            print(f"    Saved: {comp_path}")
        else:
            print(f"  WARNING: Could not load original data for {call_id}, skipping comparison.")

        if i < len(sim_files) - 1:
            print("\n  Waiting before next evaluation...")
            time.sleep(8)

    # --- Summary ---
    print(f"\n{'='*60}")
    print("EVALUATION COMPLETE")
    print(f"{'='*60}")
    print(f"Evaluated reports: {EVAL_DIR}/")
    print(f"Comparisons:       {PART2_DIR}/call_*_comparison.json")


if __name__ == "__main__":
    main()
