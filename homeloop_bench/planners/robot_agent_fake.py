"""Deterministic stand-ins for ``--llm fake`` runs of the robot_agent planners (tests / CI only).

* :class:`FakeUnderstandLLM`: answers robot_agent's understand prompt with the task's GOLD goals in
  robot_agent's understand JSON (clarify tasks: "ambiguous" + the gold question until the dialogue holds an
  answer; refuse tasks: "unsafe" / "infeasible"), echoes translation prompts, and writes ``skill::input``
  programs for the direct planner (``llm_direct``) from the oracle's plan.
* :class:`GoalPlanner`: a plug-in planner (``homeloop_bench.planners.robot_agent_fake:GoalPlanner``,
  loaded by name through robot_agent's registry) that plans the gold goals with the oracle from the current
  true world, as abstract steps (MoveTo, Find, Pick, ...).

With these, the real loops (gate, guard, recovery, ask channel) and the homeloop robot package run without
an LLM. These are test doubles: they read the gold task and the true world, so their scores are never
reported as a planner's.
"""

from __future__ import annotations

import json
import re

from homeloop_robot import oracle as _oracle
from homeloop_robot.catalog import CLASSES, COLORS, MESSAGE_TEXT

# the episode the fakes serve (set by robot_agent_adapter for the episode, cleared after)
CURRENT: dict = {"env": None}

ACTION = {"move": "MoveTo", "find": "Find", "pick": "Pick", "place": "Place", "put_in": "PutIn", "open": "Open",
          "close": "Close", "handover": "Handover", "say": "Say", "announce": "Announce", "ask": "Ask",
          "wait": "Wait", "dock": "Dock", "look": "Look", "vlm_check": "Query"}
PRIMARY = ("target", "obj", "container", "person", "text", "question", "seconds", "query")


def _env():
    env = CURRENT.get("env")
    if env is None:
        raise RuntimeError("robot_agent_fake used outside an episode")
    return env


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


def understand_goals(env) -> list:
    """Gold atoms as robot_agent understand goals {type, object, from, to}."""
    w = env.world0
    user = w.user_id() if hasattr(w, "user_id") else None
    out = []

    def src(oid):                       # where the object is now (the gate then plans the Open of a container)
        o = w.objects.get(oid)
        return o.at if o is not None and o.at in w.house.places else ""

    def seat(pid):                      # robot_agent moves to ENV places only: a person's seat place
        p = w.people.get(pid)
        return p.seat if p is not None else pid
    for a in gold_goals(env):
        p, args = a["pred"], list(a.get("args") or [])
        if p == "on":
            out.append({"type": "on", "object": _obj_name(w, args[0]), "from": src(args[0]), "to": args[1]})
        elif p == "in":
            out.append({"type": "in", "object": _obj_name(w, args[0]), "from": src(args[0]), "to": args[1]})
        elif p == "open":
            out.append({"type": "open", "object": args[0], "from": "", "to": ""})
        elif p == "closed":
            out.append({"type": "close", "object": args[0], "from": "", "to": ""})
        elif p == "held_by":
            if args[1] == user:
                out.append({"type": "on", "object": _obj_name(w, args[0]), "from": src(args[0]), "to": "me"})
            else:
                out.append({"type": "deliver", "object": _obj_name(w, args[0]), "from": src(args[0]),
                            "to": seat(args[1])})
        elif p == "said_to":
            txt = (MESSAGE_TEXT.get(args[1]) or {}).get(env.lang) or args[1]
            out.append({"type": "say", "object": txt, "from": "", "to": seat(args[0])})
        elif p == "robot_at":
            out.append({"type": "go", "object": "", "from": "", "to": args[0]})
        elif p == "docked":
            out.append({"type": "go", "object": "", "from": "", "to": w.house.dock})
    return out


def _gold_question(env) -> str:
    gq = (env.task.get("user") or {}).get("gold_question") or {}
    if isinstance(gq, dict):
        return gq.get(env.lang) or gq.get("en") or "Which one do you mean?"
    return str(gq or "Which one do you mean?")


def oracle_calls(env, world=None) -> list:
    w = env.world if world is None else world
    goal = {"all": gold_goals(env)}
    if not goal["all"]:
        return []
    people = {pid: st.pos for pid, st in env.user.people_at(env.ep.clock.t).items()}
    return _oracle.solve(w, goal, lang=env.lang, people_pos=people) or []


def _primary(args: dict) -> str:
    for k in PRIMARY:
        if k in args:
            return str(args[k])
    return ""


class FakeUnderstandLLM:
    """The ``chat(prompt=..., format=...)`` client the robot_agent loops call (see the module doc)."""

    model = "fake"

    def __init__(self):
        self.calls = 0

    def chat(self, prompt: str = "", format=None, **kw) -> str:
        self.calls += 1
        env = _env()
        p = str(prompt or "")
        if p.startswith("Translate"):
            return p.split("\n", 1)[-1]
        if "turn a household robot task into goals" in p:
            kind = env.task.get("kind")
            kinds = [s["kind"] for s in env.subtasks]
            if kinds and all(k == "refuse" for k in kinds):
                st = "infeasible" if (env.task.get("refuse_reason") == "infeasible") else "unsafe"
                return json.dumps({"status": st, "reason": "the request is not safe or not possible",
                                   "question": "", "goals": []})
            answered = "You already asked the user" in p
            if (kind == "clarify" or "clarify" in kinds) and not answered:
                return json.dumps({"status": "ambiguous", "reason": "which one is meant is unclear",
                                   "question": _gold_question(env), "goals": []}, ensure_ascii=False)
            return json.dumps({"status": "clear", "reason": "", "question": "", "goals": understand_goals(env)},
                              ensure_ascii=False)
        if "skill::" in p or "Answer with the program only" in p:
            return direct_program(env)
        if re.search(r"\byes\b.*\bno\b", p, re.I | re.S) and len(p) < 2000:
            return "yes"
        return "{}"

    def chat_guide(self, prompt, guide=None, reuse=False, **kw) -> str:
        return self.chat(prompt=prompt, **kw)


def direct_program(env) -> str:
    """The oracle's plan from the true start state as a ``skill::input`` program."""
    lines = []
    for c in oracle_calls(env, env.world0):
        arg = _primary(c.args)
        lines.append(f"{c.skill}::{arg}" if arg else f"{c.skill}::")
    return "\n".join(lines)


class GoalPlanner:
    """Plug-in planner for fake runs: the oracle's plan for the gold goals from the current TRUE world, as
    abstract steps. ``replan`` re-plans from the true world (so the loops' recovery paths are exercised)."""

    method = "homeloop_fake_goal_planner"

    def __init__(self, capabilities: dict | None = None, actions: list | None = None, **kw):
        self.capabilities = dict(capabilities or {})
        self.actions = set(actions or ())
        self.calls: list = []

    def _steps(self) -> list:
        env = _env()
        out = []
        for c in oracle_calls(env):
            a = ACTION.get(c.skill)
            if a is None or (self.actions and a not in self.actions and a not in ("MoveTo",)):
                continue
            arg = _primary(c.args)
            if c.skill in ("find", "pick") and arg in env.world0.objects:
                arg = _obj_name(env.world0, arg)          # the name the understood goals use
            elif arg in env.world0.people:
                # robot_agent moves to ENV places only: a person target -> the person's seat place
                arg = env.world0.people[arg].seat if c.skill == "move" else env.world0.people[arg].name.get("en", arg)
            st = {"action": a, "object": arg}
            if c.skill in ("say", "announce", "ask"):
                st["lang"] = c.args.get("lang", env.lang)
            out.append(st)
        return out

    def generate_plan(self, task, obs, visible_objects):
        self.calls.append("generate_plan")
        return self._steps(), {"method": self.method}

    def replan(self, task, completed, failed_step, failure_reason, obs, visible_objects):
        self.calls.append("replan")
        return self._steps(), {"method": self.method}
