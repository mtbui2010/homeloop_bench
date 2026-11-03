"""Korean texts that put something inside an object (R2-5 B5): "접시 안에 넣어" = "put it inside the plate".

A container in a goal is always a place (fridge, drawer, cabinet), never an object. A Korean text with
``<object name> 안에 / 속에 넣 / 담`` therefore says something else than the goal: usually the object particle was
dropped before 안에 ("접시를 안에 넣어" -> "접시 안에 넣어"), by the KO paraphraser or by a template's particle drop.

* :func:`object_as_container` finds such a phrase (an object class name of the catalog, not also a place name of
  the task's house, right before 안에 / 속에 + 넣 / 담).
* :func:`fix_record` repairs one record deterministically: an LLM paraphrase falls back to its template text; a
  template text gets the object particle back (``josa(name, '을')``). The old text is kept in
  ``meta.ko_fix``. Idempotent.
"""

from __future__ import annotations

import functools
import re

from .ko import josa
from .textcheck import words


@functools.lru_cache(maxsize=1)
def _object_names() -> tuple:
    from homeloop_robot.catalog import CLASSES, class_names
    names = {n for c in CLASSES for n in class_names(c, "ko") if n}
    return tuple(sorted(names, key=lambda s: (-len(s), s)))


@functools.lru_cache(maxsize=None)
def _place_names(house: str) -> frozenset:
    from homeloop_robot.houses import load_house
    h = load_house(house)
    out = set()
    for p in h.places.values():
        out.add(p.name.get("ko", ""))
        out.update((p.aliases or {}).get("ko") or [])
    return frozenset(x for x in out if x)


def _rx(name: str):
    return re.compile(r"(?<![가-힣])" + re.escape(name) + r"\s*(안|속)에\s*(넣|담)")


def object_as_container(text: str, house: str) -> list:
    """The object names used as a container in Korean ``text`` (empty = fine)."""
    places = _place_names(house)
    hits = []
    for n in _object_names():
        if n in places:
            continue
        if _rx(n).search(text or "") and not any(n in h for h in hits):
            hits.append(n)
    return hits


def _restore_particle(text: str, house: str) -> str:
    for n in object_as_container(text, house):
        text = _rx(n).sub(lambda m, n=n: f"{josa(n, '을')} {m.group(1)}에 {m.group(2)}", text)
    return text


def fix_record(r: dict):
    """-> (record, rule or None). rule: 'template_fallback' | 'particle'."""
    t = (r.get("text") or {}).get("ko") or ""
    if not object_as_container(t, r["house"]):
        return r, None
    meta = r.setdefault("meta", {})
    tt = meta.get("template_text") if isinstance(meta.get("template_text"), dict) else None
    src = (r.get("source_by_lang") or {}).get("ko")
    rule = None
    if src == "llm_paraphrase" and tt and tt.get("ko") and not object_as_container(tt["ko"], r["house"]):
        new = tt["ko"]
        rule = "template_fallback"
        r["source_by_lang"]["ko"] = "template"
        r.setdefault("paraphrase_model", {})["ko"] = None
        para = dict(meta.get("paraphrase") or {})
        para.pop("ko", None)
        if (r.get("source_by_lang") or {}).get("en") == "llm_paraphrase":
            meta["paraphrase"] = para
        else:                                   # no paraphrase left: a template record
            meta["paraphrase"] = None
            meta["template_text"] = None
            r["source"] = "template"
    else:
        new = _restore_particle(t, r["house"])
        rule = "particle"
        if tt and tt.get("ko") == t:
            tt["ko"] = new
        if meta.get("ko_particle_dropped") and src != "llm_paraphrase":
            meta["ko_particle_dropped"] = False       # the dropped particle is the one put back
    meta["ko_fix"] = {"rule": "object_as_container", "how": rule, "from": t}
    r["text"]["ko"] = new
    r["length_words"] = {lg: words(r["text"][lg], lg) for lg in ("en", "ko")}
    return r, rule


def fix_all(recs: list) -> tuple:
    """-> (records, report {n_fixed, by_rule, ids})."""
    out, ids, by = [], [], {}
    for r in recs:
        r, rule = fix_record(r)
        if rule:
            ids.append(r["id"])
            by[rule] = by.get(rule, 0) + 1
        out.append(r)
    return out, {"n_fixed": len(ids), "by_rule": by, "ids": ids}


def problems(recs: list) -> list:
    """(id, names) of every record whose Korean text uses an object as a container."""
    return [(r["id"], h) for r in recs for h in [object_as_container((r.get("text") or {}).get("ko", ""), r["house"])]
            if h]
