"""Oracle feasibility check of one task (validator rule 5; DESIGN 13.2).

When the bench runner is importable (``homeloop_bench.runner.run_episode``) the validator uses it: the ``oracle``
planner, profile ``ideal``, seed 0. Otherwise this local shim runs the same judge with the same mechanics:
``make_episode`` + ``oracle.solve`` re-solved from the true world after every call, the task's scripted
interruption armed on the robot, ordered subtasks done in their order, and the order constraints checked on the
call trace (docs/tasks.md, "Scoring").

Completion of a subtask = the call index after which its goal holds and keeps holding to the end (a subtask that
was already true at the start, like "close the fridge" before it is opened, completes when it last becomes true).
Order pair [a, b]: completion(a) <= completion(b).
"""

from __future__ import annotations

from homeloop_robot import goals as G
from homeloop_robot import oracle
from homeloop_robot.episode import make_episode
from homeloop_robot.rng import derive_seed
from homeloop_robot.types import UserEvent

MAX_CALLS = 60


def _goal_of(task) -> dict:
    return {"all": list(task["goal"]["all"])}


def completion_times(subs: list, trace_holds: list) -> list:
    """trace_holds[k][i]: subtask i holds after call k (k = 0 is the start)."""
    out = []
    for i in range(len(subs)):
        last = None
        for k, row in enumerate(trace_holds):
            if row[i] and (k == 0 or not trace_holds[k - 1][i]):
                last = k
            if not row[i]:
                last = None
        out.append(last)
    return out


def order_ok(order, comp) -> bool:
    for a, b in order or []:
        if comp[a] is None or comp[b] is None or comp[a] > comp[b]:
            return False
    return True


def run_shim(task: dict, lang: str = "en", seed: int = 0, profile: str = "ideal") -> dict:
    """{"success", "status", "calls", "reason"} for the oracle on one task record."""
    ep = make_episode(task["house"], task["seed_state"], profile, seed=derive_seed(task["id"], seed), lang=lang,
                      user_spec=task.get("user"), key=f"{task['id']}|{seed}")
    w, robot = ep.world, ep.robot
    it = (task.get("user") or {}).get("interrupt")
    if it:
        robot.schedule_interrupt(int(it["after_calls"]), UserEvent(0.0, it["kind"], it["text"][lang], it.get("new_goal")))
    if task["kind"] == "refuse":
        ok = G.evaluate(_goal_of(task), w).holds and not w.semantic_violations
        return {"success": ok, "status": "refuse", "calls": 0, "reason": "" if ok else "refuse atoms"}
    subs = task.get("subtasks") or [{"goal": _goal_of(task)}]
    order = task.get("order")
    if order:
        stages = [{"all": [a for s in subs[:i + 1] for a in s["goal"]["all"]]} for i in range(len(subs))]
    else:
        stages = [_goal_of(task)]
    holds = [[G.evaluate(s["goal"], w).holds for s in subs]]
    n, stopped, changed = 0, False, False
    if task.get("user", {}).get("gold_question"):
        robot.call("ask", question=task["user"]["gold_question"][lang], lang=lang)
    goal = None
    # delivery modes as a robot chooses them (the words and the start scene), never the labels
    text = (task.get("text") or {}).get(lang, "")
    modes = oracle.delivery_modes(w, _goal_of(task), text=text, lang=lang)
    if it and it.get("new_goal"):
        t2 = f"{text} {(it.get('text') or {}).get(lang, '')}"
        modes = {**oracle.delivery_modes(w, it["new_goal"], text=t2, lang=lang), **modes}
    while stages and not stopped:
        goal = stages[0]
        while not G.evaluate(goal, w).holds:
            if n >= MAX_CALLS:
                return {"success": False, "status": "budget", "calls": n, "reason": "call budget"}
            plan = oracle.solve(w, goal, lang=lang, modes=modes)
            if not plan:
                return {"success": False, "status": "give_up", "calls": n,
                        "reason": "no plan: " + oracle.explain_unsolvable(w, goal)}
            c = plan[0]
            r = robot.call(c.skill, **c.args)
            n += 1
            holds.append([G.evaluate(s["goal"], w).holds for s in subs])
            evs = robot.pop_events()
            if evs:
                ev = evs[0]
                if ev.kind == "stop":
                    stopped = True
                    break
                if ev.kind == "correction" and ev.new_goal:
                    goal = {"all": list(ev.new_goal["all"])}
                    stages = [goal]
                    changed = True
                    subs = [{"goal": goal}]
                    holds = [[G.evaluate(goal, w).holds]]
                    continue
            if not r.ok and r.code is not None and r.code.value != "cancelled":
                return {"success": False, "status": "give_up", "calls": n, "reason": f"{c.skill} failed: {r.msg}"}
        stages = stages[1:]
    if stopped:
        return {"success": True, "status": "done", "calls": n, "reason": "stopped"}
    final = goal if changed else _goal_of(task)
    ok = G.evaluate(final, w).holds
    why = ""
    if not ok:
        why = "goal not reached: " + ", ".join(a for a, h in G.evaluate(final, w).atoms if not h)
    if w.semantic_violations:
        ok, why = False, "semantic violation: " + w.semantic_violations[0].code
    if ok and order and not changed and not order_ok(order, completion_times(subs, holds)):
        ok, why = False, "order constraint"
    return {"success": ok, "status": "done" if ok else "give_up", "calls": n, "reason": why}


def run(task: dict, lang: str = "en") -> dict:
    """Use the bench runner when it exists, else the shim."""
    try:
        from homeloop_bench.runner import run_episode  # noqa: F401
        from homeloop_bench.tasks import Task
    except ImportError:
        return run_shim(task, lang)
    try:
        rec = run_episode(Task.from_dict(task), "oracle", "ideal", 0, lang, None)
    except Exception as e:  # noqa: BLE001 - a runner bug must not hide the shim result
        out = run_shim(task, lang)
        out["runner_error"] = type(e).__name__
        return out
    return {"success": bool(rec.get("success")), "status": rec.get("status"), "calls": rec.get("n_calls"),
            "reason": "" if rec.get("success") else f"runner status {rec.get('status')}"}
