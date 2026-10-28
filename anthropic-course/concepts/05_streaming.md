# Lesson 05 — Streaming

**Anthropic course concept** → Claude ([`05_streaming_claude.py`](05_streaming_claude.py)) +
Gemini ([`05_streaming.py`](05_streaming.py)). Interview Qs: [`../INTERVIEW.md`](../INTERVIEW.md) "Lesson 05".

---

## The concept

A full response can take **10–30s**. Without streaming the user stares at a spinner until the whole
thing is ready. **Streaming** sends the response in small pieces *as it's generated*, so text appears
word-by-word — a much more responsive feel. All the pieces are part of **one** request.

**Claude's stream events** (in order):

| Event | Meaning |
|---|---|
| `MessageStart` | a new message is beginning |
| `ContentBlockStart` | a new block (text / tool use / …) starts |
| **`ContentBlockDelta`** | **the actual chunks of generated text** ← what you display |
| `ContentBlockStop` | that block is done |
| `MessageDelta` | message-level updates (e.g. stop reason) |
| `MessageStop` | end of the message |

Two levels of API:
- **Raw events** — `client.messages.create(..., stream=True)` then iterate; you handle each event type.
- **Simplified** — `with client.messages.stream(...) as stream: for text in stream.text_stream:` —
  the SDK filters to just the text deltas (usually what you want).
- **Both worlds** — after the loop, `stream.get_final_message()` gives the assembled whole for
  storage / further processing. Live chunks for the user **and** a complete object for your logic.

## Claude ↔ Gemini mapping

| | Claude | Gemini |
|---|---|---|
| start a stream | `client.messages.stream(...)` (context manager) | `client.models.generate_content_stream(...)` (iterator) |
| the text chunks | `for text in stream.text_stream` | `for chunk in stream: chunk.text` |
| the assembled whole | `stream.get_final_message()` | join the chunks yourself |
| raw-event mode | `messages.create(..., stream=True)` → typed events | iterate the chunk objects (each has candidates/parts) |

Same UX, different surface: Claude gives a tidy `text_stream` + `get_final_message()` helper; Gemini
hands you chunk objects you read `.text` from and assemble.

> **Claude-5 note:** with thinking on, `text_stream` still yields only the **visible answer** text
> (thinking is separate), so you don't hit the `ThinkingBlock` issue from Lesson 02 here. `flush=True`
> on `print` matters — otherwise the terminal buffers and it looks un-streamed.

## Where this fits in my project

Streaming is a **known enhancement** I flagged in `interview-prep/GENAI.md` ("SSE streaming
responses — latency-perceived win"). Today the narration **`/chat` (P3)** returns the full answer in
one shot; streaming it (server-sent events) would make the assistant feel instant. The `get_final_message`
pattern maps cleanly onto P3's flow: **stream to the user, then persist the assembled turn** to
`chat_turns` — exactly the "best of both worlds" above. Not built yet; this lesson is the design for it.
