#!/usr/bin/env python3
"""
Part 3 — Prompt Analyzer: Reads judge reports, extracts violations,
feeds them to an LLM to identify root-cause prompt flaws and suggest fixes.

Usage:
  python pipeline/analyze.py --reports-dir results/pipeline/run/evaluated/ \
                              --prompt surgeon/system-prompt-fixed.md \
                              --output results/pipeline/run/suggested_fixes.md
"""

import argparse
import json
import os
import sys
import glob
import re
from collections import Counter, defaultdict
from dotenv import load_dotenv
import google.generativeai as genai

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

GOOGLE_API_KEY = os.getenv("google_api_key")
MODEL_NAME = os.getenv("LLM_MODEL", "gemini-2.5-flash")
RULES_FILE = os.path.join(BASE_DIR, "detective", "rules_and_violations.json")


def load_rules():
    with open(RULES_FILE) as f:
        return json.load(f)


def load_reports(reports_dir):
    """Load all *_report.json files from the given directory."""
    pattern = os.path.join(reports_dir, "*_report.json")
    reports = []
    for path in sorted(glob.glob(pattern)):
        with open(path) as f:
            reports.append(json.load(f))
    return reports


def load_prompt_text(prompt_path):
    """Load the system prompt. If it's a .md with code blocks, extract them."""
    with open(prompt_path) as f:
        content = f.read()

    blocks = re.findall(r"```(?:json)?\n(.*?)```", content, re.DOTALL)
    if blocks:
        return "\n\n---\n\n".join(blocks[:-1]) if len(blocks) > 1 else blocks[0]
    return content


def extract_violations(reports):
    """Extract violation_detail and agent_message from all reports."""
    per_call = []
    rule_freq = Counter()
    all_rules_data = defaultdict(list)

    for report in reports:
        call_name = report.get("file", "unknown")
        customer = report.get("customer_name", "unknown")
        total_applicable = report.get("total_applicable", 0)
        violations = report.get("violations", [])

        call_violations = []
        for v in violations:
            rule_name = v.get("rule_name", "unknown")
            entry = {
                "violation_detail": v.get("violation_detail", ""),
                "agent_message": v.get("agent_message", ""),
            }
            call_violations.append(entry)
            rule_freq[rule_name] += 1
            all_rules_data[rule_name].append({
                "call": call_name,
                **entry,
            })

        per_call.append({
            "call": call_name,
            "customer": customer,
            "violations_count": len(violations),
            "total_applicable": total_applicable,
            "violations": call_violations,
        })

    return per_call, rule_freq, all_rules_data


def build_analyzer_prompt(prompt_text, rules, per_call, rule_freq, total_calls):
    """Build the full analyzer prompt with all 5 sections."""

    rules_text = json.dumps(rules, indent=2, ensure_ascii=False)

    violation_data_parts = []
    for call in per_call:
        lines = [f"### {call['call']} (Customer: {call['customer']})"]
        lines.append(f"Violations: {call['violations_count']} / {call['total_applicable']} applicable rules\n")
        for i, v in enumerate(call["violations"], 1):
            lines.append(f"**Violation {i}:**")
            if v["violation_detail"]:
                lines.append(f"- Detail: {v['violation_detail']}")
            if v["agent_message"]:
                lines.append(f"- Agent said: \"{v['agent_message'][:300]}\"")
            lines.append("")
        violation_data_parts.append("\n".join(lines))

    freq_lines = []
    for rule_name, count in rule_freq.most_common(20):
        freq_lines.append(f"- **{rule_name}**: violated in {count}/{total_calls} calls")
    frequency_summary = "\n".join(freq_lines)

    prompt = f"""
=============================================
SECTION 1 — ROLE & CONTEXT
=============================================

You are a senior prompt engineering expert specializing in conversational AI for voice agents. You have deep experience debugging LLM system prompts — understanding why models ignore certain instructions, how instruction priority works, and how to restructure prompts so models reliably follow them.

You are analyzing a system prompt for an AI debt collection voice agent named "Alex" that calls borrowers about education loans. The agent follows a 4-phase conversational flow: Opening → Discovery → Negotiation → Closing. It can call functions to switch phases, schedule callbacks, switch languages, and end calls.

Your job is NOT to just list violations — it is to identify the ROOT-CAUSE FLAWS in the system prompt that CAUSED those violations. Multiple violations often share a single root cause (e.g., 5 different rules broken because identity verification wasn't enforced as a hard gate). Think structurally about why the LLM behaves the way it does given this prompt.

Key things to consider when analyzing:
- Instructions buried deep in long prompts get less attention from LLMs
- Contradictory or ambiguous instructions cause unpredictable behavior
- Rules without explicit enforcement language ("MUST", "NEVER", "STOP") get treated as suggestions

=============================================
SECTION 2 — THE SYSTEM PROMPT BEING ANALYZED
=============================================

{prompt_text}

=============================================
SECTION 3 — RULE DEFINITIONS (for reference)
=============================================

These are the 80 rules/violations the agent is evaluated against. Each has an id, name, type (rule or violation), severity (critical/high/medium/low), source (which section of the prompt it comes from), and explanation.

{rules_text}

=============================================
SECTION 4 — VIOLATION DATA
=============================================

The agent was tested on {total_calls} calls. Below are the violations found in each call, showing what went wrong (violation_detail) and what the agent actually said (agent_message).

{chr(10).join(violation_data_parts)}

--- CROSS-CALL FREQUENCY (top offenders) ---

{frequency_summary}

=============================================
SECTION 5 — YOUR TASK
=============================================

Analyze the system prompt and violation data above. Produce a detailed markdown report:

1. Identify 5-10 root-cause flaws in the system prompt. Do NOT just restate individual violations — group related violations that share a common root cause in the prompt's structure, wording, or organization.

2. For each flaw, provide:
   - **What's Wrong**: Explain exactly what in the prompt caused this problem. Reference specific sections or phrases of the prompt. Explain WHY the LLM ignores or misapplies this instruction — is it buried too deep? Does it contradict another instruction? Is there no enforcement language? Is there no fallback for edge cases?
   - **Evidence**: Cite 2-3 specific violation_details and agent_messages from Section 4 that prove this flaw exists. Quote the actual agent text.
   - **Suggested Fix**: Provide concrete, copy-pasteable prompt text that would fix this flaw. Not vague advice like "add more emphasis" — write the actual rewritten prompt section. Show exactly where in the prompt it should go.

3. Rank flaws from most severe (caused the most violations or the most critical ones) to least severe.

4. At the end, include a "Summary of Changes" section that lists all suggested modifications in priority order, with a one-line description of each.

Output format: Markdown. Use ## headings for each flaw (numbered). Be specific, be actionable, cite evidence from the data.
"""
    return prompt


def main():
    parser = argparse.ArgumentParser(description="Analyze judge reports and suggest prompt fixes")
    parser.add_argument("--reports-dir", required=True, help="Directory with *_report.json files")
    parser.add_argument("--prompt", required=True, help="Path to the system prompt that was tested")
    parser.add_argument("--output", required=True, help="Output path for suggested_fixes.md")
    args = parser.parse_args()

    if not GOOGLE_API_KEY:
        print("ERROR: google_api_key not found in .env")
        sys.exit(1)

    print(f"Loading reports from: {args.reports_dir}")
    reports = load_reports(args.reports_dir)
    if not reports:
        print(f"ERROR: No *_report.json files found in {args.reports_dir}")
        sys.exit(1)
    print(f"  Found {len(reports)} report(s)")

    print(f"Loading prompt: {args.prompt}")
    prompt_text = load_prompt_text(args.prompt)

    print(f"Loading rules: {RULES_FILE}")
    rules = load_rules()

    per_call, rule_freq, all_rules_data = extract_violations(reports)

    total_violations = sum(c["violations_count"] for c in per_call)
    print(f"  Total violations across all calls: {total_violations}")
    print(f"  Top offending rules:")
    for rule_name, count in rule_freq.most_common(5):
        print(f"    {rule_name}: {count}/{len(reports)} calls")

    analyzer_prompt = build_analyzer_prompt(
        prompt_text, rules, per_call, rule_freq, len(reports)
    )

    print(f"\nRunning LLM analyzer (model: {MODEL_NAME})...")
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(model_name=MODEL_NAME)

    for attempt in range(3):
        try:
            response = model.generate_content(
                analyzer_prompt,
                generation_config={"temperature": 0.3, "max_output_tokens": 8192},
            )
            analysis = response.text

            if analysis and len(analysis) > 100:
                os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
                with open(args.output, "w") as f:
                    f.write(analysis)
                print(f"\nAnalysis saved to: {args.output}")
                print(f"  Length: {len(analysis)} chars")
                return

            print(f"  Response too short (attempt {attempt+1}), retrying...")

        except Exception as e:
            print(f"  API error (attempt {attempt+1}): {e}")
            if attempt < 2:
                import time
                time.sleep(10)

    print("FAILED — could not generate analysis after 3 attempts")
    sys.exit(1)


if __name__ == "__main__":
    main()
