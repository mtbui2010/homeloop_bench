"""Split by task identity (docs/splits.md; review round 1): the last step of the data pipeline.

The first generation split tasks one by one, so the same request (same house, same goal, same subtasks, same kind)
could sit in train and in test with nearly the same wording. ``resplit`` groups the records and assigns whole groups
to one split:

* group = union of records with the same identity key (house, kind, subtasks with their kinds, goals, conditions and
  requested atoms, order) and of records whose texts are near duplicates in either language (Jaccard >= 0.90,
  ``dedup``), so no identity and no near-duplicate text crosses a split;
* groups with a held-out house or a test-only template go to test (with the identity grouping this is about 4,500
  tasks, mostly one-subtask tasks);
* the other groups top test up to its size (5,000) in the strata where it is below the data's shares, fill dev to
  its size (1,000) and train with the rest, greedily by the deficit of the group's stratum (kind x number of
  subtasks), so the splits keep close to the same label shares;
* file order: a stratified order (each next record comes from the stratum furthest below its share), so any prefix
  of a split (``--limit N``) has about the split's kind / subtask-count shares;
* ids ``hl-<split>-<6 digits>`` in file order; ``meta.gen_id`` / ``meta.gen_split`` keep the generation-time id and
  split (the paraphrase step derives its seeds and selection from them, so its LLM cache stays valid).

Deterministic: groups and records are ordered by sha256 of their generation ids and ``gen_seed``.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from . import dedup
from .sample import HELD_OUT
from .split import is_test_template


RESPLIT_SIZES = {"train": 4000, "dev": 1000, "test": 5000}      # train gets the rest (design choice)


def gen_id(r: dict) -> str:
    return (r.get("meta") or {}).get("gen_id") or r["id"]


def identity(r: dict) -> str:
    """The task identity: what the robot has to achieve, independent of the wording."""
    subs = []
    for s in r.get("subtasks") or [{"kind": r["kind"], "goal": r["goal"]}]:
        subs.append({k: s.get(k) for k in ("kind", "goal", "condition", "requested") if s.get(k) is not None})
    return json.dumps([r["house"], r["kind"], subs, r.get("order")], sort_keys=True, ensure_ascii=False)


def stratum(r: dict) -> str:
    return f"{r['kind']}|{len(r.get('subtasks') or []) or 1}"


def _h(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


def groups(records: list) -> list:
    """Lists of record indices that must share a split."""
    uf = _UF(len(records))
    first: dict = {}
    for i, r in enumerate(records):
        k = identity(r)
        if k in first:
            uf.union(first[k], i)
        else:
            first[k] = i
    for lg in ("en", "ko"):
        idx = dedup.NearDupIndex()
        for i, r in enumerate(records):
            idx.add(i, r["text"][lg], lg, "all")
        for i, r in enumerate(records):          # every near-duplicate pair (MinHash candidates, exact Jaccard)
            sh = dedup.shingles(r["text"][lg], lg)
            mh = dedup.minhash(sh)
            for b in idx._bands(mh):
                for key in idx.buckets[lg].get(b, ()):
                    if key != i and uf.find(key) != uf.find(i) and \
                            dedup.jaccard(sh, idx.items[lg][key][1]) >= dedup.NEAR_DUP_J:
                        uf.union(i, key)
    out: dict = {}
    for i in range(len(records)):
        out.setdefault(uf.find(i), []).append(i)
    return list(out.values())


def _forced_test(rs: list) -> bool:
    return any(r["house"] in HELD_OUT or is_test_template(r["template_id"]) for r in rs)


def assign(records: list, gen_seed: int = 2026, sizes: dict = RESPLIT_SIZES) -> dict:
    """{split: [records]} (not yet ordered)."""
    gs = groups(records)
    gs.sort(key=lambda g: _h(gen_seed, "group", min(gen_id(records[i]) for i in g)))
    out = {"train": [], "dev": [], "test": []}
    free = []
    for g in gs:
        rs = [records[i] for i in g]
        (out["test"].extend(rs) if _forced_test(rs) else free.append(rs))
    n_free = sum(len(g) for g in free)
    n_all = n_free + len(out["test"])
    glob = Counter(stratum(r) for g in gs for r in (records[i] for i in g))
    forced = Counter(stratum(r) for r in out["test"])
    # test first takes the forced groups (held-out houses, test-only templates and every task that shares an
    # identity or a near-duplicate text with them), which are mostly one-subtask tasks; free groups then top test up
    # to its size in the strata where it is below the data's shares, dev gets its size, train the rest
    want = {"test": max(0, sizes["test"] - len(out["test"])), "dev": sizes["dev"]}
    want["train"] = max(0, n_free - want["test"] - want["dev"])
    tgt = {"test": {k: max(0.0, sizes["test"] * v / n_all - forced[k]) for k, v in glob.items()}}
    left = {k: glob[k] - forced[k] - tgt["test"][k] for k in glob}
    n_left = max(1.0, sum(left.values()))
    for s in ("dev", "train"):
        tgt[s] = {k: want[s] * max(0.0, left[k]) / n_left for k in glob}
    have = {s: Counter() for s in want}
    size = {s: 0 for s in want}
    for rs in free:
        st = Counter(stratum(r) for r in rs).most_common(1)[0][0]
        best, best_d = None, None
        for s in ("test", "dev", "train"):
            if size[s] + len(rs) > want[s] and s != "train":
                continue
            d = (tgt[s][st] - have[s][st]) / max(1.0, tgt[s][st])
            if best is None or d > best_d + 1e-12:
                best, best_d = s, d
        out[best].extend(rs)
        size[best] += len(rs)
        for r in rs:
            have[best][stratum(r)] += 1
    return out


def stratified_order(records: list, gen_seed: int, split: str) -> list:
    """Each next record from the stratum with the largest deficit against its share (ties: name), records within
    a stratum by seeded hash and, round-robin, by capability."""
    by: dict = {}
    for r in sorted(records, key=lambda r: _h(gen_seed, "order", split, gen_id(r))):
        by.setdefault(stratum(r), {}).setdefault(r["capability"], []).append(r)
    n = len(records)
    share = {k: sum(len(v) for v in caps.values()) / n for k, caps in by.items()}
    taken = Counter()
    rr = {k: 0 for k in by}
    out = []
    for i in range(n):
        k = max((k for k in by if any(by[k].values())), key=lambda k: (share[k] * (i + 1) - taken[k], k))
        caps = sorted(c for c in by[k] if by[k][c])
        c = caps[rr[k] % len(caps)]
        rr[k] += 1
        out.append(by[k][c].pop(0))
        taken[k] += 1
    return out


def resplit(records: list, gen_seed: int = 2026, sizes: dict = RESPLIT_SIZES) -> dict:
    for r in records:
        m = r.setdefault("meta", {}) or {}
        r["meta"] = m
        m.setdefault("gen_id", r["id"])
        m.setdefault("gen_split", r["split"])
    parts = assign(records, gen_seed, sizes)
    out = {}
    for s, rs in parts.items():
        rs = stratified_order(rs, gen_seed, s)
        for i, r in enumerate(rs):
            r["id"] = f"hl-{s}-{i:06d}"
            r["split"] = s
        out[s] = rs
    return out


def leakage(records: list) -> dict:
    """Cross-split identity leaks: {"identity": n records whose identity is also in another split}."""
    where: dict = {}
    for r in records:
        where.setdefault(identity(r), set()).add(r["split"])
    n = sum(1 for r in records if len(where[identity(r)]) > 1)
    return {"identity": n}
