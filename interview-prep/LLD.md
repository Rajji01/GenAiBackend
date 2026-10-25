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

## LLD fundamentals to keep sharp (backlog — one card per walk)
- SOLID with a repo example per letter (e.g. OCP = Strategy in payments; DIP = `JobQueue` protocol).
- Composition-over-inheritance example from the repo.
- "How do you make this testable?" — the mocked `PlatformTransactionManager` / injectable-clock tricks.
- Concurrency LLD: optimistic (`@Version`) vs pessimistic vs Redis SETNX (ticketing Week 1).
- **ConcurrentHashMap internals** (MobiKwik signal 2026-10-25): Java 8 — CAS to place the first node in an empty bin, then `synchronized` on the **bin head** only (fine-grained, not the Java-7 segment lock, not a whole-map lock); treeify a bin at 8 nodes; `size()` via striped `CounterCell`s to avoid a hot counter. Trade-off vs `Hashtable`/`Collections.synchronizedMap` (full-object lock) and the weakly-consistent iterator. Repo bridge: this is the in-memory cousin of the ticketing concurrency ladder (`@Version` / SETNX).
- **LRU cache, O(1) get+put** (MobiKwik signal): HashMap(key→node) + doubly-linked list, head=MRU / tail=LRU; get = lookup + move-to-head; put = insert-head + evict-tail past capacity. Real-world answer: `LinkedHashMap(accessOrder=true)` override `removeEldestEntry`, or Caffeine. Repo echo: P3 chat memory-cap (N=6) + the semantic-cache backlog in `GENAI.md`. **Also the first DSA design-a-DS deposit — see `dsa/`.**
