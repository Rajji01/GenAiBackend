# anthropic-course — PRACTICE (you build, Jarvis verifies)

**How this works:** pick a task → write a small script in `anthropic-course/practice/` (e.g.
`practice/t1.py`) → run it → paste your code + output to Jarvis → Jarvis checks it against the
**Acceptance** box and gives feedback/fixes. Do them in **Gemini or Claude** (or both — bonus points
for noticing the divergences). Keys already load from `narration-enrichment/.env`.

> No solutions in this file (on purpose — doing it is the learning). Hints point to the lesson.

---

## Section 1 — API basics (Lessons 01–06)

### Task 1 — First request, clean answer  ·  _L01_
**Goal:** ask the model "Name 3 Indian street foods" and print **only** the answer text.
**Hint:** L01. On Claude use the `text_of()` helper (thinking block can be at index 0).
**Acceptance:** runs with no crash; prints the 3 foods; on Claude you did NOT use `content[0].text`.

### Task 2 — Prove statelessness  ·  _L02_
**Goal:** 3-turn chat — (1) "My favourite language is Python." (2) model replies (3) ask "What did I
just say my favourite language is?" Then run the SAME 3rd question with a FRESH empty history.
**Hint:** L02 helpers (`add_user_message`/`add_assistant_message`). Feed the model's reply back in.
**Acceptance:** with history → it answers "Python"; without history → it canNOT (asks/guesses). You
explain in one line WHY (API is stateless).

### Task 3 — Two personas, one question  ·  _L03_
**Goal:** ask "Explain recursion" twice — once with a **system prompt** "You are a strict professor,
answer in 1 sentence", once with "You explain to a 5-year-old with a toy analogy". Show both.
**Hint:** L03. Claude `system=`; Gemini `config.system_instruction`. Reuse your `chat()`.
**Acceptance:** the two answers are visibly different in tone/length; the only thing you changed is
the system prompt.

### Task 4 — Feel the temperature  ·  _L04 (Gemini)_
**Goal:** generate a one-line startup idea **3 times at temperature 0.0** and **3 times at 1.0**;
print both batches.
**Hint:** L04 Gemini (`GenerateContentConfig(temperature=...)`). On **Claude**, instead show the
divergence (temperature is removed → it errors) in a comment or try/except.
**Acceptance:** temp 0.0 batch is near-identical lines; temp 1.0 batch shows variety. One line on
WHY (sampling distribution).

### Task 5 — Stream it  ·  _L05_
**Goal:** stream a "write a 3-sentence story about a chai tapri" response so text appears
chunk-by-chunk, then print the total character count of the assembled text.
**Hint:** L05. Claude `messages.stream` + `text_stream` + `get_final_message`; Gemini
`generate_content_stream` + join chunks. `flush=True` on print.
**Acceptance:** output visibly streams (not one dump); you print the final length from the ASSEMBLED
message, not by re-asking.

### Task 6 — Clean JSON, the modern way  ·  _L06_
**Goal:** ask for "a user profile (name, age, city, hobbies[]) as JSON" and get it **parseable with
`json.loads` on the first try** — no markdown fence, no prose.
**Hint:** L06. Do NOT use prefill (it 400s on current Claude). Use a "JSON only" system prompt +
`stop_sequences` (Claude) or `response_mime_type="application/json"` (Gemini).
**Acceptance:** `json.loads()` succeeds; the parsed dict has all 4 keys; `hobbies` is a list.

### ⭐ Capstone — mini-`/enrich` (combine L01+L03+L06)  ·  _ties to your P1_
**Goal:** write `classify(narration)` that takes a messy transaction string (e.g.
`"UPI/P2M/.../SWIGGY BANGALORE/Payment"`) and returns a **parsed dict**
`{merchant, category, is_subscription}` — using a system prompt to set the rules + structured JSON
output. Run it on 2–3 sample narrations.
**Hint:** this is P1 without Instructor — system prompt does the instruction, JSON-mode/stop gives
clean output, `json.loads` parses. Category should be from a small fixed set you define in the system prompt.
**Acceptance:** returns a real dict (not a string) for each input; `category` is always one of your
allowed set; code has a single reusable function. (Bonus: note how Instructor+Pydantic in real P1
makes the "always valid" part guaranteed instead of hoped-for.)

---

**When you finish a task:** paste the code + output here. I verify against the Acceptance box, point
out anything off, and we move on. Finish all 7 → **Section 1 signed off**, and we start Section 2
when the course gives the next batch.
