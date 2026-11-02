"""``python -m homeloop_bench.data stats [--json]`` (DESIGN 10.7, 14)."""

from __future__ import annotations

from collections import Counter

LONG = {"en": 25, "ko": 15}


def is_long(r) -> bool:
    lw = r.get("length_words") or {}
    return lw.get("en", 0) >= LONG["en"] or lw.get("ko", 0) >= LONG["ko"]


def stats(recs: list) -> dict:
    n = len(recs)

    def by(f):
        return dict(sorted(Counter(r[f] for r in recs).items()))
    return {
        "total": n,
        "en": sum(1 for r in recs if (r["text"].get("en") or "").strip()),
        "ko": sum(1 for r in recs if (r["text"].get("ko") or "").strip()),
        "by_kind": by("kind"), "by_capability": by("capability"), "by_ambiguity": by("ambiguity"),
        "by_source": by("source"), "by_house": by("house"), "by_split": by("split"),
        "by_source_lang": {lg: dict(sorted(Counter((r.get("source_by_lang") or {}).get(lg, r["source"])
                                                   for r in recs).items())) for lg in ("en", "ko")},
        "paraphrased_both": sum(1 for r in recs if set((r.get("source_by_lang") or {}).values()) == {"llm_paraphrase"}),
        "by_subtasks": {str(k): v for k, v in sorted(Counter(r.get("n_subtasks", 1) for r in recs).items())},
        "by_structure": by("structure"),
        "long_share": round(sum(1 for r in recs if is_long(r)) / max(1, n), 4),
        "mixed_kind_share": round(sum(1 for r in recs if r.get("mixed_kind")) / max(1, n), 4),
    }
