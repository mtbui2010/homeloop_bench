"""30-task gate, round 1 fixes on the bench side (docs/experiments.md "Pilot rounds").

hl-dev-000028 KO: SAGE planned {"action": "Wait", "object": 5}; robot_agent's planner crashed on the int ("'int'
object has no attribute 'strip'") and ended the run "failed" with code software. The episode was scored as a plain
give_up, so n_error did not see the crash. It is status error now (error RobotAgentSoftwareError)."""
import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.metrics import summarize  # noqa: E402
from homeloop_bench.planners import robot_agent_adapter as ad  # noqa: E402
from homeloop_bench.planners.robot_agent_fake import GoalPlanner  # noqa: E402
from homeloop_bench.runner import run_episode  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}


class CrashingPlanner(GoalPlanner):
    """A generator whose own code raises, as robot_agent's did on the 028 step's int object."""

    def generate_plan(self, task, obs, visible_objects):
        return (5).strip(), {}

    def replan(self, task, completed, failed_step, failure_reason, obs, visible_objects):
        return (5).strip(), {}


def test_software_crash_of_the_stored_028_final_event():
    final = {"status": "failed", "code": "software", "device": "planner",
             "msg": "the planner failed: 'int' object has no attribute 'strip'",
             "evidence": {"call": "planner", "error": "'int' object has no attribute 'strip'"}}
    assert ad._software_crash(final)
    # the LLM server down / a timeout, or a skill's failure, is not a crash of the planner's code
    assert not ad._software_crash({**final, "code": "hw_fault"})
    assert not ad._software_crash({**final, "code": "timeout"})
    assert not ad._software_crash({"status": "failed", "code": "software", "msg": "pick failed"})
    assert not ad._software_crash({"status": "success"})
    assert not ad._software_crash(None)


def test_a_planner_crash_is_status_error(monkeypatch):
    monkeypatch.setattr(ad, "FAKE_GENERATOR", f"{__name__}:CrashingPlanner")
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["status"] == "error", (e["status"], e.get("final_say"))
    assert e["error"] == "RobotAgentSoftwareError" and "strip" in e["error_msg"], e.get("error_msg")
    assert not e["success"] and not e["claimed"]
    s = summarize([e], {})
    assert s["n_error"] == 1 and s["errors_by_type"] == {"RobotAgentSoftwareError": 1}


def test_a_normal_fake_run_is_not_an_error():
    e = run_episode(TASKS["fx-feas-000"], "robot_agent:sage", "ideal", 0, "en", "fake")
    assert e["status"] == "done" and e.get("error") is None


def test_008_person_spot_refresh_reaches_robot_agents_own_copy_of_the_env(monkeypatch):
    """hl-dev-000008: the nightstand beside grandma was full at the start (the blue book the task moves), so her ENV
    entry had no spot. After the book is gone, a move to her goes to the nightstand, and robot_agent's own copy of
    the ENV (AssistLoop's ``Places(dict(ENV))``, which its arrival check reads) sees the new loc."""
    import math

    from robot_agent.core.planning.assist_loop import Places

    from homeloop_bench.env import EpisodeEnv
    from homeloop_bench.runner import load_tasks
    from homeloop_robot.configs import backend as hb
    from homeloop_robot.configs import ra_skills
    from homeloop_robot.configs.tasks import env_for, person_key

    task = next(t for t in load_tasks("dev", 30, None) if (t["id"] if isinstance(t, dict) else t.id) == "hl-dev-000008")
    env = EpisodeEnv(task, "ideal", 0, "en")
    w = env._world
    ENV = env_for(w)
    key = person_key(w, "grandma")
    assert ENV[key]["spot"] is None and w.objects["book_2"].at == "nightstand@bedroom"
    places = Places(dict(ENV))
    monkeypatch.setattr(ra_skills, "_env", lambda: ENV)
    old = hb._backend
    hb.set_backend(env.robot)
    try:
        robot = hb.get_backend()
        assert ra_skills.move(None, inputs="nightstand@bedroom")["isdone"]
        assert ra_skills.find(None, inputs="blue book")["isdone"] and ra_skills.pick(None, inputs="blue book")["isdone"]
        assert ra_skills.move(None, inputs="tv_stand@living")["isdone"]
        assert ra_skills.place(None, inputs="tv_stand@living")["isdone"]
        assert ra_skills.move(None, inputs="counter@kitchen")["isdone"]
        assert ra_skills.find(None, inputs="water bottle")["isdone"]
        assert ra_skills.pick(None, inputs="water bottle")["isdone"]
        assert ra_skills.move(None, inputs=key)["isdone"]
        loc = places.env[key]["loc"]
        assert places.env[key]["spot"] == "nightstand@bedroom"
        assert math.dist(robot.world.robot.pose[:2], (loc["x"], loc["y"])) <= 0.3
        assert ra_skills.place(None, inputs=key)["isdone"]
        assert w.objects["water_bottle_1"].at == "nightstand@bedroom"
    finally:
        hb.set_backend(old)
