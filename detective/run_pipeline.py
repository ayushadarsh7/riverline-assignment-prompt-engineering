#!/usr/bin/env python3
"""
Part 1 Pipeline: Runs all 3 steps end-to-end.

Usage:
  python detective/run_pipeline.py                                    # all transcripts
  python detective/run_pipeline.py cleaned_transcripts/call_01.json   # single file
"""

import json
import os
import sys
import time
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DETECTIVE_DIR = os.path.join(BASE_DIR, "detective")

sys.path.insert(0, DETECTIVE_DIR)

from clean_transcripts import INPUT_DIR, OUTPUT_DIR
import clean_transcripts  # noqa: reuse its constants
from llm_judge import (
    load_rules, load_full_rules, build_per_transcript_report,
    evaluate_transcript, RULES_FILE, PER_TRANSCRIPT_DIR, TRANSCRIPTS_DIR,
    GOOGLE_API_KEY, MODEL_NAME, SYSTEM_INSTRUCTION, RESULTS_DIR,
)
from score_call import score_report, load_transcript

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(os.path.join(BASE_DIR, ".env"))


def step1_clean():
    """Clean raw transcripts into cleaned_transcripts/."""
    print("=" * 60)
    print("STEP 1: Cleaning transcripts")
    print("=" * 60)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    count = 0
    for filepath in sorted(glob.glob(os.path.join(INPUT_DIR, "call_*.json"))):
        with open(filepath) as f:
            raw = json.load(f)
        cleaned = {
            "customer_name": raw["customer"]["name"],
            "pending_amount": raw["customer"]["pending_amount"],
            "closure_amount": raw["customer"]["closure_amount"],
            "settlement_amount": raw["customer"]["settlement_amount"],
            "transcript": raw["transcript"],
            "function_calls": raw["function_calls"],
        }
        out_path = os.path.join(OUTPUT_DIR, os.path.basename(filepath))
        with open(out_path, "w") as f:
            json.dump(cleaned, f, indent=2)
        count += 1

    print(f"  Cleaned {count} transcripts -> cleaned_transcripts/\n")


def step2_judge(model, rules, full_rules, transcript_files):
    """Run LLM judge on each transcript, return reports."""
    print("=" * 60)
    print("STEP 2: LLM Judge evaluation")
    print("=" * 60)

    os.makedirs(PER_TRANSCRIPT_DIR, exist_ok=True)
    reports = []

    for i, filepath in enumerate(transcript_files):
        filename = os.path.basename(filepath)
        call_id = filename.replace(".json", "")
        print(f"  [{i+1}/{len(transcript_files)}] {filename}...", end=" ", flush=True)

        with open(filepath) as f:
            transcript_data = json.load(f)

        evaluations = evaluate_transcript(model, transcript_data, rules)

        if evaluations:
            report = build_per_transcript_report(filename, transcript_data, evaluations, full_rules)
            reports.append(report)

            report_path = os.path.join(PER_TRANSCRIPT_DIR, f"{call_id}_report.json")
            with open(report_path, "w") as f:
                json.dump(report, f, indent=2)

            print(f"violations: {report['total_violations']}/{report['total_applicable']}")
        else:
            reports.append({"file": filename, "customer_name": transcript_data["customer_name"], "error": "Failed"})
            print("FAILED")

        if i < len(transcript_files) - 1:
            time.sleep(8)

    print()
    return reports


def step3_score(reports):
    """Score each report and produce final verdicts."""
    print("=" * 60)
    print("STEP 3: Scoring")
    print("=" * 60)

    part1_dir = os.path.join(BASE_DIR, "results", "part1")
    os.makedirs(part1_dir, exist_ok=True)
    scored = []

    for report in reports:
        if "error" in report:
            print(f"  {report['file']:>15}  SKIPPED (judge failed)")
            continue

        transcript = load_transcript(report["file"])
        result = score_report(report, transcript)
        scored.append(result)

        tag = "GOOD" if result["verdict"] == "good" else "BAD "
        crit = " [CRITICAL]" if result["critical_gate_triggered"] else ""
        struct = f" [STRUCT x{result['structural_multiplier']}]" if result["structural_multiplier"] < 1.0 else ""
        print(f"  {result['file']:>15}  {tag}  {result['final_score']:5.1f}/100{crit}{struct}")

        call_id = result["file"].replace(".json", "")
        with open(os.path.join(part1_dir, f"{call_id}_scored.json"), "w") as f:
            json.dump(result, f, indent=2)

    print()
    return scored


def print_summary(scored):
    """Print final summary."""
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)

    good = [s for s in scored if s["verdict"] == "good"]
    bad = [s for s in scored if s["verdict"] == "bad"]

    print(f"  Total calls:  {len(scored)}")
    print(f"  Good:         {len(good)}  {[s['file'] for s in good]}")
    print(f"  Bad:          {len(bad)}  {[s['file'] for s in bad]}")
    print()

    for s in scored:
        tag = "GOOD" if s["verdict"] == "good" else "BAD "
        print(f"  {s['file']:>15}  {tag}  {s['final_score']:5.1f}  {s['reason'][:80]}")

    print()


def main():
    api_key = os.getenv("google_api_key") or GOOGLE_API_KEY
    if not api_key:
        print("ERROR: google_api_key not found in .env")
        sys.exit(1)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=MODEL_NAME, system_instruction=SYSTEM_INSTRUCTION)

    rules = load_rules(RULES_FILE)
    full_rules = load_full_rules(RULES_FILE)

    # --- Determine input ---
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        single_file = arg if os.path.isabs(arg) else os.path.join(os.getcwd(), arg)

        if not os.path.exists(single_file):
            raw_path = os.path.join(BASE_DIR, "prompt-engineer-assignment", "transcripts", os.path.basename(arg))
            if os.path.exists(raw_path):
                step1_clean()
                single_file = os.path.join(TRANSCRIPTS_DIR, os.path.basename(arg))
            else:
                print(f"ERROR: File not found: {arg}")
                sys.exit(1)

        transcript_files = [single_file]
        print(f"\nRunning pipeline on: {os.path.basename(single_file)}\n")
    else:
        step1_clean()
        transcript_files = sorted(glob.glob(os.path.join(TRANSCRIPTS_DIR, "call_*.json")))
        print(f"\nRunning pipeline on all {len(transcript_files)} transcripts\n")

    os.makedirs(os.path.join(BASE_DIR, "results"), exist_ok=True)

    reports = step2_judge(model, rules, full_rules, transcript_files)
    scored = step3_score(reports)
    print_summary(scored)


if __name__ == "__main__":
    main()
