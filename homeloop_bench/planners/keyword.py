"""The rule-based brain behind :class:`homeloop_bench.llm.FakeLLM` (tests and CI only).

It reads ONLY the prompt text a planner sends (the ``MODE:`` line, the instruction, the house / memory /
history lines of :func:`prompts.render_observation`) plus catalog common sense (object names, aliases,
tags, liftability), and answers in the format of that mode:

* ``inner_monologue`` / ``knowno_exec`` / ``repair``: the next tool call or a finish, as JSON;
* ``saycan``: the index of one listed option;
* ``progprompt``: a whole program;
* ``knowno_options`` / ``knowno_choice``: candidate interpretations / one letter.

It is a deterministic stand-in so the LLM planners' loops, parsers and the runner can be tested without
a model. Its numbers are never reported as a planner's results.
"""

from __future__ import annotations

import json
import re
import unicodedata

from homeloop_robot.catalog import CLASSES, COLORS, MESSAGE_TEXT, MESSAGES

# ── prompt parsing ─────────────────────────────────────────────────────────────────────────────────────

_LINE_RX = re.compile(r"^- (.*)$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    s = re.sub(r"[^\w\s@']", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _split_names(cell: str) -> dict:
    en, _, ko = cell.partition(" / ")
    return {"en": en.strip(), "ko": ko.strip()}


def _parse_args(s: str) -> dict:
    out = {}
    for m in re.finditer(r'(\w+)=("(?:[^"\\]|\\.)*"|[^,]+)(?:, |$)', s):
        k, v = m.group(1), m.group(2).strip()
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


_HIST_RX = re.compile(r"^(\d+)\. (\w+)\((.*?)\) -> (ok.*|FAILED (\w+): (.*))$")
_HIST_NR_RX = re.compile(r"^(\d+)\. (\w+)\((.*)\)$")


def parse_prompt(prompt: str) -> dict:
    """Sections of a prompt rendered by planners/prompts.py."""
    info = {"mode": "", "instruction": "", "lang": "en", "places": [], "people": [], "memory": [], "history": [],
            "events": [], "options": [], "interpretation": None, "declined": [], "robot_at": None,
            "holding_sensor": False, "choices": []}
    sec = None
    for raw in prompt.splitlines():
        line = raw.rstrip()
        if line.startswith("MODE:") and not info["mode"]:
            info["mode"] = line[5:].strip()
            continue
        m = re.match(r"^Instruction \((\w+)\): ?(.*)$", line)
        if m:
            info["lang"], info["instruction"] = m.group(1), m.group(2)
            sec = None
            continue
        if line.startswith("Places ("):
            sec = "places"; continue
        if line.startswith("People ("):
            sec = "people"; continue
        if line.startswith("People now ("):
            sec = "people_now"; continue
        if line.startswith("Object memory"):
            sec = "memory"; continue
        if line.startswith("User events:"):
            sec = "events"; continue
        if line.startswith("History:"):
            sec = "history"; continue
        if line.startswith("Options:"):
            sec = "options"; continue
        if line.startswith("Choices:"):
            sec = "choices"; continue
        if line.startswith("Interpretation:"):
            info["interpretation"] = line.split(":", 1)[1].strip(); sec = None; continue
        if line.startswith("Declined:"):
            info["declined"] = [x.strip() for x in line.split(":", 1)[1].split("|")]; sec = None; continue
        m = re.match(r"^Robot: at=(\S+) holding_sensor=(\w+)", line)
        if m:
            info["robot_at"] = None if m.group(1) == "none" else m.group(1)
            info["holding_sensor"] = m.group(2) == "yes"
            sec = None
            continue
        if sec == "places" and line.startswith("- "):
            c = [x.strip() for x in line[2:].split(" | ")]
            if len(c) >= 5:
                rm = re.match(r"^(\S+) \((.*)\)$", c[2])
                info["places"].append({"id": c[0], "name": _split_names(c[1]), "room": rm.group(1) if rm else c[2],
                                       "room_name": _split_names(rm.group(2)) if rm else {}, "kind": c[3],
                                       "openable": c[4] == "yes",
                                       "aliases": [] if len(c) < 6 or c[5] == "-" else [x.strip() for x in c[5].split(";")]})
        elif sec == "people" and line.startswith("- "):
            c = [x.strip() for x in line[2:].split(" | ")]
            info["people"].append({"id": c[0], "name": _split_names(c[1]), "usual": c[2] if len(c) > 2 else "",
                                   "role": c[3] if len(c) > 3 else "other"})
        elif sec == "memory" and line.startswith("- "):
            c = [x.strip() for x in line[2:].split(" | ")]
            attrs = {} if c[3] == "-" else dict(kv.split("=", 1) for kv in c[3].split(",") if "=" in kv)
            info["memory"].append({"id": c[0], "cls": c[1], "name": _split_names(c[2]), "attrs": attrs, "usual": c[4]})
        elif sec == "events" and line.startswith("- "):
            k, _, t = line[2:].partition(": ")
            try:
                t = json.loads(t)
            except ValueError:
                pass
            info["events"].append({"kind": k, "text": t})
        elif sec == "history":
            m = _HIST_RX.match(line)
            if m:
                ok = m.group(4).startswith("ok")
                rest = m.group(4)
                data = {}
                if ok:
                    for dm in re.finditer(r'(\w+)=("(?:[^"\\]|\\.)*"|\[[^\]]*\]|\S+)', rest[2:]):
                        v = dm.group(2)
                        try:
                            v = json.loads(v)
                        except ValueError:
                            pass
                        data[dm.group(1)] = v
                info["history"].append({"skill": m.group(2), "args": _parse_args(m.group(3)), "ok": ok,
                                        "code": None if ok else m.group(5), "msg": "" if ok else m.group(6),
                                        "data": data, "known": True})
                em = re.search(r"\[user (\w+): (\".*\")\]$", "" if ok else m.group(6))
                if em:
                    try:
                        info["events"].append({"kind": em.group(1), "text": json.loads(em.group(2))})
                    except ValueError:
                        pass
            else:
                m = _HIST_NR_RX.match(line)
                if m:
                    info["history"].append({"skill": m.group(2), "args": _parse_args(m.group(3)), "ok": True,
                                            "code": None, "msg": "", "data": {}, "known": False})
        elif sec == "options":
            m = re.match(r"^(\d+): (\w+)\((.*)\)$", line)
            if m:
                info["options"].append((int(m.group(1)), m.group(2), _parse_args(m.group(3))))
        elif sec == "choices":
            m = re.match(r"^([A-Z]): (.*)$", line)
            if m:
                info["choices"].append((m.group(1), m.group(2)))
    return info


# ── lexicons ───────────────────────────────────────────────────────────────────────────────────────────

def _obj_names(o: dict, lang: str) -> list:
    c = CLASSES.get(o["cls"])
    base = [o["name"].get(lang) or ""] + (list((c.aliases or {}).get(lang) or []) if c else [])
    base = [b for b in base if b]
    out = list(base)
    col = o["attrs"].get("color")
    if col in COLORS:
        out += [f"{COLORS[col][lang]} {b}" for b in base]
    return out


def _place_names(p: dict, lang: str) -> list:
    base = [p["name"].get(lang, "")] + [a for a in p.get("aliases") or [] if _is_lang(a, lang)]
    base = [b for b in base if b]
    rn = (p.get("room_name") or {}).get(lang, "")
    out = list(base)
    if rn and base:
        out += [f"{rn} {base[0]}", f"{rn}의 {base[0]}" if lang == "ko" else f"{base[0]} in the {rn}"]
    return out


def _is_lang(s: str, lang: str) -> bool:
    has_ko = bool(re.search(r"[가-힣]", s))
    return has_ko if lang == "ko" else not has_ko


def _person_names(p: dict, lang: str) -> list:
    return [x for x in [p["name"].get(lang, "")] if x]


ME = {"en": [r"\bme\b", r"\bmy\b", r"\bfor me\b"], "ko": ["저한테", "제게", "저에게", "나한테", "내게", "저 ", "제 "]}


def _find_all(text: str, names_by_id: dict, lang: str) -> list:
    """[(start, end, [ids])] for name mentions, longest match first, no overlaps."""
    t = _norm(text) if lang == "en" else _norm(text).replace(" ", "")
    cands = []
    for i, names in names_by_id.items():
        for n in names:
            nn = _norm(n) if lang == "en" else _norm(n).replace(" ", "")
            if not nn:
                continue
            if lang == "en":
                for m in re.finditer(r"(?<![\w])" + re.escape(nn) + r"s?(?![\w])", t):
                    cands.append((m.start(), m.end(), nn, i))
            else:
                start = t.find(nn)
                while start >= 0:
                    cands.append((start, start + len(nn), nn, i))
                    start = t.find(nn, start + 1)
    cands.sort(key=lambda x: (-(x[1] - x[0]), x[0], x[3]))
    taken, out = [], []
    for s, e, nn, i in cands:
        if any(not (e <= a or s >= b) for a, b, _ in taken):
            for k, (a, b, ids) in enumerate(taken):
                if a == s and b == e and i not in ids:
                    ids.append(i)
            continue
        taken.append((s, e, [i]))
    taken.sort()
    for a, b, ids in taken:
        out.append((a, b, sorted(ids)))
    return out


def _clauses(text: str, lang: str) -> list:
    if lang == "ko":
        parts = re.split(r"\s*(?:그리고|그다음에|그 다음에|다음에|고 나서|그러고 나서|, |\. )\s*", text)
    else:
        parts = re.split(r"\s*(?:,? and then |,? then |\. |; |, and |,? after that,? |,? also |"
                         r"\band (?=(?:please |also )?(?:put|place|bring|take|open|close|shut|tell|let|go|give|get|"
                         r"move|leave|hand|fetch|remind|say)\b))\s*", text, flags=re.I)
    return [p for p in parts if p and p.strip()]


EN_VERBS = [("open", r"\bopen\b"), ("close", r"\b(close|shut)\b"),
            ("tell", r"\b(tell|let \w+ know|remind|inform|say to|ask \w+ to)\b"),
            ("fetch", r"\b(bring|fetch|get me|hand|give)\b"),
            ("put", r"\b(put|place|move|take|leave|set|return|store|tidy|keep|throw)\b"),
            ("dock", r"\b(dock|charg)"), ("go", r"\b(go|drive|come|head)\b")]
KO_VERBS = [("open", "열어"), ("close", "닫아"), ("tell", "(전해|말해|알려|말씀|얘기해)"),
            ("fetch", "(가져다|갖다|가져와|갖다줘|건네)"), ("put", "(놓아|놔|올려|넣어|두어|둬|정리|치워|꺼내)"),
            ("dock", "충전"), ("go", "(가 줘|가 주|가세요|이동|가줘)")]

INFEASIBLE_EN = r"\b(cook|wash the dishes|vacuum|front door|mop|fold|iron)\b"
INFEASIBLE_KO = r"(요리|설거지|청소기|현관문|다림질)"


def _verb(clause: str, lang: str) -> str | None:
    t = clause.lower()
    for v, rx in (KO_VERBS if lang == "ko" else EN_VERBS):
        if re.search(rx, t):
            return v
    return None


def _message_key(clause: str, lang: str) -> str | None:
    t = clause.lower()
    for key in sorted(MESSAGES):
        for kws in MESSAGES[key].get(lang) or []:
            if all(k.lower() in t for k in kws):
                return key
    return None


def _child(p: dict) -> bool:
    n = (p["name"].get("en", "") + " " + p["id"]).lower()
    return bool(re.search(r"\b(child|son|daughter|kid|boy|girl)\b", n))


def _hazard(atom: tuple, info: dict) -> str | None:
    """Common-sense hazard check of one guessed atom (object tags x destination / receiver)."""
    pred, args = atom
    if pred not in ("on", "in", "delivered"):
        return None
    mem = {o["id"]: o for o in info["memory"]}
    o = mem.get(args[0])
    if o is None:
        return None
    c = CLASSES.get(o["cls"])
    tags = set(c.tags) if c else set()
    if c is not None and not c.liftable:
        return "too heavy or fixed for the robot"
    dst = args[1]
    if pred == "delivered":
        per = next((p for p in info["people"] if p["id"] == dst), None)
        if per and _child(per) and tags & {"sharp", "toxic", "medicine"}:
            return "unsafe to hand to a child"
        return None
    d = dst.split("@")[0]
    if "toxic" in tags and re.search(r"fridge|counter|stove|microwave|table|cupboard|dish", d):
        return "a toxic product near food"
    if "flammable" in tags and re.search(r"stove|oven|heater|cooktop|microwave", d):
        return "a flammable item on a heat source"
    if "liquid" in tags and re.search(r"tv|socket|power|router|computer|electr", d):
        return "a liquid on electrical equipment"
    if "metal" in tags and "microwave" in d:
        return "metal in the microwave"
    return None


def understand(text: str, lang: str, info: dict) -> dict:
    """Guess goal atoms from the instruction. -> {"atoms": [(pred, args)], "ambiguous": [(slot_index,
    [ids])], "refused": [reason], "unparsed": bool}"""
    mem = info["memory"]
    places = [p for p in info["places"] if p["kind"] != "floor"]
    obj_names = {o["id"]: _obj_names(o, lang) for o in mem}
    place_names = {p["id"]: _place_names(p, lang) for p in places}
    person_names = {p["id"]: _person_names(p, lang) for p in info["people"]}
    user = next((p["id"] for p in info["people"] if p["role"] == "user"), None)
    atoms, amb, refused = [], [], []
    if re.search(INFEASIBLE_KO if lang == "ko" else INFEASIBLE_EN, text.lower()):
        refused.append("not a skill this robot has")
    for clause in _clauses(text, lang):
        v = _verb(clause, lang)
        objs = _find_all(clause, obj_names, lang)
        pls = _find_all(clause, place_names, lang)
        # a place name inside an object name (or the reverse) keeps the longer one
        pls = [p for p in pls if not any(o[0] <= p[0] and p[1] <= o[1] and (o[1] - o[0]) > (p[1] - p[0]) for o in objs)]
        objs = [o for o in objs if not any(p[0] <= o[0] and o[1] <= p[1] and (p[1] - p[0]) > (o[1] - o[0]) for p in pls)]
        ppl = _find_all(clause, person_names, lang)
        me = any(re.search(rx, clause.lower()) if lang == "en" else rx in clause for rx in ME[lang])
        person = ppl[0][2][0] if ppl else (user if me else None)
        msg = _message_key(clause, lang)

        def obj_slot():
            if not objs:
                return None
            ids = objs[0][2]
            if len(ids) > 1:
                amb.append((len(atoms), ids))
            return ids[0]
        if v in ("open", "close") and pls:
            pid = pls[-1][2][0]
            atoms.append(("open" if v == "open" else "closed", [pid]))
        elif v == "tell" or (msg and ppl and not objs):
            if msg:
                for p in (ppl or [(0, 0, [person])]):
                    if p[2][0]:
                        atoms.append(("said_to", [p[2][0], msg]))
        elif v == "fetch" or (objs and person and not pls):
            o = obj_slot()
            if o and (person or user):
                atoms.append(("delivered", [o, person or user]))
        elif objs and pls:
            o = obj_slot()
            pid = pls[-1][2][0]
            pk = next(p for p in places if p["id"] == pid)
            into = pk["kind"] == "container" or bool(re.search(r"\b(in|into|inside)\b", clause.lower())) \
                or bool(re.search(r"(넣어|안에)", clause))
            atoms.append(("in" if (into and pk["kind"] == "container") else "on", [o, pid]))
        elif v == "dock":
            atoms.append(("docked", []))
        elif v == "go" and pls:
            atoms.append(("robot_at", [pls[-1][2][0]]))
    for a in atoms:
        h = _hazard(a, info)
        if h:
            refused.append(f"{h} ({a[1][0]})" if a[1] else h)
    safe = [a for a in atoms if not _hazard(a, info)]
    return {"atoms": safe, "all_atoms": atoms, "ambiguous": amb, "refused": refused,
            "unparsed": not atoms and not refused}


# ── belief and next action ────────────────────────────────────────────────────────────────────────────

class Belief:
    def __init__(self, info: dict):
        self.info = info
        self.at = None
        self.near = None                 # person id after a move to a person
        self.holding = None
        self.found = {}
        self.opened = set()
        self.searched = {}
        self.placed = {}
        self.handed = {}
        self.said = set()
        self.docked = False
        self.visited = set()
        self.fails = {}
        self.last = None
        self.answers = []
        self.asked = 0
        self.places = {p["id"]: p for p in info["places"]}
        self.people = {p["id"] for p in info["people"]}

    def key(self, skill, args):
        where = f"@{self.at or self.near}" if skill in ("find", "pick", "open", "close", "place", "put_in") else ""
        return skill + json.dumps(args, sort_keys=True, ensure_ascii=False) + where

    def update(self, skill, args, ok, code=None, data=None):
        data = data or {}
        k = self.key(skill, args)
        self.last = (skill, args, ok, code)
        if skill == "ask":
            self.asked += 1
            if ok:
                self.answers.append(str(data.get("answer", "")))
        if not ok:
            self.fails[k] = self.fails.get(k, 0) + 1
            if skill == "find" and code == "absent":
                self.searched.setdefault(args.get("obj"), set()).add(self.at)
                self.found.pop(args.get("obj"), None)
            if skill == "pick" and code == "absent":
                self.found.pop(args.get("obj"), None)
            if code == "dropped":
                self.holding = None
            return
        self.fails.pop(k, None)
        if skill == "move":
            t = args.get("target")
            if t in self.people:
                self.near, self.at = t, None
            else:
                self.at, self.near = t, None
                self.visited.add(t)
            self.docked = False
        elif skill == "find":
            f = data.get("found") or args.get("obj")
            self.found[f] = self.at
        elif skill == "pick":
            self.holding = args.get("obj")
            self.found.pop(args.get("obj"), None)
        elif skill in ("place", "put_in"):
            if self.holding:
                self.placed[self.holding] = (args.get("target") or args.get("container"), skill == "put_in")
            self.holding = None
        elif skill == "handover":
            if self.holding:
                self.handed[self.holding] = args.get("person") or self.near
            self.holding = None
        elif skill == "open":
            self.opened.add(args.get("container"))
        elif skill == "close":
            self.opened.discard(args.get("container"))
        elif skill in ("say", "announce"):
            for key in sorted(MESSAGES):
                if _message_key(args.get("text", ""), args.get("lang", "en")) == key and self.near:
                    self.said.add((self.near, key))
        elif skill == "dock":
            self.docked = True

    def done(self, atom) -> bool:
        p, a = atom
        if p in ("on", "in"):
            return self.placed.get(a[0], (None,))[0] == a[1] and self.holding != a[0]
        if p == "delivered":
            return self.handed.get(a[0]) == a[1]
        if p == "said_to":
            return tuple(a) in self.said
        if p == "open":
            return a[0] in self.opened
        if p == "closed":
            return a[0] not in self.opened
        if p == "robot_at":
            return a[0] in self.visited
        if p == "docked":
            return self.docked
        return True


def _say_text(key, lang):
    return (MESSAGE_TEXT.get(key) or {}).get(lang) or key.replace("_", " ")


def _sources(b: Belief, oid: str) -> list:
    mem = {o["id"]: o for o in b.info["memory"]}
    seen = b.searched.get(oid, set())
    usual = mem.get(oid, {}).get("usual")
    order = [usual] if usual else []
    order += sorted(p["id"] for p in b.info["places"] if p["kind"] in ("container", "surface", "seat", "floor"))
    out = []
    for p in order:
        if p and p not in seen and p not in out:
            out.append(p)
    return out


def next_call(b: Belief, atoms: list, lang: str):
    """The next (skill, args) toward ``atoms`` from belief ``b``; ("finish", status) when done / stuck."""
    if b.last and not b.last[2]:
        skill, args, _ok, code = b.last
        if b.fails.get(b.key(skill, args), 0) >= 3 or code in ("hw_fault", "estop"):
            return ("finish", "give_up")
        if code in ("perception_unavailable", "blocked") and skill != "wait":
            return ("wait", {"seconds": 5})
        if code == "timeout" and skill == "handover":
            return ("handover", dict(args))
    for atom in atoms:
        if b.done(atom):
            continue
        p, a = atom
        if p in ("open", "closed"):
            c = a[0]
            if b.holding:
                return _stow(b)
            if b.at != c:
                return ("move", {"target": c})
            return ("open" if p == "open" else "close", {"container": c})
        if p == "robot_at":
            return ("move", {"target": a[0]})
        if p == "docked":
            dock = next((x["id"] for x in b.info["places"] if x["kind"] == "dock"), "dock")
            if b.at != dock:
                return ("move", {"target": dock})
            return ("dock", {})
        if p == "said_to":
            if b.near != a[0]:
                return ("move", {"target": a[0]})
            return ("say", {"text": _say_text(a[1], lang), "lang": lang})
        o = a[0]
        if b.holding not in (None, o):
            return _stow(b)
        if p == "in" and a[1] not in b.opened and b.places.get(a[1], {}).get("openable"):
            if b.holding == o:
                # hand full: put it down here first, then open
                return _stow(b)
            if b.at != a[1]:
                return ("move", {"target": a[1]})
            return ("open", {"container": a[1]})
        if b.holding == o:
            dst = a[1]
            if p == "delivered":
                if b.near != dst:
                    return ("move", {"target": dst})
                return ("handover", {"person": dst})
            if b.at != dst:
                return ("move", {"target": dst})
            return ("put_in" if p == "in" else "place", {"container": dst} if p == "in" else {"target": dst})
        here = b.found.get(o)
        if here is not None and here == b.at:
            return ("pick", {"obj": o})
        srcs = _sources(b, o)
        if not srcs:
            return ("finish", "give_up")
        src = srcs[0]
        if b.at != src:
            return ("move", {"target": src})
        if b.places.get(src, {}).get("openable") and src not in b.opened:
            return ("open", {"container": src})
        return ("find", {"obj": o})
    return ("finish", "done")


def _stow(b: Belief):
    if b.at:
        pl = b.places.get(b.at, {})
        if pl.get("kind") == "container":
            return ("put_in", {"container": b.at}) if b.at in b.opened or not pl.get("openable") else ("open", {"container": b.at})
        return ("place", {"target": b.at})
    mem = {o["id"]: o for o in b.info["memory"]}
    return ("move", {"target": mem.get(b.holding, {}).get("usual") or sorted(b.places)[0]})


# ── disambiguation ─────────────────────────────────────────────────────────────────────────────────────

def _pick_candidate(ids: list, answers: list, info: dict, lang: str) -> str:
    mem = {o["id"]: o for o in info["memory"]}
    for ans in reversed(answers):
        a = _norm(ans)
        for i in ids:
            o = mem.get(i)
            col = (o or {}).get("attrs", {}).get("color")
            if col in COLORS and _norm(COLORS[col][lang]) in a:
                return i
        if re.search(r"\b(other|second|another)\b", a) or re.search(r"(다른|두 번째|두번째)", ans):
            return ids[1] if len(ids) > 1 else ids[0]
        if re.search(r"\b(first)\b", a) or "첫" in ans:
            return ids[0]
    return ids[0]


def question_for(ids: list, info: dict, lang: str) -> str:
    mem = {o["id"]: o for o in info["memory"]}
    o = mem.get(ids[0], {"name": {"en": "one", "ko": "것"}})
    if lang == "ko":
        return f"어느 {o['name'].get('ko', '')} 말씀이세요?"
    return f"Which {o['name'].get('en', 'one')} do you mean?"


def apply_events(atoms: list, info: dict, lang: str) -> list:
    """A correction event ("not that one, the other one") swaps the object of the first object atom."""
    for e in info["events"]:
        if e["kind"] != "correction":
            continue
        txt = str(e["text"])
        mem = {o["id"]: o for o in info["memory"]}
        named = _find_all(txt, {o["id"]: _obj_names(o, lang) for o in info["memory"]}, lang)
        out = []
        swapped = False
        for p, a in atoms:
            if not swapped and p in ("on", "in", "delivered"):
                o = a[0]
                cls = mem.get(o, {}).get("cls")
                new = None
                cand = [x for n in named for x in n[2] if x != o]
                if cand:
                    new = cand[-1]
                elif re.search(r"\b(other|another)\b", txt.lower()) or "다른" in txt:
                    same = sorted(x for x, m in mem.items() if m["cls"] == cls and x != o)
                    new = same[0] if same else None
                if new:
                    a = [new] + list(a[1:])
                    swapped = True
            out.append((p, a))
        atoms = out
    return atoms


def goal_atoms_from_string(s: str) -> list:
    from homeloop_robot import goals as G
    try:
        g = G.parse(s)
    except Exception:  # noqa: BLE001 - an unparsable interpretation -> nothing
        return []
    return [("delivered" if a["pred"] == "held_by" else a["pred"], list(a.get("args") or [])) for a in g.get("all") or []
            if "pred" in a]


def plan_state(info: dict) -> tuple:
    """(atoms, belief, meta) after replaying the history of the prompt."""
    lang = info["lang"]
    b = Belief(info)
    b.at = info["robot_at"]
    for h in info["history"]:
        b.update(h["skill"], h["args"], h["ok"], h["code"], h["data"])
    if info.get("interpretation"):
        u = {"atoms": goal_atoms_from_string(info["interpretation"]), "ambiguous": [], "refused": [], "unparsed": False}
        u["all_atoms"] = list(u["atoms"])
    else:
        u = understand(info["instruction"], lang, info)
    atoms = list(u["atoms"])
    for idx, ids in u["ambiguous"]:
        if idx < len(atoms):
            pick = _pick_candidate(ids, b.answers, info, lang)
            p, a = atoms[idx]
            atoms[idx] = (p, [pick] + list(a[1:]))
    atoms = apply_events(atoms, info, lang)
    return atoms, b, u


# ── answers per mode ───────────────────────────────────────────────────────────────────────────────────

def _step_answer(info: dict, may_ask: bool = True, may_decline: bool = True) -> dict:
    lang = info["lang"]
    if any(e["kind"] == "stop" for e in info["events"]):
        return {"thought": "the user said stop", "finish": "done", "say": "OK, stopping."}
    atoms, b, u = plan_state(info)
    if u["refused"] and not atoms:
        return {"thought": "unsafe or impossible", "finish": "refuse", "say": "I can't do that: " + u["refused"][0]}
    if u["unparsed"]:
        return {"thought": "I do not understand the request", "finish": "refuse", "say": "I can't do that."}
    if may_decline and u["refused"] and not info["declined"]:
        return {"thought": "decline the unsafe part", "action": {"skill": "decline", "args": {"reason": u["refused"][0]}}}
    if may_ask and u["ambiguous"] and b.asked == 0:
        return {"thought": "ambiguous", "action": {"skill": "ask", "args": {
            "question": question_for(u["ambiguous"][0][1], info, lang), "lang": lang}}}
    c = next_call(b, atoms, lang)
    if c[0] == "finish":
        return {"thought": "finished" if c[1] == "done" else "stuck", "finish": c[1], "say": ""}
    return {"thought": "next step", "action": {"skill": c[0], "args": c[1]}}


def _saycan_answer(info: dict) -> dict:
    a = _step_answer(info, may_ask=False, may_decline=False)
    opts = info["options"]
    if "action" in a:
        want = (a["action"]["skill"], a["action"]["args"])
        for i, s, args in opts:
            if s == want[0] and all(args.get(k) == v for k, v in want[1].items() if k != "lang"):
                return {"choice": i}
    want_fin = a.get("finish", "give_up")
    for i, s, args in opts:
        if s == "finish" and args.get("status") == want_fin:
            return {"choice": i}
    for i, s, args in opts:
        if s == "finish" and args.get("status") == "give_up":
            return {"choice": i}
    return {"choice": opts[0][0] if opts else 0}


def _program_answer(info: dict) -> str:
    lang = info["lang"]
    atoms, b, u = plan_state(info)
    if (u["refused"] and not atoms) or u["unparsed"]:
        return 'finish("refuse")'
    lines = []
    if u["refused"]:
        lines.append(f'decline({json.dumps(u["refused"][0], ensure_ascii=False)})')
    for _ in range(80):
        c = next_call(b, atoms, lang)
        if c[0] == "finish":
            break
        skill, args = c
        argv = ", ".join(json.dumps(args[k], ensure_ascii=False) for k in ("target", "obj", "container", "person",
                                                                           "text", "lang", "seconds") if k in args)
        lines.append(f"{skill}({argv})")
        if skill == "pick":
            lines.append(f'assert holding({json.dumps(args["obj"])}) else: pick({json.dumps(args["obj"])})')
        if skill == "find":
            b.update("find", args, True, None, {"found": args["obj"]})
        else:
            b.update(skill, args, True)
    lines.append('finish("done")')
    return "\n".join(lines)


def _options_answer(info: dict) -> dict:
    from homeloop_robot import goals as G
    atoms, b, u = plan_state(info)
    if u["refused"] and not atoms:
        return {"options": ["refuse"]}
    if not atoms:
        return {"options": ["refuse"]}

    def fmt(ats):
        return G.format({"all": [{"pred": p, "args": list(a)} for p, a in ats]})
    opts = []
    if u["ambiguous"]:
        idx, ids = u["ambiguous"][0]
        for i in ids[:4]:
            ats = list(atoms)
            p, a = ats[idx]
            ats[idx] = (p, [i] + list(a[1:]))
            opts.append(fmt(ats))
    else:
        opts.append(fmt(atoms))
    return {"options": opts[:4]}


def _choice_answer(info: dict, seed: int) -> dict:
    ch = info["choices"]
    if not ch:
        return {"choice": "A"}
    real = [c for c in ch if not c[1].lower().startswith("none")]
    amb = understand(info["instruction"], info["lang"], info)["ambiguous"]
    if amb and len(real) > 1:
        return {"choice": real[seed % len(real)][0]}
    return {"choice": real[0][0] if real else ch[0][0]}


def answer(prompt: str, temperature: float = 0.0, seed: int = 0) -> str:
    info = parse_prompt(prompt)
    mode = info["mode"]
    if mode == "repair":
        marker = "Answer again, JSON only.\n\n"
        inner = prompt.split(marker, 1)[1] if marker in prompt else prompt
        return answer(inner, temperature, seed)
    if mode == "saycan":
        out = _saycan_answer(info)
    elif mode == "progprompt":
        return _program_answer(info)
    elif mode == "knowno_options":
        out = _options_answer(info)
    elif mode == "knowno_choice":
        out = _choice_answer(info, seed)
    else:
        out = _step_answer(info, may_ask=mode != "knowno_exec")
    return json.dumps(out, ensure_ascii=False, sort_keys=True)
