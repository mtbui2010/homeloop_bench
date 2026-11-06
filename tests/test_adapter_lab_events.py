"""Adapter: the lab-flag events reach episodes.jsonl, every loop option is recorded in planner_config, and the wait
variants see the (assumed) schedule through the pack's own Wait action. Skipped when robot_agent is not importable."""
import json
import types

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.planners import robot_agent_adapter as A  # noqa: E402
from homeloop_bench.runner import run_episode, run_many  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}


def test_run_config_records_every_loop_option():
    from homeloop_bench.planners import planner_class
    cfg = planner_class("robot_agent:sage_r3").run_config()
    assert cfg["loop_options"] == {"exec_integrity": "1", "go_steps": "1", "inventory_ask": "1", "kind_anchor": "1",
                                   "name_canon": "1"}
    assert planner_class("robot_agent:sage_ground2").run_config()["loop_options"]["go_steps"] == "1"
    assert planner_class("robot_agent:sage_reask").run_config()["loop_options"] == {"reask_abstain": "1"}
    assert "loop_options" not in planner_class("robot_agent:sage").run_config()          # summary.json as before
    assert "manifest_overlay" not in planner_class("robot_agent:sage").run_config()


def test_run_config_records_the_wait_schedule():
    from homeloop_bench.planners import planner_class
    for name in ("robot_agent:sage_exec", "robot_agent:sage_ei_wait", "robot_agent:sage_r3"):
        ov = planner_class(name).run_config()["manifest_overlay"]
        assert ov["planner"]["recovery"]["wait"] == {"action": "Wait", "schedule_s": [2, 4, 8]} and ov["assumed"] is True
    assert "manifest_overlay" not in planner_class("robot_agent:sage_ei_gate").run_config()


def test_reset_container_variants_declare_the_blocked_putin_remedy():
    from homeloop_bench.planners import planner_class
    for name in ("robot_agent:sage_exec", "robot_agent:sage_ei_reset", "robot_agent:sage_r3", "robot_agent:sage_r3u"):
        ov = planner_class(name).run_config()["manifest_overlay"]
        assert ov["planner"]["recovery"]["blocked_putin"] == ["Close", "Open"] and ov["assumed"] is True
    ov = planner_class("robot_agent:sage_ei_wait").run_config()["manifest_overlay"]
    assert "blocked_putin" not in ov["planner"]["recovery"]


def test_summary_carries_the_overlay(tmp_path):
    s = run_many("robot_agent:sage_ei_wait", "dev", None, "ideal", 1, "en", "fake", tmp_path, tasks=[TASKS["fx-feas-000"]])
    assert s["config"]["planner_config"]["manifest_overlay"]["planner"]["recovery"]["wait"]["schedule_s"] == [2, 4, 8]


def _capture_loop(monkeypatch):
    got = []
    orig = A._RobotAgentPlanner._make_loop

    def make(self, agent, tmp, fake):
        loop = orig(self, agent, tmp, fake)
        got.append(loop)
        return loop
    monkeypatch.setattr(A._RobotAgentPlanner, "_make_loop", make)
    return got


def test_the_wait_variant_sees_the_schedule_and_binds_the_packs_wait(monkeypatch):
    got = _capture_loop(monkeypatch)
    run_episode(TASKS["fx-feas-000"], "robot_agent:sage_ei_wait", "ideal", 0, "en", "fake")
    loop = got[0]
    assert loop.cfg["wait_on_robot"] is True
    assert loop._manifest_planner("recovery")["wait"] == {"action": "Wait", "schedule_s": [2, 4, 8]}
    from robot_agent.core.planning.exec_integrity import wait_schedule
    assert wait_schedule(loop._manifest_planner("recovery")["wait"]) == ("Wait", [2.0, 4.0, 8.0])
    skill, params = loop._bind({"action": "Wait", "object": "4"}, loop.robot.adapter and types.SimpleNamespace(arrived=None))
    assert skill == "wait" and str(params.get("inputs")) == "4"


def test_a_variant_without_the_overlay_sees_no_schedule(monkeypatch):
    got = _capture_loop(monkeypatch)
    run_episode(TASKS["fx-feas-000"], "robot_agent:sage_exec", "ideal", 0, "en", "fake")
    run_episode(TASKS["fx-feas-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert got[0]._manifest_planner("recovery")["wait"]["schedule_s"] == [2, 4, 8]
    assert got[1]._manifest_planner("recovery") is None


def test_the_pack_manifest_file_is_not_changed_by_the_overlay(monkeypatch):
    run_episode(TASKS["fx-feas-000"], "robot_agent:sage_ei_wait", "ideal", 0, "en", "fake")
    assert "recovery" not in A.manifest_planner()


def test_lab_events_are_copied_into_the_episode(monkeypatch):
    log = [{"flag": "go_steps", "dropped": 1}, {"flag": "reset_container", "container": "c", "held": "o", "source": "s"}]
    orig = A._RobotAgentPlanner._make_loop

    def make(self, agent, tmp, fake):
        loop = orig(self, agent, tmp, fake)
        real_run = loop.run_blocking

        def run_blocking(*a, **k):
            yield from real_run(*a, **k)
            loop.lab_log = list(log)                    # what a flag would have written
        loop.run_blocking = run_blocking
        return loop
    monkeypatch.setattr(A._RobotAgentPlanner, "_make_loop", make)
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage_ground2", "ideal", 0, "en", "fake")
    assert e["lab_events"] == log


def test_episode_has_lab_events_only_for_variants_with_options(tmp_path):
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert "lab_events" not in e
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage_exec", "ideal", 0, "en", "fake")
    assert e["lab_events"] == [] or all("flag" in x for x in e["lab_events"])
    e2 = run_episode(TASKS["fx-feas-000"], "robot_agent:sage_exec", "ideal", 0, "en", "fake")
    assert json.dumps(e, sort_keys=True) == json.dumps(e2, sort_keys=True)


def test_unstick_variant_is_registered_and_recorded():
    from homeloop_bench.planners import planner_class
    cfg = planner_class("robot_agent:sage_unstick").run_config()
    assert cfg["loop_options"] == {"dialog_unstick": "1"} and cfg["dialog_unstick"] == 1


def test_unstick_variant_runs_and_logs_nothing_on_a_clean_task():
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage_unstick", "ideal", 0, "en", "fake")
    assert e["success"] and e["lab_events"] == []


def test_sage_r3u_is_registered_and_is_sage_r3_plus_dialog_unstick():
    from homeloop_bench.planners import REGISTRY, list_planners, planner_class
    assert "robot_agent:sage_r3u" in REGISTRY
    assert "robot_agent:sage_r3u" in [n for n, _d, _ok in list_planners()]
    cfg = planner_class("robot_agent:sage_r3u").run_config()
    r3 = planner_class("robot_agent:sage_r3").run_config()
    assert cfg["loop_options"] == {**r3["loop_options"], "dialog_unstick": "1"}
    assert cfg["manifest_overlay"] == r3["manifest_overlay"]
    # the loop accepts the option (an unknown one is dropped)
    import robot_agent.core.planning.assist_loop as AL
    assert set(cfg["loop_options"]) <= AL.ASSIST_OPTIONS
