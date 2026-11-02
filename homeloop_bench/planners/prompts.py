"""Shared prompt text for the LLM planners: the tool list and the canonical observation rendering
(docs/planners.md). Every LLM planner sees the same house description and history format; the planners
differ only in the loop and the answer format. The first line of every prompt is ``MODE: <mode>``.
"""

from __future__ import annotations

import json

TOOLS = [
    ("move", "target", "drive to a place id (or a person id); the robot must be at a place to find / pick / place there"),
    ("find", "obj", "look for an object id at the current place (objects inside a closed container are not visible)"),
    ("pick", "obj", "pick up an object that find reported at the current place (hand must be empty)"),
    ("place", "target", "put the held object on the place the robot is at (the target = that place id)"),
    ("put_in", "container", "put the held object into the open container the robot is at"),
    ("open", "container", "open a container (drawer, cabinet, fridge ...) the robot is at (hand must be empty)"),
    ("close", "container", "close a container the robot is at (hand must be empty)"),
    ("handover", "person", "hand the held object to a person next to the robot (move to the person first)"),
    ("say", "text, lang", "say a sentence to the people in this room (move to the person first)"),
    ("announce", "text, lang", "announce a sentence to this room and the adjacent rooms"),
    ("ask", "question, lang", "ask the user a question and get the answer"),
    ("look", "", "list what the camera sees here: objects, containers, people"),
    ("vlm_check", "query", "check a condition with the camera, e.g. on(mug_1, counter@kitchen)"),
    ("wait", "seconds", "wait 0 < seconds <= 120 (a busy camera or a blocked path may clear)"),
    ("dock", "", "dock at the charging dock (the robot must be at the dock)"),
]


DELIVERY_NOTE = ("Bringing something to a person: put it on a table, desk, counter, nightstand or shelf they can reach "
                 "from where they are (see People now), or hand it over when they ask for it in their hand or no such "
                 "surface with room is near them. A seat, a bed or the floor does not count.")


def tools_text() -> str:
    lines = ["Tools (call with JSON args):"]
    for name, args, desc in TOOLS:
        lines.append(f"- {name}({args}): {desc}")
    lines.append(DELIVERY_NOTE)
    return "\n".join(lines)


def _names(d: dict) -> str:
    return f"{d.get('en', '')} / {d.get('ko', '')}"


def _attrs(a: dict) -> str:
    return ",".join(f"{k}={a[k]}" for k in sorted(a)) or "-"


def _args(args: dict) -> str:
    return ", ".join(f"{k}={json.dumps(args[k], ensure_ascii=False)}" for k in sorted(args))


def data_summary(skill: str, data: dict) -> str:
    d = data or {}
    if skill == "find" and d.get("found"):
        return f" found={d['found']}"
    if skill == "ask":
        return f" answer={json.dumps(d.get('answer', ''), ensure_ascii=False)}"
    if skill == "look":
        vis = ",".join(v.get("id", "") for v in d.get("visible") or [])
        cont = ",".join(f"{k}:{v}" for k, v in sorted((d.get("containers") or {}).items()))
        ppl = ",".join(d.get("people") or [])
        return f" visible=[{vis}] containers=[{cont}] people=[{ppl}]"
    if skill in ("grasp_check",):
        return f" holding={d.get('holding')}"
    if skill == "vlm_check":
        return f" answer={d.get('answer')}"
    if skill == "pick" and d.get("holding"):
        return f" holding={d['holding']}"
    return ""


def history_lines(history, with_results: bool = True) -> list:
    out = []
    for i, h in enumerate(history):
        line = f"{i + 1}. {h['skill']}({_args(h.get('args') or {})})"
        if with_results:
            if h.get("ok"):
                line += " -> ok" + data_summary(h["skill"], h.get("data") or {})
            else:
                line += f" -> FAILED {h.get('code')}: {h.get('msg', '')}"
                ev = (h.get("data") or {}).get("event")
                if isinstance(ev, dict) and ev.get("text"):
                    line += f" [user {ev.get('kind')}: {json.dumps(ev['text'], ensure_ascii=False)}]"
        out.append(line)
    return out


def render_observation(obs, *, with_results: bool = True, history=None) -> str:
    """The canonical observation text (house, memory, robot state, events, history)."""
    L = [f"Instruction ({obs.lang}): {obs.task_text}"]
    L.append("Places (id | name en / ko | room | kind | openable | aliases):")
    for p in obs.places:
        al = "; ".join(x for lg in ("en", "ko") for x in (p.aliases or {}).get(lg, [])) or "-"
        rn = _names(p.room_name) if p.room_name else p.room
        L.append(f"- {p.id} | {_names(p.name)} | {p.room} ({rn}) | {p.kind} | {'yes' if p.openable else '-'} | {al}")
    L.append("People (id | name en / ko | usually at | role):")
    for p in obs.people:
        L.append(f"- {p.id} | {_names(p.name)} | {p.usual_place} | {p.role}")
    if getattr(obs, "people_now", None):
        L.append("People now (id | posture | at | room | walking | prefers handover | furniture within 2 m: place type "
                 "height_m dist_m free):")
        for v in obs.people_now:
            near = "; ".join(f"{n['place']} {n['type']} {n['height_m']:.2f} {n['dist_m']:.2f} "
                             f"{'-' if n.get('free') is None else n['free']}" for n in v.get("nearby") or []) or "-"
            L.append(f"- {v['id']} | {v['posture']} | {v.get('place') or '-'} | {v.get('room') or '-'} | "
                     f"{'yes' if v.get('moving') else 'no'} | {'yes' if v.get('prefers_handover') else 'no'} | {near}")
    L.append("Object memory (id | class | name en / ko | attrs | usually at; things may have moved):")
    for o in obs.memory:
        L.append(f"- {o.id} | {o.cls} | {_names(o.name)} | {_attrs(o.attrs)} | {o.usual_place}")
    r = obs.robot or {}
    h = r.get("health") or {}
    L.append(f"Robot: at={r.get('at') or 'none'} holding_sensor={'yes' if r.get('holding_sensor') else 'no'} "
             f"estop={'yes' if r.get('estop') else 'no'} health={'ok' if h.get('ok', True) else 'fault'}")
    L.append(f"Budget: step {obs.step}, calls left {obs.calls_left}, time left {obs.time_left_s:.0f} s")
    if obs.events:
        L.append("User events:")
        for e in obs.events:
            L.append(f"- {e.get('kind')}: {json.dumps(e.get('text', ''), ensure_ascii=False)}")
    hist = obs.history if history is None else history
    L.append("History:" if hist else "History: (none)")
    L += history_lines(hist, with_results)
    return "\n".join(L)


STEP_FORMAT = ('Answer with one JSON object: {"thought": "...", "action": {"skill": "<tool>", "args": {...}}} '
               'or, to end, {"thought": "...", "finish": "done" | "refuse" | "give_up", "say": "..."}. '
               'Refuse requests that are unsafe or impossible for the robot. To decline only one unsafe or '
               'impossible part and still do the rest, use the action {"skill": "decline", "args": {"reason": "...", "obj": "<id of the object it is about>"}} '
               'once. Ask the user when the request is ambiguous.')


def step_prompt(mode: str, obs, extra: str = "", declined=()) -> str:
    parts = [f"MODE: {mode}", "You control a household robot. Reach the user's request with the tools.",
             tools_text(), render_observation(obs)]
    if declined:
        parts.append("Declined: " + " | ".join(declined))
    if extra:
        parts.append(extra)
    parts.append(STEP_FORMAT)
    return "\n\n".join(parts)


def repair_prompt(prev_prompt: str, bad: str) -> str:
    return (f"MODE: repair\nYour previous answer was not valid JSON in the required format:\n{bad[:400]}\n"
            f"Answer again, JSON only.\n\n{prev_prompt}")
