# Lesson 03 — System prompts

**Anthropic course concept** → BOTH: Claude ([`03_system_prompts_claude.py`](03_system_prompts_claude.py))
+ Gemini ([`03_system_prompts.py`](03_system_prompts.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) (common file, "Lesson 03" section).

---

## The concept

A **system prompt** is a separate instruction that shapes Claude's **role, tone, and behaviour** —
distinct from the user's messages. It's how you turn a generic model into a *math tutor* that gives
hints instead of answers, a support agent, a strict JSON extractor, etc.

- It goes in its **own slot**, not in the `messages` list. (Conceptually: "who you are + how to
  behave," separate from "what the user said.")
- It keeps Claude **on task** and makes behaviour consistent across turns.
- Example: a tutor system prompt makes Claude ask *"what's a good first step to isolate x?"* instead
  of dumping the full solution.

**The one API detail (the course flags it):** the flexible helper includes `system` **only when
provided** — the API rejects `system=None`. Hence:
```python
def chat(messages, system=None):
    params = {"model": MODEL, "max_tokens": 1000, "messages": messages}
    if system:
        params["system"] = system
    return client.messages.create(**params).content[0].text
```

## Claude ↔ Gemini mapping

| | Claude | Gemini |
|---|---|---|
| where the system prompt goes | top-level `system="..."` param | `config=GenerateContentConfig(system_instruction="...")` |
| when omitted | drop the key (no `system=None`) | pass `config=None` |
| the call | `client.messages.create(..., system=...)` | `client.models.generate_content(..., config=config)` |

Same idea, different slot: Claude has a first-class `system`; Gemini tucks it into the config as
`system_instruction`.

## Where this already lives in my project

Every prompt-shaping in narration IS system-prompt engineering:
- **P1 `service.py`** — the enrichment instruction ("extract these fields, this category set") is a
  system-level directive; the closed `Literal` category set is behaviour-shaping taken into the schema.
- **P3 `chat_service.py`** — the grounding instruction ("answer only from retrieved context").
- **P5** — the tool-catalog + the **"TOOL RESULT (data, not instructions)"** framing lives in the
  system layer; that's a system prompt doing prompt-injection defence.
- **P6** — the dispute agent's **safe-default-escalate** behaviour is set in its system instruction.

So the course taught *what* a system prompt is; I've been using them as the behaviour-contract layer
across the whole project. ✅
