# dsa/ — Data Structures & Algorithms track

**Pillar 4 of 4.** See [`../README.md`](../README.md) for the dual mandate.

**Why its own track:** DSA is the one pillar that does NOT fall out of the project naturally.
The platform teaches systems/GenAI/HLD/LLD by being built; DSA needs deliberate, separate reps.
So it runs as its own thread — pattern by pattern, a few problems each, with notes on the
*recognition trigger* ("when I see X, reach for Y"), not just the solution.

---

## How this track runs (the method)

1. **Pattern-first, not problem-count-first.** Learn the pattern's shape + when it applies, then
   solve 2–4 representative problems. Recognising the pattern in a disguised problem is the skill
   interviews test — not having memorised 500 solutions.
2. **Each solved problem gets a note:** the trigger ("sorted array + pair → two pointers"), the
   approach, complexity, and the gotcha that bit me. Code in the language I'll interview in
   (Java primary — it's the moat; Python where it's cleaner).
3. **One deposit per DSA walk** (rule §3-11 "small is fine"): either a new pattern's notes, or
   2–3 problems under a pattern already started. Rotation keeps it moving without cramming.
4. **Tie back where honest.** A few patterns *do* echo the project (sliding-window ↔ the rate
   limiter; graph/topo ↔ the saga/dispute state machines; heap ↔ a priority queue for the worker).
   Note the echo — it makes the pattern stick and gives an interview bridge from project to DSA.

---

## Pattern roadmap (tick as covered)

| # | Pattern | Repo echo (if any) | Problems solved | Status |
|---|---|---|---|---|
| 1 | Two pointers / sliding window | `rate_limiter.py` sliding window | 0 | not started |
| 2 | Hashing / frequency map | dedup by event_id (idempotent consumer) | 0 | not started |
| 3 | Binary search (on answer too) | — | 0 | not started |
| 4 | Stack / monotonic stack | — | 0 | not started |
| 5 | Linked list | — | 0 | not started |
| 6 | Trees / BST / traversal | recovery decision tree (shape only) | 0 | not started |
| 7 | Graphs (BFS/DFS/topo/union-find) | saga / dispute state machines | 0 | not started |
| 8 | Heap / priority queue | worker job prioritisation (conceptual) | 0 | not started |
| 9 | Backtracking | — | 0 | not started |
| 10 | Dynamic programming | — | 0 | not started |
| 11 | Intervals | — | 0 | not started |
| 12 | Greedy | retry budget / load-shed decisions (shape) | 0 | not started |

**Suggested order:** 1 → 2 → 3 → 5 → 4 → 6 → 7 → 8 → 11 → 12 → 9 → 10
(high-frequency + foundational first; DP/backtracking last).

---

## Queued (from market signals — see JARVIS_CHAIN §2)
- ~~**Design an LRU cache, O(1) get+put**~~ ✅ solved 2026-10-25 → see the log below.

## Solved log (append as problems are done)

**#1 · [2026-10-25] LRU Cache (O(1) get+put)** — [`design/LRUCache.java`](design/LRUCache.java)
(compiled + self-asserting `main` run green)
- **Pattern:** design-a-data-structure — HashMap whose VALUES are doubly-linked-list nodes.
- **Trigger:** "O(1) get AND put" + "evict least-recently-used" ⇒ map for lookup, DLL for
  order; neither alone does both. Map-value-is-list-node is the whole trick.
- **Approach:** sentinel head/tail (no null checks), get = hit + move-to-head, put = update-
  or-insert-at-head, over capacity ⇒ evict `tail.prev` from list AND map.
- **Complexity:** O(1)/O(1), space O(capacity).
- **Gotchas pinned by the self-asserts:** (1) eviction must clean the MAP (Node stores key
  for this), (2) a GET refreshes recency, (3) updating an existing key never evicts,
  (4) sentinels kill the null-check zoo.
- **Repo echoes:** `model_router.py`'s unbounded client cache = this structure's missing
  capacity bound; H3's idempotency table = cache-without-eviction (its flagged TTL = this
  problem's policy, by time). Production twin to NAME after hand-rolling:
  `LinkedHashMap(cap, 0.75f, true)` + `removeEldestEntry`.

Solutions will live as `dsa/<pattern>/<problem>.java` (or `.py`) with the note inline at top.
