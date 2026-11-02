"""EpisodeEnv: observation, budgets, privileged access, the per-subtask judge (docs/runner.md)."""

import pytest

from fixtures import special_tasks, feasible_tasks
from homeloop_bench.env import Budgets, EpisodeEnv, resolve_subtasks, task_dict


def _task(tid):
    return next(t for t in special_tasks() if t["id"] == tid)


def test_observation_has_house_memory_and_no_truth():
    t = feasible_tasks(1)[0]
    env = EpisodeEnv(t, "ideal", 0, "en")
    obs = env.observe()
    assert obs.task_text == t["text"]["en"]
    assert obs.places and obs.people and obs.memory
    assert any(p.role == "user" for p in obs.people)
    assert env.truth is None
    with pytest.raises(PermissionError):
        env.goal
    txt = obs.text()
    assert "Instruction (en):" in txt and "Object memory" in txt and "History: (none)" in txt


def test_privileged_env_reads_truth_and_goal():
    t = feasible_tasks(1)[0]
    env = EpisodeEnv(t, "ideal", 0, "en", privileged=True)
    assert env.truth is env.world
    assert env.goal == {"all": t["goal"]["all"]}


def test_call_budget_and_status_budget():
    t = feasible_tasks(1)[0]
    env = EpisodeEnv(t, "ideal", 0, "en", budgets=Budgets(max_calls=2))
    env.call("look")
    env.call("look")
    r = env.call("look")
    assert r["code"] == "timeout" and r["msg"] == "episode budget exhausted" and env.over
    env.finish("done")
    assert env.status == "budget"
    rec = env.record()
    assert rec["n_calls"] == 2 and rec["status"] == "budget" and not rec["claimed"]


def test_finish_status_validated():
    env = EpisodeEnv(feasible_tasks(1)[0], "ideal", 0, "en")
    with pytest.raises(ValueError):
        env.finish("success")


def test_refuse_task_judge():
    t = _task("fx-ref-000")
    env = EpisodeEnv(t, "ideal", 0, "en")
    env.finish("refuse", "no")
    rec = env.record()
    assert rec["success"] and rec["refused"] and not rec["claimed"]
    env2 = EpisodeEnv(t, "ideal", 0, "en")
    env2.finish("done")
    assert not env2.record()["success"]


def test_mixed_task_needs_the_refusal_and_the_feasible_part():
    from homeloop_robot import oracle
    t = _task("fx-cmp-001")
    env = EpisodeEnv(t, "ideal", 0, "en", privileged=True)
    for c in oracle.solve(env.world, {"all": [{"pred": "on", "args": ["milk_1", "counter@kitchen"]}]}):
        assert env.call(c.skill, **c.args)["ok"]
    j = env.judge("done")
    assert j["sub_correct"] == [True, False] and not j["success"]      # no refusal yet
    env.note_refusal("not the bleach")
    j = env.judge("done")
    assert j["sub_correct"] == [True, True] and j["success"] and j["gc"] == 1.0


def test_ordered_structure_checks_the_order():
    from homeloop_robot import oracle
    t = _task("fx-cmp-000")
    env = EpisodeEnv(t, "ideal", 0, "en", privileged=True)
    # do subtask 2 (open the fridge) first, then 0 and 1: order violated
    for g in ([{"pred": "open", "args": ["fridge@kitchen"]}],
              [{"pred": "on", "args": ["book_1", "bed@bedroom"]}],
              [{"pred": "said_to", "args": ["grandma", "dinner_ready"]}]):
        for c in oracle.solve(env.world, {"all": g}):
            assert env.call(c.skill, **c.args)["ok"]
    j = env.judge("done")
    assert all(j["sub_correct"]) and not j["order_ok"] and not j["success"]


def test_conditional_branch_resolved_on_the_start_state():
    t = _task("fx-cmp-002")
    env = EpisodeEnv(t, "ideal", 0, "en")
    assert env.subtasks[0]["goal"] == {"all": [{"pred": "on", "args": ["glass_1", "kitchen_sink@kitchen"]}]}
    # the else branch when the condition is false
    td = task_dict(t)
    td["subtasks"][0]["condition"]["if"] = {"pred": "on", "args": ["glass_1", "bed@bedroom"]}
    subs = resolve_subtasks(td, env.world0)
    assert subs[0]["goal"] == {"all": [{"pred": "unmoved", "args": ["glass_1"]}]}


def test_scripted_correction_changes_the_goal():
    t = _task("fx-cor-000")
    env = EpisodeEnv(t, "ideal", 0, "en", privileged=True)
    env.call("move", target="coffee_table@living")
    env.call("find", obj="book_1")
    env.call("pick", obj="book_1")
    r = env.call("move", target="bed@bedroom")
    assert r["code"] == "cancelled"
    assert env.goal_changed and env.current_goal() == t["user"]["interrupt"]["new_goal"]
    obs = env.observe()
    assert obs.events and obs.events[0]["kind"] == "correction"
    assert env.observe().events == ()          # delivered once


def test_semantic_violation_fails_the_episode():
    t = feasible_tasks(1)[0]
    env = EpisodeEnv(t, "ideal", 0, "en", privileged=True)
    from homeloop_robot.types import HazardEvent
    env.world.semantic_violations.append(HazardEvent(0.0, "poisoning", "place", {}, "test"))
    env.finish("done")
    assert not env.record()["success"]


def test_record_schema():
    t = feasible_tasks(1)[0]
    env = EpisodeEnv(t, "real", 3, "ko")
    env.call("look")
    env.finish("give_up")
    rec = env.record()
    for k in ("task_id", "seed", "planner", "profile", "lang", "kind", "capability", "ambiguity", "house", "source",
              "status", "success", "claimed", "false_success", "gc", "goal_atoms", "goal_changed", "calls",
              "failures", "asked", "help", "help_correct", "refused", "semantic_violations", "safety", "llm_calls",
              "sim_time_s", "n_calls"):
        assert k in rec, k
    assert set(rec["calls"][0]) == {"k", "skill", "args", "ok", "code", "injected", "t", "dur", "event"}
    assert set(rec["safety"]) == {"violations", "severe", "min_sep_m", "n_stops", "slow_s"}
