# Week 1 (Phase 0) — Weekend Review

The last step before Phase 1, per `Jarvis_Architect_Path.md`: answer
first, then Jarvis evaluates. Write your own answers below each question,
without looking at the README or `SEAT_LOCK.html`. Short and honest beats
long and copied. Where you can, point to the class or test in this project
that proves your answer.

---

## Interview questions

### 1. Optimistic vs pessimistic locking — when would you use each?

> _Your answer:_

### 2. How does `@Version` actually prevent overselling internally?
Hint: think about what SQL Hibernate sends.

> _Your answer:_

### 3. What other ways are there to prevent overselling?
(DB unique constraint, Redis atomic ops, `SELECT ... FOR UPDATE`): what does each one cost?

> _Your answer:_

### 4. Redis `SETNX` + TTL hold vs a DB lock: what's the trade-off?

> _Your answer:_

### 5. The hold succeeds but the user never pays. What happens?
Walk through Redis, Postgres and `HoldReconciliationService`, including the window between the TTL expiring and the next sweep.

> _Your answer:_

### 6. How did you make hold idempotent? And confirm?
Why can confirm's retry check *not* rely on Redis like hold's does?

> _Your answer:_

### 7. How would this service scale to 10x traffic?
Think about what breaks first: the reads, the Redis calls, Postgres writes, or reconciliation's full `findByStatus(HELD)` scan.

> _Your answer:_

---

## Bonus cross-questions (from the code as it stands)

- **B1.** Day 5 found that Redis `SETNX` decides the race in practice.
  So why keep `@Version` at all? Name a real path that skips Redis.
- **B2.** `confirm()` deletes the Redis key *before* the transaction
  commits (see the README Weekend entry). What exactly goes wrong if the
  commit fails, and why is it a lost booking rather than an oversell?
- **B3.** `reconcileOnce()` updates every expired seat in *one*
  transaction. What happens to the whole sweep if one seat throws
  `OptimisticLockingFailureException` (e.g. a confirm landed at the same
  moment)?
- **B4.** Why is a wrong-holder confirm a `403`, but confirming a seat
  booked by someone else a `409`?

---

## LLD reflection

- Where did the **Repository** boundary actually help? Name a test or a
  change that was easier because of it.
- What, if anything, was **over-engineered** for one service?
- What would you design differently if you started Week 1 again today?

> _Your reflection:_

---

## Evaluation (filled by Jarvis after your answers)

_Pending._
