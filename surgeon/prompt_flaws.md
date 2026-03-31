# System Prompt — Flaw Analysis



---

## Flaw 1: Identity Verification Is Not a Hard Gate

### What's Wrong

The prompt says *"NEVER disclose amounts to anyone other than the confirmed borrower"* — but this is buried in the Amount Hierarchy section (line 57) alongside formatting rules. There is no explicit **gate** that blocks the agent from proceeding until identity is confirmed. The Opening phase says *"AFTER BORROWER RESPONDS (identity confirmed)"* but doesn't define what "confirmed" means or what happens if the agent skips it.

LLMs prioritize high-frequency conversational patterns (like replying quickly) over rare compliance rules. Without hard failure language ("This is a compliance violation. STOP."), the model treats identity verification as a suggestion, not a wall.

### Evidence from Call Reports

**Call 02 — Turn 3** (critical):
> `"Okay, you have fifty thousand rupees pending."`
>
> The agent disclosed the loan amount at turn 3 before confirming identity. The customer later clarified she was the husband's wife — the agent had disclosed financial details to a non-primary borrower.

**Call 05 — Turn 4** (critical):
> `"There's fifty thousand rupees pending on your DemoLender loan. Have you been facing any difficulties?"`
>
> Amount disclosed before any identity verification attempt.

**Call 07 — Turn 10** (critical):
> `"We have fifty-five thousand three hundred and thirty-five rupees pending on the account."`
>
> Agent disclosed amount before confirming borrower identity.

**Call 08 — Turn 14** (critical):
> `"Suresh Rao, I'm calling about your DemoLender education loan. We're showing a pending amount of fifty thousand rupees."`
>
> The person on the call gave different names (Harry, Evan, Arthur) and said "No, sir" — clearly not the borrower. The agent *still* disclosed the full loan amount to this stranger.

### Fix Direction

Move identity verification to the top of the prompt. Make it a hard compliance gate with explicit failure consequences: *"If identity is NOT confirmed, you MUST NOT disclose any amounts. This is a compliance violation."* Define what "confirmed" means (borrower says their name or confirms "Yes, this is [name]").

---

## Flaw 2: No Explicit Language Detection Trigger

### What's Wrong

The prompt provides a `switch_language` function but **never tells the agent when to use it**. There is no instruction like "If the borrower speaks a language other than English, immediately call `switch_language` with the detected language code." The agent has no guidance on:
- How to detect the borrower's language
- When to switch (immediately? after confirmation?)
- What to do if it switches to the wrong language
- That it must **stay** in the switched language

### Evidence from Call Reports

**Call 02 — Turn 36** (critical):
> The agent switched to English mid-conversation despite the customer requesting Hindi multiple times (turns 4, 37, 38). A long English monologue was delivered while the borrower spoke Hindi.
>
> Agent message: *"I am so sorry to hear about your husband's passing, Rahul. That must be incredibly difficult..."* (full English paragraph to a Hindi speaker)

**Call 03 — Turn 69** (critical):
> Agent called `switch_language(language=hi)` at turn 20 while the customer was speaking Tamil, then spoke English at turn 69 while the customer was speaking Hindi, then called `switch_language(language=ta)` at turn 86 while the customer was speaking Hindi. Complete language confusion.
>
> Agent also said at turn 167: *"माफ़ कीजिएगा, मेरी हिंदी में बात करने की क्षमता सीमित है।"* (Apologizing for limited Hindi ability — while having spoken Hindi fluently for many turns.)

**Call 07 — Turns 1–31** (critical):
> The agent spoke English from turns 1-31 despite the borrower being a Tamil speaker. The `switch_language(language=ta)` call came at turn 19, but the agent continued in English until turn 31.

### Fix Direction

Add an explicit rule: *"If the borrower speaks a language other than your current language, IMMEDIATELY call `switch_language` with the correct language code. Once switched, you MUST continue in that language for the rest of the call. NEVER revert to English unless the borrower asks."*

---

## Flaw 3: Dispute Detection Is Keyword-Gated (Brittle Logic)

### What's Wrong

The prompt gates `proceed_to_dispute` behind four specific phrases:
- "This loan is not mine" / "I never took this loan"
- "I never received classes" / "The institute shut down"
- "I was promised cancellation"
- "This is a scam/fraud"

This is keyword-matching logic forced into a semantic model. If a borrower says *"I haven't been in that school for six years, why are you calling?"* or *"My husband already paid this"*, the LLM sees it doesn't match the four phrases and either ignores the signal or **misapplies it** to non-dispute situations.

### Evidence from Call Reports

**Call 03 — Turn 35** (incorrectly triggered):
> Agent called `proceed_to_dispute()` when the customer was trying to provide a UTR number for a payment she'd already made. This was payment verification, not a dispute — but the rigid logic confused the agent.

**Call 05 — Turn 26** (incorrectly triggered):
> Agent called `proceed_to_dispute` when the customer was clarifying charges and negotiating the principal amount. The customer wanted to pay the principal without extra charges — a negotiation point, not a loan dispute.

**Call 02 — Turn 152** (missed trigger):
> Customer repeatedly said her husband already paid the loan (turns 22, 55, 98, 100). This is either a dispute or a "claims_already_paid" exit. The agent did neither — it scheduled a callback instead, prolonging the call unnecessarily. The phrase "my husband paid" didn't match the four keyword patterns.

### Fix Direction

Replace keyword-gated detection with semantic intent detection: *"Call `proceed_to_dispute` when the borrower's INTENT is to deny the loan's validity or existence — not just when they say specific phrases. Distinguish between: (a) loan disputes (denying the loan), (b) payment disputes (claiming already paid → use `end_call` with `claims_already_paid`), (c) charge disputes (disagreeing with amounts → stay in discovery/negotiation)."*

---

## Flaw 4: No Anti-Repetition Framework (Tell Without Teach)

### What's Wrong

The prompt says *"NEVER repeat the same phrase twice"* and *"NEVER echo what the customer said"* — but provides no concrete strategy for what to do **instead**. It's a prohibition without an alternative. The "CONVERSATION PROGRESSION — DO NOT LOOP" section in Phase 3 lists 5 progression angles, but:
1. It's only in the Negotiation phase — not in Discovery or Opening
2. It doesn't tell the agent to **track** what it has already said
3. There's no explicit instruction like "Before speaking, check: have I said this already?"

The result: the agent repeatedly restates amounts, re-introduces itself, and loops on the same questions.

### Evidence from Call Reports

**Call 01 — Turns 3, 7, 21, 26**:
> The agent quoted the 50,000 TOS and 35,000 POS amounts **four separate times** without progressing through different persuasion angles.

**Call 02 — Turns 3, 7, 10, 17, 66**:
> Agent repeatedly stated the outstanding amount five times. Also gave inconsistent amounts (50k, 28k, 35k) at different points.
>
> Turn 66: *"इस समय आपके प्रॉपरल लोन पर पैंतीस हज़ार पाँच सौ अठासी रुपये बकाया दिख रहा है।"*

**Call 03 — Turns 72, 74, 76, 78**:
> Agent asked for the UTR number four times in a row: *"क्या आप मुझे अपना यूटीआर नंबर बता सकती हैं ताकि मैं इसे सत्यापित कर सकूँ?"*

**Call 07 — Turns 1, 2, 10, 19, 26, 50, 59**:
> Agent repeated its introduction and loan amount across 7 different turns. Even re-stated name, company, and amount after the borrower had already acknowledged them.

### Fix Direction

Add a universal anti-repetition rule across ALL phases (not just Negotiation): *"Before every response, internally check: Have I already said this? If yes, you MUST use a different angle or new information. The 5-step progression ladder (amount → credit impact → deadline → timeline → escalation) applies to ALL phases."* Additionally, add explicit state-tracking: *"Once you have disclosed amounts, mark them as DISCLOSED. Do not re-state them unless the borrower asks."*

---

## Flaw 5: Short Responses Treated as Refusals — Agent Gives Up Too Quickly

### What's Wrong

The prompt says *"SHORT/DISMISSIVE RESPONSES ('Nothing', 'No', 'Not really'): These are NOT refusals."* — but only in the Discovery phase. In Negotiation, the guidance is weaker. More critically, there's no handling for ambiguous signals like "I'm waiting", "I can see", or "I'll think about it" that the agent consistently misreads as reasons to schedule a callback and end the call.

The "Two Attempt Rule" (make at least 2 genuine persuasion attempts before ending) exists conceptually in Discovery but is not enforced in Negotiation or Closing.

### Evidence from Call Reports

**Call 10 — Turn 18** (the defining bad call):
> The borrower said "I'm waiting" (turn 17). The agent interpreted this as "needs time to think" and immediately scheduled a callback:
>
> *"Okay, I understand you need some time to consider the options. Would it be alright if I checked in with you in about a week?"*
>
> The call ended at turn 18 — only 9 agent turns. No urgency conveyed, no credit education, no concrete bridges attempted. The LLM judge flagged 20 violations.

**Call 04 — Turn 69**:
> Customer said "No. Right now, I'm not able to pay." The agent immediately offered a callback instead of trying a concrete bridge, credit impact, or exploring partial payment.

**Call 09 — Turn 36**:
> Agent scheduled a callback while still explaining settlement options. The customer was engaged but the agent prematurely closed with `callback_scheduled`.

### Fix Direction

Add a hard rule across ALL phases: *"You MUST make at least 2 genuine persuasion attempts using DIFFERENT angles before scheduling a callback or ending the call. A short or ambiguous response ('I'm waiting', 'I'll see', 'Maybe') is NOT a refusal. Only end the call if the borrower EXPLICITLY refuses TWICE after genuine attempts."*

---

## Flaw 6: Premature Phase Transitions — No Pre-Conditions Enforced

### What's Wrong

The function descriptions for phase transitions are too permissive:
- `proceed_to_discovery`: "Call this after you have disclosed the TOS/POS amounts and the borrower has engaged." — but the agent calls it before disclosure.
- `proceed_to_negotiation`: "Call this after discovery is complete." — but "complete" is undefined.

There are no **hard pre-conditions** that must be met before a transition is allowed.

### Evidence from Call Reports

**Call 09 — Turn 3**:
> Agent called `proceed_to_negotiation` at turn 3, completely skipping the Opening and Discovery phases. No identity confirmation, no discovery of financial situation.

**Call 03 — Turn 6**:
> `proceed_to_discovery()` called before identity was fully confirmed and before loan amounts were disclosed.

**Call 07 — Turn 2**:
> `proceed_to_discovery` called at turn 2 — the second turn of the call, before anything meaningful happened.

**Call 10 — Turn 6**:
> `proceed_to_negotiation` called after the borrower said "I can see" — a vague acknowledgment, not a completed discovery.

### Fix Direction

Add explicit pre-conditions to each phase transition function:
- `proceed_to_discovery`: "ONLY call after: (1) borrower's identity is confirmed, (2) TOS and POS amounts have been stated."
- `proceed_to_negotiation`: "ONLY call after: (1) you understand the root cause of non-payment, (2) you know if the hardship is temporary or permanent, (3) you have assessed willingness to pay."

---

## Flaw 7: No De-escalation Strategy for Hostile/Angry Borrowers

### What's Wrong

The prompt says *"If harassed by previous collectors: empathize immediately"* and *"If borrower vents, LISTEN"* — but these are one-line mentions. There's no concrete de-escalation playbook for when a borrower is angry, hostile, or refuses to engage. The agent defaults to repeating information, which escalates the situation.

### Evidence from Call Reports

**Call 07 — Turn 57**:
> Borrower said "I don't have a job" — a clear hardship signal. The agent's response (turn 59) was to repeat the loan amount in Tamil without acknowledging the hardship, without exploring alternatives, and without any empathetic response. The call ended abruptly.

**Call 09 — Turn 25**:
> Customer disputed the agent's numbers ("my records show 97k vs my 39k"). Instead of de-escalating with *"Let me verify"*, the agent insisted on its numbers, creating friction.

**Call 03 — Turns 137, 178**:
> Customer complained multiple times that the agent was "speaking too fast and like a computer." The agent apologized submissively instead of adjusting its communication style.

### Fix Direction

Add a concrete de-escalation protocol:
1. *"If the borrower is angry: FIRST validate their emotion ('I understand you're frustrated, and that's completely fair.'). THEN ask what specifically is upsetting them. ONLY THEN address the issue."*
2. *"If the borrower says they can't pay due to hardship: DO NOT immediately repeat the amount. Instead, ask about their situation — employment, timeline, family support."*
3. *"If the borrower has been called multiple times: Acknowledge this directly ('I know you've been contacted before and that can be frustrating. I want to see if there's a better path forward.')."*

---

## Flaw 8: Agent Name Inconsistency / Identity Concealment Failure

### What's Wrong

The prompt defines the agent as "Alex from DemoCompany" but provides weak identity concealment guidance: *"Try to avoid saying you are an AI if the customer asks."* The word "try" makes this optional. Additionally, there's no rule preventing the agent from changing its own name mid-call.

### Evidence from Call Reports

**Call 03 — Turn 45**:
> Agent introduced itself as *"अभिषेक, रिवरलाइन"* instead of "Alex from DemoCompany" — both the name and company were wrong.

**Call 02 — Turns 10, 13, 15**:
> Agent changed its name from "Alex" to "Abhishek" mid-call. At turn 13: *"नमस्ते, मैं अभिषेक बात कर"*
>
> This inconsistency damages trust and sounds like a scam to the borrower.

### Fix Direction

Make this an absolute rule: *"Your name is ALWAYS Alex. Your company is ALWAYS DemoCompany. You MUST NEVER use a different name or company name. If you switch languages, your name stays Alex."*

---

### Comment 


The prompt is ~360 lines long and tries to control compliance, persuasion, scripting, and psychology all in one flat document. Critical compliance rules (identity verification, amount confidentiality) are buried in the middle alongside low-priority formatting rules (how to say numbers). 
```
LLMs give higher attention weight to tokens that appear early in the context window.

https://arxiv.org/abs/2307.03172
(Lost in the Middle: How Language Models Use Long Contexts)

```


### Evidence

This is a structural flaw proved by the *pattern* across all bad calls: the agent consistently follows the conversational rules (responds naturally, uses Hindi when switched) but violates compliance rules (discloses amounts pre-identity, skips phase gates). The rules that appear early (greeting, conversation quality) are followed more reliably than rules that appear later (identity gates, phase pre-conditions).

### Fix Direction

Restructure the prompt with a clear priority hierarchy:
1. **COMPLIANCE BLOCK (top)**: Identity verification, amount confidentiality, phase gates — with hard failure language
2. **STRATEGY BLOCK**: Conversation flow, persuasion angles, de-escalation

---

