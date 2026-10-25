// =============================================================================
// DSA deposit #1 — Design an LRU Cache, O(1) get + put
// Pattern: design-a-data-structure (HashMap over a doubly-linked list)
// Source signal: MobiKwik Q2 (JARVIS_CHAIN §2, 2026-10-25)
// -----------------------------------------------------------------------------
// TRIGGER (recognition): "O(1) get AND put" + "evict least-recently-used"
//   ⇒ you need O(1) lookup (HashMap) AND O(1) reordering/eviction at both
//     ends (doubly-linked list). Neither alone can do both jobs:
//     - HashMap alone: no order.
//     - List alone: O(n) lookup.
//     The map's VALUES are list NODES — that pointer is the whole trick.
//
// APPROACH:
//   - Doubly-linked list holds usage order: head side = most recent,
//     tail side = least recent. Two SENTINEL nodes (head, tail) so
//     insert/unlink never special-cases null neighbours.
//   - get(k): map hit → unlink node, re-insert at head (it's now MRU).
//   - put(k,v): existing → update value + move to head. New → insert at
//     head; if over capacity, evict tail.prev (the true LRU) from BOTH
//     the list and the map.
//
// COMPLEXITY: get O(1), put O(1), space O(capacity).
//
// GOTCHAS (the ones that bite in interviews):
//   1. Evicting from the LIST but forgetting map.remove(evicted.key) —
//      the map grows forever and a stale key resurrects freed nodes.
//      (That's why Node stores the KEY, not just the value.)
//   2. get() must ALSO move-to-head — "read refreshes recency" IS the
//      LRU contract; forgetting it passes the happy-path test and fails
//      the eviction-order one.
//   3. put() on an EXISTING key must not evict — size didn't grow.
//   4. Sentinels: without them, every unlink needs four null checks.
//
// REPO ECHOES (the interview bridge):
//   - model_router.py's client cache is a capacity-UNbounded map — the
//     moment models multiply, THIS structure is its bounded upgrade.
//   - The idempotency_keys table (H3) is "cache without eviction" — its
//     flagged missing TTL is this problem's eviction policy, by time
//     instead of recency.
//   - Production twin: java.util.LinkedHashMap(capacity, 0.75f, true)
//     with removeEldestEntry overridden — SAY this in the interview
//     after hand-rolling; it shows you know the JDK shipped the answer.
// =============================================================================

import java.util.HashMap;
import java.util.Map;

public class LRUCache {

    private static final class Node {
        final int key;        // stored so eviction can clean the map (gotcha #1)
        int value;
        Node prev, next;

        Node(int key, int value) {
            this.key = key;
            this.value = value;
        }
    }

    private final int capacity;
    private final Map<Integer, Node> index = new HashMap<>();
    private final Node head = new Node(-1, -1);   // sentinel: MRU side
    private final Node tail = new Node(-1, -1);   // sentinel: LRU side

    public LRUCache(int capacity) {
        if (capacity <= 0) throw new IllegalArgumentException("capacity must be positive");
        this.capacity = capacity;
        head.next = tail;
        tail.prev = head;
    }

    public int get(int key) {
        Node node = index.get(key);
        if (node == null) return -1;
        moveToHead(node);                          // read refreshes recency (gotcha #2)
        return node.value;
    }

    public void put(int key, int value) {
        Node existing = index.get(key);
        if (existing != null) {                    // update: no growth, no eviction (gotcha #3)
            existing.value = value;
            moveToHead(existing);
            return;
        }
        Node node = new Node(key, value);
        index.put(key, node);
        insertAtHead(node);
        if (index.size() > capacity) {
            Node lru = tail.prev;                  // true LRU lives next to the tail sentinel
            unlink(lru);
            index.remove(lru.key);                 // the map cleanup everyone forgets (gotcha #1)
        }
    }

    public int size() {
        return index.size();
    }

    // --- list plumbing: sentinels mean no null checks anywhere (gotcha #4) ---

    private void unlink(Node node) {
        node.prev.next = node.next;
        node.next.prev = node.prev;
    }

    private void insertAtHead(Node node) {
        node.next = head.next;
        node.prev = head;
        head.next.prev = node;
        head.next = node;
    }

    private void moveToHead(Node node) {
        unlink(node);
        insertAtHead(node);
    }

    // --- self-verifying: java LRUCache runs the interview's test cases ---

    public static void main(String[] args) {
        // The classic LeetCode-146 sequence.
        LRUCache c = new LRUCache(2);
        c.put(1, 1);
        c.put(2, 2);
        assertEq(c.get(1), 1);          // 1 is now MRU
        c.put(3, 3);                    // evicts 2 (the LRU), NOT 1
        assertEq(c.get(2), -1);
        c.put(4, 4);                    // evicts 1
        assertEq(c.get(1), -1);
        assertEq(c.get(3), 3);
        assertEq(c.get(4), 4);

        // Gotcha #2: a GET must refresh recency.
        LRUCache r = new LRUCache(2);
        r.put(1, 1);
        r.put(2, 2);
        r.get(1);                       // 1 refreshed → 2 is now LRU
        r.put(3, 3);                    // must evict 2
        assertEq(r.get(1), 1);
        assertEq(r.get(2), -1);

        // Gotcha #3: updating an existing key never evicts.
        LRUCache u = new LRUCache(2);
        u.put(1, 1);
        u.put(2, 2);
        u.put(1, 99);                   // update, size stays 2
        assertEq(u.size(), 2);
        assertEq(u.get(1), 99);
        assertEq(u.get(2), 2);          // nothing was evicted

        // Gotcha #1: eviction cleans the MAP too (stale key stays gone).
        LRUCache m = new LRUCache(1);
        m.put(1, 1);
        m.put(2, 2);                    // evicts 1 from list AND map
        assertEq(m.get(1), -1);
        assertEq(m.size(), 1);

        System.out.println("LRUCache: all assertions passed");
    }

    private static void assertEq(int actual, int expected) {
        if (actual != expected) {
            throw new AssertionError("expected " + expected + " got " + actual);
        }
    }
}
