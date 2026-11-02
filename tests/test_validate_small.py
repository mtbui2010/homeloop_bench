import json

import yaml

from homeloop_bench.gen.realism import report
from homeloop_bench.gen.sample import Gen
from homeloop_bench.gen.split import assign_ids
from homeloop_bench.gen.validate import validate


def test_small_generated_dataset_validates(tmp_path):
    g = Gen(77, {"train": 60, "dev": 20, "test": 40})
    out = g.run()
    paths = {}
    recs = []
    for s, rs in out.items():
        rs = assign_ids(rs, s, 77)
        recs += rs
        p = tmp_path / f"{s}.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        paths[s] = p
    pol = tmp_path / "policy.yaml"
    pol.write_text(yaml.safe_dump({"min_share": 0.0, "documented_small": {}}))
    lines = []
    fails, warns = validate(paths=paths, out=lines.append, policy_path=pol)
    assert fails == 0 and warns == 0, "\n".join(lines)
    rep = report(recs)
    assert rep["ok"], json.dumps(rep["rules"], ensure_ascii=False)[:2000]


def test_validator_catches_a_broken_record(tmp_path):
    g = Gen(78, {"train": 6, "dev": 4, "test": 6})
    out = g.run()
    paths = {}
    for s, rs in out.items():
        rs = assign_ids(rs, s, 78)
        if s == "dev":
            rs[0]["text"]["ko"] = rs[1]["text"]["ko"]          # exact duplicate
            rs[1]["goal"] = {"all": [{"pred": "on", "args": ["no_such_object", "x"]}]}
        p = tmp_path / f"{s}.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        paths[s] = p
    pol = tmp_path / "policy.yaml"
    pol.write_text(yaml.safe_dump({"min_share": 0.0}))
    lines = []
    fails, _ = validate(paths=paths, out=lines.append, policy_path=pol)
    assert fails >= 2
    assert any(l.startswith("FAIL  3a") for l in lines)
