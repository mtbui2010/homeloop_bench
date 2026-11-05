"""robot_agent:sage_gold (DIAGNOSTIC, PRIVILEGED): robot_agent's AssistLoop started from the task's gold goals, understand
step skipped (robot_agent option accept_goals). Through the real adapter and loop with --llm fake (the planner is the
fake's goal planner; the language model is asked nothing). Skipped when robot_agent is not importable."""

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.env import EpisodeEnv  # noqa: E402
from homeloop_bench.gold_goals import understand_goals  # noqa: E402
from homeloop_bench.planners import REGISTRY, make_planner, planner_class  # noqa: E402
from homeloop_bench.runner import run_episode  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}


def test_registered_and_labelled_privileged():
    assert "robot_agent:sage_gold" in REGISTRY
    cls = planner_class("robot_agent:sage_gold")
    assert cls.privileged and cls.loop_options == {"accept_goals": "1"}
    rc = cls.run_config()
    assert rc["privileged"] is True and rc["accept_goals"] == 1 and rc["loop"] == "assist"
    assert "privileged" not in planner_class("robot_agent:sage").run_config()          # the other variants' records stay as they were
    assert "PRIVILEGED" in REGISTRY["robot_agent:sage_gold"][2]
    assert "accept_goals" not in planner_class("robot_agent:sage").loop_options


def test_gold_goals_are_given_and_the_understand_step_is_skipped():
    for tid in ("fx-feas-000", "fx-feas-002", "fx-feas-010"):
        e = run_episode(TASKS[tid], "robot_agent:sage_gold", "ideal", 0, "en", "fake")
        assert e["success"] and e["status"] == "done", (tid, e.get("error"), e["status"])
        assert e["llm_calls"] == 0                                                      # nobody asked the model
        b = run_episode(TASKS[tid], "robot_agent:sage", "ideal", 0, "en", "fake")
        assert b["llm_calls"] >= 1                                                      # the plain planner understands the request


def test_the_loop_gets_exactly_the_converted_gold_goals_without_a_source():
    env = EpisodeEnv(TASKS["fx-feas-004"], "ideal", 0, "en", llm=None, privileged=True)
    goals = understand_goals(env, with_source=False)
    assert goals and all(g["from"] == "" for g in goals)                                # no true location is handed over
    assert any(g["from"] for g in understand_goals(env))                                # the fake's form keeps it
    p = make_planner("robot_agent:sage_gold", llm=None)
    assert p.run_kwargs(env) == {"goals": goals}
    assert make_planner("robot_agent:sage", llm=None).run_kwargs(env) == {}


def test_clarify_is_not_asked_and_a_refusal_is_understood_as_usual():
    e = run_episode(TASKS["fx-clar-000"], "robot_agent:sage_gold", "ideal", 0, "en", "fake")
    assert e["asked"] == 0 and e["success"]                                             # the goals are known: nothing to ask
    e = run_episode(TASKS["fx-ref-000"], "robot_agent:sage_gold", "ideal", 0, "en", "fake")
    assert e["status"] == "refuse" and e["success"] and e["llm_calls"] >= 1             # no gold goal to give: the usual understanding


def test_korean_and_a_room_goal_run():
    from homeloop_bench.tasks import load_split
    anyg = next(t for t in load_split("dev") if any("any" in a for a in t.goal["all"]) and t.kind == "feasible"
                and t.n_subtasks == 1)
    for lang in ("en", "ko"):
        e = run_episode(anyg, "robot_agent:sage_gold", "ideal", 0, lang, "fake")
        assert e["success"], (anyg.id, lang, e.get("error"), e["status"])
        assert e["llm_calls"] == 0
