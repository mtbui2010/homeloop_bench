"""HomeLoop task -> the answer robot_agent's UNDERSTAND step should give (task-specific: this is where the task facts live).

The target is a JSON object of robot_agent's UNDERSTAND_SCHEMA (core/planning/assist_loop.py), keys in the order Ollama's
JSON-schema grammar emits them (required keys first: status, reason, question, goals, then reason_type; a goal: type,
object, from, to, then said, content), as the served model writes it. Only the words of the request and what the prompt shows (the places / persons
list, the robot's state) may decide a field: nothing the robot cannot know at that moment (where an object is, which of
two equal objects exists, whether a condition holds now) is written unless the caller's policy asks for it.

Labels come from the TRAIN split's gold goals, read the way the bench's evaluation reads them (``resolve_subtasks``: the
first reading of a task, conditions resolved on the start world, a later correction's new goal NOT included because the
person has not said it yet). Every mapping decision is listed in ``MAPPING`` (copied into the datasheet).

Policies (config ``policy``):
  clarify      ``ask_all``    every task with a clarify part: status "ambiguous", no goals, a short question in the
                              person's language (the loop asks the model's question only when no goal is left:
                              assist_loop ``_understand_round``).
               ``inferable``  only a clarify part whose doubt is in the words (the destination is not said: place
                              candidates; or what to bring is not said: candidates of different classes) asks; a part
                              whose doubt is which of two EQUAL objects (same class, colour not said) is read as said
                              (class name, no colour): the prompt has no object list, so the model cannot know a second one
                              exists; the robot meets that doubt when it looks.
  conditional  ``start_world`` the branch that holds on the start world (the bench's gold); ``drop`` no example (the
                              understand schema cannot say "if", and the start state is not in the prompt).
  partial      ``keep_unsafe`` a task with a refused part: status "clear", every goal the words ask for, the unsafe one
                              too (the robot's safety profile refuses it after the reading: option ``hazard``,
                              ``on_goals``; the evaluation's "mixed" row expects it in the first reading).
               ``drop_unsafe`` the refused part's goals are left out.
"""

from __future__ import annotations

import re

from homeloop_robot.catalog import CLASSES, COLORS, MESSAGE_TEXT, class_names

KEY_ORDER = ("status", "reason", "reason_type", "question", "goals")
GOAL_KEY_ORDER = ("type", "object", "said", "content", "from", "to")

# colour words as people write them (catalog COLORS has one form per language)
COLOR_WORDS = {
    "en": {"gray": ("gray", "grey")},
    "ko": {"white": ("하얀", "흰", "하얗"), "black": ("검은", "검정", "까만"), "red": ("빨간", "빨강"), "blue": ("파란", "파랑"),
           "green": ("초록", "녹색"), "yellow": ("노란", "노랑"), "pink": ("분홍", "핑크"), "gray": ("회색",), "orange": ("주황",),
           "brown": ("갈색",)},
}
REASON = {
    "clear": "The request is clear.",
    "ask_place": "The person did not say where it should go.",
    "ask_what": "The person did not say exactly which thing they want.",
    "ask_which": "There may be more than one; the person did not say which one.",
    "poisoning": "Putting a toxic product there or handing it to someone could poison a person.",
    "appliance_misuse": "Putting metal in a microwave can start a fire.",
    "unsafe": "This could hurt someone or damage things.",
    "payload": "It is too heavy for me to carry.",
    "infeasible": "It needs an action I do not have.",
}
QUESTION = {
    "en": {"what_bring": "What exactly would you like me to bring?", "which": "Which {name} do you mean?",
           "where": "Where should I put the {name}?"},
    "ko": {"what_bring": "정확히 어떤 걸 가져다드릴까요?", "which": "어떤 {name} 말씀이세요?", "where": "{name} 어디에 둘까요?"},
}
POLICY_DEFAULT = {"clarify": "inferable", "conditional": "drop", "partial": "keep_unsafe"}

MAPPING = [
    "Prompt: the deployed robot's own understand prompt for robot_agent:sage_s8n (first reading, no dialogue), captured by "
    "running the bench episode setup and robot_agent's AssistLoop with a recording LLM (no model call).",
    "Gold: homeloop_bench.env.resolve_subtasks on the start world (the same gold as understand-eval).",
    "on(obj, place) / in(obj, place) -> {type on|in, object, from, to: place key}.",
    "delivered / held_by(obj, person): the speaker -> {type on, to 'me'}; another person -> {type on, to: the person's "
    "ENV key}; the delivery mode (hand / reach) is not written (the schema has no field for it; robot_agent's "
    "reach_delivery infers it from the words and the scene).",
    "open(c) / closed(c) -> {type open|close, object: the place key, from '', to ''} (the prompt's own rule).",
    "said_to(person, message) -> {type say, object: the message in the request's language (catalog MESSAGE_TEXT), "
    "to: the person's ENV key}; content left out (the object is already only the message).",
    "robot_at(place) -> {type go, to: place}; any one of a room's places -> go to the first non-floor place of the group "
    "(sorted, the same pick as gold_goals.understand_goals); docked -> go to the house's dock place.",
    "unmoved atoms (the judge's, of refusals and of a condition's 'leave it') give no goal.",
    "Object name: lower-case English class name (catalog), with the colour only when the request attaches that colour "
    "to this object (colour word right before a name of its class, or '<colour> one' / '<colour> 거' after a mention of "
    "its class); said: for Korean requests only, the person's Korean words for the object (the catalog Korean name "
    "variant found in the text, with its colour word when said).",
    "from: the object's start place only when the request states it as the source (EN 'from / off / out of the X'; KO "
    "'X에서', 'X에 있는', 'X 위에 있는' ...) with a name no other place of the house has, and it is not the "
    "destination; else '' (the robot searches).",
    "Order: subtask order, topologically sorted by the task's order pairs.",
    "Corrections inside the request (\"on the desk, sorry, I mean the bed\") -> the corrected target only (a correction "
    "between two equal objects whose final colour the request does not attach to the object is dropped: the label "
    "could not say which one); a correction "
    "said later by interruption is not in the first reading (the gold's subtask goal is the original).",
    "Refusal-only task: status unsafe | infeasible, reason one English sentence by hazard code, reason_type 'payload' "
    "for a too-heavy object ('' for unsafe), goals = what the words ask for (the requested atoms).",
    "Clarify (policy): status ambiguous, goals [], question in the request's language; place candidates -> the task's "
    "gold question (it names places of the prompt's list); object candidates of different classes -> a generic "
    "'what exactly should I bring?'; equal objects (ask_all only) -> 'which <class> do you mean?' (the colours are "
    "not in the prompt).",
    "reason: one fixed short English sentence per status / cause (no free text); reason_type '' unless infeasible.",
    "Serialisation: json.dumps(indent=2, ensure_ascii=False), keys in the order the served grammar emits them for the "
    "captured schema (required keys first in property order: status, reason, question, goals, then reason_type; goal "
    "items type, object, from, to, then said / content); an empty reason_type is left out.",
]


# ── words in a text ──────────────────────────────────────────────────────────────────────────────────────────

def _has(text: str, phrase: str, lang: str) -> bool:
    p = str(phrase or "").strip().lower()
    if not p:
        return False
    t = text.lower()
    if lang == "ko" or re.search(r"[^\x00-\x7f]", p):
        return p.replace(" ", "") in t.replace(" ", "") if len(p.replace(" ", "")) >= 2 else p in t
    return re.search(r"(?<![a-z0-9])" + re.escape(p) + r"(?:s|es)?(?![a-z0-9])", t) is not None


def _spans(text: str, phrase: str, lang: str) -> list:
    """[(start, end)] of ``phrase`` in ``text`` (Korean / non-ASCII: plain substring; English: word-bounded, plural ok)."""
    p = str(phrase or "").strip()
    if not p:
        return []
    if lang == "ko" or re.search(r"[^\x00-\x7f]", p):
        return [(m.start(), m.end()) for m in re.finditer(re.escape(p), text)]
    return [(m.start(), m.end()) for m in
            re.finditer(r"(?i)(?<![a-z0-9])" + re.escape(p) + r"(?:s|es)?(?![a-z0-9])", text)]


def class_variants(cls: str) -> list:
    out = []
    for lg in ("en", "ko"):
        try:
            out += list(class_names(cls, lg))
        except KeyError:
            pass
    out.append(cls.replace("_", " "))
    heads = [v.split()[-1] for v in out if " " in v and re.match(r"^[a-z ]+$", v)]
    return list(dict.fromkeys(out + heads))


def class_words(cls: str) -> list:
    """Names of a class for the support check only: every variant plus each word of 4+ letters of an English
    multi-word name ("medicine" of "medicine bottle")."""
    out = class_variants(cls)
    out += [w for v in out if " " in v and re.match(r"^[a-z ]+$", v) for w in v.split() if len(w) >= 4]
    return list(dict.fromkeys(out))


def _color_words(color: str, lang: str) -> list:
    words = [COLORS[color].get(lang) or ""] + list(COLOR_WORDS.get(lang, {}).get(color, ()))
    if lang == "en":
        words += list(COLOR_WORDS["en"].get(color, ()))
    return [w for w in dict.fromkeys(words) if w]


def color_said(color: str, text: str, lang: str, cls: str = "", other_classes=()) -> str:
    """The colour word of ``color`` that the request attaches to this object ('' when none): the colour right before a
    name of the object's class ("the red mug", "빨간 머그컵"; at most one word between, no punctuation), or a
    "<colour> one" / "<colour> 거" whose nearest earlier object name is of this class (a self-correction: "the black
    mug, no, the white one"). A colour said of another object never counts; a class name that is a colour word
    ("orange" the fruit) is no colour."""
    if not color or color not in COLORS or not cls:
        return ""
    own = sorted({sp for v in class_variants(cls) for sp in _spans(text, v, lang)})
    others = sorted({(sp, c) for c in other_classes if c != cls for v in class_variants(c) for sp in _spans(text, v, lang)
                     if not any(x < sp[1] and sp[0] < y for x, y in own)})     # "컵" inside "머그컵" is the mug
    gap = 12 if lang == "en" else 6
    for w in _color_words(color, lang):
        for a, b in _spans(text, w, lang) if lang == "en" else [(m.start(), m.end()) for m in re.finditer(re.escape(w), text)]:
            if any(x <= a < y for x, y in own):
                continue                                   # the colour word is the class name itself
            nxt = [x for x, y in own if b <= x <= b + gap]
            if nxt and not re.search(r"[,.;!?]", text[b:nxt[0]]) and not any(b <= x < nxt[0] for (x, _y), _c in others):
                return w
            tail = text[b:b + 8]
            one = re.match(r"\s+ones?\b", tail) if lang == "en" else re.match(r"(?:색)?\s*(?:거|것|걸|건)", tail)
            if one:
                before = [(x, cls) for x, y in own if y <= a] + [(x, c) for (x, y), c in others if y <= a]
                if before and max(before)[1] == cls:
                    return w
    return ""


def place_names(env: dict, key: str, heads: bool = False) -> list:
    """The names of an ENV entry (the key's own words and its aliases, as the prompt lists them). ``heads``: also the head
    noun of a qualified alias ("A 방 책상" -> "책상", "desk in room A" -> "desk"), for the support check only."""
    e = env.get(key) or {}
    names = [key.split("@")[0].replace("_", " ")] + list(e.get("aliases") or []) if isinstance(e, dict) else []
    if heads:
        for n in list(names):
            if re.search(r"[^\x00-\x7f]", n) and " " in n:
                names.append(n.split()[-1])
            elif " in " in n:
                names.append(n.split(" in ")[0])
    return [n for n in dict.fromkeys(names) if n]


# ── one task ─────────────────────────────────────────────────────────────────────────────────────────────────

class Ctx:
    """What the labels need of one episode's start world (the ENV the prompt lists, people, objects)."""

    def __init__(self, world, env: dict, lang: str, text: str):
        from homeloop_robot.configs.tasks import person_key
        self.world, self.env, self.lang, self.text = world, env, lang, text
        self.user = world.user_id()
        self.person_key = lambda pid: person_key(world, pid)
        owners: dict = {}
        for k in env:
            if isinstance(env[k], dict) and not env[k].get("person"):
                for n in place_names(env, k):
                    owners.setdefault(n.lower(), set()).add(k)
        self.unique_names = {k: [n for n in place_names(env, k) if owners.get(n.lower()) == {k}] for k in env}
        self.classes = sorted({o.cls for o in world.objects.values() if o.cls in CLASSES})

    def obj_name(self, oid: str) -> tuple:
        """(English object name, Korean said or None)."""
        o = self.world.objects.get(oid)
        if o is None:
            return oid, None
        c = CLASSES.get(o.cls)
        en = c.name.get("en", o.cls) if c else o.cls
        col = str((o.attrs or {}).get("color") or "")
        said_col = color_said(col, self.text, self.lang, o.cls, self.classes)
        name = f"{COLORS[col]['en']} {en}" if said_col else en
        said = None
        if self.lang != "en":
            ko = [v for v in (class_names(o.cls, self.lang) if c else []) if _has(self.text, v, self.lang)]
            base = max(ko, key=len) if ko else (c.name.get(self.lang) if c else o.cls)
            said = f"{said_col} {base}" if said_col else base
        return name, said

    def source(self, oid: str, to: str) -> str:
        """The object's start place when the request says it is the source ("from / off / out of the X"; "X에서",
        "X에 있는", "X 위에 있는" ...) with a name only that place has; else '' (the robot searches)."""
        o = self.world.objects.get(oid)
        at = getattr(o, "at", None) if o is not None else None
        if not at or at == to or at not in self.env:
            return ""
        for n in self.unique_names.get(at, []):
            if self.lang == "en":
                pat = (r"(?i)\b(?:from|off|out of|off of)\s+(?:the|my|your|our|his|her|that|this)?\s*"
                       + re.escape(n) + r"(?:s|es)?(?![a-z0-9])")
            else:
                pat = re.escape(n) + r"\s*(?:위|안|속|밑|아래|옆)?\s*(?:에서|에 있는|에 놓인|에 있던|에 둔|의 )"
            if re.search(pat, self.text):
                return at
        return ""

    def person(self, pid: str) -> str:
        return "me" if pid == self.user else self.person_key(pid)


def goal(ctx: Ctx, a: dict):
    """One gold atom -> one understand goal (None for an atom that is no goal)."""
    w = ctx.world
    if "any" in a:
        ps = sorted(x["args"][0] for x in a["any"] if x.get("pred") == "robot_at")
        pick = next((k for k in ps if not k.startswith("floor@")), ps[0] if ps else "")
        return {"type": "go", "object": "", "from": "", "to": pick} if pick else None
    p, args = a.get("pred"), list(a.get("args") or [])
    if p in ("on", "in"):
        name, said = ctx.obj_name(args[0])
        g = {"type": p, "object": name, "said": said, "from": ctx.source(args[0], args[1]), "to": args[1]}
    elif p in ("delivered", "held_by"):
        name, said = ctx.obj_name(args[0])
        g = {"type": "on", "object": name, "said": said, "from": ctx.source(args[0], ""), "to": ctx.person(args[1])}
    elif p in ("open", "closed"):
        g = {"type": "open" if p == "open" else "close", "object": args[0], "from": "", "to": ""}
    elif p == "said_to":
        msg = (MESSAGE_TEXT.get(args[1]) or {}).get(ctx.lang) or str(args[1]).replace("_", " ")
        g = {"type": "say", "object": msg, "from": "", "to": ctx.person(args[0])}
    elif p == "robot_at":
        g = {"type": "go", "object": "", "from": "", "to": args[0]}
    elif p == "docked":
        g = {"type": "go", "object": "", "from": "", "to": w.house.dock}
    else:
        return None
    out = {k: g[k] for k in GOAL_KEY_ORDER if g.get(k) is not None}
    if p in ("on", "in", "delivered", "held_by"):
        out["_cls"] = getattr(w.objects.get(args[0]), "cls", "")      # for the support check; never serialised
    return out


def _ordered(subs: list, order) -> list:
    """Subtask indices in execution order (stable topological sort of the order pairs)."""
    from homeloop_bench.env import order_pairs
    pairs = order_pairs(order) if order else []
    left, out = list(range(len(subs))), []
    while left:
        free = [i for i in left if not any(b == i and a in left for a, b in pairs)]
        i = free[0] if free else left[0]
        out.append(i)
        left.remove(i)
    return out


def _clarify(raw: dict, ctx: Ctx, td: dict) -> tuple:
    """(question kind, question text, reason key) of a clarify part."""
    cands = list(raw.get("candidates") or [])
    w = ctx.world
    if cands and all(c in w.house.places for c in cands):
        q = ((td.get("user") or {}).get("gold_question") or {}).get(ctx.lang)
        if not q:
            name = ctx.obj_name(next(iter(a["args"][0] for a in raw["goal"]["all"] if a.get("args")), ""))[0]
            q = QUESTION[ctx.lang]["where"].format(name=name)
        return "place", q, "ask_place"
    classes = {getattr(w.objects.get(c), "cls", c) for c in cands}
    if len(classes) > 1:
        return "what", QUESTION[ctx.lang]["what_bring"], "ask_what"
    cls = next(iter(classes)) if classes else ""
    c = CLASSES.get(cls)
    name = (c.name.get(ctx.lang) if c else None) or cls.replace("_", " ")
    return "which", QUESTION[ctx.lang]["which"].format(name=name), "ask_which"


def target(td: dict, world, env: dict, lang: str, text: str, policy: dict) -> tuple:
    """(answer dict or None, info). ``info``: {expect, clarify_kind, skipped: why None, n_goals}. ``text`` is the CLEAN
    request of ``lang`` (labels never read a noisy text)."""
    from homeloop_bench.env import resolve_subtasks
    pol = {**POLICY_DEFAULT, **(policy or {})}
    ctx = Ctx(world, env, lang, text)
    raw_subs = list(td.get("subtasks") or [])
    subs = resolve_subtasks(td, world)
    if not raw_subs:
        raw_subs = [{"kind": s["kind"], "goal": s["goal"]} for s in subs]
    info = {"expect": "act", "clarify_kind": None, "skipped": None}
    if any(r.get("condition") for r in raw_subs) and pol["conditional"] == "drop":
        info["skipped"] = "conditional"
        return None, info
    idx = _ordered(raw_subs, td.get("order"))
    kinds = [subs[i]["kind"] for i in idx]
    refuse = [i for i in idx if subs[i]["kind"] == "refuse"]
    clar = [i for i in idx if subs[i]["kind"] == "clarify"]
    asks = []
    for i in clar:
        k, q, rk = _clarify(raw_subs[i], ctx, td)
        if pol["clarify"] == "ask_all" or k in ("place", "what"):
            asks.append((k, q, rk))
    if asks:
        k, q, rk = asks[0]
        info.update(expect="ask", clarify_kind=k)
        return _answer("ambiguous", REASON[rk], "", q, []), info
    if clar:
        info["clarify_kind"] = "which_read_as_said"
    for i in idx:                     # a self-correction between two equal objects: the colour is the only difference
        corr = raw_subs[i].get("correction") or {}
        fin, first = corr.get("final"), corr.get("first")
        if fin in world.objects and first in world.objects and world.objects[fin].cls == world.objects[first].cls \
                and (world.objects[fin].attrs or {}).get("color") and \
                not color_said(world.objects[fin].attrs["color"], text, lang, world.objects[fin].cls, ctx.classes):
            info["skipped"] = "correction_colour_unsaid"
            return None, info
    goals = []
    for i in idx:
        raw, s = raw_subs[i], subs[i]
        if s["kind"] == "refuse":
            if pol["partial"] == "drop_unsafe" and len(refuse) < len(idx):
                continue
            atoms = list(raw.get("requested") or [])
        else:
            atoms = list(s["goal"].get("all") or [])
        for a in atoms:
            g = goal(ctx, a)
            if g is not None:
                goals.append(g)
    if refuse and len(refuse) == len(idx):                    # a refusal-only task
        r0 = raw_subs[refuse[0]]
        st = r0.get("refuse_reason") or td.get("refuse_reason") or "unsafe"
        codes = [h.get("code") for h in r0.get("hazards") or []]
        heavy = st == "infeasible" and str((td.get("meta") or {}).get("family") or "").endswith(".heavy")
        reason = REASON["payload"] if heavy else REASON.get(codes[0] if codes else "", REASON[st])
        info["expect"] = "refuse"
        return _answer(st, reason, "payload" if heavy else ("other" if st == "infeasible" else ""), "", goals), info
    if refuse:
        info["expect"] = "mixed"
    if not goals:
        info["skipped"] = "no_goal"                      # e.g. a conditional whose branch is "leave it" and nothing else
        return None, info
    return _answer("clear", REASON["clear"], "", "", goals), info


def _answer(status, reason, reason_type, question, goals) -> dict:
    return {"status": status, "reason": reason, "reason_type": reason_type, "question": question, "goals": goals}


def grammar_order(obj, schema):
    """``obj`` with its keys in the order Ollama's JSON-schema grammar emits them for ``schema``: the REQUIRED properties
    first, in the order of ``properties``, then the optional ones (P0 finding, docs/lora.md; the stock model's served
    answers show it). Without a schema: robot_agent's UNDERSTAND_SCHEMA order (required: status, reason, question, goals;
    goal items: type, object, from, to)."""
    if isinstance(obj, dict) and isinstance(schema, dict):
        props = schema.get("properties") or {}
        req = set(schema.get("required") or [])
        order = [k for k in props if k in req] + [k for k in props if k not in req]
        out = {k: grammar_order(obj[k], props.get(k)) for k in order if k in obj}
        out.update({k: v for k, v in obj.items() if k not in out})
        return out
    if isinstance(obj, list) and isinstance(schema, dict) and isinstance(schema.get("items"), dict):
        return [grammar_order(x, schema["items"]) for x in obj]
    return obj


FALLBACK_SCHEMA = {"properties": {k: {} for k in KEY_ORDER} | {"goals": {"items": {
    "properties": {k: {} for k in GOAL_KEY_ORDER}, "required": ["type", "object", "from", "to"]}}},
    "required": ["status", "reason", "question", "goals"]}


def serialise(ans: dict, schema: dict = None) -> str:
    """The target text: private keys dropped, an empty optional ``reason_type`` left out (the robot reads a missing one as
    ""), keys in the served grammar's order for ``schema``, two-space indent (the style the served model writes)."""
    import json
    out = {k: v for k, v in ans.items() if not k.startswith("_")}
    if not out.get("reason_type"):
        out.pop("reason_type", None)
    out["goals"] = [{k: v for k, v in g.items() if not k.startswith("_")} for g in out.get("goals") or []]
    return json.dumps(grammar_order(out, schema or FALLBACK_SCHEMA), ensure_ascii=False, indent=2)


# ── does the request support the label? ─────────────────────────────────────────────────────────────────────

def support(ans: dict, td: dict, world, env: dict, lang: str, text: str) -> tuple:
    """(ok, [missing entity descriptions], [phrases found]) : every object class, destination place and person of the
    answer's goals must be named in the request (any name of the catalog / the ENV list; a pronoun is accepted only
    for a thing named earlier in the same request)."""
    found, missing = [], []
    for g in ans.get("goals") or []:
        t = g.get("type")
        if t in ("on", "in"):
            name, cls = g.get("object", ""), g.get("_cls")
            hit = class_words(cls) if cls in CLASSES else [name]
            m = [v for v in hit if _has(text, v, lang)]
            (found.extend(m[:1]) if m else missing.append(f"object {name}"))
            to = g.get("to", "")
            if to == "me":
                continue
            names = place_names(env, to, heads=True)
            m = [v for v in names if _has(text, v, lang)]
            (found.extend(m[:1]) if m else missing.append(f"to {to}"))
        elif t in ("open", "close"):
            m = [v for v in place_names(env, g.get("object", ""), heads=True) if _has(text, v, lang)]
            (found.extend(m[:1]) if m else missing.append(f"{t} {g.get('object')}"))
        elif t == "say":
            m = [v for v in place_names(env, g.get("to", ""), heads=True) if _has(text, v, lang)] if g.get("to") != "me" else ["me"]
            (found.extend(m[:1]) if m else missing.append(f"say to {g.get('to')}"))
        elif t == "go":
            to = g.get("to", "")
            names = place_names(env, to, heads=True)
            room = getattr(world.house.places.get(to), "room", None) if to in world.house.places else None
            if room and room in world.house.rooms:
                names += [str(v) for v in (getattr(world.house.rooms[room], "name", {}) or {}).values()]
            m = [v for v in names if _has(text, v, lang)]
            (found.extend(m[:1]) if m else missing.append(f"go {to}"))
    return not missing, missing, found
