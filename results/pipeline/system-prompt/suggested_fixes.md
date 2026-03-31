As a senior prompt engineering expert, I've analyzed the provided system prompt and violation data. The agent, "Alex," struggles with fundamental conversational flow, adherence to critical gates, and effective persuasion, leading to repetitive, non-compliant, and ultimately unproductive calls. The root causes lie in the prompt's structure, lack of explicit enforcement, and insufficient guidance for dynamic conversation management.

Here are the 6 most severe root-cause flaws, ranked by impact:

---

## 1. Lack of Strict Gating for Identity Verification and Phase Transitions

**What's Wrong**: The prompt states that amounts "MUST disclose amounts only AFTER the borrower responds and you confirm their identity" (Opening phase) and that `proceed_to_discovery` should be called "after disclosing amounts." However, these are presented as sequential steps rather than *hard, blocking gates*. The LLM often prioritizes the "disclose amounts" instruction over the "confirm identity" prerequisite because the latter isn't framed as an absolute, non-negotiable condition that *must* be met before proceeding. Similarly, phase transitions are described as outcomes ("after disclosing amounts -> call proceed_to_discovery") rather than explicit, mandatory function calls that gate the next stage of the conversation. This leads to critical compliance violations (premature disclosure) and structural failures (getting stuck in phases).

**Evidence**:
*   **Violation 3 (call_02_simulated.json)**: "The agent disclosed the total outstanding and closure amount in Turn 2, before confirming the borrower's identity (which happened in Turn 10)."
    *   **Agent said**: "आपका कुल बकाया पचास हज़ार रुपये है. लेकिन हम सभी शुल्क हटाकर आपका लोन शून्य रुपये में बंद कर सकते हैं."
*   **Violation 15 (call_07_simulated.json)**: "The agent disclosed financial information (loan amounts) in Turn 2 without explicitly confirming the borrower's identity first."
    *   **Agent said**: "Hello, Meera Joshi. I am Alex from DemoCompany. Your total outstanding is fifty thousand rupees. But we can remove all charges and close your loan at just zero rupees."
*   **Violation 4 (call_07_simulated.json)**: "After disclosing the TOS/POS amounts and adding urgency in Turn 18, the agent failed to call `proceed_to_discovery` and instead got stuck in a loop of repeating the offer and then handling language issues."

**Suggested Fix**:
Introduce a prominent "CRITICAL GATES" section at the very top of the prompt. Rephrase identity confirmation as an explicit, blocking prerequisite for *any* financial disclosure. Make phase transitions explicit function calls that *must* be executed to progress. Add a `current_phase` variable to the internal state for better tracking.

**Placement**: At the very top of the prompt, before any other instructions.

```markdown
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
- Missing fallback/exit strategies cause the model to improvise poorly
- Keyword-gated logic (vs. semantic intent) breaks when customers use different words
- Lack of state tracking causes repetition and phase confusion

=============================================
SECTION 2 — THE SYSTEM PROMPT BEING ANALYZED
=============================================

You are Alex from DemoCompany, working with DemoLender for education loans.

--- CRITICAL GATES & NON-NEGOTIABLES ---

1.  **IDENTITY VERIFICATION (HARD GATE)**: You **MUST** confirm the borrower's identity (by name) **BEFORE** disclosing ANY loan amounts or specific financial details. If identity is not confirmed, you **MUST NOT** proceed with the loan discussion.
2.  **PHASE TRANSITIONS (MANDATORY FUNCTION CALLS)**: You **MUST** use `proceed_to_discovery`, `proceed_to_negotiation`, `proceed_to_closing`, and `end_call` functions to manage the conversation flow. **NEVER** verbally transition or imply a phase change; **ALWAYS** use the function call.
3.  **LANGUAGE SWITCHING (PROACTIVE)**: If the borrower speaks in a language other than English, you **MUST IMMEDIATELY** use the `switch_language` function to accommodate them. Do not state you "can only communicate in English."
4.  **NO REPETITION**: You **MUST NEVER** repeat the same phrase, sentence, or core information (e.g., the exact offer amount) twice in a conversation. Rephrase or progress.
5.  **NO META-COMMENTARY**: You **MUST NEVER** output stage directions, brackets, or meta-commentary.

---

========================================
IDENTITY HANDLING
========================================
You are Alex, a calling agent. Try to avoid saying you are an AI if the customer asks.
If they press further, say something like "I'm just here to help with your account."
```

---

## 2. Absence of Robust State Tracking and Progression Logic

**What's Wrong**: The prompt contains rules like "NEVER repeat the same sentence twice" and "Do NOT repeat this introduction," and even a "Conversation Progression" section in Negotiation. However, it lacks explicit mechanisms for the LLM to track what it has *already said*, what *persuasion angle* it has tried, or its current *conversational state*. Without this, the LLM defaults to repeating information or questions, leading to circular exchanges. The "dig deeper" instruction is present, but the LLM often re-pitches the offer or asks the same generic question instead of exploring new angles. The `anti_stuck_circular_exchange` rule is too high (5-6 exchanges) and doesn't provide enough guidance on *how* to progress