"""Validator (DESIGN 10.7): ``python -m homeloop_bench.data validate [--strict] [--workers N]``.

Numbered checks with PASS / FAIL (WARN lines fail only under --strict); exit 0 only if all pass:
  1 schema   2 ids / split field   3 exact + cross-split near duplicates   4 goals validate, not already true
  5 oracle solves every feasible task in `ideal` (clarify reported; refuse: unsafe -> hazard, infeasible -> unsolvable)
  6 label shares >= 5 % unless documented   7 paraphrases have a model and a cached LLM response
  8 >= 6 houses, held-out houses only in test, test-only template ids only in test
  9 compound fields (DESIGN 14): goal = conjunction of subtask goals, kinds, order indices
"""

from __future__ import annotations

import json
import re
from collections import Counter

import yaml

from homeloop_robot import goals as G
from homeloop_robot import oracle
from homeloop_robot.hazards import goal_hazards
from homeloop_robot.houses import list_houses

from ..data import CACHE_DIR, POLICY, SPLITS
from ..tasks import read_records
from . import dedup
from .split import is_test_template
from .sample import HELD_OUT

KINDS = ("feasible", "clarify", "refuse")
AMBIG = ("none", "preference", "common_sense", "safety")
CAPS = ("fetch", "rearrange", "contain", "articulate", "multi_object", "search", "message", "navigate", "correction")
SOURCES = ("template", "llm_paraphrase")
STRUCTS = ("single", "sequence", "conjunction", "ordered", "conditional", "shared_object", "with_context", "correction")
REQUIRED = ("id", "split", "house", "seed_state", "text", "goal", "kind", "capability", "ambiguity", "source",
            "template_id", "refuse_reason", "hazards", "user", "expected", "meta", "subtasks", "n_subtasks",
            "structure", "length_words", "activity_source")
ID_RE = re.compile(r"^hl-(train|dev|test)-\d{6}$")


def load_all(paths=None) -> list:
    recs = []
    for s in SPLITS:
        for r in read_records(s, (paths or {}).get(s)):
            r["_file"] = s
            recs.append(r)
    return recs


def _schema(r) -> list:
    errs = [f"missing {k}" for k in REQUIRED if k not in r]
    if errs:
        return errs
    if r["kind"] not in KINDS:
        errs.append(f"kind {r['kind']!r}")
    if r["ambiguity"] not in AMBIG:
        errs.append(f"ambiguity {r['ambiguity']!r}")
    if r["capability"] not in CAPS:
        errs.append(f"capability {r['capability']!r}")
    if r["source"] not in SOURCES:
        errs.append(f"source {r['source']!r}")
    sbl = r.get("source_by_lang") or {}
    if set(sbl) != {"en", "ko"} or any(v not in SOURCES for v in sbl.values()):
        errs.append(f"source_by_lang {sbl!r}")
    elif (r["source"] == "llm_paraphrase") != ("llm_paraphrase" in sbl.values()):
        errs.append("source does not match source_by_lang")
    pm = r.get("paraphrase_model") or {}
    if any(bool(pm.get(lg)) != (sbl.get(lg) == "llm_paraphrase") for lg in ("en", "ko")):
        errs.append(f"paraphrase_model {pm!r} does not match source_by_lang")
    if r["structure"] not in STRUCTS:
        errs.append(f"structure {r['structure']!r}")
    if r["refuse_reason"] not in (None, "unsafe", "infeasible"):
        errs.append(f"refuse_reason {r['refuse_reason']!r}")
    for lg in ("en", "ko"):
        if not (r["text"].get(lg) or "").strip():
            errs.append(f"empty text.{lg}")
    if not re.search(r"[가-힣]", r["text"].get("ko", "")):
        errs.append("text.ko has no Hangul")
    if (r["kind"] == "refuse") != bool(r["goal"].get("refuse")):
        errs.append("refuse kind / goal flag mismatch")
    if r["kind"] == "clarify" and not (r["user"].get("candidates") and r["user"].get("answer")):
        errs.append("clarify without candidates / answer")
    return errs


def _oracle_job(r):
    from .oracle_check import run
    return r["id"], run(r, "en")


def _compound(r) -> list:
    errs = []
    subs = r["subtasks"]
    if len(subs) != r["n_subtasks"]:
        errs.append("n_subtasks != len(subtasks)")
    atoms = [a for s in subs for a in s["goal"]["all"]]
    if G.format({"all": atoms}) != G.format({"all": r["goal"]["all"]}):
        errs.append("goal is not the conjunction of the subtask goals")
    for a, b in r.get("order") or []:
        if not (0 <= a < len(subs) and 0 <= b < len(subs)) or a == b:
            errs.append(f"bad order pair {[a, b]}")
    return errs


def validate(paths=None, workers: int = 1, out=print, policy_path=POLICY) -> tuple:
    """Returns (n_fail, n_warn)."""
    recs = load_all(paths)
    policy = yaml.safe_load(open(policy_path, encoding="utf-8"))
    fails, warns = 0, 0

    def line(ok, name, msg="", warn=False):
        nonlocal fails, warns
        tag = "PASS" if ok else ("WARN" if warn else "FAIL")
        if not ok:
            if warn:
                warns += 1
            else:
                fails += 1
        out(f"{tag}  {name}" + (f": {msg}" if msg else ""))

    n = len(recs)
    out(f"records: {n}")
    # 1 schema
    bad = [(r.get("id"), e) for r in recs for e in _schema(r)]
    line(not bad and n > 0, "1 schema", f"{len(bad)} problems, e.g. {bad[:3]}" if bad else f"{n} records")
    if bad:
        return fails + 1, warns
    # 2 ids
    ids = Counter(r["id"] for r in recs)
    dup_ids = [i for i, c in ids.items() if c > 1]
    wrong = [r["id"] for r in recs if r["split"] != r["_file"] or not ID_RE.match(r["id"]) or
             r["id"].split("-")[1] != r["split"]]
    line(not dup_ids and not wrong, "2 ids unique, split field = file", f"dups {dup_ids[:3]} wrong {wrong[:3]}")
    # 3 duplicates
    exact = []
    for lg in ("en", "ko"):
        c = Counter(dedup.norm(r["text"][lg], lg) for r in recs)
        exact += [(lg, t) for t, k in c.items() if k > 1]
    near = []
    for lg in ("en", "ko"):
        near += [(lg,) + p for p in dedup.near_dup_pairs(recs, lg)]
    line(not exact, "3a no exact duplicate texts (per language)", f"{len(exact)}: {exact[:3]}")
    line(not near, f"3b no near duplicates across splits (Jaccard >= {dedup.NEAR_DUP_J})", f"{len(near)}: {near[:3]}")
    # 4 goals
    from homeloop_robot.world import from_house
    g_bad = []
    cache = {}
    for r in recs:
        k = (r["house"], r["seed_state"])
        if k not in cache:
            if len(cache) > 4096:
                cache.clear()
            cache[k] = from_house(*k)
        w = cache[k]
        e = G.validate({"all": r["goal"]["all"]}, w)
        if e:
            g_bad.append((r["id"], e[0]))
        elif r["kind"] != "refuse" and G.evaluate({"all": r["goal"]["all"]}, w).holds:
            g_bad.append((r["id"], "goal already true"))
        if r["kind"] == "refuse" or any(s["kind"] == "refuse" for s in r["subtasks"]):
            for s in r["subtasks"]:
                if s["kind"] != "refuse":
                    continue
                req = {"all": s.get("requested") or []}
                if s.get("refuse_reason") == "unsafe" and not goal_hazards(w, req):
                    g_bad.append((r["id"], "unsafe refuse without a hazard"))
                if s.get("refuse_reason") == "infeasible" and oracle.solve(w, req) is not None:
                    g_bad.append((r["id"], "infeasible refuse is solvable"))
    line(not g_bad, "4 goals validate; feasible / clarify not already true; refuse requests hazardous / infeasible",
         f"{len(g_bad)}: {g_bad[:3]}")
    # 5 oracle in ideal
    todo = [r for r in recs if r["kind"] in ("feasible", "clarify")]
    clean = [{k: v for k, v in r.items() if k != "_file"} for r in todo]
    if workers > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(workers) as pool:
            res = dict(pool.map(_oracle_job, clean, chunksize=64))
    else:
        res = dict(_oracle_job(r) for r in clean)
    f_bad = [(r["id"], res[r["id"]]["reason"]) for r in todo if r["kind"] == "feasible" and not res[r["id"]]["success"]]
    c_bad = [(r["id"], res[r["id"]]["reason"]) for r in todo if r["kind"] == "clarify" and not res[r["id"]]["success"]]
    n_f = sum(1 for r in todo if r["kind"] == "feasible")
    line(not f_bad, "5a oracle solves 100 % of feasible tasks in `ideal`", f"{n_f - len(f_bad)}/{n_f}; e.g. {f_bad[:3]}")
    n_c = sum(1 for r in todo if r["kind"] == "clarify")
    line(not c_bad, "5b oracle solves clarify tasks (intended goal)", f"{n_c - len(c_bad)}/{n_c}; e.g. {c_bad[:3]}",
         warn=True)
    # 6 label shares
    small = []
    doc = (policy or {}).get("documented_small") or {}
    for field, values in (("kind", KINDS), ("capability", CAPS), ("ambiguity", AMBIG)):
        c = Counter(r[field] for r in recs)
        for v in values:
            share = c.get(v, 0) / max(1, n)
            if share < policy.get("min_share", 0.05) and f"{field}:{v}" not in doc:
                small.append(f"{field}={v} {share:.3f}")
    documented = [k for k in doc]
    line(not small, "6 every kind / capability / ambiguity value >= 5 %",
         f"below: {small}" if small else f"documented smaller: {documented}")
    # 7 paraphrases
    cache_shas = set()
    for cp in sorted(CACHE_DIR.glob("*.jsonl")):
        for l in open(cp, encoding="utf-8"):
            if l.strip():
                cache_shas.add(json.loads(l)["sha"])
    p_bad = []
    n_para = Counter()
    for r in recs:
        if r["source"] != "llm_paraphrase":
            continue
        n_para["any"] += 1
        mp = (r["meta"] or {}).get("paraphrase") or {}
        tt = (r["meta"] or {}).get("template_text") or {}
        for lg in ("en", "ko"):
            if (r.get("source_by_lang") or {}).get(lg) != "llm_paraphrase":
                if tt and tt.get(lg) != r["text"][lg]:
                    p_bad.append((r["id"], f"{lg} text differs from its template but is labelled template"))
                continue
            n_para[lg] += 1
            p = mp.get(lg) or {}
            if not p.get("model") or p.get("model") != (r.get("paraphrase_model") or {}).get(lg):
                p_bad.append((r["id"], f"{lg}: no model"))
            for k in ("sha_req", "sha_judge") + (("sha_back",) if lg == "ko" else ()):
                if p.get(k) not in cache_shas:
                    p_bad.append((r["id"], f"{lg}.{k} not in the LLM cache"))
    line(not p_bad, "7 llm_paraphrase texts have a model and cached responses (writer, judge, back-translation)",
         f"{dict(n_para)} paraphrased; {p_bad[:3]}")
    # 8 houses
    houses = Counter(r["house"] for r in recs)
    held = [r["id"] for r in recs if r["house"] in HELD_OUT and r["split"] != "test"]
    unknown = [h for h in houses if h not in list_houses()]
    tt = [r["id"] for r in recs if r["split"] != "test" and is_test_template(r["template_id"])]
    line(len(houses) >= 6 and not held and not unknown and not tt,
         "8 >= 6 houses; held-out houses and test-only templates only in test",
         f"houses {len(houses)} held-out leaks {held[:3]} unknown {unknown} test-template leaks {tt[:3]}")
    # 9 compound fields
    c_bad = [(r["id"], e) for r in recs for e in _compound(r)]
    line(not c_bad, "9 subtasks: goal = conjunction, n_subtasks, order pairs", f"{len(c_bad)}: {c_bad[:3]}")
    out(f"== validate: {fails} FAIL, {warns} WARN")
    return fails, warns
