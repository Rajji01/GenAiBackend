"""
P7 Day 2 — Okapi BM25 + Reciprocal Rank Fusion, pure Python.

Why this exists (P7_DESIGN.md §2): dense retrieval trades surface form
for meaning — the literal token `NETFLIX` inside `UPI/NETFLIX/Payment`
can lose to fuzzier semantic neighbours under cosine. BM25 scores the
token itself. Production RAG runs both channels and fuses; this file
is both halves of that, at this repo's scale (rule 3-7):

- No persisted inverted index — scoring a few hundred docs per query
  is microseconds; the index is the at-scale move, named not built.
- No numpy — same call as rag.cosine_similarity's.
- Tokenizer = lowercase alphanumeric split. Bank narrations are
  `UPI/NETFLIX/Payment` strings: splitting on every non-alnum IS the
  domain-right tokenizer here, not a shortcut.

Fusion is RRF over RANK POSITIONS (`Σ 1/(k + rank)`, k=60): cosine
(0..1) and BM25 (unbounded) are incomparable scales, and weighted
score-mixing needs per-corpus calibration that silently drifts. Ranks
are scale-free.
"""

from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Standard literature defaults; tuning them without an eval set that
# shows the defaults losing would be rule-3-7 bait.
K1 = 1.5
B = 0.75

# The RRF smoothing constant from the original paper. Larger k flattens
# the head of each ranking (rank 1 vs rank 2 matters less).
RRF_K = 60


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25:
    """Score a fixed corpus against ad-hoc queries. Built per query
    call-site from the same rows the dense path reads — corpus
    freshness is the DB's problem, not a cache's."""

    def __init__(self, documents: list[str], k1: float = K1, b: float = B):
        self._k1 = k1
        self._b = b
        self._doc_tokens = [tokenize(d) for d in documents]
        self._doc_lens = [len(t) for t in self._doc_tokens]
        self._n = len(documents)
        self._avgdl = (sum(self._doc_lens) / self._n) if self._n else 0.0
        # Document frequency per term.
        self._df: dict[str, int] = {}
        for tokens in self._doc_tokens:
            for term in set(tokens):
                self._df[term] = self._df.get(term, 0) + 1

    def _idf(self, term: str) -> float:
        # BM25+-style floor at 0: a term in >half the corpus carries
        # no signal, but must never carry NEGATIVE signal (the classic
        # BM25 idf can go below zero and make matching a common term
        # WORSE than not matching — nonsense for retrieval).
        df = self._df.get(term, 0)
        if df == 0:
            return 0.0
        return max(0.0, math.log((self._n - df + 0.5) / (df + 0.5) + 1.0))

    def scores(self, query: str) -> list[float]:
        """BM25 score of every corpus doc against the query, corpus
        order. 0.0 means no term overlap — the lexical channel's
        natural entry bar."""
        q_terms = tokenize(query)
        out: list[float] = []
        for tokens, dl in zip(self._doc_tokens, self._doc_lens):
            if not tokens:
                out.append(0.0)
                continue
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            norm = self._k1 * (1 - self._b + self._b * dl / self._avgdl)
            for term in q_terms:
                f = tf.get(term, 0)
                if f == 0:
                    continue
                score += self._idf(term) * (f * (self._k1 + 1)) / (f + norm)
            out.append(score)
        return out


def rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Fuse ranked lists of item KEYS (any hashable ints — row ids
    here) into {key: fused_score}. An item absent from a ranking
    simply contributes nothing from that channel — no penalty, no
    imputed rank. Appearing high in BOTH channels beats topping one."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            fused[key] = fused.get(key, 0.0) + 1.0 / (k + rank + 1)
    return fused
