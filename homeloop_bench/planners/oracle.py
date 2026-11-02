"""``oracle``: the privileged closed-loop reference planner (docs/planners.md).

Reads the TRUE world and the hidden goal. After every call it re-solves from the true state with
``homeloop_robot.oracle.solve``; per (skill, args) at most 3 consecutive attempts; ``wait(5)`` before
retrying perception_unavailable / blocked; an ``ask`` for help while a path is blocked (STRANDS-style
human help). Clarify tasks: it asks the gold question once (for the help metrics) and then acts on the true
intent. Refuse tasks: ``finish("refuse")``; mixed tasks: it declines the refuse part and does the rest.
It finishes ``done`` only when the judge would score success, so its false-success rate is 0.
"""

from __future__ import annotations

from homeloop_robot import oracle as _oracle

MAX_ATTEMPTS = 3


def task_kinds(env) -> list:
    return [s["kind"] for s in env.subtasks]


def solve_target(env) -> dict:
    """The goal to plan for now: every non-refuse subtask whose ``order`` predecessors (``(a, b)`` pairs:
    ``a`` before ``b``) already hold; ``unmoved`` atoms are kept by not touching."""
    subs = env.subtasks
    use = [i for i, s in enumerate(subs) if s["kind"] != "refuse"]
    if env.order:
        from homeloop_robot import goals as G
        done = {i: G.evaluate(subs[i]["goal"], env.world).holds for i in use}
        use = [i for i in use if all(done.get(a, True) for a, b in env.order if b == i)]
    atoms = []
    for i in use:
        atoms += [a for a in subs[i]["goal"]["all"] if a.get("pred") != "unmoved"]
    return {"all": atoms}


def gold_question(env):
    gq = (env.task.get("user") or {}).get("gold_question")
    if isinstance(gq, dict):
        return gq.get(env.lang) or gq.get("en")
    return gq or None


class OraclePlanner:
    name = "oracle"
    privileged = True
    needs_llm = False
    description = "privileged: re-solves from the true world after every call, retries, waits, asks for help"

    def __init__(self, llm=None):
        pass

    def run(self, env) -> None:
        w = env.truth
        kinds = task_kinds(env)
        if kinds and all(k == "refuse" for k in kinds):
            env.finish("refuse", "I can't do that safely.")
            return
        if any(k == "refuse" for k in kinds):
            env.note_refusal("I won't do the unsafe part.")
        is_clarify = env.task.get("kind") == "clarify" or "clarify" in kinds
        q = gold_question(env)
        if is_clarify and q:
            env.call("ask", question=q, lang=env.lang)
        fails: dict = {}
        while env.status is None:
            if env.over:
                env.finish("give_up", "budget exhausted")
                return
            if env.stop_k is not None:
                env.finish("done", "Stopped.")
                return
            if env.judge("done")["success"]:
                env.finish("done")
                return
            target = solve_target(env)
            people = {pid: st.pos for pid, st in env.user.people_at(env.ep.clock.t).items()}
            plan = _oracle.solve(w, target, lang=env.lang, people_pos=people) if target["all"] else []
            if not plan:
                env.finish("give_up", "no plan from the current state")
                return
            c = plan[0]
            key = (c.skill, tuple(sorted(c.args.items())))
            if fails.get(key, 0) >= MAX_ATTEMPTS:
                env.finish("give_up", f"{c} failed {MAX_ATTEMPTS} times")
                return
            r = env.call(c.skill, **c.args)
            if r["ok"]:
                fails.pop(key, None)
                continue
            fails[key] = fails.get(key, 0) + 1
            code = r.get("code")
            if w.robot.estop or (code == "hw_fault" and any(f.clears_on == "never" for f in w.faults.values())):
                env.finish("give_up", r.get("msg", ""))
                return
            if code == "cancelled":
                continue                         # the event (stop / correction) is handled at the top
            if code == "blocked" and c.skill == "move":
                env.call("ask", question="Could you please clear the way for me?" if env.lang == "en"
                         else "지나갈 수 있게 길을 좀 비켜 주시겠어요?", lang=env.lang)
            elif code in ("perception_unavailable", "blocked"):
                env.call("wait", seconds=5)
