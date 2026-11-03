"""``oracle``: the privileged closed-loop reference planner (docs/planners.md).

Reads the TRUE world and the hidden goal. After every call it re-solves from the true state with
``homeloop_robot.oracle.solve``; per (skill, args) at most 3 consecutive attempts; ``wait(5)`` before
retrying perception_unavailable / blocked; an ``ask`` for help with a blocked path when the user can hear
the robot (STRANDS-style human help), else a wait. The follow-up policy is
``homeloop_robot.oracle.recovery_call``, shared with ``homeloop_robot.oracle.rollout``; before the last attempt of a
move that stays blocked it backs off to the room's floor spot (or its start place) and comes another way. Clarify tasks: it asks the gold question once (for the help metrics) and then acts on the true
intent. Refuse tasks: ``finish("refuse")``; mixed tasks: it declines the refuse part and does the rest.
It finishes ``done`` only when the judge would score success, so its false-success rate is 0.

Deliveries (docs/runner.md, "Delivery"): the oracle never reads an atom's ``mode`` label. It chooses reach or hand
itself, once, from what a robot observes when it gets the request (:func:`observed_modes`: the heard instruction,
the house profile and the furniture around the person at the start, ``homeloop_robot.oracle.delivery_modes``), and
for a correction's new deliveries with the correction's words added. In reach mode the robot oracle puts the
object on the nearest reachable support surface with room where the person is now, else hands it over.
"""

from __future__ import annotations

from homeloop_robot import oracle as _oracle

from .base import refusal_text

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
        done = {i: G.evaluate(subs[i]["goal"], env.truth).holds for i in use}
        use = [i for i in use if all(done.get(a, True) for a, b in env.order if b == i)]
    atoms = []
    for i in use:
        atoms += [a for a in subs[i]["goal"]["all"] if a.get("pred") != "unmoved"]
    return {"all": atoms}


def note_refusals(env) -> None:
    """Decline every refuse subtask of a mixed task by index and object (the judge ties a refusal to its
    subtask)."""
    for i, s in enumerate(env.subtasks):
        if s["kind"] != "refuse":
            continue
        objs = [a["args"][0] for a in s["goal"]["all"] if a.get("pred") == "unmoved" and a.get("args")]
        env.note_refusal("I won't do the unsafe part.", subtask=i, obj=objs[0] if objs else None)


def gold_question(env):
    gq = (env.task.get("user") or {}).get("gold_question")
    if isinstance(gq, dict):
        return gq.get(env.lang) or gq.get("en")
    return gq or None


def gold_meaning(env) -> dict:
    """The structured form of the gold clarification question (homeloop_robot docs/user_model.md): which object
    or which place, with the candidates as the question names them."""
    u = env.task.get("user") or {}
    opts = []
    for c in u.get("candidates") or []:
        m = ((c.get("mentions") or {}).get(env.lang) or (c.get("mentions") or {}).get("en") or [c.get("id")])
        opts.append(str(m[0]))
    qt = "which_place" if u.get("slot") == "destination" else "which_object"
    return {"qtype": qt, "options": opts} if opts else {"qtype": qt}


def heard_text(env) -> str:
    """The instruction as heard, plus the words of every correction said so far."""
    extra = [str(e.get("text") or "") for e in env._events if e.get("kind") == "correction"]
    return " ".join([env.task_text] + extra).strip()


def observed_modes(env, world, goal: dict, people_pos=None) -> dict:
    """{(obj, person): reach | hand} chosen from the heard words and the scene (never the goal's labels)."""
    return _oracle.delivery_modes(world, goal, text=heard_text(env), lang=env.lang, people_pos=people_pos)


def retreat_place(w):
    """Where to back off to when a move stays blocked by a person who cannot clear the way (e.g. in bed next to
    the target): the floor spot of the robot's room, else the robot's start place; None when already there."""
    room = w.room_of(tuple(w.robot.pose[:2]))
    floors = sorted(pid for pid, p in w.house.places.items() if p.kind == "floor" and p.room == room)
    for cand in floors + [w.house.robot_start]:
        if cand != w.robot.at:
            return cand
    return None


class OraclePlanner:
    name = "oracle"
    privileged = True
    needs_llm = False
    description = "privileged: re-solves from the true world after every call, retries, waits, asks for help"
    qtypes = ("which_object", "which_place", "help")      # the structured questions it asks (meaning=)

    def __init__(self, llm=None):
        pass

    def run(self, env) -> None:
        w = env.truth
        kinds = task_kinds(env)
        if kinds and all(k == "refuse" for k in kinds):
            env.finish("refuse", refusal_text(env.lang))
            return
        note_refusals(env)
        is_clarify = env.task.get("kind") == "clarify" or "clarify" in kinds
        q = gold_question(env)
        if is_clarify and q:
            env.call("ask", question=q, lang=env.lang, meaning=gold_meaning(env))
        fails: dict = {}
        modes, modes_key = None, None
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
            key = (len(env._events), env.goal_changed)
            if modes is None or key != modes_key:
                # once at the start, and again after a user event (a correction brings new words and goals);
                # from the scene the robot saw when it got the request (the start), choices already made are kept
                modes = {**observed_modes(env, env.world0, env.current_goal()), **(modes or {})}
                modes_key = key
            plan = _oracle.solve(w, target, lang=env.lang, people_pos=people, modes=modes) if target["all"] else []
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
            if code == "blocked" and c.skill == "move" and fails[key] == MAX_ATTEMPTS - 1:
                back = retreat_place(w)
                if back is not None:
                    env.call("move", target=back)     # back off and come another way (last try)
                    continue
            rc = _oracle.recovery_call(code, c.skill, w, env.user, env.ep.clock.t, env.lang)
            if rc is not None:
                env.call(rc.skill, **rc.args)
