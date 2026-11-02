"""Split by task identity (gen/resplit.py) and the goal-level leakage check."""

import copy

from homeloop_bench.gen import resplit as R


def _rec(i, house, obj, split, text_en, text_ko, tpl="rearrange.feasible.00", kind="feasible"):
    g = {"all": [{"pred": "on", "args": [obj, "table@living"]}]}
    return {"id": f"hl-{split}-{i:06d}", "split": split, "house": house, "kind": kind, "goal": g,
            "subtasks": [{"kind": kind, "goal": g}], "order": None, "capability": "rearrange",
            "template_id": tpl, "text": {"en": text_en, "ko": text_ko}, "meta": {}}


def _data():
    out = []
    for i in range(40):
        obj = f"obj_{i % 20}"                       # every identity twice, with different wording
        out.append(_rec(i, "senior_flat", obj, "train" if i < 20 else "test",
                        f"Variant {i}: please move {obj} {'now' if i < 20 else 'later'} to the table number {i}",
                        f"{obj} 를 {i}번 탁자에 놓아 주세요 버전 {i}"))
    return out


def test_identity_groups_never_cross_splits():
    recs = _data()
    assert R.leakage(recs)["identity"] > 0
    out = R.resplit(copy.deepcopy(recs), sizes={"train": 20, "dev": 10, "test": 10})
    allr = [r for rs in out.values() for r in rs]
    assert len(allr) == 40 and R.leakage(allr)["identity"] == 0
    assert all(r["meta"]["gen_id"].startswith("hl-") for r in allr)
    again = R.resplit(copy.deepcopy(allr), sizes={"train": 20, "dev": 10, "test": 10})
    assert {s: [r["meta"]["gen_id"] for r in rs] for s, rs in again.items()} == \
        {s: [r["meta"]["gen_id"] for r in rs] for s, rs in out.items()}


def test_held_out_house_goes_to_test():
    recs = _data()
    recs[0]["house"] = "care_home_suite"
    out = R.resplit(copy.deepcopy(recs), sizes={"train": 20, "dev": 10, "test": 10})
    assert all(r["split"] == "test" for r in out["test"])
    assert any(r["house"] == "care_home_suite" for r in out["test"])
    assert not any(r["house"] == "care_home_suite" for s in ("train", "dev") for r in out[s])


def test_stratified_order_keeps_prefix_shares():
    recs = [_rec(i, "senior_flat", f"o{i}", "dev", f"t{i}", f"k{i}", kind="refuse" if i % 10 == 0 else "feasible")
            for i in range(100)]
    for r in recs:
        r["meta"]["gen_id"] = r["id"]
    order = R.stratified_order(recs, 2026, "dev")
    assert sum(1 for r in order[:20] if r["kind"] == "refuse") == 2
