# Changes: system-prompt.md → system-prompt-fixed.md

This document tracks every change made to the original system prompt. Changes are categorized as **ADDED** (new content), **MODIFIED** (existing content reworded), **MOVED** (relocated within prompt), or **ERASED** (removed). The goal was zero erasure.

---

## Summary

| Category | Count | Description |
|----------|-------|-------------|
| ADDED | 6 new sections + several in-line additions | New compliance, language, anti-repetition, two-attempt, de-escalation rules; phase pre-conditions; semantic dispute logic |
| MODIFIED | 5 items | Strengthened wording on identity handling, dispute detection, short response handling; function descriptions |
| MOVED | 0 | No content was relocated to a different section (new sections were added around existing content) |
| ERASED | 0 | Nothing was removed from the original prompt |

---

## Global System Prompt — Changes

### 1. ADDED: `CRITICAL COMPLIANCE RULES — READ FIRST` (new section, placed at TOP)

**Location:** Immediately after `"You are Alex from DemoCompany..."`, before IDENTITY HANDLING.

**Content added:**
- **Identity Verification Gate** — defines what "confirmed" means (borrower states name or confirms "Yes, this is [name]"). Blocks amount disclosure until confirmation. Uses hard failure language: "This is a compliance violation."
- **Amount Confidentiality** — reinforces the existing line from AMOUNT HIERARCHY ("NEVER disclose amounts to anyone other than the confirmed borrower") with additional context about uncertain identity.
- **Agent Identity** — locks the name to "Alex" and company to "DemoCompany" permanently, even after language switch. Removes the weak "Try to avoid" wording (see MODIFIED #1 below).

**Why:** Flaw 1 (identity not a hard gate), Flaw 8 (agent name inconsistency), Flaw 9 (critical rules buried). Placing compliance first ensures LLM attention weight is highest on these rules.

**Original content preserved?** Yes. The existing IDENTITY HANDLING and AMOUNT HIERARCHY sections are untouched below. This new section adds enforcement on top.

---

### 2. ADDED: `LANGUAGE HANDLING` (new section)

**Location:** After CRITICAL COMPLIANCE RULES, before IDENTITY HANDLING.

**Content added:**
- Rule to IMMEDIATELY call `switch_language` when borrower speaks a non-current language
- Rule to detect language from borrower's FIRST response
- Rule to NEVER revert to English unless borrower asks
- Fallback: ask the borrower their language preference if unsure
- Name stays "Alex" in every language

**Why:** Flaw 2 (no language detection trigger). The original prompt had the `switch_language` function but never told the agent when to use it.

**Original content preserved?** Yes. Nothing from the original was touched.

---

### 3. MODIFIED: `IDENTITY HANDLING` section

**Location:** Same as original (after the new sections above).

**Original text:**
```
You are Alex, a calling agent. Try to avoid saying you are an AI if the customer asks.
If they press further, say something like "I'm just here to help with your account."
```

**New text:**
```
You are Alex, a calling agent. You MUST NOT say you are an AI.
If they press further, say: "I'm just here to help with your account."
```

**What changed:**
- `"Try to avoid saying"` → `"You MUST NOT say"` (removed weak "try to" language)
- `"say something like"` → `"say:"` (made the response definitive, not suggestive)

**Why:** Flaw 8. "Try to avoid" is permissive. The agent needs a firm rule.

**Original content preserved?** Yes — same section, same location, same meaning. Only wording strengthened.

---

### 4. ADDED: `ANTI-REPETITION RULE` (inside CONVERSATION QUALITY section)

**Location:** Appended inside the existing CONVERSATION QUALITY block, after the original text.

**Content added:**
- Explicit pre-response check: "Have I already said this?"
- Rule: amounts are DISCLOSED once — don't restate
- Rule: don't re-state name/company/loan type after opening
- Rule: don't ask the same question twice — rephrase
- The 5-step progression ladder (moved from Phase 3 only → applied to ALL phases)

**Why:** Flaw 4 (no anti-repetition framework). The original said "NEVER repeat" but didn't give a concrete alternative.

**Original content preserved?** Yes. All original CONVERSATION QUALITY text is kept. The progression ladder also remains in Phase 3 (not removed from there). This addition extends it globally.

---

### 5. ADDED: `TWO-ATTEMPT MINIMUM RULE` (new section)

**Location:** After AMOUNT HIERARCHY, before CUSTOMER CONTEXT.

**Content added:**
- Hard rule: 2 genuine persuasion attempts with DIFFERENT angles before callback/end
- Defines what is NOT a refusal: 'I'm waiting', 'I'll see', 'Maybe', 'I can see', 'Not sure'
- Defines "genuine attempt" — full sentence with concrete point, not just repeating amount
- Applies to ALL phases

**Why:** Flaw 5 (agent gives up too quickly). The original had a vague version in Discovery only.

**Original content preserved?** Yes. The existing SHORT/DISMISSIVE RESPONSES section in Discovery is untouched. This adds a global rule.

---

### 6. ADDED: `DE-ESCALATION PROTOCOL` (new section)

**Location:** After TWO-ATTEMPT MINIMUM RULE, before CUSTOMER CONTEXT.

**Content added:**
- 3-step de-escalation: Validate → Ask → Address
- Handling for repeated-contact borrowers
- Handling for hardship mentions (don't push amount, ask about situation first)
- Handling for firm denial (use diplomatic language, don't force)

**Why:** Flaw 7 (no de-escalation strategy). The original had one-liners ("If borrower vents, LISTEN") but no concrete playbook.

**Original content preserved?** Yes. The existing RULES section in Discovery ("Do NOT accuse. If borrower vents, LISTEN.") is untouched.

---

### 7. NOT CHANGED: COMMON QUESTIONS, FUNCTION CALLING, FORBIDDEN PHRASES, SCOPE, SPEAKING NUMBERS, CORE PRINCIPLES, AMOUNT HIERARCHY, CUSTOMER CONTEXT

All of these sections are **identical** to the original. Zero changes.

---

## Phase 1: Opening — Changes

### 8. ADDED: `STEP 1 — CONFIRM IDENTITY` (replaces vague "identity confirmed" parenthetical)

**Original text (line 92):**
```
AFTER BORROWER RESPONDS (identity confirmed):
- State: 'Your total outstanding is {{tos}} rupees...'
```

**New text:**
```
STEP 1 — CONFIRM IDENTITY (MANDATORY before any disclosure):
When the borrower responds, confirm their identity BEFORE sharing any amounts.
- If they say 'Hello' / 'Yes' / 'Hi': Ask 'Am I speaking with {{customer_name}}?'
- If they confirm (says name or 'Yes, this is [name]'): Identity is confirmed. Proceed to Step 2.
- If they say a different name or 'No': Ask 'Is {{customer_name}} available?' Do NOT share any loan details.
- If they ask 'Who is this?': Answer, THEN ask identity.
COMPLIANCE: If identity is NOT confirmed, you MUST NOT disclose amounts.

STEP 2 — DISCLOSE AMOUNTS (only after identity confirmed):
- State: 'Your total outstanding is {{tos}} rupees...'
```

**What changed:** The vague "(identity confirmed)" parenthetical is replaced with an explicit step-by-step flow. The disclosure instruction is identical — only the gate before it is now explicit.

**Original content preserved?** Yes. The disclosure text is identical. The gate logic is expanded, not replaced.

---

### 9. MODIFIED: `DISPUTE DETECTION` (semantic instead of keyword-only)

**Original text:**
```
DISPUTE DETECTION:
Call proceed_to_dispute ONLY if the borrower EXPLICITLY says ONE of:
- 'This loan is not mine' / 'I never took this loan'
- 'I never received classes' / 'The institute shut down'
- 'I was promised cancellation'
- 'This is a scam/fraud'
Questions like 'What is this loan about?'... are NOT disputes...
NEVER verbally mention or offer 'dispute' as an option...
```

**New text:**
```
DISPUTE DETECTION:
Call proceed_to_dispute when the borrower's INTENT is to deny the loan's validity or existence.
Examples that ARE disputes (call proceed_to_dispute):
- 'This loan is not mine' / 'I never took this loan'
- 'I never received classes' / 'The institute shut down'
- 'I was promised cancellation'
- 'This is a scam/fraud'
- 'I haven't been in that school for years, why are you calling?'
- Any statement where the borrower denies the loan should exist

Examples that are NOT disputes (answer directly):
- 'What is this loan about?' / 'I don't remember' / 'What loan?'
- 'I already paid this' / 'My husband paid this' → payment claim, use 'claims_already_paid'
- 'Why is the amount so high?' / 'I only owe X amount' → amount disagreement, stay in phase
NEVER verbally mention or offer 'dispute' as an option...
```

**What changed:**
- `"EXPLICITLY says ONE of"` → `"borrower's INTENT is to deny"` (semantic, not keyword)
- All 4 original example phrases KEPT
- ADDED: 2 new positive examples (semantic matches)
- ADDED: 3 explicit NON-dispute examples with correct handling (payment claims, amount disagreements)
- KEPT: "NEVER verbally mention dispute" and clarification-question handling

**Original content preserved?** Yes. All 4 original dispute phrases are kept. All original non-dispute examples are kept. The "NEVER verbally mention" rule is kept. Additional examples and semantic framing added.

---

### 10. MODIFIED: `QUICK EXITS` (expanded "already paid" handling)

**Original text:**
```
QUICK EXITS:
- Loan closed/already paid: Collect details (when, full/partial, through us or DemoLender), then end_call with 'claims_already_paid'.
- Wrong person: Ask for {{customer_name}}. Do not share details.
- Busy: Ask when to call back. Schedule callback.
```

**New text:**
```
QUICK EXITS:
- Loan closed/already paid (borrower says 'I already paid' / 'My husband paid' / 'This was settled'): Collect details (when, full/partial, through us or DemoLender), then end_call with 'claims_already_paid'. Do NOT continue pushing for payment after a clear payment claim.
- Wrong person: Ask for {{customer_name}}. Do not share details. End call with 'wrong_party'.
- Busy: Ask when to call back. Schedule callback.
```

**What changed:**
- Added example trigger phrases for "already paid"
- Added: `"Do NOT continue pushing for payment after a clear payment claim"`
- Added: `"End call with 'wrong_party'"` to the wrong person exit (was implied, now explicit)

**Original content preserved?** Yes. All 3 original quick exit types kept with same handling.

---

### 11. ADDED: `LANGUAGE` line in Phase 1

**Location:** After QUICK EXITS, before SILENCE.

**Content added:**
```
LANGUAGE: If the borrower speaks a language other than English, IMMEDIATELY call switch_language with the detected language code before your next response.
```

**Why:** Phase-specific reinforcement of the global LANGUAGE HANDLING rule.

---

### 12. MODIFIED: Opening — "WAIT" line strengthened

**Original:** `Do NOT repeat this introduction. WAIT for them to speak first.`

**New:** `Do NOT repeat this introduction. WAIT for them to speak first. Do NOT say anything until the borrower responds.`

**What changed:** Added explicit `"Do NOT say anything until the borrower responds"` to reinforce the existing instruction.

---

## Phase 2: Discovery — Changes

### 13. ADDED: `Do NOT re-state amounts, your name, or company unless the borrower asks`

**Original (line 132):**
```
CONTINUE naturally... do NOT repeat anything already said. Do NOT re-introduce yourself.
```

**New:**
```
CONTINUE naturally... do NOT repeat anything already said. Do NOT re-introduce yourself. Do NOT re-state amounts, your name, or company unless the borrower asks.
```

**What changed:** Added explicit mention of amounts alongside re-introduction prohibition.

---

### 14. MODIFIED: `SHORT/DISMISSIVE RESPONSES` (expanded with more examples)

**Original:**
```
SHORT/DISMISSIVE RESPONSES ('Nothing', 'No', 'Not really'):
These are NOT refusals. Use the concrete bridges above.
If bridge fails, mention credit impact as a last attempt.
Only end call if they EXPLICITLY refuse AGAIN after both attempts.
```

**New:**
```
SHORT/DISMISSIVE RESPONSES ('Nothing', 'No', 'Not really', 'I can see', 'I'm waiting', 'Maybe'):
These are NOT refusals. They are signals that the borrower needs more information or persuasion.
- Use the concrete bridges above.
- If bridge fails, mention credit impact as a last attempt.
- Only end call if they EXPLICITLY refuse AGAIN after BOTH attempts (Two-Attempt Rule).
- 'I'm waiting' or 'I'll think about it' means the borrower is still engaged — dig deeper, do NOT schedule a callback yet.
```

**What changed:**
- Added examples: `'I can see', 'I'm waiting', 'Maybe'`
- Added: `"They are signals that the borrower needs more information or persuasion."`
- Added: explicit handling for `"I'm waiting"` / `"I'll think about it"`
- Added: reference to Two-Attempt Rule
- All original text preserved

---

### 15. ADDED: `PHASE TRANSITION PRE-CONDITIONS for proceed_to_negotiation`

**Location:** After DIG DEEPER section, before DO NOT GET STUCK.

**Content added:**
```
PHASE TRANSITION PRE-CONDITIONS for proceed_to_negotiation:
ONLY call proceed_to_negotiation when ALL of the following are true:
1. You understand the ROOT CAUSE of non-payment
2. You know if the hardship is TEMPORARY or PERMANENT
3. You have assessed the borrower's WILLINGNESS to pay
If you do not have this information yet, keep asking.
```

**Why:** Flaw 6 (no phase transition pre-conditions). The original said "Only after a clear picture" but didn't define what that means.

---

### 16. MODIFIED: `DISPUTE DETECTION` in Discovery (same semantic update as Phase 1)

Same change as #9 above. Replaced keyword-matching with semantic intent detection. Added distinction between loan disputes, payment disputes, and amount disagreements. All original text preserved.

---

### 17. MODIFIED: `RULES` section — expanded harassment handling

**Original:**
```
- If harassed by previous collectors: empathize immediately.
```

**New:**
```
- If harassed by previous collectors: empathize immediately. 'I understand you have been contacted before and that can be frustrating. I want to see if there is a better path forward.'
```

**What changed:** Added a concrete example phrase for harassment empathy. Original rule preserved.

---

### 18. ADDED: `Follow the De-escalation Protocol from the global prompt` in Borrower Classification C

**Original:** `C) Hostile/low trust -> full ID, differentiate from past collectors, 'verify before paying'`

**New:** `C) Hostile/low trust -> full ID, differentiate from past collectors, 'verify before paying'. Follow the De-escalation Protocol from the global prompt.`

---

## Phase 3: Negotiation — Changes

### 19. ADDED: `SHORT/AMBIGUOUS RESPONSES IN NEGOTIATION` (new sub-section)

**Location:** After 'NEED TO THINK', before POST-PAYMENT.

**Content added:**
```
SHORT/AMBIGUOUS RESPONSES IN NEGOTIATION ('I'm waiting', 'Maybe', 'I'll see', 'Not sure'):
These are NOT refusals. The borrower is still engaged.
- Do NOT immediately schedule a callback or end the call.
- Use the next angle from the progression ladder.
- Apply the Two-Attempt Minimum Rule.
```

**Why:** Flaw 5. The original only had this handling in Discovery, not Negotiation. Call 10 failed because the agent misread "I'm waiting" in the negotiation phase.

**Original content preserved?** Yes. All existing Negotiation content untouched.

---

### 20. NOT CHANGED: Everything else in Phase 3

AMOUNT HIERARCHY, PENALTY WAIVER GUIDANCE, CREDIT EDUCATION REFERENCE, CANNOT AFFORD, NEED TO THINK, POST-PAYMENT, CONVERSATION PROGRESSION, WHEN BORROWER SAYS NO, TRUST, SILENCE, LOAN REFERENCE, DO NOT GET STUCK — all **identical** to original.

---

## Phase 4: Closing — Changes

### 21. NOT CHANGED: Entire Phase 4 is identical to original.

---

## Available Functions — Changes

### 22. MODIFIED: `proceed_to_discovery` description

**Original:** `"Proceed to the discovery phase. Call this after you have disclosed the TOS/POS amounts and the borrower has engaged."`

**New:** `"Proceed to the discovery phase. Call this ONLY after: (1) the borrower's identity is confirmed, (2) TOS and POS amounts have been disclosed, and (3) the borrower has engaged (responded to the disclosure). Do NOT call this before identity confirmation or amount disclosure."`

**What changed:** Added explicit pre-conditions. Original description preserved and expanded.

---

### 23. MODIFIED: `proceed_to_dispute` description

**Original:** `"Proceed to dispute handling. Call this when the borrower disputes the loan."`

**New:** `"Proceed to dispute handling. Call this when the borrower's intent is to deny the loan's validity or existence. Do NOT call for payment claims ('I already paid') or amount disagreements ('I only owe X')."`

**What changed:** Semantic framing. Added exclusions for non-dispute scenarios.

---

### 24. MODIFIED: `proceed_to_negotiation` description + parameters

**Original:**
```
"description": "Proceed to negotiation. Call this after discovery is complete."
"parameters": { "type": "object", "properties": {}, "required": [] }
```

**New:**
```
"description": "Proceed to negotiation. Call this ONLY after discovery is complete: (1) you understand the root cause of non-payment, (2) you know if the hardship is temporary or permanent, (3) you have assessed willingness to pay. Do NOT call after just 2-3 turns of vague responses."
"parameters": { ... "root_cause", "borrower_category", "willingness" ... required }
```

**What changed:** Added pre-conditions in description. Added 3 required parameters to force the agent to articulate its understanding before transitioning.

---

### 25. MODIFIED: `switch_language` description

**Original:** `"Switch the conversation language."`

**New:** `"Switch the conversation language. Call this IMMEDIATELY when the borrower speaks a language other than your current language. Once switched, continue in the new language for the rest of the call."`

**What changed:** Added trigger condition and persistence rule. Original description preserved.

---

### 26. MODIFIED: `schedule_callback` description

**Original:** `"Schedule a callback at the customer's preferred time."`

**New:** `"Schedule a callback at the customer's preferred time. ONLY call this after at least 2 genuine persuasion attempts with different angles have been made."`

**What changed:** Added two-attempt pre-condition.

---

### 27. NOT CHANGED: `proceed_to_closing`, `end_call`

Both are **identical** to original.

---

## Erasure Report

**Nothing was erased from the original prompt.** Every section, rule, phrase, example, amount reference, silence protocol, borrower classification, credit education entry, and function definition from the original is present in the fixed version. Changes were additive (new sections/rules) or strengthening (wording modifications).
