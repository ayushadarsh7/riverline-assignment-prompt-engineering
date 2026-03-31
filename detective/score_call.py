#!/usr/bin/env python3
"""
Step 3: Scoring Pipeline — takes LLM judge reports and computes a
severity-weighted score (1-100) with critical-gate logic and
structural penalty multipliers.

Usage:
  python detective/score_call.py results/per_transcript/call_01_report.json
  python detective/score_call.py results/per_transcript/          # all reports
"""

import json
import sys
import os
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEVERITY_WEIGHTS = {
    "critical": 10,
    "high": 5,
    "medium": 2,
    "low": 1,
}

CRITICAL_CAP = 40
VERDICT_THRESHOLD = 65
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "cleaned_transcripts")

VALID_SHORT_CALL_REASONS = {
    "wrong_party", "voicemail", "claims_already_paid",
}


def load_transcript(report_filename):
    """Load the matching cleaned transcript for structural analysis."""
    path = os.path.join(TRANSCRIPTS_DIR, report_filename)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def compute_structural_penalties(report, transcript):
    """
    Compute deterministic penalty multipliers from transcript structure.
    Each penalty is a dict with a multiplier (0.0-1.0) and a reason.
    A multiplier of 1.0 means no penalty.
    """
    penalties = []
    if transcript is None:
        return penalties

    turns = transcript.get("transcript", [])
    function_calls = transcript.get("function_calls", [])
    total_turns = len(turns)

    end_call_reasons = [
        fc["params"].get("reason", "")
        for fc in function_calls if fc["function"] == "end_call"
    ]
    is_valid_short_exit = any(r in VALID_SHORT_CALL_REASONS for r in end_call_reasons)

    phases_called = [fc["function"] for fc in function_calls]
    reached_negotiation = "proceed_to_negotiation" in phases_called
    reached_discovery = "proceed_to_discovery" in phases_called

    # --- Penalty 1: Call too short ---
    if total_turns < 20 and not is_valid_short_exit:
        penalties.append({
            "name": "call_too_short",
            "multiplier": 0.70,
            "reason": f"Call had only {total_turns} turns without a valid quick-exit "
                      f"reason (wrong person, voicemail, already paid). Agent likely "
                      f"gave up too quickly.",
        })

    # --- Penalty 2: No urgency delivered ---
    # Only applies when the call actually needed urgency — i.e. the agent reached
    # discovery or negotiation (a real conversation happened) and the call didn't
    # end with a valid quick-exit like busy/wrong person/already paid.
    QUICK_EXIT_NO_URGENCY = VALID_SHORT_CALL_REASONS | {
        "callback_scheduled", "resolved_callback_scheduled",
        "borrower_refused_conversation", "dispute_unresolved",
    }
    call_needed_urgency = (
        (reached_discovery or reached_negotiation)
        and not any(r in QUICK_EXIT_NO_URGENCY for r in end_call_reasons)
    )

    if call_needed_urgency:
        violated_ids = {v["rule_id"] for v in report.get("violations", [])}
        urgency_rules = {14, 15, 52}
        urgency_violated = urgency_rules & violated_ids
        if len(urgency_violated) >= 2:
            penalties.append({
            "name": "no_urgency_delivered",
            "multiplier": 0.80,
                "reason": "Agent failed to convey urgency across multiple rules "
                          "(convey_urgency, firm_reminder, create_urgency). Borrower "
                          "was given no reason to act.",
            })

    return penalties


def score_report(report, transcript=None):
    evaluations = report.get("full_evaluations", [])
    violations = report.get("violations", [])

    applicable = [e for e in evaluations if e.get("score") is not None]

    total_weight = sum(SEVERITY_WEIGHTS.get(e["severity"], 1) for e in applicable)
    penalty = sum(SEVERITY_WEIGHTS.get(e["severity"], 1) for e in applicable if e["score"] == 1)

    weighted_score = round(100 * (1 - penalty / total_weight), 1) if total_weight > 0 else 100

    critical_violations = [v for v in violations if v.get("severity") == "critical"]
    has_critical = len(critical_violations) > 0

    # --- Structural penalties ---
    structural_penalties = compute_structural_penalties(report, transcript)
    structural_multiplier = 1.0
    for sp in structural_penalties:
        structural_multiplier *= sp["multiplier"]

    if has_critical:
        final_score = round(min(CRITICAL_CAP, weighted_score * structural_multiplier), 1)
        verdict = "bad"
    else:
        final_score = round(weighted_score * structural_multiplier, 1)
        verdict = "good" if final_score >= VERDICT_THRESHOLD else "bad"

    severity_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for v in violations:
        sev = v.get("severity", "medium")
        severity_breakdown[sev] = severity_breakdown.get(sev, 0) + 1

    worst_violations = sorted(violations, key=lambda v: -SEVERITY_WEIGHTS.get(v.get("severity", "medium"), 1))
    top_issues = worst_violations[:5]

    # --- Build reason ---
    reason_parts = []
    if has_critical:
        reason_parts.append(
            f"FAILED — {len(critical_violations)} critical violation(s): "
            + ", ".join(v["rule_name"] for v in critical_violations)
            + f". Critical violations cap the score at {CRITICAL_CAP}."
        )
    elif verdict == "bad":
        reason_parts.append(
            f"POOR — Weighted score {final_score} is below threshold {VERDICT_THRESHOLD}. "
            f"{len(violations)} violation(s) found."
        )
    else:
        reason_parts.append(
            f"PASSED — Score {final_score} meets threshold {VERDICT_THRESHOLD}. "
            f"{len(violations)} minor violation(s)."
        )

    if structural_penalties:
        penalty_names = [sp["name"] for sp in structural_penalties]
        reason_parts.append(
            f"Structural penalties applied: {', '.join(penalty_names)} "
            f"(multiplier: {structural_multiplier:.2f})."
        )

    reason = " ".join(reason_parts)

    # --- Build analysis ---
    analysis_parts = []
    if severity_breakdown["critical"] > 0:
        analysis_parts.append(
            f"{severity_breakdown['critical']} critical violation(s) — compliance/safety failures "
            f"that make the call unacceptable"
        )
    if severity_breakdown["high"] > 0:
        analysis_parts.append(
            f"{severity_breakdown['high']} high-severity issue(s) — significant conversation or strategy failures"
        )
    if severity_breakdown["medium"] > 0:
        analysis_parts.append(
            f"{severity_breakdown['medium']} medium-severity issue(s) — missed best practices"
        )
    if severity_breakdown["low"] > 0:
        analysis_parts.append(
            f"{severity_breakdown['low']} low-severity issue(s) — minor missed opportunities"
        )

    for sp in structural_penalties:
        analysis_parts.append(f"[STRUCTURAL] {sp['name']}: {sp['reason']}")

    if top_issues:
        analysis_parts.append("Top issues: " + "; ".join(
            f"[{v['severity']}] {v['rule_name']}: {v.get('violation_detail', '')[:120]}"
            for v in top_issues
        ))

    analysis = ". ".join(analysis_parts) + "."

    return {
        "file": report["file"],
        "customer_name": report["customer_name"],
        "final_score": final_score,
        "verdict": verdict,
        "reason": reason,
        "analysis": analysis,
        "severity_breakdown": severity_breakdown,
        "total_applicable": len(applicable),
        "total_violations": len(violations),
        "critical_gate_triggered": has_critical,
        "weighted_score_before_cap": weighted_score,
        "structural_penalties": structural_penalties,
        "structural_multiplier": round(structural_multiplier, 2),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python score_call.py <report.json or directory/>")
        sys.exit(1)

    raw_target = sys.argv[1]
    target = raw_target if os.path.isabs(raw_target) else os.path.join(os.getcwd(), raw_target)

    if os.path.isdir(target):
        files = sorted(glob.glob(os.path.join(target, "*_report.json")))
    else:
        files = [target]

    all_scores = []

    for filepath in files:
        with open(filepath) as f:
            report = json.load(f)

        if "error" in report:
            print(f"  {os.path.basename(filepath)}: SKIPPED (evaluation error)")
            continue

        transcript = load_transcript(report["file"])
        result = score_report(report, transcript)
        all_scores.append(result)

        tag = "GOOD" if result["verdict"] == "good" else "BAD "
        crit = " [CRITICAL]" if result["critical_gate_triggered"] else ""
        struct = f" [STRUCT x{result['structural_multiplier']}]" if result["structural_multiplier"] < 1.0 else ""
        print(f"  {result['file']:>15}  {tag}  {result['final_score']:5.1f}/100{crit}{struct}  "
              f"violations: {result['total_violations']}/{result['total_applicable']}")
        for sp in result["structural_penalties"]:
            print(f"    ^ {sp['name']}: {sp['reason'][:90]}...")

    part1_dir = os.path.join(BASE_DIR, "results", "part1")
    os.makedirs(part1_dir, exist_ok=True)
    if len(all_scores) > 1:
        out_path = os.path.join(part1_dir, "scored_summary.json")
    else:
        call_id = all_scores[0]["file"].replace(".json", "")
        out_path = os.path.join(part1_dir, f"{call_id}_scored.json")

    output = all_scores if len(all_scores) > 1 else all_scores[0]
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
