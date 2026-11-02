"""Exact and near-duplicate detection (DESIGN 10.6).

Normalisation: NFKC, lower case, punctuation removed, whitespace collapsed; Korean also drops spaces.
Near duplicate: Jaccard >= 0.90 of character 5-gram sets (English) / 3-gram sets (Korean). Candidates come from
MinHash LSH (32 hashes = 8 bands x 4 rows; a pair at Jaccard 0.90 is a candidate with probability 0.9998) and are
then verified with the exact Jaccard. Hashes are crc32-based, so results do not depend on Python's salted hash().
"""

from __future__ import annotations

import re
import unicodedata
import zlib

NEAR_DUP_J = 0.90
SHINGLE = {"en": 5, "ko": 3}
N_HASH, BANDS = 32, 8
ROWS = N_HASH // BANDS
_P = (1 << 61) - 1
_AB = [((2 * i + 1) * 0x9E3779B97F4A7C15 % _P, (i * 0xBF58476D1CE4E5B9 + 7) % _P) for i in range(N_HASH)]


def norm(text: str, lang: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if lang == "ko":
        s = s.replace(" ", "")
    return s


def shingles(text: str, lang: str) -> frozenset:
    s = norm(text, lang)
    k = SHINGLE[lang]
    if len(s) <= k:
        return frozenset([s])
    return frozenset(s[i:i + k] for i in range(len(s) - k + 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def minhash(sh: frozenset) -> tuple:
    hs = [zlib.crc32(x.encode("utf-8")) for x in sh]
    return tuple(min((a * h + b) % _P for h in hs) for a, b in _AB)


class NearDupIndex:
    """Incremental index of texts per language; ``find(text, lang, other_than=split)`` returns the key of an
    indexed text in another split with Jaccard >= threshold (or None)."""

    def __init__(self, threshold: float = NEAR_DUP_J):
        self.t = threshold
        self.buckets = {"en": {}, "ko": {}}
        self.items = {"en": {}, "ko": {}}          # key -> (split, shingles)

    def _bands(self, mh):
        return [(i, mh[i * ROWS:(i + 1) * ROWS]) for i in range(BANDS)]

    def find(self, text: str, lang: str, other_than: str | None = None, same_split: bool = False):
        sh = shingles(text, lang)
        mh = minhash(sh)
        seen = set()
        for b in self._bands(mh):
            for key in self.buckets[lang].get(b, ()):
                if key in seen:
                    continue
                seen.add(key)
                split, sh2 = self.items[lang][key]
                if (same_split or split != other_than) and jaccard(sh, sh2) >= self.t:
                    return key
        return None

    def add(self, key, text: str, lang: str, split: str):
        sh = shingles(text, lang)
        self.items[lang][key] = (split, sh)
        for b in self._bands(minhash(sh)):
            self.buckets[lang].setdefault(b, []).append(key)


def near_dup_pairs(records: list, lang: str) -> list:
    """All cross-split near-duplicate pairs (id_a, id_b, jaccard) among records (validator)."""
    idx = NearDupIndex()
    out = []
    for r in records:
        t = r["text"][lang]
        sh = shingles(t, lang)
        mh = minhash(sh)
        seen = set()
        for b in idx._bands(mh):
            for key in idx.buckets[lang].get(b, ()):
                if key in seen:
                    continue
                seen.add(key)
                split, sh2 = idx.items[lang][key]
                if split != r["split"]:
                    j = jaccard(sh, sh2)
                    if j >= idx.t:
                        out.append((key, r["id"], round(j, 4)))
        idx.add(r["id"], t, lang, r["split"])
    return out
