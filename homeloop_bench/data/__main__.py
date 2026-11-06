"""``python -m homeloop_bench.data {generate,paraphrase,validate,stats,realism,quality}`` (docs/generation.md).

generate    build the template tasks and write data/tasks/{train,dev,test}.jsonl
paraphrase  LLM paraphrases (local Ollama on GPU 0 via tools/llm_gpu0.sh; cached, resumable)
resplit     the final split by task identity (gen/resplit.py): no goal or near-duplicate text across splits
validate    the dataset checks (--strict: warnings fail too)
stats       counts per label (--json)
realism     realism rules R-a..R-h (--strict); writes <repo>/data/quality/realism_report.json
quality     paraphrase + Korean back-translation quality report (needs the LLM for new back-translations)
delivery    round 2: held_by -> delivered(mode, mode_reason), explicit-hand variants, within-reach reseeds
            (gen/delivery.py; deterministic, idempotent); writes <repo>/data/quality/delivery_report.json
datasheet   rewrite docs/datasheet.md from the shipped quality reports (no LLM)
kofix       R2-5 B5: Korean texts that put something inside an object ("접시 안에 넣어") fall back to the template
            text or get the object particle back (gen/kofix.py; deterministic, idempotent)
"""

from __future__ import annotations

import argparse
import json
import sys

from . import QUALITY_DIR, SPLITS, TASKS_DIR


def _dump(recs, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            r = {k: v for k, v in r.items() if not k.startswith("_")}
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")


def _all():
    from ..tasks import read_records
    return [r for s in SPLITS for r in read_records(s)]


def cmd_generate(a):
    from ..gen.sample import Gen
    from ..gen.split import assign_ids
    sizes = {"train": a.train, "dev": a.dev, "test": a.test}
    g = Gen(a.gen_seed, sizes)
    out = g.run(log=lambda m: print(m, file=sys.stderr))
    for s in SPLITS:
        recs = assign_ids(out[s], s, a.gen_seed)
        _dump(recs, TASKS_DIR / f"{s}.jsonl")
        print(f"{s}: {len(recs)} -> {TASKS_DIR / (s + '.jsonl')}")
    print(json.dumps({"rejected": g.stats["rejected"]}, sort_keys=True))
    return 0


def cmd_resplit(a):
    from ..gen.resplit import leakage, resplit
    recs = _all()
    before = leakage(recs)
    out = resplit(recs, a.gen_seed)
    for s in SPLITS:
        _dump(out[s], TASKS_DIR / f"{s}.jsonl")
    after = leakage([r for s in SPLITS for r in out[s]])
    print(json.dumps({"sizes": {s: len(out[s]) for s in SPLITS}, "identity_leak_before": before["identity"],
                      "identity_leak_after": after["identity"]}, sort_keys=True))
    return 0


def cmd_validate(a):
    from ..gen.validate import validate
    fails, warns = validate(workers=a.workers)
    return 1 if fails or (a.strict and warns) else 0


def cmd_stats(a):
    from ..gen.stats import stats
    s = stats(_all())
    if a.json:
        print(json.dumps(s, sort_keys=True, ensure_ascii=False))
    else:
        for k, v in s.items():
            print(f"{k}: {v}")
    return 0


def cmd_realism(a):
    from ..gen.realism import report
    rep = report(_all())
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUALITY_DIR / "realism_report.json", "w", encoding="utf-8") as f:
        json.dump(rep, f, sort_keys=True, ensure_ascii=False, indent=1)
        f.write("\n")
    print(json.dumps(rep, sort_keys=True, ensure_ascii=False))
    return 1 if (a.strict and not rep["ok"]) else 0


def cmd_delivery(a):
    from ..gen.delivery import delivery_stats, rewrite_all
    from ..tasks import read_records
    recs = [r for s in SPLITS for r in read_records(s)]
    out, report = rewrite_all(recs)
    for s in SPLITS:
        _dump([r for r in out if r["split"] == s], TASKS_DIR / f"{s}.jsonl")
    report["by_split"] = {s: delivery_stats([r for r in out if r["split"] == s]) for s in SPLITS}
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUALITY_DIR / "delivery_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, sort_keys=True, ensure_ascii=False, indent=1)
        f.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "by_split"}, sort_keys=True))
    return 0


def cmd_tellfix(a):
    """Lab round 3, H3: re-render the train / dev tell_fetch tasks with the fetch clause in its own sentence."""
    from ..gen.tellfix import apply
    from ..tasks import read_records
    recs = [r for s in SPLITS for r in read_records(s)]
    n = apply(recs, log=lambda m: print(m, file=sys.stderr))
    for s in SPLITS:
        _dump([r for r in recs if r["split"] == s], TASKS_DIR / f"{s}.jsonl")
    print(json.dumps(n, sort_keys=True))
    return 0 if not n["failed"] else 1


def cmd_kofix(a):
    from ..gen.kofix import fix_all
    out, report = fix_all(_all())
    for s in SPLITS:
        _dump([r for r in out if r["split"] == s], TASKS_DIR / f"{s}.jsonl")
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


def cmd_datasheet(a):
    from ..gen.quality import datasheet_from_reports
    datasheet_from_reports(_all())
    return 0


def cmd_paraphrase(a):
    from ..gen.paraphrase import run
    return run(url=a.url, model=a.model, ko_model=a.ko_model, ko_judge=a.ko_judge, frac=a.frac, rounds=a.rounds,
               ko_rounds=a.ko_rounds, workers=a.workers, apply=not a.no_apply, offline=a.offline,
               langs=tuple(a.langs.split(",")), tellfix=a.tellfix)


def cmd_quality(a):
    from ..gen.quality import run
    return run(url=a.url, model=a.model, n=a.n, offline=a.offline)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m homeloop_bench.data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--gen-seed", type=int, default=2026)
    g.add_argument("--train", type=int, default=6000)
    g.add_argument("--dev", type=int, default=1000)
    g.add_argument("--test", type=int, default=3000)
    v = sub.add_parser("validate")
    v.add_argument("--strict", action="store_true")
    v.add_argument("--workers", type=int, default=1)
    rs = sub.add_parser("resplit")
    rs.add_argument("--gen-seed", type=int, default=2026)
    s = sub.add_parser("stats")
    s.add_argument("--json", action="store_true")
    r = sub.add_parser("realism")
    r.add_argument("--strict", action="store_true")
    p = sub.add_parser("paraphrase")
    p.add_argument("--url", default="http://127.0.0.1:11536")
    p.add_argument("--model", default="qwen3-vl:8b-instruct", help="English writer and judge")
    p.add_argument("--ko-model", default="exaone3.5:latest", help="Korean writer")
    p.add_argument("--ko-judge", default="qwen3-vl:30b-a3b-instruct", help="Korean judge and back-translator")
    p.add_argument("--langs", default="en,ko")
    p.add_argument("--frac", type=float, default=0.6)
    p.add_argument("--rounds", type=int, default=3, help="English rounds")
    p.add_argument("--ko-rounds", type=int, default=4)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--no-apply", action="store_true", help="only fill the cache")
    p.add_argument("--offline", action="store_true", help="use only cached responses (no LLM calls)")
    p.add_argument("--tellfix", action="store_true",
                   help="lab round 3 (H3): paraphrase again only the records `tellfix` re-rendered")
    sub.add_parser("tellfix")
    q = sub.add_parser("quality")
    q.add_argument("--url", default="http://127.0.0.1:11536")
    q.add_argument("--model", default="qwen3-vl:30b-a3b-instruct", help="back-translator (the Korean judge model)")
    q.add_argument("--n", type=int, default=600)
    q.add_argument("--offline", action="store_true")
    sub.add_parser("delivery")
    sub.add_parser("datasheet")
    sub.add_parser("kofix")
    a = ap.parse_args(argv)
    return {"delivery": cmd_delivery, "datasheet": cmd_datasheet, "kofix": cmd_kofix, "generate": cmd_generate, "validate": cmd_validate, "stats": cmd_stats, "realism": cmd_realism,
            "tellfix": cmd_tellfix, "paraphrase": cmd_paraphrase, "quality": cmd_quality, "resplit": cmd_resplit}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
