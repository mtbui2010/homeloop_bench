"""Accuracy audit of the simulated user's reading of robot questions (R2-7a, homeloop_robot docs/user_model.md
"Accuracy audit").

The audit set is fixed: ``data/quality/sim_user_audit/questions.jsonl`` (533 real robot questions from the runs,
266 EN / 267 KO) and the gold labels of a 3-judge agent panel (``labels_{1,2,3}.json``: qtype + slots per
question). Gold = the qtype at least two judges chose; a question where all three disagree is listed in
``disagreements`` and left out of the accuracy (``n_disagree_excluded``).

For each question the simulator's interpretation chain runs as in an episode of that task (profile ideal,
seed 0; ``user.SimUser._content``):

1. **structured**: the meaning the planner attaches, rebuilt from what the run had:
   - ``robot_agent:sage``: ``homeloop_robot.configs.ra_dialog.derive`` of SAGE's English question before
     translation (the question itself in EN; ``context.robot_en`` in KO);
   - ``oracle``: ``planners.oracle.gold_meaning`` for its gold clarification question, ``{"qtype": "help"}``
     for its help request (``homeloop_robot.oracle.HELP_QUESTION``);
   - other planners: no meaning (free text);
2. **rules** (``dialog.compose``);
3. **llm**: the intent classifier (``user_intent.IntentClassifier``), only when the rules do not understand.

The heard-text check applies in both languages (homeloop_robot docs/user_model.md "Heard-text check"): a meaning
counts only when the text reads as the same qtype with slots naming the same things; else the reading of the text
is scored (path structured_mismatch).

A reading is correct when its qtype is the gold qtype and, for each key slot both sides have, its value matches
one of the gold judges' values for that slot (``KEY_SLOT``: where_is.obj, did_you_mean.word, repeat.about,
what_to_say.person, which_place.obj / options, confirm.goal / obj; same words, or naming the same objects, places
and people of the house; a reading by a rule of ``dialog.compose`` has no slots, so only its qtype is checked).

A Korean question with no Hangul (robot_agent's translation failed and the English went out as is) is not
followed by the Korean user by design (``intent.in_lang``): its gold label (the English meaning) does not apply,
so it is left out of the accuracy and listed in ``untranslated_ko`` with the simulator's reading.

CLI::

    python -m homeloop_bench.sim_user_audit [--set DIR] [--llm URL] [--model M] [--cache FILE] [--out FILE]

``--cache`` (default ``DIR/user_intent_cache.jsonl``) holds the classifier's answers, so a rerun without the
server gives the same result; with no ``--llm`` and no cache the chain is rules only.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SET_DIR = ROOT / "data" / "quality" / "sim_user_audit"
OUT = ROOT / "data" / "quality" / "sim_user_audit.json"
KEY_SLOT = {"where_is": ("obj",), "did_you_mean": ("word",), "repeat": ("about",), "what_to_say": ("person",),
            "which_place": ("obj", "options"), "confirm": ("goal", "obj")}
# slots whose values name things of the house in a sentence or a list: compared by what they name
ENTITY_KEYS = ("options", "goal")


def _hangul(s: str) -> bool:
    return any("가" <= ch <= "힣" for ch in str(s or ""))


def load_set(d: Path = SET_DIR):
    rows = [json.loads(x) for x in (d / "questions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    judges = []
    for i in (1, 2, 3):
        doc = json.loads((d / f"labels_{i}.json").read_text(encoding="utf-8"))
        judges.append({x["qid"]: x for x in (doc["labels"] if isinstance(doc, dict) else doc)})
    return rows, judges


def gold(qid: str, judges: list) -> dict | None:
    """{qtype, slots: {name: [values of the judges who chose it]}} or None (all three disagree)."""
    labs = [j[qid] for j in judges if qid in j]
    c = collections.Counter(x["qtype"] for x in labs)
    qt, n = c.most_common(1)[0]
    if n < 2:
        return None
    slots: dict = {}
    for x in labs:
        if x["qtype"] == qt:
            for k, v in (x.get("slots") or {}).items():
                vs = v if isinstance(v, list) else [v]
                slots.setdefault(k, []).extend(str(s) for s in vs if str(s or "").strip())
    return {"qtype": qt, "slots": slots, "votes": n}


_ART = re.compile(r"^(the|a|an|my|your|his|her|our)\s+")


def _norm(s: str) -> str:
    s = re.sub(r"[\"'“”‘’?.!,()]", " ", str(s or "").lower())
    s = " ".join(s.split())
    return _ART.sub("", s)


def _ents(world, text: str) -> dict:
    from homeloop_robot import intent as _intent
    return _intent.entities(world, text)


def _union(world, vals) -> dict:
    out = {"obj": set(), "place": set(), "person": set()}
    for v in vals:
        for k, e in _ents(world, str(v)).items():
            out[k] |= e
    return out


def _same_things(a: dict, b: dict) -> bool:
    return any(a[k] & b[k] for k in a) and not any((a[k] - b[k]) and (b[k] - a[k]) for k in a)


def entity_match(sim, golds: list, world) -> bool | None:
    """For a list / sentence slot (options, a read-back goal): do the simulator's value and the gold name the same
    objects, places and people of the house (at least one in common, and no kind where each names one the other
    does not)? Against one judge's value, else against all judges' values together. None = the gold names nothing
    of the house (a word the translation made up: "부두" for the dock; not comparable, not checked); False when
    only the simulator's value names nothing."""
    a = _union(world, sim if isinstance(sim, (list, tuple)) else [sim])
    b = _union(world, golds)
    if not any(b.values()):
        return None
    if not any(a.values()):
        return False
    return any(_same_things(a, _union(world, [g])) for g in golds) or _same_things(a, b)


def _incomparable(sim, golds: list, world) -> bool:
    """A word slot neither side of which names anything of the house, in two languages ("water bottle" / "물병"
    when the house has none): words of different languages cannot be compared."""
    if world is None:
        return False
    vals = sim if isinstance(sim, (list, tuple)) else [sim]
    if any(_union(world, vals).values()) or any(_union(world, golds).values()):
        return False
    return any(_hangul(v) for v in vals) != any(_hangul(g) for g in golds)


def slot_match(sim: str, golds: list, world=None) -> bool:
    """Same words (containment after normalising), or naming the same object of the house (an English slot
    from SAGE's template against the Korean words of the gold: "plates" / "접시")."""
    if isinstance(sim, (list, tuple)):
        sim = " ".join(str(x) for x in sim)
    a = _norm(sim)
    for g in golds:
        b = _norm(g)
        if a and b and (a == b or a in b or b in a):
            return True
    if world is not None:
        from homeloop_robot import dialog as D
        sa = set(D.mentioned_objects(world, D._q_text(sim)))
        return bool(sa) and any(sa & set(D.mentioned_objects(world, D._q_text(g))) for g in golds)
    return False


def meaning_for(r: dict, task: dict):
    """The structured meaning the run's planner attached to this question (see the module doc)."""
    planner = (r.get("context") or {}).get("planner") or ""
    lang = r.get("lang") or "en"
    q = str(r.get("question") or "")
    if planner.startswith("robot_agent:sage"):
        from homeloop_robot.configs.ra_dialog import derive
        en = q if lang == "en" else (r.get("context") or {}).get("robot_en")
        if not en and not _hangul(q):
            en = q
        return derive(en) if en else None
    if planner == "oracle":
        import types

        from homeloop_robot.oracle import HELP_QUESTION

        from .planners.oracle import gold_meaning, gold_question
        env = types.SimpleNamespace(task=task, lang=lang)
        ws = lambda s: " ".join(str(s or "").split())
        if ws(q) == ws(HELP_QUESTION.get(lang)):
            return {"qtype": "help"}
        if ws(q) == ws(gold_question(env)):
            return gold_meaning(env)
    return None


def read_all(rows: list, clf=None) -> list:
    """The simulator's reading of each question: {qid, lang, path, qtype, slots, rule, answer}."""
    from homeloop_robot import intent as _intent
    from homeloop_robot.dialog import GoalView

    from .env import EpisodeEnv, task_dict
    from .tasks import load_split
    tasks = {}
    for sp in ("train", "dev", "test"):
        for t in load_split(sp):
            tasks[str(task_dict(t)["id"])] = t
    out = []
    for r in rows:
        t = tasks.get(r.get("task_id"))
        lang = r.get("lang") or "en"
        if t is None:
            raise KeyError(f"{r.get('qid')}: unknown task {r.get('task_id')}")
        env = EpisodeEnv(t, "ideal", 0, lang)
        u = env.user
        u.classifier = clf
        gv = GoalView(u.world, u.wants, u.user_id, lambda pid: u.place_of(pid, 0.0)[0]) if u.wants else None
        kw = dict(knows_location=True, other_place=None, user_place=u.place_of(u.user_id, 0.0) if u.user_id else None,
                  goal=gv, request=u.request, last_answer=None)
        meaning = meaning_for(r, task_dict(t))
        q = str(r.get("question") or "")
        u.last_reading = None
        c, path, qtype = u._content(q, lang, meaning, kw)
        m = u.last_reading            # the meaning the answer was read by (structured, or the heard text's reading)
        slots = {k: v for k, v in (m or {}).items() if k != "qtype"}
        out.append({"qid": r["qid"], "lang": lang, "path": path, "qtype": qtype, "slots": slots, "rule": c.rule,
                    "in_lang": _intent.in_lang(q, lang),
                    "kind": c.kind, "answer": c.text, "meaning": meaning,
                    "planner": (r.get("context") or {}).get("planner"), "_world": u.world})
    return out


def score(rows: list, judges: list, reads: list) -> dict:
    by_q = {r["qid"]: r for r in rows}
    n = {"all": 0, "en": 0, "ko": 0}
    ok = {"all": 0, "en": 0, "ko": 0}
    qt_ok = {"all": 0, "en": 0, "ko": 0}
    by_path: dict = {}
    conf = collections.Counter()
    conf_ex: dict = {}
    wrong, disagree, untranslated = [], [], []
    slot_checked = slot_ok = 0
    by_slot: dict = {}
    for rd in reads:
        qid, L = rd["qid"], rd["lang"]
        g = gold(qid, judges)
        if g is None:
            disagree.append({"qid": qid, "lang": L, "question": by_q[qid]["question"],
                             "labels": [j[qid]["qtype"] for j in judges]})
            continue
        if L == "ko" and not rd.get("in_lang", True):
            untranslated.append({"qid": qid, "question": by_q[qid]["question"], "gold": g["qtype"],
                                 "sim": rd["qtype"], "path": rd["path"], "rule": rd["rule"], "answer": rd.get("answer")})
            continue
        good_qt = rd["qtype"] == g["qtype"]
        good = good_qt
        for ks in KEY_SLOT.get(g["qtype"], ()):
            if not (good_qt and rd["slots"].get(ks) and g["slots"].get(ks)):
                continue
            if ks in ENTITY_KEYS:
                ok_ = entity_match(rd["slots"][ks], g["slots"][ks], rd.get("_world"))
                if ok_ is None and not slot_match(rd["slots"][ks], g["slots"][ks]):
                    continue                         # the gold names nothing of the house: not comparable
                ok_ = True if ok_ is None else ok_
            else:
                ok_ = slot_match(rd["slots"][ks], g["slots"][ks], rd.get("_world"))
                if not ok_ and _incomparable(rd["slots"][ks], g["slots"][ks], rd.get("_world")):
                    continue
            slot_checked += 1
            st = by_slot.setdefault(f"{g['qtype']}.{ks}", {"checked": 0, "matched": 0})
            st["checked"] += 1
            if ok_:
                slot_ok += 1
                st["matched"] += 1
            else:
                good = False
        for k in ("all", L):
            n[k] += 1
            ok[k] += good
            qt_ok[k] += good_qt
        p = by_path.setdefault(rd["path"], {"n": 0, "correct": 0, "en": 0, "ko": 0})
        p["n"] += 1
        p["correct"] += good
        p[L] += 1
        if not good:
            key = (g["qtype"], rd["qtype"] if not good_qt else rd["qtype"] + " (slot)", rd["path"])
            conf[key] += 1
            conf_ex.setdefault(key, []).append(qid)
            wrong.append({"qid": qid, "lang": L, "question": by_q[qid]["question"], "gold": g["qtype"],
                          "gold_slots": g["slots"], "sim": rd["qtype"], "sim_slots": rd["slots"], "path": rd["path"],
                          "rule": rd["rule"], "planner": rd["planner"]})
    for p in by_path.values():
        p["share"] = round(p["n"] / max(n["all"], 1), 4)
        p["accuracy"] = round(p["correct"] / max(p["n"], 1), 4)
    acc = lambda k: round(ok[k] / max(n[k], 1), 4)
    return {
        "n": n["all"], "n_en": n["en"], "n_ko": n["ko"],
        "accuracy": acc("all"), "accuracy_en": acc("en"), "accuracy_ko": acc("ko"),
        "accuracy_qtype_only": round(qt_ok["all"] / max(n["all"], 1), 4),
        "key_slots": {"checked": slot_checked, "matched": slot_ok, "by_slot": dict(sorted(by_slot.items()))},
        "by_path": dict(sorted(by_path.items())),
        "confusions": [{"gold": k[0], "sim": k[1], "path": k[2], "count": v, "qids": conf_ex[k]}
                       for k, v in sorted(conf.items(), key=lambda kv: (-kv[1], kv[0]))],
        "n_questions": len(reads),
        "n_disagree_excluded": len(disagree),
        "disagreements": disagree,
        "n_untranslated_ko_excluded": len(untranslated),
        "untranslated_ko": untranslated,
        "errors": [{k: v for k, v in e.items()} for e in wrong],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m homeloop_bench.sim_user_audit")
    ap.add_argument("--set", default=str(SET_DIR))
    ap.add_argument("--llm", default=None, help="Ollama URL for the classifier (none: the cache, else rules only)")
    ap.add_argument("--model", default="qwen3-vl:8b-instruct")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--rules-only", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    d = Path(a.set)
    rows, judges = load_set(d)
    clf = None
    cache = Path(a.cache) if a.cache else d / "user_intent_cache.jsonl"
    if not a.rules_only and (a.llm or cache.exists()):
        from .llm import CachedLLM, OllamaHTTP
        from .user_intent import PROMPT_VERSION, IntentClassifier

        class _Offline:          # cache only: a miss is an error, not a silent rules answer
            model = a.model

            def chat(self, *x, **k):
                raise SystemExit("classifier cache miss and no --llm")
        inner = OllamaHTTP(a.llm, a.model) if a.llm else _Offline()
        clf = IntentClassifier(CachedLLM(inner, str(cache)))
    reads = read_all(rows, clf)
    if clf is not None and clf.failed is not None:
        raise clf.failed
    res = score(rows, judges, reads)
    res["classifier"] = ({"kind": "llm", "model": a.model, "prompt_version": PROMPT_VERSION}
                         if clf is not None else {"kind": "rules"})
    base = d / "baseline.json"
    if base.exists():          # the same set and scorer before the R2-7a fixes (reported next to the result)
        res["before_fixes"] = json.loads(base.read_text(encoding="utf-8"))
    res["set"] = str(Path(a.set).resolve().relative_to(ROOT)) if Path(a.set).resolve().is_relative_to(ROOT) else a.set
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("n", "n_en", "n_ko", "accuracy", "accuracy_en", "accuracy_ko",
                                         "n_disagree_excluded")}), file=sys.stderr)
    for c in res["confusions"][:12]:
        print(f"  {c['count']:3d}  gold={c['gold']:<14} sim={c['sim']:<20} path={c['path']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
