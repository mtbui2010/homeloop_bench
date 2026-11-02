"""Planner interface (docs/planners.md).

A planner drives one episode through :class:`homeloop_bench.env.EpisodeEnv` and ends it with
``env.finish(status, say)``. :class:`StepPlanner` is the helper for planners that choose one call at a
time; :class:`PlanPlanner` for planners that write a whole plan and then execute it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..env import Finish, ToolCall


@runtime_checkable
class Planner(Protocol):
    name: str
    privileged: bool                     # True: may read env.truth (oracle, naive only)

    def run(self, env) -> None: ...


class StepPlanner:
    """``run`` loops ``act(obs)`` until it returns a :class:`Finish` or the budget is used up."""

    name = "step"
    privileged = False
    needs_llm = False
    description = ""

    def __init__(self, llm=None):
        self.llm = llm

    def reset(self, env) -> None:
        self.env = env

    def act(self, obs) -> "ToolCall | Finish":
        raise NotImplementedError

    def run(self, env) -> None:
        self.reset(env)
        while env.status is None:
            if env.over:
                env.finish("give_up", "budget exhausted")
                return
            a = self.act(env.observe())
            if isinstance(a, Finish):
                env.finish(a.status, a.say)
                return
            env.call(a.skill, **dict(a.args))


class PlanPlanner:
    """``plan(obs)`` returns a list of :class:`ToolCall` (and optionally a trailing :class:`Finish`);
    ``run`` executes it and stops at the first failure unless ``on_failure`` returns more calls."""

    name = "plan"
    privileged = False
    needs_llm = False
    description = ""

    def __init__(self, llm=None):
        self.llm = llm

    def plan(self, obs) -> list:
        raise NotImplementedError

    def on_failure(self, call: ToolCall, result: dict, obs) -> list | None:
        return None

    def run(self, env) -> None:
        self.env = env
        queue = list(self.plan(env.observe()))
        while queue and env.status is None:
            a = queue.pop(0)
            if isinstance(a, Finish):
                env.finish(a.status, a.say)
                return
            if env.over:
                break
            r = env.call(a.skill, **dict(a.args))
            if not r["ok"]:
                more = self.on_failure(a, r, env.observe())
                if more is None:
                    env.finish("give_up", r.get("msg", ""))
                    return
                queue = list(more) + queue
        if env.status is None:
            env.finish("give_up" if env.over else "done")


MAX_REPAIRS = 2


def ask_json(llm, prompt: str, *, check=None, temperature: float = 0.0, seed: int = 0, format="json"):
    """Call the LLM and parse a JSON answer; up to 2 repair prompts on an unparsable / invalid answer.
    ``check(obj)`` returns an error string or None. -> the object, or None after the repairs (the
    planner then gives up). Every attempt is one LLM call."""
    from ..llm import parse_json
    p = prompt
    for _attempt in range(MAX_REPAIRS + 1):
        raw = llm.chat(p, format=format, temperature=temperature, seed=seed)
        try:
            obj = parse_json(raw)
            err = check(obj) if check else None
        except ValueError as e:
            obj, err = None, str(e)
        if err is None and obj is not None:
            return obj
        from .prompts import repair_prompt
        p = repair_prompt(prompt, f"{raw}\n(problem: {err})")
    return None


def step_check(obj) -> str | None:
    """Validate a step answer: {"action": {"skill", "args"}} or {"finish": status}."""
    from .prompts import TOOLS
    if not isinstance(obj, dict):
        return "not a JSON object"
    if "finish" in obj:
        return None if obj["finish"] in ("done", "refuse", "give_up") else "finish must be done | refuse | give_up"
    a = obj.get("action")
    if not isinstance(a, dict) or not isinstance(a.get("skill"), str):
        return "missing action.skill"
    if a["skill"] != "decline" and a["skill"] not in {t[0] for t in TOOLS}:
        return f"unknown tool {a['skill']!r}"
    if not isinstance(a.get("args", {}), dict):
        return "action.args must be an object"
    return None
