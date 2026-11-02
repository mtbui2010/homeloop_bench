"""Split policy (DESIGN 10.6): ids, file order, held-out houses and test-only template ids.

File order within a split: shuffled by ``gen_seed``, then interleaved round-robin over (kind, capability) so that
the first few hundred dev tasks hold every kind and capability (the checker runs ``--limit 300``).
"""

from __future__ import annotations

from homeloop_robot.rng import rng_for

from . import compound as CP
from . import templates_en as EN
from .sample import HELD_OUT, SPLIT_HOUSES


def is_test_template(template_id: str) -> bool:
    parts = template_id.split(".")
    try:
        nn = int(parts[-1])
    except ValueError:
        return False
    if parts[0] == "compound":
        return nn in CP.TEST_PATTERNS
    return nn in EN.WRAP_TEST


def order_split(records: list, split: str, gen_seed: int) -> list:
    rng = rng_for(gen_seed, "order", split)
    recs = sorted(records, key=lambda r: r["_key"] if "_key" in r else r.get("id", ""))
    rng.shuffle(recs)
    groups = {}
    for r in recs:
        groups.setdefault((r["kind"], r["capability"]), []).append(r)
    keys = sorted(groups)
    rng.shuffle(keys)
    out = []
    while any(groups.values()):
        for k in keys:
            if groups[k]:
                out.append(groups[k].pop(0))
    return out


def assign_ids(records: list, split: str, gen_seed: int) -> list:
    out = order_split(records, split, gen_seed)
    for i, r in enumerate(out):
        r.pop("_key", None)
        r["id"] = f"hl-{split}-{i:06d}"
        r["split"] = split
    return out


__all__ = ["HELD_OUT", "SPLIT_HOUSES", "assign_ids", "is_test_template", "order_split"]
