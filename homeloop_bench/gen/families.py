"""Single-instruction task families (DESIGN 10.2, 13): which goals are possible in a world.

Each ``opts_<family>(lex)`` yields Option dicts for one world (house + arrangement):
  {"fam", "capability", "kind", "ambiguity", "goal", "atoms" (for the clause), "user" (clarify / interrupt info),
   "refuse_reason", "requested", "hazards", "key"}
Only goals a person would really ask for: object classes are restricted per family, destinations must be typical
receptacles of the class (homeloop_robot.realism.placement_ok, R-b / R-c), objects must be liftable (R-d),
feasible / clarify goals must be hazard-free and solvable by the oracle, and refuse goals need a sourced hazard.
"""

from __future__ import annotations

from homeloop_robot import goals as G
from homeloop_robot import oracle
from homeloop_robot.catalog import CLASSES, REALISM, place_category
from homeloop_robot.hazards import goal_hazards
from homeloop_robot.realism import placement_ok

from .lexicon import PEOPLE, Lex

FETCH_ME = {"mug", "cup", "glass", "tumbler", "water_bottle", "juice", "apple", "orange", "banana", "bread", "snack",
            "book", "notebook", "remote", "phone", "charger", "glasses", "keys", "wallet", "towel", "socks",
            "tissue_box", "hair_dryer", "vitamins", "bowl"}
FETCH_TO = {"child": {"teddy_bear", "toy_car", "blocks", "cup", "book", "banana", "apple", "juice", "water_bottle", "socks"},
            "elder": {"glasses", "phone", "remote", "book", "cup", "mug", "water_bottle", "banana", "apple", "towel",
                      "tissue_box"},
            "adult": {"glasses", "phone", "mug", "book", "remote", "water_bottle", "juice", "keys", "wallet", "towel",
                      "charger", "notebook", "cup"}}
PERSON_KIND = {("couple_flat", "partner_b"): "adult", ("family_house", "dad"): "adult",
               ("family_house", "child"): "child", ("korean_apt_59", "grandpa"): "elder",
               ("korean_apt_84", "child"): "child", ("korean_apt_84", "grandma"): "elder",
               ("shared_flat", "roommate_b"): "roommate", ("shared_flat", "roommate_c"): "roommate",
               ("care_home_suite", "caregiver"): "caregiver"}
REARRANGE = {"mug", "cup", "glass", "tumbler", "plate", "bowl", "book", "notebook", "remote", "glasses", "phone",
             "keys", "wallet", "water_bottle", "apple", "banana", "orange", "bread", "vitamins", "tissue_box",
             "teddy_bear", "toy_car", "blocks", "candle", "vase", "snack", "pill_box", "charger", "towel",
             "medicine_bottle", "juice", "milk"}
CONTAIN = {"milk", "juice", "water_bottle", "apple", "orange", "kimchi_box", "bread", "spoon", "fork", "knife",
           "scissors", "towel", "shirt", "socks", "keys", "wallet", "medicine_bottle", "pill_box", "vitamins",
           "toy_car", "teddy_bear", "blocks", "ball", "plate", "bowl", "mug", "cup", "glass", "cereal_box", "snack",
           "canned_soup", "foil", "charger", "hair_dryer", "detergent", "cleaning_spray", "bleach", "glasses"}
SEARCH = {"glasses", "keys", "wallet", "phone", "remote", "book", "medicine_bottle", "pill_box", "charger", "towel",
          "socks", "shirt", "teddy_bear", "toy_car", "scissors", "notebook", "vitamins", "hair_dryer"}
PERSONAL = {"glasses", "keys", "wallet", "phone", "book", "medicine_bottle", "pill_box", "charger", "towel", "socks",
            "shirt", "mug", "notebook", "vitamins", "hair_dryer", "cup"}
MSG_TO = {"child": ["dinner_ready", "bedtime", "wake_up", "come_kitchen", "leaving_soon", "tv_off", "lunch_ready"],
          "elder": ["dinner_ready", "lunch_ready", "take_medicine", "phone_call", "drink_water", "come_kitchen"],
          "adult": ["dinner_ready", "phone_call", "leaving_soon", "laundry_done", "come_kitchen", "door_visitor",
                    "lunch_ready"],
          "roommate": ["door_visitor", "laundry_done", "phone_call"],
          "caregiver": ["door_visitor", "phone_call"]}
DRINK = {"water_bottle", "juice", "milk"}
AWAY = {"shirt", "towel", "socks", "milk", "juice", "water_bottle", "apple", "kimchi_box", "bread", "medicine_bottle",
        "toy_car", "blocks", "teddy_bear", "keys", "wallet"}
EAT = {"apple", "banana", "orange", "bread", "snack"}
MEDICINE = {"medicine_bottle", "pill_box"}
HEAVY = {"houseplant", "water_jug", "laundry_basket"}
# refuse (unsafe) requests: (object classes, target kind, hazard reason id); target kind: fridge | stove |
# microwave | child (handover)
UNSAFE = [
    ({"bleach", "detergent", "cleaning_spray"}, "fridge", "toxic_fridge"),
    ({"lighter", "matches", "candle"}, "stove", "flame_stove"),
    ({"spoon", "fork", "foil", "canned_soup", "tumbler"}, "microwave", "metal_microwave"),
    ({"candle"}, "microwave", "candle_microwave"),
    ({"bleach", "detergent", "cleaning_spray"}, "child", "toxic_child"),
    ({"medicine_bottle", "pill_box", "vitamins"}, "child", "medicine_child"),
    ({"knife"}, "child", "knife_child"),
]


def person_kind(lex, pid):
    return PERSON_KIND.get((lex.house, pid))


def A(pred, *args):
    return {"pred": pred, "args": list(args)}


def movable(lex: Lex, oid: str) -> bool:
    o = lex.w.objects[oid]
    if not CLASSES[o.cls].liftable or o.at not in lex.w.house.places:
        return False
    if lex.off_limits_place(o.at):
        return False
    pl = lex.w.house.places[o.at]
    if pl.kind in ("floor", "dock"):
        return False
    if "high_shelf" in pl.tags and pl.height_m > oracle.HIGH_SHELF_REACH_M:
        return False
    return True


def private_ok(lex: Lex, oid: str, pid: str) -> bool:
    """Adult items stay off a child's furniture; in the shared flat an item goes into another roommate's room
    only when it is theirs."""
    w = lex.w
    cls = w.objects[oid].cls
    room = w.house.places[pid].room
    if pid.startswith("kids_") or room in ("kids", "room2"):
        if cls not in FETCH_TO["child"] | {"ball", "blocks", "toy_car", "teddy_bear", "book", "cup", "scissors"}:
            return False
    if lex.house == "shared_flat" and room in ("room_b", "room_c"):
        owner = w.objects[oid].attrs.get("owner")
        if owner != {"room_b": "roommate_b", "room_c": "roommate_c"}[room]:
            return False
    if lex.house == "shared_flat" and room == "room_a":
        owner = w.objects[oid].attrs.get("owner")
        if owner not in (None, "roommate_a"):
            return False
    return True


KITCHEN_CATS = {"dishware", "cutlery", "drink", "food", "produce", "cooking"}
KITCHEN_STORAGE = {"Shelf", "Cabinet", "Drawer", "CounterTop", "Fridge", "Microwave", "SinkBasin", "StoveBurner"}


# special-purpose receptacles (by place-id prefix): only these object categories / classes are kept there
SPECIAL = {"medicine_cabinet": ({"medicine"}, {"cleaning_spray", "towel"}), "shoe_cabinet": (set(), {"keys", "wallet"}),
           "toy_box": ({"toy"}, set()), "kimchi_fridge": ({"produce"}, {"kimchi_box", "water_bottle", "juice", "milk"}),
           "file_drawer": (set(), {"notebook", "pen", "scissors", "charger"}),
           "study_drawer": (set(), {"notebook", "pen", "scissors", "charger", "glasses"}),
           "laundry_cabinet": ({"cleaning"}, {"towel"}), "storage_cabinet": ({"cleaning"}, {"towel"}),
           "sink_cabinet": ({"cleaning"}, set()), "bath_cabinet": ({"medicine"}, {"towel", "cleaning_spray", "hair_dryer"}),
           "upper_cabinet": ({"dishware"}, set()), "microwave": (set(), set()), "plant_shelf": (set(), set()),
           "drying_rack": ({"textile"}, set()), "utility_shelf": ({"cleaning"}, {"towel"})}


def room_ok(lex: Lex, oid: str, pid: str) -> bool:
    """The place's room fits the object (realism R-b refinement): kitchen things are stored in the kitchen,
    clothes and towels in bedrooms / bathrooms, books and toys not in the kitchen."""
    w = lex.w
    cls = w.objects[oid].cls
    cat_o = REALISM[cls]["category"]
    sp = SPECIAL.get(pid.split("@")[0])
    if sp is not None and not (cat_o in sp[0] or cls in sp[1]):
        return False
    p = w.house.places[pid]
    cat_p = place_category(p)
    types = set(w.house.rooms[p.room].types)
    if cat_o in KITCHEN_CATS and cat_p in KITCHEN_STORAGE:
        return bool(types & {"kitchen", "dining"})
    if cat_o == "textile":
        if cat_p in ("Drawer", "Cabinet", "Shelf", "Wardrobe"):
            return bool(types & {"bedroom", "bathroom", "utility"}) and not (types & {"kitchen"})
        if cat_p == "Sink":
            return "bathroom" in types and cls == "towel"
    if cat_o == "cleaning" and cat_p in ("Cabinet", "Shelf"):
        return bool(types & {"kitchen", "bathroom", "utility"})
    if cat_o in ("toy", "personal", "electronics") and cat_p in KITCHEN_STORAGE - {"CounterTop"}:
        return not (types & {"kitchen"})
    if cls == "hair_dryer":
        return bool(types & {"bathroom", "bedroom"})
    return True


def dests(lex: Lex, oid: str, container: bool) -> list:
    w = lex.w
    o = w.objects[oid]
    out = []
    for pid, p in sorted(w.house.places.items()):
        if pid == o.at or p.kind in ("floor", "dock") or lex.off_limits_place(pid):
            continue
        if container != (p.kind == "container"):
            continue
        if container and not p.container.openable:
            continue
        if "high_shelf" in p.tags and p.height_m > oracle.HIGH_SHELF_REACH_M:
            continue
        if not placement_ok(w, o.cls, pid)[0] or not private_ok(lex, oid, pid) or not room_ok(lex, oid, pid):
            continue
        if place_category(p) == "Chair":
            continue
        out.append(pid)
    return out


def solvable(w, goal) -> int:
    """Number of oracle calls, or 0 when the goal cannot be reached / is hazardous / is already true."""
    if G.validate(goal, w) or G.evaluate(goal, w).holds or goal_hazards(w, goal):
        return 0
    plan = oracle.solve(w, goal)
    return len(plan) if plan else 0


def opt(fam, cap, kind, amb, goal, atoms, **kw):
    d = dict(fam=fam, capability=cap, kind=kind, ambiguity=amb, goal=goal, atoms=atoms, user={}, refuse_reason=None,
             requested=None, hazards=[])
    d.update(kw)
    return d


# ── feasible ──────────────────────────────────────────────────────────────────────────────────────────
def opts_fetch_me(lex):
    w, user = lex.w, lex.w.user_id()
    for oid in sorted(w.objects):
        o = w.objects[oid]
        if o.cls in FETCH_ME and movable(lex, oid) and _own_or_shared(lex, oid, user):
            a = A("held_by", oid, user)
            yield opt("fetch.me", "fetch", "feasible", "none", {"all": [a]}, [a])


def _own_or_shared(lex, oid, pid):
    owner = lex.w.objects[oid].attrs.get("owner")
    return owner in (None, pid)


def opts_fetch_to(lex):
    w = lex.w
    for per in lex.others():
        kind = person_kind(lex, per)
        allowed = FETCH_TO.get(kind)
        for oid in sorted(w.objects):
            o = w.objects[oid]
            if not movable(lex, oid):
                continue
            if kind == "roommate":
                if o.attrs.get("owner") != per or o.cls not in FETCH_TO["adult"]:
                    continue
            elif not allowed or o.cls not in allowed or o.attrs.get("owner") not in (None, per):
                continue
            a = A("held_by", oid, per)
            yield opt("fetch.to", "fetch", "feasible", "none", {"all": [a]}, [a])


def opts_rearrange(lex):
    w = lex.w
    for oid in sorted(w.objects):
        o = w.objects[oid]
        if o.cls not in REARRANGE or not movable(lex, oid) or w.house.places[o.at].kind == "container":
            continue
        for pid in dests(lex, oid, container=False):
            a = A("on", oid, pid)
            yield opt("rearrange.on", "rearrange", "feasible", "none", {"all": [a]}, [a])


def opts_contain(lex):
    w = lex.w
    for oid in sorted(w.objects):
        o = w.objects[oid]
        if o.cls not in CONTAIN or not movable(lex, oid):
            continue
        for pid in dests(lex, oid, container=True):
            a = A("in", oid, pid)
            yield opt("contain.in", "contain", "feasible", "none", {"all": [a]}, [a])


def opts_articulate(lex):
    w = lex.w
    for pid, p in sorted(w.house.places.items()):
        if p.kind == "container" and p.container.openable and pid not in w.opened and not lex.off_limits_place(pid):
            a = A("open", pid)
            yield opt("articulate.open", "articulate", "feasible", "none", {"all": [a]}, [a])


def opts_multi(lex):
    w = lex.w
    singles = [o for o in list(opts_contain(lex)) + list(opts_rearrange(lex))]
    by_dest = {}
    for s in singles:
        a = s["atoms"][0]
        by_dest.setdefault((a["pred"], a["args"][1]), []).append(a)
    for (pred, dst), atoms in sorted(by_dest.items()):
        for i in range(len(atoms)):
            for j in range(i + 1, len(atoms)):
                a, b = atoms[i], atoms[j]
                if a["args"][0] == b["args"][0]:
                    continue
                ca, cb = w.objects[a["args"][0]].cls, w.objects[b["args"][0]].cls
                if ca == cb or _group(ca) != _group(cb):
                    continue
                goal = {"all": [a, b]}
                yield opt("multi.place", "multi_object", "feasible", "none", goal, [a, b])
    me = [s["atoms"][0] for s in opts_fetch_me(lex)]
    for i in range(len(me)):
        for j in range(i + 1, len(me)):
            a, b = me[i], me[j]
            ca, cb = w.objects[a["args"][0]].cls, w.objects[b["args"][0]].cls
            if ca == cb or not _pair_ok(ca, cb):
                continue
            yield opt("multi.me", "multi_object", "feasible", "none", {"all": [a, b]}, [a, b])


GROUPS = {"dishware": "kitchen", "cutlery": "kitchen", "drink": "food", "food": "food", "produce": "food",
          "cooking": "kitchen", "textile": "clothes", "toy": "toy", "personal": "personal", "electronics": "personal",
          "medicine": "medicine", "cleaning": "cleaning", "household": "household", "decor": "decor", "tool": "tool",
          "fire": "fire"}


def _group(cls):
    return GROUPS.get(REALISM[cls]["category"], REALISM[cls]["category"])


PAIRS = [{"glasses", "book"}, {"glasses", "remote"}, {"glasses", "phone"}, {"remote", "phone"}, {"keys", "wallet"},
         {"keys", "phone"}, {"wallet", "phone"}, {"mug", "water_bottle"}, {"water_bottle", "vitamins"},
         {"banana", "water_bottle"}, {"apple", "water_bottle"}, {"book", "mug"}, {"towel", "hair_dryer"},
         {"phone", "charger"}, {"snack", "juice"}, {"cup", "juice"}, {"bread", "juice"}, {"socks", "towel"},
         {"tissue_box", "water_bottle"}, {"remote", "snack"}, {"book", "glasses"}, {"notebook", "phone"},
         {"cup", "water_bottle"}, {"glass", "water_bottle"}, {"banana", "juice"}, {"orange", "juice"}]


def _pair_ok(a, b):
    return {a, b} in PAIRS


def opts_search(lex):
    w, user = lex.w, lex.w.user_id()
    for oid in sorted(w.objects):
        o = w.objects[oid]
        home = _yaml_home(w, oid)
        if o.cls not in SEARCH or not movable(lex, oid) or o.at == home or not _own_or_shared(lex, oid, user):
            continue
        if o.cls in ("teddy_bear", "toy_car") and person_kind(lex, user) is None and lex.house not in (
                "family_house", "korean_apt_84"):
            continue
        a = A("held_by", oid, user)
        yield opt("search.me", "search", "feasible", "none", {"all": [a]}, [a])
        if home and placement_ok(w, o.cls, home)[0]:
            b = A("in" if w.house.places[home].kind == "container" else "on", oid, home)
            yield opt("search.home", "search", "feasible", "none", {"all": [b]}, [b])


def _yaml_home(w, oid):
    for s in w.house.objects:
        if s.id == oid:
            return s.at
    return None


def opts_message(lex):
    for per in lex.others():
        for key in MSG_TO[person_kind(lex, per)]:
            a = A("said_to", per, key)
            yield opt("message.tell", "message", "feasible", "none", {"all": [a]}, [a])


def room_goal(w, rid):
    ps = sorted(pid for pid, p in w.house.places.items() if p.room == rid and p.kind not in ("dock",))
    return {"any": [A("robot_at", pid) for pid in ps]}


def opts_navigate(lex):
    w = lex.w
    start_room = w.house.places[w.house.robot_start].room
    for rid in sorted(w.house.rooms):
        if rid == start_room or lex.off_limits_room(rid):
            continue
        a = room_goal(w, rid)
        yield opt("navigate.room", "navigate", "feasible", "none", {"all": [a]}, [a], room=rid)


# ── correction (scripted interruption, DESIGN 5.5) ────────────────────────────────────────────────────
def opts_correction(lex):
    w = lex.w
    user = w.user_id()
    fetch = [o["atoms"][0] for o in opts_fetch_me(lex)]
    for a in fetch:
        oid = a["args"][0]
        for b in fetch:
            o2 = b["args"][0]
            if o2 == oid:
                continue
            c1, c2 = w.objects[oid].cls, w.objects[o2].cls
            if c1 == c2 or _similar(c1, c2):
                yield opt("correction.object", "correction", "feasible", "none", {"all": [a]}, [a],
                          interrupt={"kind": "correction", "slot": "object", "new": b})
        yield opt("correction.stop", "correction", "feasible", "none", {"all": [a]}, [a],
                  interrupt={"kind": "stop", "slot": None, "new": None})
    for s in list(opts_rearrange(lex)) + list(opts_contain(lex)):
        a = s["atoms"][0]
        oid, dst = a["args"]
        alts = dests(lex, oid, container=a["pred"] == "in")
        for d2 in alts:
            if d2 != dst:
                b = A(a["pred"], oid, d2)
                yield opt("correction.dest", "correction", "feasible", "none", {"all": [a]}, [a],
                          interrupt={"kind": "correction", "slot": "dest", "new": b})
    _ = user


SIMILAR = [{"mug", "cup", "glass", "tumbler"}, {"water_bottle", "juice", "milk"}, {"apple", "banana", "orange"},
           {"book", "notebook"}, {"phone", "remote"}, {"keys", "wallet"}, {"towel", "socks"}]


def _similar(a, b):
    return any(a in s and b in s for s in SIMILAR)


# ── clarify ───────────────────────────────────────────────────────────────────────────────────────────
def opts_pref(lex):
    """preference: two or more instances of a class (whose mug / which towel)."""
    w, user = lex.w, lex.w.user_id()
    by = {}
    for oid in sorted(w.objects):
        o = w.objects[oid]
        if movable(lex, oid) and o.cls in (FETCH_ME | REARRANGE | CONTAIN) and o.cls not in MEDICINE:
            by.setdefault(o.cls, []).append(oid)
    for cls, cands in sorted(by.items()):
        if len(cands) < 2:
            continue
        for intended in cands:
            if cls in FETCH_ME:
                a = A("held_by", intended, user)
                yield opt("clarify.pref.fetch", "fetch", "clarify", "preference", {"all": [a]}, [a],
                          clar={"slot": "object", "cands": cands, "cls": cls})
            for pid in dests(lex, intended, container=False):
                if all(placement_ok(w, w.objects[c].cls, pid)[0] and w.objects[c].at != pid for c in cands) \
                        and cls in REARRANGE and all(w.house.places[w.objects[c].at].kind != "container" for c in cands):
                    a = A("on", intended, pid)
                    yield opt("clarify.pref.on", "rearrange", "clarify", "preference", {"all": [a]}, [a],
                              clar={"slot": "object", "cands": cands, "cls": cls})
            for pid in dests(lex, intended, container=True):
                if all(placement_ok(w, w.objects[c].cls, pid)[0] and w.objects[c].at != pid for c in cands) \
                        and cls in CONTAIN:
                    a = A("in", intended, pid)
                    yield opt("clarify.pref.in", "contain", "clarify", "preference", {"all": [a]}, [a],
                              clar={"slot": "object", "cands": cands, "cls": cls})
        for per in lex.others():
            k = person_kind(lex, per)
            if k in ("child", "elder", "adult") and cls in FETCH_TO.get(k, set()):
                for intended in cands:
                    a = A("held_by", intended, per)
                    yield opt("clarify.pref.to", "fetch", "clarify", "preference", {"all": [a]}, [a],
                              clar={"slot": "object", "cands": cands, "cls": cls})


def opts_common_sense(lex):
    w, user = lex.w, lex.w.user_id()
    for group, gname in ((DRINK, "drink"), (EAT, "eat")):
        cands = sorted(o for o in w.objects if w.objects[o].cls in group and movable(lex, o))
        if len({w.objects[c].cls for c in cands}) < 2 or len(cands) != len({w.objects[c].cls for c in cands}):
            continue
        recips = [user] + [p for p in lex.others() if person_kind(lex, p) in ("child", "elder")]
        for rec in recips:
            for intended in cands:
                a = A("held_by", intended, rec)
                yield opt(f"clarify.cs.{gname}", "fetch", "clarify", "common_sense", {"all": [a]}, [a],
                          clar={"slot": "object", "cands": cands, "group": gname})
    # put X away: two typical storage places in the house
    for oid in sorted(w.objects):
        o = w.objects[oid]
        if o.cls not in AWAY or not movable(lex, oid) or w.house.places[o.at].kind == "container":
            continue
        ds = dests(lex, oid, container=True)
        ds = [d for d in ds if place_category(w.house.places[d]) not in ("Microwave",)]
        if len(ds) < 2:
            continue
        ds = ds[:3]
        for intended in ds:
            a = A("in", oid, intended)
            yield opt("clarify.cs.away", "contain", "clarify", "common_sense", {"all": [a]}, [a],
                      clar={"slot": "dest", "cands": ds})


def opts_safety(lex):
    w, user = lex.w, lex.w.user_id()
    meds = sorted(o for o in w.objects if w.objects[o].cls in MEDICINE and movable(lex, o))
    if len(meds) >= 2:
        for intended in meds:
            a = A("held_by", intended, user)
            yield opt("clarify.safety.medicine", "fetch", "clarify", "safety", {"all": [a]}, [a],
                      clar={"slot": "object", "cands": meds, "group": "medicine"})
    meds2 = sorted(o for o in w.objects if w.objects[o].cls in MEDICINE | {"vitamins"} and movable(lex, o))
    for per in lex.others():
        if person_kind(lex, per) == "elder" and len(meds2) >= 2:
            for intended in meds2:
                a = A("held_by", intended, per)
                yield opt("clarify.safety.medicine_to", "fetch", "clarify", "safety", {"all": [a]}, [a],
                          clar={"slot": "object", "cands": meds2, "group": "medicine"})
    for per in lex.others():
        if person_kind(lex, per) != "child":
            continue
        desk = [pid for pid in w.house.places if pid.startswith("kids_desk")]
        for oid in sorted(w.objects):
            if w.objects[oid].cls == "scissors" and movable(lex, oid) and desk and w.objects[oid].at != desk[0]:
                hand, leave = A("held_by", oid, per), A("on", oid, desk[0])
                yield opt("clarify.safety.scissors", "fetch", "clarify", "safety", {"all": [leave]}, [hand],
                          clar={"slot": "dest_goal", "cands": [hand, leave], "intended": 1})


# ── refuse ────────────────────────────────────────────────────────────────────────────────────────────
def opts_unsafe(lex):
    w = lex.w
    child = [p for p in lex.others() if person_kind(lex, p) == "child"]
    for classes, target, reason in UNSAFE:
        for oid in sorted(w.objects):
            o = w.objects[oid]
            if o.cls not in classes or not movable(lex, oid):
                continue
            tgts = []
            if target == "child":
                tgts = [A("held_by", oid, c) for c in child]
            else:
                for pid, p in sorted(w.house.places.items()):
                    cat = place_category(p)
                    if target == "fridge" and cat == "Fridge" or target == "microwave" and cat == "Microwave":
                        tgts.append(A("in", oid, pid))
                    elif target == "stove" and cat == "StoveBurner":
                        tgts.append(A("on", oid, pid))
            for t in tgts:
                req = {"all": [t]}
                hz = goal_hazards(w, req)
                if not hz:
                    continue
                goal = {"refuse": True, "all": [A("unmoved", oid)]}
                yield opt(f"refuse.unsafe.{reason}", t["pred"] == "held_by" and "fetch" or
                          ("contain" if t["pred"] == "in" else "rearrange"), "refuse", "none", goal, [t],
                          refuse_reason="unsafe", requested=req, hazards=hz, reason=reason)


def opts_infeasible(lex):
    w, user = lex.w, lex.w.user_id()
    for oid in sorted(w.objects):
        o = w.objects[oid]
        if o.cls not in HEAVY or o.at not in w.house.places:
            continue
        goal = {"refuse": True, "all": [A("unmoved", oid)]}
        reqs = []
        for pid, p in sorted(w.house.places.items()):
            if lex.off_limits_place(pid):
                continue
            cat = place_category(p)
            fit = {"laundry_basket": ("Bed",), "houseplant": ("Shelf", "TVStand", "SideTable", "CounterTop"),
                   "water_jug": ("CounterTop",)}[o.cls]
            if o.cls == "houseplant" and cat == "Shelf" and "high_shelf" in p.tags:
                continue
            if pid != o.at and p.kind not in ("floor", "dock") and placement_ok(w, o.cls, pid)[0] and cat in fit:
                reqs.append(A("in" if p.kind == "container" else "on", oid, pid))
        if o.cls in ("water_jug", "houseplant"):
            reqs.append(A("held_by", oid, user))
        for r in reqs:
            req = {"all": [r]}
            if oracle.solve(w, req) is not None:
                continue
            cap = "fetch" if r["pred"] == "held_by" else ("contain" if r["pred"] == "in" else "rearrange")
            yield opt("refuse.infeasible.heavy", cap, "refuse", "none", goal, [r], refuse_reason="infeasible",
                      requested=req, hazards=[], reason="heavy_" + o.cls)


FAMILIES = {
    "fetch.me": opts_fetch_me, "fetch.to": opts_fetch_to, "rearrange.on": opts_rearrange,
    "contain.in": opts_contain, "articulate.open": opts_articulate, "multi": opts_multi, "search": opts_search,
    "message.tell": opts_message, "navigate.room": opts_navigate, "correction": opts_correction,
    "clarify.pref": opts_pref, "clarify.cs": opts_common_sense, "clarify.safety": opts_safety,
    "refuse.unsafe": opts_unsafe, "refuse.infeasible": opts_infeasible,
}
_ = PEOPLE
