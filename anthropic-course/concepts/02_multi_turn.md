# Lesson 02 — Multi-turn conversations

**Anthropic course concept** → implemented in **BOTH** Claude ([`02_multi_turn_claude.py`](02_multi_turn_claude.py))
and free Gemini ([`02_multi_turn.py`](02_multi_turn.py)).

---

## The concept — the API is STATELESS

The single thing to internalise: **Claude (and every LLM chat API) remembers NOTHING between
requests.** Each `create()` call is independent. There is no server-side session.

So if you ask *"What is quantum computing?"*, get an answer, then send *"Write another sentence"*
as a brand-new request — Claude writes a sentence about something **random**, because it never saw
the first exchange.

**To get memory, YOU do two things:**
1. Keep a `messages` list in your own code.
2. Send the **entire history** with every request — your questions AND Claude's past replies.

The loop that works:
```
user msg → send [user] → reply
          append reply as assistant → append next user msg
          send [user, assistant, user] → reply with full context
```

## The three helpers (the course's pattern)

```python
def add_user_message(messages, text):      messages.append({"role": "user", "content": text})
def add_assistant_message(messages, text): messages.append({"role": "assistant", "content": text})
def chat(messages):                        return client.messages.create(model=MODEL, max_tokens=1000, messages=messages).content[0].text
```
Append → `chat()` → append the reply → append the next question → `chat()` again. The list IS the memory.

## Claude ↔ Gemini mapping

| Piece | Claude | Gemini |
|---|---|---|
| assistant turn role | `"assistant"` | `"model"` |
| message shape | `{"role","content": "..."}` | `{"role","parts":[{"text":"..."}]}` |
| the call | `client.messages.create(messages=...)` | `client.models.generate_content(contents=...)` |
| built-in stateful helper | *(none — you manage the list)* | `client.chats.create()` + `.send_message()` keeps history for you |

Both ports here do it **manually** — because that's what the course teaches, and it's what a real
app does when it needs to *persist* and *trim* history (see tie-in).

## The cost nobody mentions (interview point)
Resending the whole history every turn means **token cost grows with conversation length** — turn
10 pays for turns 1–9 again. Real apps therefore **cap / summarise / trim** the history. That's the
bridge to the next idea and to my project.

## Where this already lives in my project — narration **P3**

P3's knowledge assistant IS this lesson, taken to production:
- "Maintain the list yourself" → P3 **persists** every turn in the `chat_sessions` + `chat_turns`
  tables (`chat_service.py`), so memory survives a restart — not just an in-RAM list.
- "History grows unboundedly" → P3's **memory cap `N=6`** (`CHAT_MEMORY_MAX_TURNS`): only the last
  6 turns go into the prompt, older turns stay in the DB. That's the trim this lesson's cost-note
  predicts.
- Plus P3 adds what the lesson doesn't: auth, existence-hiding on 404, and retrieval-grounded
  **earned citations**.

So: the course taught stateless + manual history; I already shipped the durable, capped,
production version of it. ✅ (Interview-linked in `interview-prep/GENAI.md`'s memory row.)
