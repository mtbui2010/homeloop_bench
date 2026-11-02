"""Realism rules R-a .. R-h on the task data (DESIGN 13.2; docs/realism.md).

Robot-side rules (catalog R-a / R-d, houses R-b / R-c / R-h) come from ``homeloop_robot.realism``; this module adds
the task-side checks: goal destinations (R-b, R-c), robot ability (R-d), activity provenance (R-e), kind
semantics (R-f) and language (R-g). Refuse requests with a sourced hazard are intentional: the requested
placement is never part of a goal, so it is reported under ``intentional`` and does not count as a violation.
"""

from __future__ import annotations

import re

from homeloop_robot import goals as G
from homeloop_robot import realism as RR
from homeloop_robot.catalog import CLASSES
from homeloop_robot.hazards import HAZARD_CODES, goal_hazards
from homeloop_robot.world import from_house

from .dedup import norm
from .lexicon import Lex
from .sources import HAZARD_SOURCES
from .textcheck import check_text

EXAMPLES = 20
KO_DROPPED_MAX = 0.30
CONDITIONAL_ASSUMED_MAX = 0.05
_W = {}


def world(rec):
    k = (rec["house"], rec["seed_state"])
    if k not in _W:
        if len(_W) > 4096:
            _W.clear()
        _W[k] = from_house(*k)
    return _W[k]


def _v(rule, rec, why):
    return {"rule": rule, "id": rec.get("id"), "why": why}


def _sub_atoms(rec):
    for i, s in enumerate(rec.get("subtasks") or []):
        for a in G.iter_preds(s["goal"]):
            yield i, s, a
        for a in (s.get("condition") or {}).get("then", []) + (s.get("condition") or {}).get("else", []):
            yield i, s, a


def touched_objects(rec, w):
    ids = set()
    for _, s, a in _sub_atoms(rec):
        ids.update(x for x in a.get("args", []) if x in w.objects)
    for s in rec.get("subtasks") or []:
        for a in s.get("requested") or []:
            ids.update(x for x in a.get("args", []) if x in w.objects)
    for c in (rec.get("user") or {}).get("candidates") or []:
        if c.get("id") in w.objects:
            ids.add(c["id"])
    it = (rec.get("user") or {}).get("interrupt") or {}
    for a in (it.get("new_goal") or {}).get("all", []):
        ids.update(x for x in a.get("args", []) if x in w.objects)
    return ids


def check_record(rec) -> tuple:
    """(violations, intentional) for one record."""
    w = world(rec)
    out, intentional = [], []
    # R-b / R-c: where touched objects are now, and every goal destination
    for oid in sorted(touched_objects(rec, w)):
        o = w.objects[oid]
        if o.at in w.house.places and w.house.places[o.at].kind not in ("floor",):
            ok, why = RR.placement_ok(w, o.cls, o.at)
            if not ok:
                out.append(_v("R-c" if "fit" in why else "R-b", rec, "initial: " + why))
    dests = [(a["args"][0], a["args"][1]) for _, s, a in _sub_atoms(rec) if a.get("pred") in ("on", "in")]
    it = (rec.get("user") or {}).get("interrupt") or {}
    dests += [(a["args"][0], a["args"][1]) for a in (it.get("new_goal") or {}).get("all", []) if a["pred"] in ("on", "in")]
    for c in (rec.get("user") or {}).get("candidates") or []:
        g = c.get("goal")
        if g and g.get("pred") in ("on", "in"):
            dests.append(tuple(g["args"]))
    for oid, pid in dests:
        ok, why = RR.placement_ok(w, w.objects[oid].cls, pid)
        if not ok:
            out.append(_v("R-c" if "fit" in why or "liquid" in why else "R-b", rec, "goal: " + why))
    for s in rec.get("subtasks") or []:
        for a in s.get("requested") or []:
            if a.get("pred") in ("on", "in"):
                ok, why = RR.placement_ok(w, w.objects[a["args"][0]].cls, a["args"][1])
                if not ok:
                    codes = [h["code"] for h in s.get("hazards") or []]
                    if s.get("refuse_reason") == "unsafe" and codes and all(c in HAZARD_SOURCES for c in codes):
                        intentional.append(_v("R-b", rec, f"refused request (sourced hazard {codes}): {why}"))
                    elif s.get("refuse_reason") == "infeasible":
                        intentional.append(_v("R-b", rec, f"refused infeasible request: {why}"))
                    else:
                        out.append(_v("R-b", rec, "requested: " + why))
    # R-d: feasible pick / place objects are graspable and within the payload
    for _, s, a in _sub_atoms(rec):
        if s["kind"] in ("feasible", "clarify") and a.get("pred") in ("on", "in", "held_by", "delivered"):
            cls = w.objects[a["args"][0]].cls
            if not RR.REALISM[cls]["graspable"]:
                out.append(_v("R-d", rec, f"{a['args'][0]} ({cls}) is not graspable / over the payload"))
    # R-e: activity provenance
    src = rec.get("activity_source") or {}
    if not src.get("url", "").startswith("https://") or not src.get("source"):
        out.append(_v("R-e", rec, "no activity_source with a URL"))
    # R-f: kind semantics
    out += _r_f(rec, w)
    # R-g: language
    compound = rec.get("n_subtasks", 1) > 1 or rec.get("structure", "single") != "single"
    for lg in ("en", "ko"):
        for e in check_text(rec["text"][lg], lg, compound):
            out.append(_v("R-g", rec, f"{lg}: {e}"))
    return out, intentional


def _names(lex, oid, lang):
    names = list(lex.obj_names(oid, lang))
    if lex.n_same(oid) == 1:
        cls = lex.w.objects[oid].cls
        names += [CLASSES[cls].name[lang]] + list((CLASSES[cls].aliases or {}).get(lang) or [])
    return names


def _in(text, names, lang):
    t = norm(text, lang)
    return any(norm(n, lang) and norm(n, lang) in t for n in names)


def _r_f(rec, w):
    out = []
    lex = Lex(w)
    subs = rec.get("subtasks") or []
    goal = rec["goal"]
    errs = G.validate({"all": goal["all"]}, w)
    if errs:
        return [_v("R-f", rec, "invalid goal: " + errs[0])]
    if not 1 <= len(goal["all"]) <= 6:
        out.append(_v("R-f", rec, f"{len(goal['all'])} subgoals"))
    if not subs or rec.get("n_subtasks") != len(subs):
        out.append(_v("R-f", rec, "subtasks / n_subtasks mismatch"))
    dest = {}
    for _, s, a in _sub_atoms(rec):
        if a.get("pred") in ("on", "in", "held_by", "delivered") and "condition" not in s:
            o = a["args"][0]
            if o in dest and dest[o] != (a["pred"], a["args"][1]):
                out.append(_v("R-f", rec, f"contradictory goals for {o}"))
            dest[o] = (a["pred"], a["args"][1])
    kinds = [s["kind"] for s in subs]
    top = "refuse" if kinds and all(k == "refuse" for k in kinds) else ("clarify" if "clarify" in kinds else "feasible")
    if subs and rec["kind"] != top:
        out.append(_v("R-f", rec, f"top-level kind {rec['kind']} != rule {top}"))
    for i, s in enumerate(subs):
        if s["kind"] == "feasible" and not s.get("correction") and "condition" not in s:
            for a in s["goal"]["all"]:
                if a.get("pred") in ("on", "in", "held_by", "delivered"):
                    oid = a["args"][0]
                    for lg in ("en", "ko"):
                        if not _in(rec["text"][lg], _names(lex, oid, lg), lg):
                            out.append(_v("R-f", rec, f"{lg}: subtask {i} does not name {oid} resolvably"))
        elif s["kind"] == "clarify":
            cands = s.get("candidates") or [c.get("id") for c in rec["user"].get("candidates") or []]
            real = [c for c in cands if c in w.objects or c in w.house.places or c in ("hand", "desk")]
            if len(real) < 2:
                out.append(_v("R-f", rec, f"clarify subtask {i} with < 2 real candidates"))
            if s.get("ambiguity") not in ("preference", "common_sense", "safety"):
                out.append(_v("R-f", rec, "clarify without an AmbiK ambiguity type"))
            for c in cands:
                if c in w.objects and lex.n_same(c) > 1:
                    for lg in ("en", "ko"):
                        if _in(rec["text"][lg], [lex.obj(c, lg, None, True)], lg):
                            out.append(_v("R-f", rec, f"{lg}: clarify text singles out {c}"))
        elif s["kind"] == "refuse":
            if s.get("refuse_reason") == "unsafe":
                codes = [h["code"] for h in s.get("hazards") or []]
                if not codes or any(c not in HAZARD_CODES or c not in HAZARD_SOURCES for c in codes):
                    out.append(_v("R-f", rec, "unsafe refuse without a sourced hazard"))
                elif not goal_hazards(w, {"all": s.get("requested") or []}):
                    out.append(_v("R-f", rec, "unsafe refuse whose request has no hazard"))
            elif s.get("refuse_reason") != "infeasible":
                out.append(_v("R-f", rec, "refuse without a reason"))
    if rec.get("structure") == "correction":
        for s in subs:
            c = s.get("correction") or {}
            if "first" in c:
                for lg in ("en", "ko"):
                    t = rec["text"][lg]
                    p1, p2 = t.rfind(lex.color(c["first"], lg)), t.rfind(lex.color(c["final"], lg))
                    if p2 < 0 or p1 < 0 or p2 < p1:
                        out.append(_v("R-f", rec, f"{lg}: self-correction does not end on the final object"))
    return out


def report(records: list) -> dict:
    """The JSON report: per rule the violation count and up to 20 examples, plus intentional cases."""
    viol, inten = [], []
    viol += [dict(v, id=None) for v in RR.check_catalog()]
    from homeloop_robot.houses import list_houses, load_house
    for h in list_houses():
        viol += [dict(v, id=None) for v in RR.check_house(load_house(h))]
    n_assumed_cond = 0
    for rec in records:
        v, i = check_record(rec)
        viol += v
        inten += i
        if (rec.get("activity_source") or {}).get("assumed"):
            n_assumed_cond += 1
    n = max(1, len(records))
    dropped = sum(1 for r in records if (r.get("meta") or {}).get("ko_particle_dropped")) / n
    extra = []
    if dropped > KO_DROPPED_MAX:
        extra.append({"rule": "R-g", "id": None, "why": f"Korean dropped-particle share {dropped:.3f} > {KO_DROPPED_MAX}"})
    if n_assumed_cond / n > CONDITIONAL_ASSUMED_MAX:
        extra.append({"rule": "R-e", "id": None,
                      "why": f"assumed-source families {n_assumed_cond / n:.3f} > {CONDITIONAL_ASSUMED_MAX}"})
    viol += extra
    rules = {}
    for r in ("R-a", "R-b", "R-c", "R-d", "R-e", "R-f", "R-g", "R-h"):
        vs = [v for v in viol if v["rule"] == r]
        it = [v for v in inten if v["rule"] == r]
        rules[r] = {"violations": len(vs), "intentional": len(it), "examples": vs[:EXAMPLES],
                    "intentional_examples": it[:5]}
    return {"ok": not viol, "n_tasks": len(records), "violations": len(viol), "intentional": len(inten),
            "rules": rules, "ko_particle_dropped_share": round(dropped, 4),
            "assumed_source_share": round(n_assumed_cond / n, 4),
            "notes": {"intentional": "refused requests with a sourced hazard (SafeAgentBench / RoboGuard) or an "
                                     "infeasible (too heavy) request: the placement is asked for, never part of a goal",
                      "ranges": RR.RANGES_NOTE}}


_ = re
