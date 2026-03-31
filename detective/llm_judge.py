#!/usr/bin/env python3
"""
Step 2: LLM Judge — evaluates each cleaned transcript against
80 rules/violations using Gemini 2.5 Flash.

Usage:
  python detective/llm_judge.py                              # all transcripts
  python detective/llm_judge.py cleaned_transcripts/call_01.json  # single file
"""

import json
import os
import sys
import time
import glob
from dotenv import load_dotenv
import google.generativeai as genai

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GOOGLE_API_KEY = os.getenv("google_api_key")
MODEL_NAME = os.getenv("LLM_MODEL", "gemini-2.5-flash")
RULES_FILE = os.path.join(BASE_DIR, "detective", "rules_and_violations.json")
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "cleaned_transcripts")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
PER_TRANSCRIPT_DIR = os.path.join(RESULTS_DIR, "per_transcript")
VERDICT_THRESHOLD = 70


SYSTEM_INSTRUCTION = """You are a strict but fair call quality auditor for an AI debt collection voice agent named "Alex" from "DemoCompany", working with "DemoLender" for education loans.

You will receive a call transcript and a checklist of 80 rules/violations. Evaluate the AGENT's behavior only.

SCORING:
- For rules (type="rule"): 0 = rule was FOLLOWED correctly, 1 = rule was BROKEN.
- For violations (type="violation"): 0 = violation was NOT committed, 1 = violation WAS committed.
- null = the situation described never arose in this call, so it cannot be evaluated.

GUIDELINES:
- Evaluate ONLY the agent's spoken text and function calls, not the customer's behavior.
- The function_calls list shows what phase transitions and actions the agent took, and at which turn.
- Be strict: if there is clear evidence of a rule being broken, score 1.
- Be fair: if the evidence is ambiguous or borderline, score 0.
- Use null generously: if a call ended in opening phase, negotiation/closing rules are null. If the customer never asked about identity or disputed the loan, those specific rules are null.

PAY EXTRA ATTENTION TO THESE HIGH-IMPACT RULES (be especially strict):

1. PREMATURE CALL ENDING (#80, critical): If the call is short and the agent did NOT exhaust
   all options (concrete bridges, credit impact, timeline exploration, escalation warning)
   before ending, score 1. A short call where the borrower was evasive or gave short answers
   is NOT a reason to end — the agent should have tried harder. Only valid short exits are:
   wrong person, voicemail, or borrower already paid.

2. DIG DEEPER DON'T RUSH (#37, high): If the agent moved to negotiation without asking
   follow-up questions about the borrower's financial situation (employment, income, family
   support, temporary vs permanent hardship), score 1. Simply accepting vague answers like
   "I don't have money" without probing is a violation.

3. TWO ATTEMPT RULE (#36, high): The agent MUST make at least two genuine persuasion
   attempts before giving up. If the borrower says "no" or gives a dismissive answer and
   the agent immediately ends or schedules a callback without trying a different angle, score 1.

4. SHORT RESPONSES ARE NOT REFUSALS (#35, high): If the borrower gives short answers like
   "nothing", "no", "not really" and the agent treats these as final refusals instead of
   using concrete bridges to continue the conversation, score 1.

5. LANGUAGE SWITCHING (#76, medium): If the borrower clearly struggles with English or
   speaks in another language and the agent does NOT call switch_language, score 1.

6. CONVERSATION PROGRESSION NO LOOPING (#57, high): If the agent repeats the same offer
   or the same point more than twice without progressing through different angles (credit
   consequences → deadline → timeline → escalation), score 1.

OUTPUT FORMAT:
Return a JSON array of exactly 80 objects, one per rule, in order from rule_id 1 to 80. Each object must have these fields:

{
  "rule_id": <int 1-80>,
  "score": <0 | 1 | null>,
  "agent_message": <string — the EXACT quote from the agent's message in the transcript that proves the violation, or null if score is 0 or null>,
  "turn_number": <int — the turn number where the violation occurred, or null if score is 0 or null>,
  "violation_detail": <string — a concise explanation of what the agent did wrong and which specific rule/violation it breaks, or null if score is 0 or null>
}

CRITICAL RULES FOR EVIDENCE:
- "agent_message" must be the EXACT text from the transcript, not a paraphrase. Copy it verbatim.
- If a violation spans multiple turns, pick the most egregious one and mention others in "violation_detail".
- For violations where the agent FAILED TO DO something (omission, not action), set agent_message to null but still provide turn_number (the turn where it should have happened) and violation_detail.
- If score is 0 or null, set agent_message, turn_number, and violation_detail all to null."""


def load_rules(path):
    with open(path) as f:
        rules = json.load(f)
    return [
        {"id": r["id"], "name": r["name"], "type": r["type"], "explanation": r["explanation"]}
        for r in rules
    ]


def load_full_rules(path):
    with open(path) as f:
        return json.load(f)


def format_transcript(transcript):
    lines = []
    for i, turn in enumerate(transcript, 1):
        speaker = turn["speaker"].upper()
        lines.append(f"Turn {i} [{speaker}]: {turn['text']}")
    return "\n".join(lines)


def format_function_calls(function_calls):
    if not function_calls:
        return "(none)"
    lines = []
    for fc in function_calls:
        params = fc.get("params", {})
        params_str = ", ".join(f"{k}={v}" for k, v in params.items()) if params else ""
        lines.append(f"  Turn {fc['turn']}: {fc['function']}({params_str})")
    return "\n".join(lines)


def format_rules_checklist(rules):
    lines = []
    for r in rules:
        lines.append(f"{r['id']}. [{r['type'].upper()}] {r['name']}: {r['explanation']}")
    return "\n".join(lines)


def build_user_prompt(transcript_data, rules):
    return f"""Evaluate this call transcript against ALL 80 rules below.

## CALL CONTEXT
- Customer Name: {transcript_data['customer_name']}
- Pending Amount (Total Outstanding / TOS): {transcript_data['pending_amount']}
- Closure Amount (POS): {transcript_data['closure_amount'] or '(not available)'}
- Settlement Amount: {transcript_data['settlement_amount'] or '(not available)'}

## TRANSCRIPT
{format_transcript(transcript_data['transcript'])}

## FUNCTION CALLS MADE BY AGENT (with turn numbers)
{format_function_calls(transcript_data['function_calls'])}

## RULES & VIOLATIONS CHECKLIST
{format_rules_checklist(rules)}

Now evaluate each of the 80 rules. Return a JSON array of exactly 80 objects with rule_id, score, agent_message, turn_number, and violation_detail."""


def evaluate_transcript(model, transcript_data, rules, max_retries=3):
    prompt = build_user_prompt(transcript_data, rules)

    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,
                },
            )
            evaluations = json.loads(response.text)

            if isinstance(evaluations, list) and len(evaluations) > 0:
                return evaluations

            print(f"    Unexpected format (attempt {attempt+1}), retrying...")

        except json.JSONDecodeError as e:
            print(f"    JSON parse error (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
        except Exception as e:
            print(f"    API error (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(10)

    return None


def build_per_transcript_report(filename, transcript_data, evaluations, full_rules):
    rules_by_id = {r["id"]: r for r in full_rules}

    enriched = []
    for e in evaluations:
        rid = e.get("rule_id")
        rule_info = rules_by_id.get(rid, {})
        enriched.append({
            "rule_id": rid,
            "rule_name": rule_info.get("name", "unknown"),
            "rule_type": rule_info.get("type", "unknown"),
            "severity": rule_info.get("severity", "unknown"),
            "score": e.get("score"),
            "agent_message": e.get("agent_message"),
            "turn_number": e.get("turn_number"),
            "violation_detail": e.get("violation_detail"),
        })

    applicable = [e for e in enriched if e["score"] is not None]
    violations = [e for e in applicable if e["score"] == 1]
    followed = [e for e in applicable if e["score"] == 0]
    not_applicable = [e for e in enriched if e["score"] is None]

    total_applicable = len(applicable)
    total_violations = len(violations)
    score = round(100 * (1 - total_violations / total_applicable), 1) if total_applicable > 0 else 100
    verdict = "good" if score >= VERDICT_THRESHOLD else "bad"

    return {
        "file": filename,
        "customer_name": transcript_data["customer_name"],
        "pending_amount": transcript_data["pending_amount"],
        "closure_amount": transcript_data["closure_amount"],
        "settlement_amount": transcript_data["settlement_amount"],
        "score": score,
        "verdict": verdict,
        "total_rules": len(enriched),
        "total_applicable": total_applicable,
        "total_followed": len(followed),
        "total_violations": total_violations,
        "total_not_applicable": len(not_applicable),
        "violations": [
            {
                "rule_id": v["rule_id"],
                "rule_name": v["rule_name"],
                "rule_type": v["rule_type"],
                "severity": v["severity"],
                "agent_message": v["agent_message"],
                "turn_number": v["turn_number"],
                "violation_detail": v["violation_detail"],
            }
            for v in violations
        ],
        "followed_rules": [
            {"rule_id": f["rule_id"], "rule_name": f["rule_name"]}
            for f in followed
        ],
        "not_applicable_rules": [
            {"rule_id": n["rule_id"], "rule_name": n["rule_name"]}
            for n in not_applicable
        ],
        "full_evaluations": enriched,
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
    os.makedirs(PER_TRANSCRIPT_DIR, exist_ok=True)

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        transcript_files = [arg if os.path.isabs(arg) else os.path.join(os.getcwd(), arg)]
    else:
        transcript_files = sorted(glob.glob(os.path.join(TRANSCRIPTS_DIR, "call_*.json")))
    print(f"Found {len(transcript_files)} transcripts to evaluate.")
    print(f"Model: {MODEL_NAME}")
    print(f"Verdict threshold: {VERDICT_THRESHOLD}\n")

    all_reports = []

    for i, filepath in enumerate(transcript_files):
        filename = os.path.basename(filepath)
        call_id = filename.replace(".json", "")
        print(f"[{i+1}/{len(transcript_files)}] Evaluating {filename}...")

        with open(filepath) as f:
            transcript_data = json.load(f)

        evaluations = evaluate_transcript(model, transcript_data, rules)

        if evaluations:
            report = build_per_transcript_report(filename, transcript_data, evaluations, full_rules)
            all_reports.append(report)

            per_file_path = os.path.join(PER_TRANSCRIPT_DIR, f"{call_id}_report.json")
            with open(per_file_path, "w") as f:
                json.dump(report, f, indent=2)

            print(f"  Score: {report['score']} | Verdict: {report['verdict']} | "
                  f"Violations: {report['total_violations']}/{report['total_applicable']} | "
                  f"N/A: {report['total_not_applicable']}")
            if report["violations"]:
                for v in report["violations"][:3]:
                    print(f"    - [{v['severity']}] {v['rule_name']}: {v['violation_detail'][:80] if v['violation_detail'] else ''}...")
                if len(report["violations"]) > 3:
                    print(f"    ... and {len(report['violations']) - 3} more")
        else:
            all_reports.append({
                "file": filename,
                "customer_name": transcript_data["customer_name"],
                "error": "Failed after retries",
            })
            print(f"  FAILED after retries")

        if i < len(transcript_files) - 1:
            time.sleep(8)

    # --- Build aggregate summary ---
    good_calls = [r["file"] for r in all_reports if r.get("verdict") == "good"]
    bad_calls = [r["file"] for r in all_reports if r.get("verdict") == "bad"]

    violation_counts = {}
    for r in all_reports:
        for v in r.get("violations", []):
            rid = v["rule_id"]
            name = v["rule_name"]
            if rid not in violation_counts:
                violation_counts[rid] = {"name": name, "count": 0, "calls": []}
            violation_counts[rid]["count"] += 1
            violation_counts[rid]["calls"].append(r["file"])

    most_common = sorted(violation_counts.values(), key=lambda x: -x["count"])[:15]

    summary = {
        "model": MODEL_NAME,
        "verdict_threshold": VERDICT_THRESHOLD,
        "total_calls": len(all_reports),
        "good_count": len(good_calls),
        "bad_count": len(bad_calls),
        "good_calls": good_calls,
        "bad_calls": bad_calls,
        "scores": {r["file"]: r.get("score", "error") for r in all_reports},
        "most_common_violations": most_common,
    }

    summary_path = os.path.join(RESULTS_DIR, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"EVALUATION COMPLETE")
    print(f"{'='*60}")
    print(f"Good calls ({len(good_calls)}): {good_calls}")
    print(f"Bad calls  ({len(bad_calls)}):  {bad_calls}")
    print(f"\nScores:")
    for r in all_reports:
        tag = "GOOD" if r.get("verdict") == "good" else "BAD " if r.get("verdict") == "bad" else "ERR "
        print(f"  {r['file']:>15}  {tag}  {r.get('score', 'N/A')}")
    print(f"\nTop violated rules:")
    for v in most_common[:5]:
        print(f"  - {v['name']} (violated in {v['count']} calls)")
    print(f"\nPer-transcript reports: {PER_TRANSCRIPT_DIR}/")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
