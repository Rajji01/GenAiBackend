# LLD.md — Low-Level Design (OOP / design patterns) prep

**Pillar 3b of 4.** Grows each self-walk. See [`README.md`](README.md) for the dual mandate.

LLD = code-level design: patterns, class responsibilities, SOLID, testability. This repo is a
pattern museum already — this file maps **each pattern to the real file that uses it**, so the
interview answer is "yes, and here's where I used it and why," not a textbook recital.

---

## Pattern catalog (mapped to real code)

| Pattern | Where in repo | Why there (the LLD point) | Status |
|---|---|---|---|
| **Strategy** | `payment-service` payment methods | Each payment method = interchangeable algorithm behind one interface; add a method without touching the caller | mapped |
| **Adapter** | `payment-service` `UPIAdapter` etc. | Wrap a foreign gateway API into our uniform port; gateway-failure translated at the boundary | mapped |
| **Factory** | `payment-service` `PaymentGatewayFactory` | Pick the concrete adapter at runtime from method type; caller stays ignorant of construction | mapped |
| **Outbox** | `booking-service` `outbox/` | Defeat dual-write: atomic state + outbox row in one tx, async drain → at-least-once | mapped |
| **Registry + Command** | narration `tools.py` | Whitelisted tool registry; `execute_tool` = the only door; unknown/invalid → data-framed observation | mapped |
| **State machine** | `payment` (auth→capture), `dispute_agent` (named transitions) | Illegal transitions throw; terminal states sticky; the human gate is a state the agent can't construct | mapped |
| **Circuit Breaker** | narration `circuit_breaker.py` | Hystrix states, injectable clock, lazy transitions; trips only on transient whitelist | mapped |
| **Template Method / Protocol** | narration `JobQueue` (InMemory + Sqs) | One interface, two impls; moto re-proves the fake's behavioural claims | mapped |

---

## LLD design prompts (rehearse — each anchors to code)
- **"Design a payment system supporting multiple methods."** → Strategy + Adapter + Factory, the exact `payment-service` shape. Draw the class diagram from memory.
- **"Design a rate limiter."** → sliding-window (`rate_limiter.py`); discuss token-bucket vs fixed-window vs sliding trade-offs.
- **"Design a retry mechanism."** → whitelist-only (429/503/504), budget → terminal; the parent-class "ignore-exceptions" trap (Bug 5) as the anti-pattern.
- **"Design a tool-calling registry safely."** → `tools.py`: typed args as the gate, single door, read-only whitelist.

## Deep cards (one per walk, from the backlog)

### Card 1 — ConcurrentHashMap internals (MobiKwik Q1) · [2026-10-25]

**The question:** "How does CHM achieve thread safety without locking the entire map?"

**The one-breath answer:** Java 8 CHM locks **per bin, lazily, and only for writes that
collide** — reads lock nothing at all. Three mechanisms, in escalation order:

1. **Reads are lock-free.** `get()` takes no lock ever: the bin table and each node's
   `val`/`next` are `volatile`, so a reader sees a consistent node chain via the Java
   memory model, not via mutual exclusion. This is why CHM read-throughput scales
   with cores while `Hashtable` flatlines.
2. **First write into an EMPTY bin = CAS, no lock.** `put()` on an empty bin does a
   compare-and-swap of the new node into the table slot. Uncontended inserts are
   lock-free; only a lost CAS race falls through to…
3. **Write into a NON-empty bin = `synchronized` on that bin's head node.** Not the
   Java-7 segment (16 coarse stripes), not the map — the single bucket being touched.
   Two writers collide only when they hash to the SAME bin.

**The supporting facts interviewers probe next:**
- **Treeify:** a bin past 8 nodes (table ≥ 64) becomes a red-black tree — worst-case
  bucket ops drop O(n)→O(log n), a hash-flood defence as much as a perf one.
- **`size()`:** no shared hot counter (that would be the contention CHM just removed) —
  a striped `baseCount` + `CounterCell[]` array summed on read; the count is an estimate
  under concurrency, and that's the contract.
- **Resize is cooperative:** threads that hit the map mid-transfer *help move bins*
  (`ForwardingNode` marks moved buckets) instead of blocking behind one resizer.
- **Iterators are weakly consistent** (never `ConcurrentModificationException`; may or
  may not see concurrent updates) — vs `Hashtable`'s fail-fast-under-lock.
- **No null keys/values** — `null` would be ambiguous with "absent" under concurrency
  (a `get()==null` can't tell "mapped to null" from "removed between my reads").
- **Compound ops need the atomic methods:** check-then-act (`if !contains → put`) is
  STILL racy on CHM; use `putIfAbsent`/`compute`/`merge` — the per-key CAS/lock makes
  those atomic.

**Trade-off table vs the alternatives:** `Hashtable` / `Collections.synchronizedMap` =
one lock for everything (correct, zero read scaling, fail-fast iterators);
Java-7 CHM = 16 segment locks (better, but a segment is still many bins);
Java-8 CHM = per-bin (reads free, writes collide only on the same bucket).

**Repo bridge (the answer's closer):** this is the in-memory cousin of the ticketing
concurrency ladder — CAS-then-lock escalation ≈ optimistic `@Version` (CAS at the DB row)
backed by pessimistic locks when contention is real; `putIfAbsent` ≈ Redis `SETNX`
(Week 1 seat lock); and narration's `reserve_llm_call` budget is a CAS loop in SQL.
Same design instinct at three altitudes: **lock the smallest thing, for the shortest time,
and prefer a compare-and-swap to a lock at all.**

---

## LLD fundamentals to keep sharp (backlog — one card per walk)
- SOLID with a repo example per letter (e.g. OCP = Strategy in payments; DIP = `JobQueue` protocol).
- Composition-over-inheritance example from the repo.
- "How do you make this testable?" — the mocked `PlatformTransactionManager` / injectable-clock tricks.
- Concurrency LLD: optimistic (`@Version`) vs pessimistic vs Redis SETNX (ticketing Week 1).
- ~~**ConcurrentHashMap internals** (MobiKwik signal 2026-10-25)~~ ✅ → Card 1 above.
- ~~**LRU cache, O(1) get+put** (MobiKwik signal)~~ ✅ → solved as DSA deposit #1, [`dsa/design/LRUCache.java`](dsa/design/LRUCache.java) (hand-rolled + run-verified; `LinkedHashMap(accessOrder=true)`/Caffeine named as the production twins). Repo echo: P3 chat memory-cap (N=6) + the semantic-cache backlog in `GENAI.md`.
