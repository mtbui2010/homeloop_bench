"""robot_agent planners through the homeloop robot package with --llm fake (docs/robot_agent.md).
Skipped when robot_agent is not importable."""

import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.runner import run_episode, run_many  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}
PICK = [TASKS["fx-feas-000"], TASKS["fx-clar-000"], TASKS["fx-ref-000"]]
PLANNERS = ("robot_agent:sage", "robot_agent:grace", "robot_agent:llm_direct")


@pytest.mark.parametrize("planner", PLANNERS)
def test_records_complete(planner):
    for t in PICK:
        e = run_episode(t, planner, "ideal", 0, "en", "fake")
        assert e.get("error") is None, (planner, t["id"], e.get("error"))
        assert e["status"] in ("done", "refuse", "give_up") and e["planner"] == planner
        assert isinstance(e["calls"], list)


def test_sage_feasible_clarify_refuse():
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["success"] and e["status"] == "done" and e["llm_calls"] >= 1
    e = run_episode(TASKS["fx-clar-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["asked"] >= 1
    e = run_episode(TASKS["fx-ref-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["status"] == "refuse" and e["success"]


def test_robot_package_skills_are_exercised():
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:grace", "ideal", 0, "en", "fake")
    skills = [c["skill"] for c in e["calls"]]
    assert {"move", "find", "pick"} <= set(skills)


def test_deterministic_summary(tmp_path):
    a = run_many("robot_agent:sage", "dev", None, "ideal", 1, "en", "fake", tmp_path / "a", tasks=PICK)
    b = run_many("robot_agent:sage", "dev", None, "ideal", 1, "en", "fake", tmp_path / "b", tasks=PICK)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert (tmp_path / "a" / "summary.json").read_bytes() == (tmp_path / "b" / "summary.json").read_bytes()


def test_backend_restored_after_episode():
    from homeloop_robot.configs import backend as hb
    before = hb._backend
    run_episode(TASKS["fx-feas-000"], "robot_agent:llm_direct", "ideal", 0, "en", "fake")
    assert hb._backend is before


def test_correction_is_injected_into_the_sage_run():
    e = run_episode(TASKS["fx-cor-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["goal_changed"] and e["events"][0]["kind"] == "correction"
    assert not any(c["code"] == "cancelled" for c in e["calls"])     # injected, not a cancelled call
