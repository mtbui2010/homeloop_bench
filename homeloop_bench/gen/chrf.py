"""chrF (Popovic 2015): character n-gram F-score, n = 1..6, beta = 2, whitespace removed, pure Python."""

from __future__ import annotations

from collections import Counter


def _grams(s: str, n: int) -> Counter:
    s = "".join(s.split())
    return Counter(s[i:i + n] for i in range(len(s) - n + 1))


def chrf(hyp: str, ref: str, n: int = 6, beta: float = 2.0) -> float:
    """0-100. Averages precision and recall over the n-gram orders that exist in both strings."""
    hyp, ref = (hyp or "").lower(), (ref or "").lower()
    ps, rs = [], []
    for k in range(1, n + 1):
        h, r = _grams(hyp, k), _grams(ref, k)
        if not h or not r:
            continue
        m = sum((h & r).values())
        ps.append(m / sum(h.values()))
        rs.append(m / sum(r.values()))
    if not ps:
        return 0.0
    p, r = sum(ps) / len(ps), sum(rs) / len(rs)
    if p + r == 0:
        return 0.0
    b2 = beta * beta
    return 100.0 * (1 + b2) * p * r / (b2 * p + r)
