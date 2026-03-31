#!/usr/bin/env python3
"""
Step 1: Cleans raw transcripts by keeping only essential fields.

Usage: python detective/clean_transcripts.py
"""

import json
import glob
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_DIR = os.path.join(BASE_DIR, "prompt-engineer-assignment", "transcripts")
OUTPUT_DIR = os.path.join(BASE_DIR, "cleaned_transcripts")

os.makedirs(OUTPUT_DIR, exist_ok=True)

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

    turns = len(raw["transcript"])
    fn_calls = len(raw["function_calls"])
    print(f"{os.path.basename(filepath):>15}  ->  {turns} turns, {fn_calls} function calls  ✓")

print(f"\nDone. Cleaned {len(list(glob.glob(os.path.join(OUTPUT_DIR, 'call_*.json'))))} files in cleaned_transcripts/")
