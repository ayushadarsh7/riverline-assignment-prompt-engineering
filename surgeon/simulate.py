#!/usr/bin/env python3
"""
Part 2 — Re-simulation: Feeds borrower messages from bad calls into
Gemini using the fixed system prompt. Generates simulated transcripts
and before/after comparisons.

Uses a single-prompt approach (1 API call per transcript) to stay
within rate limits.

Usage:
  python surgeon/simulate.py                          # all 3 calls (07, 08, 10)
  python surgeon/simulate.py call_10                  # single call
"""

import json
import os
import re
import sys
import time
from dotenv import load_dotenv
import google.generativeai as genai

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GOOGLE_API_KEY = os.getenv("google_api_key")
MODEL_NAME = os.getenv("LLM_MODEL", "gemini-2.5-flash")

FIXED_PROMPT_PATH = os.getenv("SIM_PROMPT_PATH",
                              os.path.join(BASE_DIR, "surgeon", "system-prompt-fixed.md"))
TRANSCRIPTS_DIR = os.getenv("SIM_TRANSCRIPTS_DIR",
                            os.path.join(BASE_DIR, "prompt-engineer-assignment", "transcripts"))
PART2_DIR = os.getenv("SIM_OUTPUT_DIR",
                      os.path.join(BASE_DIR, "results", "part2"))

_sim_calls_env = os.getenv("SIM_CALLS", "")
if _sim_calls_env.lower() == "all":
    TARGET_CALLS = sorted(
        os.path.splitext(f)[0] for f in os.listdir(TRANSCRIPTS_DIR)
        if f.startswith("call_") and f.endswith(".json")
    )
elif _sim_calls_env:
    TARGET_CALLS = [c.strip() for c in _sim_calls_env.split(",") if c.strip()]
else:
    TARGET_CALLS = ["call_07", "call_08", "call_10"]

TEMPLATE_DEFAULTS = {
    "due_date": "2024-01-15",
    "today_date": "2025-03-30",
    "today_day": "Sunday",
    "loan_id": "DEMO-EDU-001",
}


def build_system_instruction(prompt_path, customer_data):
    """
    Read any system prompt file and fill in per-call customer variables.
    Supports two formats:
      - Markdown with triple-backtick code blocks (extracts prompt sections,
        drops the last block which is typically function-definition JSON)
      - Plain text / markdown without code blocks (uses entire file content)
    Template variables like {{customer_name}} are replaced with actual values.
    """
    with open(prompt_path) as f:
        raw = f.read()

    blocks = re.findall(r"```(?:json)?\n(.*?)```", raw, re.DOTALL)

    if blocks:
        last_block = blocks[-1].strip()
        is_func_def = last_block.startswith("[") or last_block.startswith("{")
        prompt_blocks = blocks[:-1] if is_func_def else blocks
        system_text = "\n\n---\n\n".join(prompt_blocks)
    else:
        system_text = raw

    variables = {
        "customer_name": customer_data.get("name", "Customer"),
        "pending_amount": customer_data.get("pending_amount", ""),
        "tos": customer_data.get("pending_amount", ""),
        "pos": customer_data.get("closure_amount", "zero"),
        "settlement_amount": customer_data.get("settlement_amount", ""),
        "dpd": customer_data.get("dpd", ""),
    }
    variables.update(TEMPLATE_DEFAULTS)

    for key, val in variables.items():
        system_text = system_text.replace("{{" + key + "}}", str(val))

    return system_text


def extract_customer_messages(transcript):
    """Extract customer messages in order, grouping consecutive ones."""
    groups = []
    current_texts = []

    for entry in transcript:
        if entry["speaker"] == "customer":
            current_texts.append(entry["text"])
        else:
            if current_texts:
                groups.append(" ".join(current_texts))
                current_texts = []

    if current_texts:
        groups.append(" ".join(current_texts))

    return groups


def build_simulation_prompt(system_instruction, customer_messages):
    """Build a single prompt that asks the model to simulate the full call."""
    numbered_messages = "\n".join(
        f"  CUSTOMER_MSG_{i+1}: \"{msg}\""
        for i, msg in enumerate(customer_messages)
    )

    return f"""You are the AI agent "Alex" on a debt collection call. Your system prompt is provided above.

A greeting has ALREADY been spoken to the borrower:
"Hello, this is Alex from DemoCompany, calling about your DemoLender loan. We reviewed your account and have a good offer to help close it. Can we talk for a moment?"

Below are ALL of the borrower's messages in chronological order. For each one, generate what you (Alex) would say in response, and any function calls you would make.

BORROWER MESSAGES:
{numbered_messages}

INSTRUCTIONS:
- Respond to each customer message in order.
- Follow your system prompt EXACTLY — especially identity verification, language handling, and the two-attempt rule.
- For each customer message, output your agent response AND any function calls.
- If you would call end_call, stop generating after that point.
- Be realistic — this is a voice call, keep responses short and natural.

OUTPUT FORMAT — Return a JSON object with this exact structure:
{{
  "turns": [
    {{
      "customer_message": "<the customer's message>",
      "agent_response": "<what you (Alex) would say>",
      "function_calls": [
        {{"function": "<function_name>", "params": {{...}}}}
      ]
    }}
  ]
}}

Rules for the JSON:
- "function_calls" is an array (can be empty if no function call).
- If you call end_call, that should be the LAST turn.
- agent_response must NEVER be empty — always say something before/after a function call.
- Generate responses for ALL customer messages unless you end the call earlier."""

    return prompt


def simulate_call_single_prompt(model, system_instruction, customer_messages, call_id):
    """Simulate the full call in a single API call."""
    prompt = build_simulation_prompt(system_instruction, customer_messages)

    print(f"  Sending simulation request ({len(customer_messages)} customer messages)...")

    for attempt in range(3):
        try:
            response = model.generate_content(
                prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.3,
                },
            )
            result = json.loads(response.text)

            if "turns" in result and isinstance(result["turns"], list):
                print(f"  Got {len(result['turns'])} simulated turns.")
                return result["turns"]

            print(f"  Unexpected format (attempt {attempt+1}), retrying...")

        except json.JSONDecodeError as e:
            print(f"  JSON parse error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(10)
        except Exception as e:
            print(f"  API error (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(15)

    return None


def turns_to_transcript_format(simulated_turns):
    """Convert simulated turns to the standard transcript + function_calls format."""
    transcript = []
    function_calls = []
    turn_counter = 0

    for turn in simulated_turns:
        # Customer message
        turn_counter += 1
        transcript.append({
            "speaker": "customer",
            "text": turn.get("customer_message", ""),
        })

        # Function calls (before or alongside agent response)
        for fc in turn.get("function_calls", []):
            turn_counter += 1
            function_calls.append({
                "turn": turn_counter,
                "function": fc.get("function", ""),
                "params": fc.get("params", {}),
            })

        # Agent response
        agent_text = turn.get("agent_response", "")
        if agent_text:
            turn_counter += 1
            transcript.append({
                "speaker": "agent",
                "text": agent_text,
            })

    return transcript, function_calls


def save_simulated_transcript(call_id, customer_data, transcript, function_calls, output_dir):
    result = {
        "customer_name": customer_data.get("name", ""),
        "pending_amount": customer_data.get("pending_amount", ""),
        "closure_amount": customer_data.get("closure_amount", ""),
        "settlement_amount": customer_data.get("settlement_amount", ""),
        "transcript": transcript,
        "function_calls": function_calls,
    }

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{call_id}_simulated.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  Saved: {path}")
    return path


def load_original_report(call_id):
    """Load the original Part 1 report for comparison."""
    per_dir = os.path.join(BASE_DIR, "results", "per_transcript")
    path = os.path.join(per_dir, f"{call_id}_report.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def load_original_scored(call_id):
    """Load the original Part 1 scored report for comparison."""
    part1_dir = os.path.join(BASE_DIR, "results", "part1")
    path = os.path.join(part1_dir, f"{call_id}_scored.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def build_comparison(call_id, original_report, original_scored, simulated_report,
                     original_transcript_data, simulated_transcript_data):
    """Build a before/after comparison JSON."""
    orig_violations = original_report.get("violations", [])
    sim_violations = simulated_report.get("violations", [])

    orig_vids = {v["rule_id"] for v in orig_violations}
    sim_vids = {v["rule_id"] for v in sim_violations}

    fixed = orig_vids - sim_vids
    new_issues = sim_vids - orig_vids
    persistent = orig_vids & sim_vids

    orig_score = None
    orig_verdict = None
    if original_scored:
        orig_score = original_scored.get("final_score")
        orig_verdict = original_scored.get("verdict")
    if orig_score is None:
        orig_score = original_report.get("score", "N/A")
        orig_verdict = original_report.get("verdict", "N/A")

    sim_score = simulated_report.get("score", "N/A")
    sim_verdict = simulated_report.get("verdict", "N/A")

    # Side-by-side of first turns
    orig_turns = original_transcript_data.get("transcript", [])
    sim_turns = simulated_transcript_data.get("transcript", [])
    max_show = min(12, max(len(orig_turns), len(sim_turns)))

    side_by_side = []
    for i in range(max_show):
        entry = {"turn": i + 1}
        if i < len(orig_turns):
            entry["original"] = f"[{orig_turns[i]['speaker'].upper()}] {orig_turns[i]['text'][:250]}"
        if i < len(sim_turns):
            entry["simulated"] = f"[{sim_turns[i]['speaker'].upper()}] {sim_turns[i]['text'][:250]}"
        side_by_side.append(entry)

    return {
        "call_id": call_id,
        "original": {
            "score": orig_score,
            "verdict": orig_verdict,
            "total_violations": original_report.get("total_violations", len(orig_violations)),
        },
        "simulated": {
            "score": sim_score,
            "verdict": sim_verdict,
            "total_violations": simulated_report.get("total_violations", len(sim_violations)),
        },
        "improvement": {
            "score_delta": round((sim_score or 0) - (orig_score if isinstance(orig_score, (int, float)) else 0), 1),
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

    if len(sys.argv) > 1:
        calls = [sys.argv[1]]
    else:
        calls = TARGET_CALLS

    os.makedirs(PART2_DIR, exist_ok=True)

    print(f"Prompt:      {FIXED_PROMPT_PATH}")
    print(f"Transcripts: {TRANSCRIPTS_DIR}")
    print(f"Output:      {PART2_DIR}")
    print(f"Calls:       {', '.join(calls)}")
    print(f"Model:       {MODEL_NAME}\n")

    for i, call_id in enumerate(calls):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(calls)}] Simulating {call_id}")
        print(f"{'='*60}")

        transcript_path = os.path.join(TRANSCRIPTS_DIR, f"{call_id}.json")
        if not os.path.exists(transcript_path):
            print(f"  ERROR: Transcript not found: {transcript_path}")
            continue

        with open(transcript_path) as f:
            original_data = json.load(f)

        customer_data = original_data["customer"]

        # Build system instruction
        system_instruction = build_system_instruction(FIXED_PROMPT_PATH, customer_data)

        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=system_instruction,
        )

        # Extract customer messages
        customer_messages = extract_customer_messages(original_data["transcript"])
        print(f"  Customer: {customer_data['name']}")
        print(f"  Original turns: {len(original_data['transcript'])}")
        print(f"  Customer message groups: {len(customer_messages)}")

        # Run single-prompt simulation
        simulated_turns = simulate_call_single_prompt(
            model, system_instruction, customer_messages, call_id
        )

        if simulated_turns is None:
            print(f"  FAILED — could not complete simulation for {call_id}")
            continue

        # Convert to standard format
        transcript, function_calls = turns_to_transcript_format(simulated_turns)

        # Save
        sim_path = save_simulated_transcript(
            call_id, customer_data, transcript, function_calls, PART2_DIR
        )

        print(f"  Simulated transcript turns: {len(transcript)}")
        print(f"  Function calls: {len(function_calls)}")

        # Print key agent responses for quick review
        agent_turns = [t for t in transcript if t["speaker"] == "agent"]
        for j, at in enumerate(agent_turns[:5]):
            preview = at["text"][:100] + "..." if len(at["text"]) > 100 else at["text"]
            print(f"    Agent turn {j+1}: {preview}")

        if i < len(calls) - 1:
            print("  Waiting before next simulation...")
            time.sleep(8)

    print(f"\n{'='*60}")
    print(f"SIMULATION COMPLETE — Model: {MODEL_NAME}")
    print(f"{'='*60}")
    print(f"Results saved to: {PART2_DIR}/")


if __name__ == "__main__":
    main()
