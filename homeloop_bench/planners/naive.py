"""``naive``: the oracle's plan from the start state, executed open loop (docs/planners.md).

No replanning, no recovery, no asking: the first failed call ends the episode with ``give_up``; when every
call reports ok it finishes ``done`` (so silent failures become false successes). Refuse tasks are
refused like the oracle does. Ordered structures are planned layer by layer (subtasks whose predecessors hold) on an ideal copy of the start
state.
"""

from __future__ import annotations

from homeloop_robot import goals as G
from homeloop_robot import make_episode
from homeloop_robot import oracle as _oracle

from .oracle import note_refusals, observed_modes, solve_target, task_kinds


def start_plan(env) -> list | None:
    """The full oracle plan from the start state (None when unsolvable). Delivery modes: chosen from the heard
    instruction and the start scene (``observed_modes``), never from the goal's labels."""
    modes = observed_modes(env, env.world0, env.current_goal())
    if not env.order:
        tgt = solve_target(env)
        return _oracle.solve(env.world0, tgt, lang=env.lang, modes=modes) if tgt["all"] else []
    sim = make_episode(env.task["house"], int(env.task["seed_state"] or 0), "ideal", 0, lang=env.lang,
                       user_impl="null", safety_impl="null")
    calls = []

    class _View:                     # solve_target reads subtasks / order / truth
        subtasks = env.subtasks
        order = env.order
        truth = sim.world
    for _ in range(len(env.subtasks) + 1):
        tgt = solve_target(_View)
        if G.evaluate(tgt, sim.world).holds:
            break
        plan = _oracle.solve(sim.world, tgt, lang=env.lang, modes=modes)
        if not plan:
            return None
        for c in plan:
            sim.robot.call(c.skill, **c.args)
            calls.append(c)
    return calls


class NaivePlanner:
    name = "naive"
    privileged = True
    needs_llm = False
    description = "privileged: the oracle's start-state plan, open loop, no recovery (ablation)"
    qtypes = ()            # it never asks; an ask in its plan would carry the oracle's meaning

    def __init__(self, llm=None):
        pass

    def run(self, env) -> None:
        kinds = task_kinds(env)
        if kinds and all(k == "refuse" for k in kinds):
            env.finish("refuse", "I can't do that safely.")
            return
        note_refusals(env)
        plan = start_plan(env)
        if plan is None:
            env.finish("give_up", "no plan")
            return
        for c in plan:
            if env.over:
                env.finish("give_up", "budget exhausted")
                return
            r = env.call(c.skill, **c.args)
            if not r["ok"]:
                env.finish("give_up", r.get("msg", ""))
                return
        env.finish("done")
