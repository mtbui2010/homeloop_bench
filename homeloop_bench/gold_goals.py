"""The task's gold goal atoms as robot_agent goals ``{type, object, from, to, said}`` (the form its understand step
returns). Used by two test / diagnostic stand-ins and by nothing else:

* the ``--llm fake`` understand stand-in (``planners/robot_agent_fake.py``), which answers with them;
* the diagnostic planner ``robot_agent:sage_gold`` (privileged: it hands them to robot_agent, which then skips its
  understand step, option ``accept_goals``).

Gold goals are the evaluation side's data: nothing here is ever given to a planner that is not labelled privileged.
Documented in docs/planners.md ("robot_agent:sage_gold") and docs/understand_eval.md ("Common form").
"""

from __future__ import annotations

from homeloop_robot.catalog import CLASSES, COLORS, MESSAGE_TEXT


def _obj_name(world, oid: str, lang: str = "en") -> str:
    o = world.objects.get(oid)
    if o is None:
        return oid
    c = CLASSES.get(o.cls)
    n = c.name.get(lang, o.cls) if c else o.cls
    col = o.attrs.get("color")
    return f"{COLORS[col][lang]} {n}" if col in COLORS else n


def gold_goals(env) -> list:
    """The task's gold goal atoms (current goal: a correction's new goal included), without unmoved."""
    return [a for a in env.current_goal().get("all") or [] if a.get("pred") != "unmoved"]


def understand_goals(env, with_source: bool = True) -> list:
    """Gold atoms as robot_agent understand goals {type, object, from, to}. ``with_source=False`` leaves every ``from``
    empty (the robot then uses its own memory and searches: no true location is handed over)."""
    w = env.world0
    user = w.user_id() if hasattr(w, "user_id") else None
    out = []

    def src(oid):                       # where the object is now (the gate then plans the Open of a container)
        o = w.objects.get(oid)
        return "" if not with_source else o.at if o is not None and o.at in w.house.places else ""

    def seat(pid):                      # robot_agent moves to ENV places only: a person's seat place
        p = w.people.get(pid)
        return p.seat if p is not None else pid
    for a in gold_goals(env):
        if "any" in a:                  # robot_at in any one of a room's places: go to the first that is not the floor
            ps = sorted(x["args"][0] for x in a["any"] if x.get("pred") == "robot_at")
            pick = next((k for k in ps if not k.startswith("floor@")), ps[0] if ps else "")
            if pick:
                out.append({"type": "go", "object": "", "from": "", "to": pick})
            continue
        p, args = a["pred"], list(a.get("args") or [])
        if p == "on":
            out.append({"type": "on", "object": _obj_name(w, args[0]), "from": src(args[0]), "to": args[1]})
        elif p == "in":
            out.append({"type": "in", "object": _obj_name(w, args[0]), "from": src(args[0]), "to": args[1]})
        elif p == "open":
            out.append({"type": "open", "object": args[0], "from": "", "to": ""})
        elif p == "closed":
            out.append({"type": "close", "object": args[0], "from": "", "to": ""})
        elif p in ("held_by", "delivered"):
            # the mode a robot infers from the words and the scene (never the label)
            mode = "hand" if p == "held_by" else _modes(env).get((args[0], args[1]), "hand")
            if args[1] == user:
                out.append({"type": "on", "object": _obj_name(w, args[0]), "from": src(args[0]), "to": "me"})
            elif mode == "reach":
                # "near the person": the robot package binds a person as a place to the surface they can reach
                out.append({"type": "on", "object": _obj_name(w, args[0]), "from": src(args[0]), "to": args[1]})
            else:
                out.append({"type": "deliver", "object": _obj_name(w, args[0]), "from": src(args[0]),
                            "to": seat(args[1])})
        elif p == "said_to":
            txt = (MESSAGE_TEXT.get(args[1]) or {}).get(env.lang) or args[1]
            # the listener's ENV entry (robot_agent goes to a person entry: its last-seen spot, or the person)
            out.append({"type": "say", "object": txt, "from": "", "to": _person_key(w, args[0])})
        elif p == "robot_at":
            out.append({"type": "go", "object": "", "from": "", "to": args[0]})
        elif p == "docked":
            out.append({"type": "go", "object": "", "from": "", "to": w.house.dock})
    # the person's own words for each object (robot_agent understand ``said``): the house's name in the episode
    # language, as a model would copy it from the request
    for g in out:
        if g["type"] in ("on", "in", "deliver") and env.lang != "en":
            oid = next((o for o in w.objects if _obj_name(w, o) == g["object"]), None)
            if oid is not None:
                g["said"] = _obj_name(w, oid, env.lang)
    return out


def _person_key(world, pid: str) -> str:
    from homeloop_robot.configs.tasks import person_key
    return person_key(world, pid)




def _modes(env) -> dict:
    """Delivery modes chosen like the oracle does: the heard words and the start scene, never the labels."""
    from .planners.oracle import observed_modes
    return observed_modes(env, env.world0, env.current_goal())
