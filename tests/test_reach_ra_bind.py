"""Moves and places to a person through robot_agent's REAL AssistLoop bind path (R2-5 B1, B2).

robot_agent's ``AssistLoop._bind`` replaces the adapter's bind result with the raw ENV key for MoveTo / Place,
so the robot package's skill functions (configs/ra_skills.py) receive the person's ENV key. These tests build the
AssistLoop the bench runs (same patches as planners/robot_agent_adapter.py), bind each step with its own
``_bind`` and execute it with robot_agent's ``run_skill`` over the homeloop registry.
"""

import contextlib
import glob
import math
import os
import types

import pytest

pytest.importorskip("robot_agent")

from homeloop_robot.catalog import CLASSES  # noqa: E402
from homeloop_robot.configs.backend import reset_backend, set_backend  # noqa: E402
from homeloop_robot.configs.tasks import RESERVED_USER_WORDS, env_for, person_key  # noqa: E402
from homeloop_robot.episode import make_episode  # noqa: E402

import homeloop_robot  # noqa: E402

HOUSES = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(
    os.path.dirname(homeloop_robot.__file__), "houses", "*.yaml")))


@contextlib.contextmanager
def assist_loop(world, tmp_path):
    """The AssistLoop of robot_agent:sage with ENV = env_for(world), as the bench planner builds it."""
    import robot_agent.core.planning.assist_loop as AL
    import robot_agent.core.planning.loop as LP
    import robot_agent.skill_configs as sc
    import robot_agent.state as state_mod
    from homeloop_bench.planners.robot_agent_adapter import (FakeNode, FakeState, HomeloopRegistry, SagePlanner,
                                                             _patched)
    node = FakeNode()
    state = FakeState(tmp_path, node)
    cur = (lambda: state)
    env = env_for(world)
    pairs = [(AL, "current", cur), (LP, "current", cur), (state_mod, "current", cur),
             (AL, "host_id", lambda: "homeloop"), (LP, "host_id", lambda: "homeloop"), (sc, "ENV", env)]
    with _patched(pairs):
        agent = types.SimpleNamespace(skill_registry=HomeloopRegistry(),
                                      device_manager=types.SimpleNamespace(_ros_node=node),
                                      _llm_cfg={"name": "llama", "url": "http://127.0.0.1:9", "model": "", "num_ctx": 8192})
        loop = SagePlanner()._make_loop(agent, tmp_path, True)
        yield loop, env


def _step(loop, action, key):
    """Bind with AssistLoop._bind (the real path) and run it with robot_agent's run_skill."""
    from robot_agent.core.planning.base import WorldState
    from robot_agent.core.planning.robot import run_skill
    skill, params = loop._bind({"action": action, "object": key}, WorldState())
    assert params["inputs"] == key            # the loop passes the raw ENV key, not the adapter's result
    return run_skill(loop.sr, skill, params, None)


def _hold_something(ep, loop, env):
    """Pick a liftable object from an open support surface (ideal profile), through the loop's own steps."""
    w = ep.world
    for oid in sorted(w.objects):
        o = w.objects[oid]
        c = CLASSES.get(o.cls)
        if c is None or not c.liftable or o.at not in env or w.is_container(o.at):
            continue
        if _step(loop, "MoveTo", o.at).ok and _step(loop, "Find", oid).ok and _step(loop, "Pick", oid).ok:
            return oid
    return None


def _cases():
    out = []
    for h in HOUSES:
        ep = make_episode(h, 0, "ideal", 0)
        for pid in sorted(ep.world.people):
            out.append((h, pid))
    return out


@pytest.mark.parametrize("house,pid", _cases())
def test_move_to_a_person_ends_at_its_env_loc(house, pid, tmp_path):
    ep = make_episode(house, 0, "ideal", 0)
    set_backend(ep.robot)
    try:
        with assist_loop(ep.world, tmp_path) as (loop, env):
            key = person_key(pid)
            loc = env[key]["loc"]
            tol = loop.cfg["arrive_tol"]
            # from the start pose, then from every other room's first place (the robot rarely comes from the dock)
            starts = [None] + sorted({min(k for k, e in env.items() if not e.get("person")
                                          and ep.world.house.places[k].room == r)
                                      for r in ep.world.house.rooms
                                      if any(not e.get("person") and ep.world.house.places[k].room == r
                                             for k, e in env.items())})
            n = 0
            for s in starts:
                if s is not None and not _step(loop, "MoveTo", s).ok:
                    continue                  # a start the safety monitor stops (a person in the way)
                n += 1
                r = _step(loop, "MoveTo", key)
                assert r.ok, (house, pid, s, r.msg)
                x, y = ep.world.robot.pose[:2]
                d = math.hypot(x - loc["x"], y - loc["y"])
                assert d <= tol, (house, pid, s, round(d, 3), env[key].get("spot"))
            assert n >= 2
    finally:
        reset_backend()


@pytest.mark.parametrize("house,pid", _cases())
def test_place_on_a_person_uses_the_spot(house, pid, tmp_path):
    ep = make_episode(house, 0, "ideal", 0)
    set_backend(ep.robot)
    try:
        with assist_loop(ep.world, tmp_path) as (loop, env):
            key = person_key(pid)
            spot = env[key]["spot"]
            oid = _hold_something(ep, loop, env)
            assert oid is not None, house
            assert _step(loop, "MoveTo", key).ok
            r = _step(loop, "Place", key)
            if spot is not None:
                assert r.ok, (house, pid, r.msg)
                assert ep.world.objects[oid].at == spot and ep.world.robot.holding is None
            else:
                # no surface beside the person: a Place on a person fails, it is never turned into a handover
                assert not r.ok
                assert ep.world.robot.holding == oid and not str(ep.world.objects[oid].at).startswith("person:")
    finally:
        reset_backend()


def test_some_people_have_no_spot_and_some_have_one():
    have, none = 0, 0
    for h in HOUSES:
        ep = make_episode(h, 0, "ideal", 0)
        for k, e in env_for(ep.world).items():
            if e.get("person"):
                have += e["spot"] is not None
                none += e["spot"] is None
    assert have and none


def test_no_env_key_is_a_robot_agent_user_word():
    import robot_agent.core.planning.assist_loop as AL
    assert set(AL._USER_WORDS) <= set(RESERVED_USER_WORDS)
    seen_alias = False
    for h in HOUSES:
        ep = make_episode(h, 0, "ideal", 0)
        env = env_for(ep.world)
        for k in env:
            w = AL.words(k)
            assert w not in AL._USER_WORDS and AL._strip_article(w) not in AL._USER_WORDS, (h, k)
        for pid in ep.world.people:
            key = person_key(pid)
            assert env[key]["person"] == pid
            seen_alias |= key != pid
    assert seen_alias            # korean_apt_59 / studio_flat: person 'user'


@pytest.mark.parametrize("house", ["korean_apt_59", "studio_flat"])
def test_reserved_person_alias_maps_back(house, tmp_path):
    ep = make_episode(house, 0, "ideal", 0)
    set_backend(ep.robot)
    try:
        with assist_loop(ep.world, tmp_path) as (loop, env):
            assert "user" not in env and "person_user" in env
            from homeloop_robot.configs.adapter import make_adapter
            ad = make_adapter()
            assert ad.bind({"action": "Handover", "object": "person_user"}) == ("handover", {"inputs": "user"})
            oid = _hold_something(ep, loop, env)
            assert _step(loop, "MoveTo", "person_user").ok
            from robot_agent.core.planning.robot import run_skill
            skill, params = ad.bind({"action": "Handover", "object": "person_user"})
            assert run_skill(loop.sr, skill, params, None).ok
            assert ep.world.objects[oid].at == "person:user"
    finally:
        reset_backend()
