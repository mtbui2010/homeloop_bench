"""Round 2 delivery rewrite (docs/tasks.md, "Delivery"): ``held_by`` -> ``delivered`` with a mode.

``python -m homeloop_bench.data delivery`` rewrites the task files in place. It is deterministic and idempotent
(a second run changes nothing). Ids, splits and LLM-written texts are kept. Per record:

1. **Within reach at the start.** A delivery whose object already rests on a support surface the person can
   reach at the start (homeloop_robot.reach) asks for something the person can take themselves; it does not
   happen in real homes and its ``reach`` goal would hold before the robot moves. Such a task gets another
   arrangement of the same house (``seed_state``), searched in a fixed order:
   pass 1 keeps everyone's seat and every other object the task names where it was, and moves only the
   within-reach object(s); when a text names the place that object is on, or pass 1 finds nothing, pass 2 keeps
   every object the task names and lets the recipient sit elsewhere. ``meta.delivery.reseed`` records the old
   seed_state and the pass.
2. **Explicit hand wording.** A share of the delivery tasks get wording that asks for the hand, from templates in
   both languages, only in texts that are template text (``source_by_lang == "template"``; LLM text is never
   touched):
   * ``ko_verb``: a task with one delivery whose English text already asks for the hand ("Hand the book to my
     husband") and whose Korean template says 가져다주- / 갖다주- / 가져다드리- / 갖다드리- once: the verb becomes
     가져다 건네- (all such tasks);
   * ``append``: a one-subtask task with one delivery and template text in both languages gets one short
     sentence at the end ("Please put it right in my hand." / "제 손에 직접 쥐여 주세요."), for the tasks whose
     sha256(gen id) falls under ``APPEND_SHARE``.
   ``meta.delivery.variant`` names the variant; ``meta.template_text`` and ``length_words`` follow the text.
3. **Labels.** Every ``held_by(o, p)`` atom (goal, subtasks, conditions, requested atoms, a correction's new goal,
   ``meta.requested_goal``) becomes ``{"pred": "delivered", "args": [o, p], "mode", "mode_reason"}``, labelled
   the way a robot would choose from what it observes (``homeloop_robot.reach.choose_mode``) at the start state:
   ``explicit`` when the text in BOTH languages asks for the hand (``reach.wording_wants_hand``), else
   ``user_needs`` when the person's house profile says ``prefers_handover``, else ``no_surface`` when no support
   surface with room is within their reach, else ``reach``. A correction's new goal is labelled with the
   instruction and the correction text together. Existing ``delivered`` atoms are relabelled the same way.

The labels are what the oracle and naive planners infer themselves from the heard text and the scene (they never
read the label): when only one language's text asks for the hand, the label is the scene's (``reach`` or a
``hand`` from the scene), and a handover in that language still satisfies ``reach``.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections import Counter

from homeloop_robot import reach
from homeloop_robot.catalog import CLASSES
from homeloop_robot.world import from_house

from .textcheck import words

APPEND_SHARE = 0.36              # design choice: about 5 % of the delivery atoms get an explicit-hand sentence
# per-split top-up of explicit-hand wording (design choice, docs/tasks.md "Delivery"): dev and train hold far fewer
# one-subtask template tasks than test, so the base ``append`` rule alone gave dev 6 explicit atoms of 490 (test 202
# of 2418). A record of split s whose sha256(gen id, "quota") falls under QUOTA_SHARE[s] may also get the
# explicit sentence when the base rule skipped it: a one-subtask task above APPEND_SHARE (``append``), or a
# compound task whose one delivery is named in the text (``append_named``: the sentence names the object).
# Per record, so the rewrite stays deterministic and idempotent on any subset.
QUOTA_SHARE = {"train": 0.4, "dev": 0.5, "test": 0.0}   # test keeps the base rule (8.2 % explicit)
QUOTA_STRUCTURES = ("sequence", "conjunction", "ordered", "shared_object", "with_context")
RESEED_TRIES = 4000
TASK_KEYS = ("goal", "subtasks", "user", "meta")
PLURAL = {"glasses", "keys", "socks", "scissors"}
NO_APPEND = {"scissors"}         # a sharp object is not put into a hand on request in the templates
_HANDS_MENTIONED = re.compile(r"\bhands?\b", re.I)
KO_VERB = re.compile(r"(가져다|갖다)\s?(주|줘|준|줄|드리|드려|드린|드릴)")

EN_ME = ("Please put it right in my hand.", "Could you put it in my hand, please?",
         "Please hand it to me; don't just set it down.", "I'd like it right in my hand.",
         "Hand it to me; don't just set it down.")
EN_ME_PL = ("Please put them right in my hand.", "Could you put them in my hand, please?",
            "Please hand them to me; don't just set them down.", "I'd like them right in my hand.",
            "Hand them to me; don't just set them down.")
EN_OTHER = ("Please put it right in {pos} hand.", "Hand it to {obj} directly, please.",
            "Put it right in {pos} hand.")
EN_OTHER_PL = ("Please put them right in {pos} hand.", "Hand them to {obj} directly, please.",
               "Put them right in {pos} hand.")
KO_ME = ("제 손에 직접 쥐여 주세요.", "그냥 두지 말고 제 손에 건네주세요.", "제 손에 바로 건네주세요.")
KO_OTHER = ("그냥 두지 말고 손에 직접 건네주세요.", "손에 직접 건네주세요.")
KO_ELDER = ("그냥 두지 말고 손에 직접 건네 드리세요.", "손에 직접 건네 드리세요.")
# append_named (a compound task: the sentence names the delivered object; {n} = its name in the text)
EN_ME_N = ("Please put the {n} right in my hand.", "Could you put the {n} in my hand, please?",
           "I'd like the {n} right in my hand.")
EN_OTHER_N = ("Please put the {n} right in {pos} hand.", "Hand the {n} to {obj} directly, please.",
              "Put the {n} right in {pos} hand.")
KO_ME_N = ("{t} 제 손에 직접 쥐여 주세요.", "{t} 그냥 두지 말고 제 손에 건네주세요.", "{t} 제 손에 바로 건네주세요.")
KO_OTHER_N = ("{t} 손에 직접 건네주세요.", "{t} 그냥 두지 말고 손에 직접 건네주세요.")
KO_ELDER_N = ("{t} 손에 직접 건네 드리세요.", "{t} 그냥 두지 말고 손에 직접 건네 드리세요.")


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest(), 16)


def _frac(*parts) -> float:
    return _h(*parts) / float(1 << 256)


def gen_id(r: dict) -> str:
    return (r.get("meta") or {}).get("gen_id") or r["id"]


# ── atoms ─────────────────────────────────────────────────────────────────────────────────────────────

def walk(x, path=()):
    """Yield (path, atom) for every atom dict (``pred`` key) inside ``x``."""
    if isinstance(x, dict):
        if "pred" in x:
            yield path, x
        for k in sorted(x):
            yield from walk(x[k], path + (k,))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from walk(v, path + (i,))


def delivery_atoms(r: dict) -> list:
    """(path, atom) of every held_by / delivered atom of a record."""
    out = []
    for k in TASK_KEYS:
        for p, a in walk(r.get(k), (k,)):
            if a.get("pred") in ("held_by", "delivered"):
                out.append((p, a))
    return out


def _in_correction(path) -> bool:
    return len(path) >= 2 and path[0] == "user" and path[1] == "interrupt"


def objects_named(r: dict, w) -> set:
    """Object ids the task names anywhere (atoms of every kind, clarify candidates)."""
    out = set()
    for k in TASK_KEYS:
        for _, a in walk(r.get(k)):
            for x in a.get("args") or []:
                if isinstance(x, str) and x in w.objects:
                    out.add(x)
    for c in (r.get("user") or {}).get("candidates") or []:
        if isinstance(c, dict) and c.get("id") in w.objects:
            out.add(c["id"])
    return out


# ── labels ────────────────────────────────────────────────────────────────────────────────────────────

def wants_hand(texts: dict) -> bool:
    """Both languages' words ask for the hand (an observer of either language would hand over)."""
    return all(reach.wording_wants_hand((texts or {}).get(lg, ""), lg) for lg in ("en", "ko"))


def label(w, person: str, texts: dict) -> tuple:
    """(mode, mode_reason) a robot infers at the start state from the words and the scene."""
    if wants_hand(texts):
        return "hand", "explicit"
    return reach.need(w, person)                # no words: the house profile, then the geometry


def correction_texts(r: dict) -> dict:
    it = (r.get("user") or {}).get("interrupt") or {}
    t = it.get("text") or {}
    return {lg: f"{r['text'].get(lg, '')} {t.get(lg, '') if isinstance(t, dict) else t}".strip() for lg in ("en", "ko")}


def _conditions(r: dict) -> list:
    return [s.get("condition") for s in r.get("subtasks") or [] if (s.get("condition") or {}).get("if") is not None]


def _branch_taken(r: dict, path, w) -> bool:
    """False for an atom in the branch of a condition that the start state ``w`` does not take."""
    if "condition" not in path:
        return True
    i = path.index("condition")
    if i + 1 >= len(path) or path[i + 1] not in ("then", "else"):
        return True
    node = r
    for k in path[:i + 1]:
        node = node[k]
    from homeloop_robot import goals as G
    return G.holds(node["if"], w) == (path[i + 1] == "then")


def within_reach(r: dict, w) -> list:
    """(obj, person) deliveries already within the person's reach at the start (atoms of a condition branch the
    start state does not take are left out)."""
    out = []
    for path, a in delivery_atoms(r):
        if not _branch_taken(r, path, w):
            continue
        o, p = a["args"][0], a["args"][1]
        if o in w.objects and p in w.people and reach.reachable(o, p, w):
            out.append((o, p))
    return sorted(set(out))


# ── step 1: another arrangement when the object is already within reach ───────────────────────────────

def _place_named(r: dict, w, oid: str) -> bool:
    pl = w.house.places.get(w.objects[oid].at)
    if pl is None:
        return False
    for lg in ("en", "ko"):
        t = (r["text"].get(lg) or "").lower()
        names = [pl.name.get(lg, "")] + list((pl.aliases or {}).get(lg) or [])
        if any(n and n.lower() in t for n in names):
            return True
    return False


def reseed(r: dict, w):
    """(new seed_state, pass) or None (see the module doc)."""
    bad = within_reach(r, w)
    if not bad:
        return None
    probs = {o for o, _ in bad}
    named = objects_named(r, w)
    keep1 = named - probs
    recips = {p for _, p in delivery_atoms_args(r)}
    conds = _conditions(r)
    from homeloop_robot import goals as G
    passes = (2,) if any(_place_named(r, w, o) for o in probs) else (1, 2)
    for ps in passes:
        for k in range(RESEED_TRIES):
            s = _h(gen_id(r), "reseed", ps, k) % 10000
            if s == r["seed_state"]:
                continue
            w2 = from_house(r["house"], s)
            if ps == 1:
                if any(w2.people[p].seat != w.people[p].seat for p in w.people):
                    continue
                if any(w2.objects[o].at != w.objects[o].at for o in keep1):
                    continue
            else:
                if any(w2.people[p].seat != w.people[p].seat for p in w.people if p not in recips):
                    continue
                if any(w2.objects[o].at != w.objects[o].at for o in named):
                    continue
            if within_reach(r, w2) or any(G.holds(c["if"], w2) != G.holds(c["if"], w) for c in conds):
                continue
            if not _same_task(r, w, w2):
                continue
            return s, ps
    return None


def _same_task(r: dict, w, w2) -> bool:
    """The task stays the same task in arrangement ``w2``: every subtask goal holds (or not) as before, and the
    oracle still solves the goal (so a moved object does not fill a place the task needs)."""
    from homeloop_robot import goals as G
    from homeloop_robot import oracle
    for s in r.get("subtasks") or []:
        g = {"all": list((s.get("goal") or {}).get("all") or [])}
        if g["all"] and G.evaluate(g, w2).holds != G.evaluate(g, w).holds:
            return False
    if r.get("kind") != "refuse":
        g = {"all": [a for a in r["goal"]["all"] if a.get("pred") != "unmoved"]}
        if g["all"] and oracle.solve(w2, g, lang="en", text=r["text"].get("en", "")) is None:
            return False
        if r.get("order"):
            return _ordered_solvable(r, w2.seed_state)
    return True


def _ordered_solvable(r: dict, seed_state: int) -> bool:
    """Ordered subtasks: the oracle reaches the goals stage by stage (subtasks 0..k in index order) in an ideal
    run, as validate's oracle check does."""
    from homeloop_robot import goals as G
    from homeloop_robot import make_episode, oracle
    sim = make_episode(r["house"], int(seed_state), "ideal", 0, lang="en", user_impl="null", safety_impl="null")
    subs = r.get("subtasks") or []
    text = r["text"].get("en", "")
    for k in range(len(subs)):
        g = {"all": [a for s in subs[:k + 1] if s.get("kind") != "refuse" for a in s["goal"]["all"]
                     if a.get("pred") != "unmoved"]}
        if not g["all"] or G.evaluate(g, sim.world).holds:
            continue
        plan = oracle.solve(sim.world, g, lang="en", text=text)
        if not plan:
            return False
        for c in plan:
            sim.robot.call(c.skill, **c.args)
        if not G.evaluate(g, sim.world).holds:
            return False
    return True


def delivery_atoms_args(r: dict) -> list:
    return [(a["args"][0], a["args"][1]) for _, a in delivery_atoms(r)]


# ── step 2: explicit hand wording ─────────────────────────────────────────────────────────────────────

def _template_lang(r: dict, lg: str) -> bool:
    return (r.get("source_by_lang") or {}).get(lg, r.get("source")) == "template"


def _elder(person) -> bool:
    from homeloop_robot.user import age_lower
    lo = age_lower(getattr(person, "age_group", None))
    return lo is not None and lo >= 65


def _quota(r: dict) -> bool:
    return _frac(gen_id(r), "quota") < QUOTA_SHARE.get(r.get("split"), 0.0)


def explicit_variant(r: dict, w):
    """(variant, {lang: new text}) or None."""
    atoms = delivery_atoms(r)
    if not atoms or r.get("kind") == "refuse" or any(_in_correction(p) for p, _ in atoms):
        return None
    if wants_hand(r["text"]):
        return None
    en, ko = r["text"]["en"], r["text"]["ko"]
    top = [a for _, a in walk(r.get("goal")) if a.get("pred") in ("held_by", "delivered")]
    one = len({tuple(a["args"]) for _, a in atoms}) == 1          # the hand wording is about this one delivery
    if one and reach.wording_wants_hand(en, "en") and _template_lang(r, "ko") and len(KO_VERB.findall(ko)) == 1 \
            and not reach.wording_wants_hand(ko, "ko"):
        new = KO_VERB.sub(lambda m: f"가져다 건네{m.group(2)}", ko)
        return "ko_verb", {"ko": new}
    if (len(top) != 1 or any(a["args"] != top[0]["args"] for _, a in atoms)
            or not (_template_lang(r, "en") and _template_lang(r, "ko"))
            or reach.wording_wants_hand(en, "en") or reach.wording_wants_hand(ko, "ko")
            or _HANDS_MENTIONED.search(en) or "손" in ko):
        return None                     # a text that talks about the hands ("my hands are full") gets no hand sentence
    oid, pid = top[0]["args"]
    cls = w.objects[oid].cls
    if cls in NO_APPEND:
        return None
    single = r.get("structure") == "single" and (r.get("n_subtasks") or 1) == 1
    if single:
        if _frac(gen_id(r), "explicit") >= APPEND_SHARE and not _quota(r):
            return None
    elif r.get("structure") in QUOTA_STRUCTURES and _quota(r):
        return _named_variant(r, w, oid, pid)
    else:
        return None
    plural = cls in PLURAL
    i = _h(gen_id(r), "explicit_form")
    person = w.people[pid]
    if pid == w.user_id():
        e = (EN_ME_PL if plural else EN_ME)
        k = KO_ME
    else:
        male = getattr(person, "sex", "") == "male"
        e = tuple(x.format(pos="his" if male else "her", obj="him" if male else "her")
                  for x in (EN_OTHER_PL if plural else EN_OTHER))
        k = KO_ELDER if _elder(person) else KO_OTHER
    en2 = _append(en, e, i)
    ko2 = _append(ko, k, i // 7)
    return "append", {"en": en2, "ko": ko2}


def _name_in(text: str, names: list, lang: str):
    """The longest of ``names`` that the text says (EN: as whole words, case-insensitive), or None."""
    t = text.lower() if lang == "en" else text
    for n in sorted({x for x in names if x and "'" not in x}, key=lambda x: (-len(x), x)):
        if lang == "en":
            if re.search(r"(?<![\w-])" + re.escape(n.lower()) + r"(?![\w-])", t):
                return n
        elif n in t:
            return n
    return None


def _named_variant(r: dict, w, oid: str, pid: str):
    """``append_named``: a sentence that names the one delivered object of a compound task, or None when the
    text does not name it by a name no other object of the task shares."""
    from .ko import josa
    from .lexicon import Lex
    lex = Lex(w)
    names = {lg: _name_in(r["text"][lg], lex.obj_names(oid, lg), lg) for lg in ("en", "ko")}
    if not all(names.values()):
        return None
    for other in objects_named(r, w) - {oid}:
        for lg in ("en", "ko"):
            if names[lg] in lex.obj_names(other, lg) or names[lg] == lex.cls_name(w.objects[other].cls, lg):
                return None
    i = _h(gen_id(r), "explicit_form")
    person = w.people[pid]
    if pid == w.user_id():
        e, k = EN_ME_N, KO_ME_N
    else:
        male = getattr(person, "sex", "") == "male"
        e = tuple(x.replace("{pos}", "his" if male else "her").replace("{obj}", "him" if male else "her")
                  for x in EN_OTHER_N)
        k = KO_ELDER_N if _elder(person) else KO_OTHER_N
    e = tuple(x.replace("{n}", names["en"]) for x in e)
    k = tuple(x.replace("{t}", josa(names["ko"], "은/는")) for x in k)
    return "append_named", {"en": _append(r["text"]["en"], e, i), "ko": _append(r["text"]["ko"], k, i // 7)}


def _append(text: str, forms: tuple, i: int) -> str:
    """``text`` + one of ``forms`` (chosen by ``i``) whose first word is not the text's last word (no "please.
    Please"), and without "please" when the text has one."""
    last = (re.findall(r"\w+", text.lower()) or [""])[-1]
    ok = [f for f in forms if (re.findall(r"\w+", f.lower()) or [""])[0] != last] or list(forms)
    if "please" in text.lower():                                    # one "please" per request is enough
        ok = [f for f in ok if "please" not in f.lower()] or ok
    return text.rstrip() + " " + ok[i % len(ok)]


# ── the rewrite ───────────────────────────────────────────────────────────────────────────────────────

def _relabel(r: dict, w) -> None:
    texts = r["text"]
    ctexts = correction_texts(r)
    for path, a in delivery_atoms(r):
        o, p = a["args"][0], a["args"][1]
        mode, why = label(w, p, ctexts if _in_correction(path) else texts)
        a.clear()
        a.update({"pred": "delivered", "args": [o, p], "mode": mode, "mode_reason": why})


def rewrite(rec: dict, no_variant: bool = False) -> tuple:
    """(new record, info) for one task record; the input is not changed. ``no_variant``: no explicit-hand
    wording (used when the wording would make a near duplicate of a text in another split)."""
    r = copy.deepcopy(rec)
    info = {"reseed": None, "variant": None}
    if not delivery_atoms(r):
        return r, info
    meta = r.setdefault("meta", {})
    w = from_house(r["house"], r["seed_state"])
    rs = reseed(r, w)
    if rs is not None:
        old = r["seed_state"]
        r["seed_state"], ps = rs
        w = from_house(r["house"], r["seed_state"])
        prev = (meta.get("delivery") or {}).get("reseed")
        info["reseed"] = prev or {"from": old, "pass": ps}
    ev = None if no_variant else explicit_variant(r, w)
    if ev is not None:
        variant, new = ev
        info["variant"] = variant
        tt = meta.get("template_text")
        for lg, t in new.items():
            r["text"][lg] = t
            if isinstance(tt, dict):
                tt[lg] = t
        r["length_words"] = {lg: words(r["text"][lg], lg) for lg in ("en", "ko")}
    d = dict(meta.get("delivery") or {})
    if info["reseed"] is not None:
        d["reseed"] = info["reseed"]
    if info["variant"] is not None:
        d["variant"] = info["variant"]
    d.setdefault("reseed", None)
    d.setdefault("variant", None)
    info = {"reseed": d["reseed"], "variant": d["variant"]}
    meta["delivery"] = d
    _relabel(r, w)
    return r, info


def _near_dup_ids(recs: list) -> set:
    from . import dedup
    ids = set()
    for lg in ("en", "ko"):
        for a, b, _j in dedup.near_dup_pairs(recs, lg):
            ids.update((a, b))
    return ids


def rewrite_all(recs: list) -> tuple:
    """(new records, report). Pass every split together: an explicit-hand variant that makes a cross-split near
    duplicate (dedup, Jaccard >= 0.90) is not applied to that task."""
    before = _near_dup_ids(recs)
    pairs = [rewrite(rec) for rec in recs]
    new = {r["id"] for (r, info), rec in zip(pairs, recs) if r["text"] != rec["text"]}
    skip = (_near_dup_ids([r for r, _ in pairs]) - before) & new
    out, c = [], Counter()
    unfixed = []
    for rec, (r, info) in zip(recs, pairs):
        if r["id"] in skip:
            r, info = rewrite(rec, no_variant=True)
            c["variant_skipped_near_duplicate"] += 1
        out.append(r)
        if delivery_atoms(r):
            c["tasks_with_delivery"] += 1
            if info["reseed"]:
                c[f"reseed_pass{info['reseed']['pass']}"] += 1
            if info["variant"]:
                c[f"variant_{info['variant']}"] += 1
            if within_reach(r, from_house(r["house"], r["seed_state"])):
                unfixed.append(r["id"])
    rep = dict(sorted(c.items()))
    rep.update(delivery_stats(out))
    rep["within_reach_at_start"] = unfixed
    return out, rep


def delivery_stats(recs: list) -> dict:
    """Counts of the delivery atoms of the task goals (top-level ``goal``) by mode and mode_reason."""
    by_mode, by_reason = Counter(), Counter()
    n = 0
    for r in recs:
        for _, a in walk(r.get("goal")):
            if a.get("pred") != "delivered":
                continue
            n += 1
            by_mode[a.get("mode")] += 1
            by_reason[f"{a.get('mode')}:{a.get('mode_reason')}"] += 1
    hand = by_mode.get("hand", 0)
    return {"delivered_atoms": n, "by_mode": dict(sorted(by_mode.items())),
            "by_mode_reason": dict(sorted(by_reason.items())),
            "hand_share": round(hand / n, 4) if n else None}
