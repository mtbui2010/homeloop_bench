"""Clauses: one subtask as a verb phrase in English and an argument pattern + verb in Korean.

A clause is built from a goal atom on a world (``build``); ``en_vp`` / ``ko_form`` render it with a chosen
variant. Single tasks wrap one clause in a request; compound tasks join several clauses (gen/compound.py).
Every rendered clause records the entity phrases it used (``ents``), which the paraphrase filter and the
realism check R-f require to stay in the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from homeloop_robot.catalog import CLASSES, place_category

from . import templates_en as EN
from . import templates_ko as KO
from .ko import josa
from .lexicon import Lex, plural

SLOT = re.compile(r"\{([A-Za-z_0-9]+)(?::([^}]+))?\}")


def fill(tpl: str, slots: dict, lang: str) -> str:
    def sub(m):
        key, part = m.group(1), m.group(2)
        if key not in slots or slots[key] is None:
            return m.group(0)                      # left unfilled: the R-g residue check catches it
        v = slots[key]
        return josa(v, part) if (part and lang == "ko") else v
    out = SLOT.sub(sub, tpl)
    return tidy(out)


def tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.?!;])", r"\1", s)
    s = s.replace(",,", ",").replace("..", ".").replace("?.", "?").replace(".?", "?")
    s = POSS_THE.sub(lambda m: (m.group(2).capitalize() if m.group(1) == "T" else m.group(2)), s)
    return s


# "the my desk" -> "my desk": place names that already carry a possessive take no article
POSS_THE = re.compile(r"\b([Tt])he (my|your|our|his|her|their)\b")


def cap1(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


@dataclass
class Clause:
    kind: str                   # fetch_me fetch_to put_on put_in open close tell go_room dock
    atom: dict                  # the goal atom it makes true
    oid: str | None = None
    place: str | None = None    # destination / container
    src: str | None = None      # where the object is now (mentioned only when src_mention)
    person: str | None = None
    msg: str | None = None
    room: str | None = None
    home: bool = False          # the destination is the object's usual place ("put it back")
    src_mention: bool = False
    force_color: bool = False
    pron: bool = False          # the person was named earlier in the utterance: use a pronoun (KO: drop it)
    ents: dict = field(default_factory=lambda: {"en": [], "ko": []})


def obj_slots_en(lex: Lex, oid: str, rng, force_color=False) -> dict:
    name = lex.obj(oid, "en", rng, force_color)
    cls = lex.w.objects[oid].cls
    pl = plural(cls, name)
    return {"o": "the " + name, "o_bare": name, "it": "them" if pl else "it", "it_is": "they're" if pl else "it's",
            "it_goes": "they go" if pl else "it goes", "it_belongs": "they belong" if pl else "it belongs",
            "It_is": "They're" if pl else "It's", "is": "are" if pl else "is"}


def ko_obj(name: str, rng, drop_p: float = 0.12, jom_p: float = 0.2) -> tuple:
    """(rendered object with particle, dropped?)  -> '우유를' | '우유 좀' | '우유'."""
    if name.endswith(("것", "거")):
        return f"{name} 좀", False
    u = rng.random()
    if u < drop_p:
        return name, True
    if u < drop_p + jom_p:
        return f"{name} 좀", False
    return josa(name, "을"), False


def build(lex: Lex, atom: dict, *, src_mention=False, force_color=False) -> Clause:
    w = lex.w
    p, a = atom["pred"], atom["args"]
    user = w.user_id()
    if p == "held_by":
        oid, per = a
        o = w.objects[oid]
        kind = "fetch_me" if per == user else "fetch_to"
        return Clause(kind, atom, oid=oid, person=None if per == user else per, src=o.at,
                      src_mention=src_mention and o.at in w.house.places, force_color=force_color)
    if p in ("on", "in"):
        oid, pid = a
        o = w.objects[oid]
        home = w.initial_at.get(oid) == pid or _yaml_home(w, oid) == pid
        return Clause("put_in" if p == "in" else "put_on", atom, oid=oid, place=pid, src=o.at, home=home,
                      src_mention=src_mention and o.at in w.house.places and o.at != pid, force_color=force_color)
    if p in ("open", "closed"):
        return Clause("open" if p == "open" else "close", atom, place=a[0])
    if p == "said_to":
        return Clause("tell", atom, person=a[0], msg=a[1])
    if p == "docked":
        return Clause("dock", atom)
    raise ValueError(f"no clause for {atom}")


def build_room(lex: Lex, room: str, atom: dict) -> Clause:
    return Clause("go_room", atom, room=room)


def _yaml_home(w, oid):
    for s in w.house.objects:
        if s.id == oid:
            return s.at
    return None


# ── English ───────────────────────────────────────────────────────────────────────────────────────────
def en_vp(lex: Lex, c: Clause, rng, variant: int | None = None) -> tuple:
    """(vp, variant key) for a clause."""
    w = lex.w
    s = {}
    if c.oid:
        s.update(obj_slots_en(lex, c.oid, rng, c.force_color))
        c.ents["en"].append(_obj_alts(lex, c.oid, "en", c.force_color, s["o_bare"]))
    if c.src and c.src in w.house.places:
        s["src"] = lex.place(c.src, "en", rng)
    if c.place:
        key = "c" if c.kind in ("put_in", "open", "close") else "dst"
        s[key] = lex.place(c.place, "en", rng)
        c.ents["en"].append(lex.place_names(c.place, "en"))
    if c.person:
        s["p"] = lex.person(c.person, "en")
        s["pp"] = lex.pron(c.person)
        s.update(EN.PRON[s["pp"]])
        if c.pron:
            s["p"] = s["pp"]
        else:
            c.ents["en"].append([s["p"]] + lex.person_names(c.person)["en"])
    if c.room:
        s["r"] = lex.room(c.room, "en")
        c.ents["en"].append([s["r"]])
    if c.msg:
        m = rng.choice(EN.MSG[c.msg])
        s["msg"] = fill(m, s, "en")
    key = _en_key(lex, c)
    opts = EN.VP[key]
    if key == "put_in" and place_category(w.house.places[c.place]) in ("Microwave",):
        opts = [opts[0], opts[2]]                  # "put away" / "store" are for storage, not appliances
    i = variant if variant is not None else rng.randrange(len(opts))
    vp = fill(opts[i % len(opts)], s, "en")
    if c.msg:
        c.ents["en"].append(_msg_alts_en(c.msg))
    return vp, f"{key}.{i % len(opts)}"


def _en_key(lex, c):
    if c.kind == "fetch_me":
        if c.src_mention:
            return "fetch_me_in" if lex.w.house.places[c.src].kind == "container" else "fetch_me_src"
        return "fetch_me"
    if c.kind == "fetch_to":
        return "fetch_to_src" if c.src_mention and lex.w.house.places[c.src].kind != "container" else "fetch_to"
    if c.kind == "put_on":
        if lex.is_sink(c.place):
            return "put_sink"
        if c.src_mention:
            return "put_on_src"
        return "put_on_home" if c.home else "put_on"
    if c.kind == "put_in":
        cls = lex.w.objects[c.oid].cls
        if cls in ("shirt",) and place_category(lex.w.house.places[c.place]) == "Wardrobe":
            return "hang"
        if c.src_mention:
            return "put_in_src"
        return "put_in_home" if c.home else "put_in"
    return c.kind


def _obj_alts(lex, oid, lang, force_color, used):
    alts = [used] + [n for n in lex.obj_names(oid, lang, force_color) if n != used]
    if lex.n_same(oid) == 1 and not force_color:
        cls = lex.w.objects[oid].cls
        alts += [n for n in [CLASSES[cls].name[lang]] + list((CLASSES[cls].aliases or {}).get(lang) or [])
                 if n not in alts]
    return alts


def _msg_alts_en(key):
    return {"dinner_ready": ["dinner"], "lunch_ready": ["lunch"], "take_medicine": ["medicine", "pill"],
            "drink_water": ["water"], "phone_call": ["phone", "call"], "door_visitor": ["door"],
            "laundry_done": ["laundry"], "wake_up": ["up"], "bedtime": ["bed"], "leaving_soon": ["minutes"],
            "tv_off": ["TV"], "come_kitchen": ["kitchen"]}[key]


def _msg_alts_ko(key):
    return {"dinner_ready": ["저녁", "진지"], "lunch_ready": ["점심"], "take_medicine": ["약"],
            "drink_water": ["물"], "phone_call": ["전화"], "door_visitor": ["문", "누가"],
            "laundry_done": ["빨래", "세탁"], "wake_up": ["일어나"], "bedtime": ["잘", "주무"],
            "leaving_soon": ["10분", "십 분"], "tv_off": ["텔레비전", "티비"], "come_kitchen": ["주방", "부엌"]}[key]


# ── Korean ────────────────────────────────────────────────────────────────────────────────────────────
def ko_parts(lex: Lex, c: Clause, rng, variant: int | None = None) -> tuple:
    """(argument text, verb key, variant key, particle_dropped)."""
    w = lex.w
    s, dropped = {}, False
    if c.oid:
        name = lex.obj(c.oid, "ko", rng, c.force_color)
        s["O"] = name
        s["Oj"], dropped = ko_obj(name, rng)
        c.ents["ko"].append(_obj_alts(lex, c.oid, "ko", c.force_color, name))
    if c.src and c.src in w.house.places:
        s["SRC"] = lex.place(c.src, "ko", rng)
    if c.place:
        key = "C" if c.kind in ("put_in", "open", "close") else "DST"
        s[key] = lex.place(c.place, "ko", rng)
        c.ents["ko"].append(lex.place_names(c.place, "ko"))
    if c.person:
        s["P"] = lex.person(c.person, "ko")
        s["Pk"] = lex.to_person_ko(c.person)
        if c.pron:
            s["Pk"] = ""
        else:
            c.ents["ko"].append([s["P"]] + lex.person_names(c.person)["ko"])
    if c.room:
        s["R"] = lex.room(c.room, "ko")
        c.ents["ko"].append([s["R"]])
    if c.msg:
        plain, hon = KO.MSG[c.msg]
        forms = hon if (c.person and lex.honor(c.person)) else plain
        kitchen = _kitchen_ko(w)
        s["MSG"] = fill(rng.choice(forms), {"KITCHEN": kitchen}, "ko")
        c.ents["ko"].append(_msg_alts_ko(c.msg))
    key = _ko_key(lex, c)
    opts = KO.VP[key]
    if key == "put_in" and place_category(w.house.places[c.place]) in ("Microwave", "Fridge"):
        opts = opts[:2]                            # 정리하다 is for storage, not appliances
    i = variant if variant is not None else rng.randrange(len(opts))
    pat, verb = opts[i % len(opts)]
    return fill(ko_pat(pat, verb), s, "ko"), verb, f"{key}.{i % len(opts)}", dropped


def ko_pat(pat: str, verb: str) -> str:
    """The argument part of a Korean pattern (patterns end with their verb key for readability)."""
    return pat[: -len(verb)].rstrip() if pat.endswith(verb) else pat


def _kitchen_ko(w):
    for rid, r in w.house.rooms.items():
        if "kitchen" in r.types:
            n = r.name["ko"]
            return "부엌" if "부엌" in n else "주방"
    return "주방"


def _ko_key(lex, c):
    w = lex.w
    honor = bool(c.person and lex.honor(c.person))
    if c.kind == "fetch_me":
        if c.src_mention:
            return "fetch_me_in" if w.house.places[c.src].kind == "container" else "fetch_me_src"
        return "fetch_me"
    if c.kind == "fetch_to":
        base = "fetch_to_src" if c.src_mention and w.house.places[c.src].kind != "container" else "fetch_to"
        return base + ("_h" if honor else "")
    if c.kind == "put_on":
        if lex.is_sink(c.place):
            return "put_sink"
        if w.objects[c.oid].cls in ("book", "notebook") and place_category(w.house.places[c.place]) == "Shelf":
            return "put_book"
        if c.src_mention:
            return "put_on_src"
        return "put_on_home" if c.home else "put_on"
    if c.kind == "put_in":
        cls = w.objects[c.oid].cls
        if cls == "shirt" and place_category(w.house.places[c.place]) == "Wardrobe":
            return "hang"
        if c.src_mention:
            return "put_in_src"
        return "put_in_home" if c.home else "put_in"
    if c.kind in ("open", "close"):
        drawer = (w.house.places[c.place].container.type in ("drawer", "box"))
        return c.kind + ("_drawer" if drawer else "")
    if c.kind == "tell":
        return "tell_h" if honor else "tell"
    return c.kind


def ko_form(verb: str, form: str) -> str:
    return KO.V[verb][form]
