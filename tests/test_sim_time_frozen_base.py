"""H1: SimTime.time() is a base frozen at construction plus the time slept, so a robot_agent health-wait loop
(``while time.time() < t_end``) takes exactly the same simulated time whatever the wall clock does. Through the real
adapter path: one episode with a camera fault (perception_unavailable) run twice with time.time advancing by
different wall amounts between calls gives byte-identical records, sim_time_s included."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.planners import robot_agent_adapter as A  # noqa: E402
from homeloop_bench.planners.robot_agent_adapter import SageGround2Planner, SimTime  # noqa: E402
from homeloop_bench.runner import run_episode  # noqa: E402
from homeloop_robot.episode import make_episode  # noqa: E402
from homeloop_robot.types import FailureCode, FaultState  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}


class CameraDownPlanner(SageGround2Planner):
    """sage_ground2 with the camera down from the start (clears only by a long wait), so the first find fails with
    perception_unavailable and the loop's health wait runs."""
    name = "robot_agent:test_camera_down"

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.on_loop = self._down

    @staticmethod
    def _down(loop, env):
        env.ep.world.faults["camera"] = FaultState(device="camera", code=FailureCode.PERCEPTION_UNAVAILABLE,
                                                   since_t=0.0, clears_on="wait", p_clear=1.0)
        return False


def _episode(monkeypatch, step):
    import time as _time
    real, state = _time.time, {"n": 0}

    def fake_time():
        state["n"] += 1
        return 1_700_000_000.0 + state["n"] * step     # every call moves the wall clock by `step`

    monkeypatch.setattr(_time, "time", fake_time)
    try:
        return run_episode(TASKS["fx-feas-000"], "test_sim_time_frozen_base:CameraDownPlanner", "ideal", 0, "en", "fake")
    finally:
        monkeypatch.setattr(_time, "time", real)


def test_time_is_frozen_base_plus_slept(monkeypatch):
    import time as _time
    ep = make_episode("senior_flat", 0, "ideal", 0)
    st = SimTime(ep.robot)
    t0 = st.time()
    monkeypatch.setattr(_time, "time", lambda: 5.0e9)       # the wall clock jumps; time() does not follow
    assert st.time() == t0
    st.sleep(0.25)
    assert st.time() == pytest.approx(t0 + 0.25)


def test_a_health_wait_episode_is_byte_identical_whatever_the_wall_clock_does(monkeypatch):
    waits = []
    orig = A.SimTime.sleep

    def spy(self, seconds):
        waits.append(seconds)
        return orig(self, seconds)

    monkeypatch.setattr(A.SimTime, "sleep", spy)
    a = _episode(monkeypatch, 0.0003)
    n_a, waits_a = len(waits), list(waits)
    waits.clear()
    b = _episode(monkeypatch, 0.07)
    assert n_a > 0, "the health wait ran (perception_unavailable)"
    assert [w for w in waits_a if w == pytest.approx(0.1)][:5] and waits == waits_a
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)
    assert a["sim_time_s"] == b["sim_time_s"]
