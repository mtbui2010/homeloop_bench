"""Lab round 3, H3: the ``tell_fetch`` family ("tell P <message> and bring me X") is rendered with the fetch clause in
its own sentence (``compound.EN_TELLFETCH`` / ``KO_TELLFETCH``), so the robot's fetch cannot be read as part of the
message. ``python -m homeloop_bench.data tellfix`` re-renders the template text of the train and dev tasks of the family
through the generator's own ``compound.render`` (same house, seed_state, goals, request wrapper nn), keeps the dock
and explicit-hand sentences the later steps appended, and resets the record to template text; ``paraphrase
--tellfix`` then redoes the LLM paraphrases of exactly those records (its EN judge asks the attachment question).
The test split is not touched (a full ``generate`` would renumber everything: the draws depend on which texts
were already accepted, so the family cannot be regenerated alone, only re-rendered).

Deterministic: the rng of a record is derived from its generation id; idempotent (a record whose texts already pass
:func:`attach.attach_problem` and carry ``meta.tellfix`` is left alone)."""

from __future__ import annotations

import copy
import re

from homeloop_robot.rng import rng_for
from homeloop_robot.world import from_house

from . import compound as CP
from .attach import FAMILIES, attach_problem
from .clauses import tidy
from .dedup import norm
from .lexicon import Lex
from .textcheck import check_text, sentences, words

SPLITS_FIXED = ("train", "dev")             # the test split is left alone
TRIES = 40


def _gid(r):
    return (r.get("meta") or {}).get("gen_id") or r["id"]


def _tails(text: str, lang: str) -> tuple:
    """(core, [tail sentences]) of a template text: trailing sentences that are the dock sentence or ask for a hand."""
    from homeloop_robot import reach
    dock = {tidy(s) for s in (CP.DOCK_EN if lang == "en" else CP.DOCK_KO)}
    sents = sentences(text)
    tails = []
    while len(sents) > 1 and (tidy(sents[-1]) in dock or reach.wording_wants_hand(sents[-1], lang)):
        tails.insert(0, sents.pop())
    return " ".join(sents), tails


def _obj_phrases(rec: dict, lang: str) -> list:
    """Phrases of the fetched object: the last entity group that is not the charging-dock group."""
    groups = [g for g in ((rec.get("meta") or {}).get("entities") or {}).get(lang, [])
              if not any(re.search(r"charg|dock|충전", str(a)) for a in g)]
    return [str(a) for a in groups[-1]] if groups else []


def _has(text: str, phrase: str, lang: str) -> bool:
    return phrase.lower() in text.lower() if lang == "en" else phrase in text


def _cand(r: dict) -> dict:
    """The generator's candidate of a stored record: its subtasks (a docked subtask is the dock sentence, not a clause),
    ``delivered`` atoms written back as the ``held_by`` the renderer reads."""
    subs = []
    for st in r["subtasks"]:
        a = st["goal"]["all"][0]
        if a["pred"] == "docked":
            continue
        st = copy.deepcopy(st)
        for x in st["goal"]["all"]:
            if x["pred"] == "delivered":
                x["pred"] = "held_by"
                for k in ("mode", "mode_reason"):
                    x.pop(k, None)
        subs.append(st)
    return {"family": "tell_fetch", "structure": "sequence", "src": "gpsr_multi", "subs": subs, "data": {}}


def retemplate(r: dict, taken: dict) -> dict | None:
    """The record with a new template text (both languages), or None when no draw passes. ``taken`` = normalised texts
    of the other tasks per language (no exact duplicate)."""
    if (r.get("meta") or {}).get("family") not in FAMILIES:
        return None
    nn = int(r["template_id"].rsplit(".", 1)[1])
    base = (r["meta"].get("template_text") or r["text"])
    cores, tails = {}, {}
    for lg in ("en", "ko"):
        cores[lg], tails[lg] = _tails(base[lg], lg)
    lex = Lex(from_house(r["house"], r["seed_state"]))
    cand = _cand(r)
    for attempt in range(TRIES):
        rng = rng_for(2026, "tellfix", _gid(r), attempt)
        out = CP.render(lex, cand, rng, nn)
        if out is None:
            continue
        txt = {lg: tidy(" ".join([out[lg]] + tails[lg])) for lg in ("en", "ko")}
        new = dict(r, text=txt, meta=dict(r["meta"], entities=out["ents"]))
        if any(attach_problem(new, lg) for lg in txt):
            continue
        if any(check_text(txt[lg], lg, True) for lg in txt):
            continue
        if any(norm(txt[lg], lg) in taken[lg] for lg in txt):
            continue
        # a kept sentence that names the object ("put the white mug right in my hand") must name the new object phrase
        if any(old and any(_has(t, o, lg) for t in tails[lg] for o in old) and
               not any(_has(t, nw, lg) for t in tails[lg] for nw in _obj_phrases(new, lg))
               for lg, old in ((lg, _obj_phrases(r, lg)) for lg in txt)):
            continue
        return {"text": txt, "entities": out["ents"], "attempt": attempt}
    return None


def apply(recs: list, log=print) -> dict:
    """Re-render the family's train / dev tasks in place. Returns counts."""
    taken = {lg: {norm(r["text"][lg], lg) for r in recs} for lg in ("en", "ko")}
    n = {"family": 0, "already": 0, "changed": 0, "failed": 0}
    for r in recs:
        if r["split"] not in SPLITS_FIXED or (r.get("meta") or {}).get("family") not in FAMILIES:
            continue
        n["family"] += 1
        if (r["meta"].get("tellfix")) and not any(attach_problem(r, lg) for lg in ("en", "ko")):
            n["already"] += 1
            continue
        for lg in ("en", "ko"):
            taken[lg].discard(norm(r["text"][lg], lg))
        res = retemplate(r, taken)
        if res is None:
            n["failed"] += 1
            log(f"tellfix: no draw for {r['id']}")
            for lg in ("en", "ko"):
                taken[lg].add(norm(r["text"][lg], lg))
            continue
        was = {lg: r["source_by_lang"][lg] for lg in ("en", "ko")}
        r["meta"]["tellfix"] = {"old_text": dict(r["text"]), "was_paraphrased": {lg: was[lg] == "llm_paraphrase" for lg in was},
                                "attempt": res["attempt"]}
        r["text"] = res["text"]
        r["meta"]["entities"] = res["entities"]
        r["meta"]["template_text"] = None
        r["meta"]["paraphrase"] = None
        r["source"] = "template"
        r["source_by_lang"] = {"en": "template", "ko": "template"}
        r["paraphrase_model"] = {"en": None, "ko": None}
        r["length_words"] = {lg: words(r["text"][lg], lg) for lg in ("en", "ko")}
        for lg in ("en", "ko"):
            taken[lg].add(norm(r["text"][lg], lg))
        n["changed"] += 1
    return n
