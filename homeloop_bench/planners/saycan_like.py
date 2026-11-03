"""``saycan_like``: after SayCan (Ahn et al. 2022, arXiv:2204.01691).

Each step the planner enumerates the calls whose preconditions hold in its own belief (affordance
filter: where it is, what it holds, what it found here, which containers it opened) and the LLM picks one
option by index. SayCan scores each skill by the LLM's log-likelihood times a learned value function; a chat
API gives no log-likelihoods, so here the LLM chooses by index among the affordable options (documented
deviation). The prompt carries the state only: no failure text and no replanning beyond the step choice.
"""

from __future__ import annotations

from homeloop_robot.catalog import MESSAGE_TEXT

from ..env import Finish, ToolCall, give_up_text
from .base import ask_json
from .prompts import render_observation, _args


class AffordanceBelief:
    """What the robot believes from its own results (no ground truth)."""

    def __init__(self):
        self.at = None
        self.near = None
        self.holding = None
        self.found_here: list = []
        self.opened: set = set()

    def update(self, skill, args, r):
        ok = r.get("ok")
        data = r.get("data") or {}
        if skill == "move" and ok:
            self.found_here = []
            t = args.get("target")
            self.near, self.at = (t, None) if self._is_person(t) else (None, t)
        elif skill == "find" and ok:
            f = data.get("found") or args.get("obj")
            if f not in self.found_here:
                self.found_here.append(f)
        elif skill == "pick" and ok:
            self.holding = args.get("obj")
            self.found_here = [x for x in self.found_here if x != args.get("obj")]
        elif skill in ("place", "put_in", "handover") and ok:
            self.holding = None
        elif r.get("code") == "dropped":
            self.holding = None
        elif skill == "open" and ok:
            self.opened.add(args.get("container"))
        elif skill == "close" and ok:
            self.opened.discard(args.get("container"))

    people: set = set()

    def _is_person(self, t):
        return t in self.people


def options(obs, b: AffordanceBelief) -> list:
    places = {p.id: p for p in obs.places}
    out = []
    for p in obs.places:
        if p.id != b.at:
            out.append(("move", {"target": p.id}))
    for p in obs.people:
        if p.id != b.near:
            out.append(("move", {"target": p.id}))
    if b.at:
        here = places.get(b.at)
        for o in obs.memory:
            if o.id not in b.found_here:
                out.append(("find", {"obj": o.id}))
        if b.holding is None:
            for o in b.found_here:
                out.append(("pick", {"obj": o}))
            if here is not None and here.openable:
                out.append(("close" if b.at in b.opened else "open", {"container": b.at}))
        else:
            if here is not None and here.kind == "container":
                if b.at in b.opened or not here.openable:
                    out.append(("put_in", {"container": b.at}))
            elif here is not None and here.kind != "dock":
                out.append(("place", {"target": b.at}))
        if here is not None and here.kind == "dock":
            out.append(("dock", {}))
    if b.near:
        if b.holding is not None:
            out.append(("handover", {"person": b.near}))
        for k in sorted(MESSAGE_TEXT):
            out.append(("say", {"text": MESSAGE_TEXT[k][obs.lang], "lang": obs.lang}))
    out += [("finish", {"status": "done"}), ("finish", {"status": "refuse"}), ("finish", {"status": "give_up"})]
    return out


class SayCanLike:
    name = "saycan_like"
    privileged = False
    needs_llm = True
    description = "LLM picks one affordance-filtered call per step by index (after SayCan)"

    def __init__(self, llm=None):
        self.llm = llm

    def run(self, env) -> None:
        if self.llm is None:
            raise RuntimeError("saycan_like needs an LLM")
        b = AffordanceBelief()
        b.people = {p.id for p in env.observe().people}
        b.at = env.observe().robot.get("at")
        while env.status is None:
            if env.over:
                env.finish("give_up", give_up_text(env.lang), reason="budget exhausted")
                return
            obs = env.observe()
            opts = options(obs, b)
            lines = [f"{i}: {s}({_args(a)})" for i, (s, a) in enumerate(opts)]
            prompt = "\n\n".join([
                "MODE: saycan",
                "You control a household robot. Choose the ONE next skill that best progresses the instruction.",
                render_observation(obs, with_results=False),
                "Options:\n" + "\n".join(lines),
                'Answer with JSON: {"choice": <option number>}.'])
            obj = ask_json(self.llm, prompt, check=lambda o: None if isinstance(o, dict) and isinstance(o.get("choice"), int)
                           and 0 <= o["choice"] < len(opts) else "choice must be an option number")
            if obj is None:
                env.finish("give_up", give_up_text(env.lang), reason="no valid choice from the LLM")
                return
            s, a = opts[obj["choice"]]
            if s == "finish":
                env.finish(a["status"])
                return
            r = env.call(s, **a)
            b.update(s, a, r)
