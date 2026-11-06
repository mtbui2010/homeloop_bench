"""Consistency fix (not tuning): a robot_agent planner that waits (sleeps while polling its sensor health) lets
simulated time pass, the same for every robot. Before, the adapter set health_wait_s=0, so the wait cost no simulated
time and a camera fault that clears on waiting never cleared by waiting."""
import pytest

pytest.importorskip("robot_agent")

from homeloop_bench.planners.robot_agent_adapter import HEALTH_WAIT_S, SimTime  # noqa: E402
from homeloop_robot.episode import make_episode  # noqa: E402
from homeloop_robot.types import FailureCode  # noqa: E402
from homeloop_robot.types import FaultState  # noqa: E402


def _camera_down(ep, p_clear=1.0):
    ep.world.faults["camera"] = FaultState(device="camera", code=FailureCode.PERCEPTION_UNAVAILABLE, since_t=0.0,
                                           clears_on="wait", p_clear=p_clear)


def test_sleep_advances_the_simulated_clock_not_the_wall_clock():
    import time
    ep = make_episode("senior_flat", 0, "ideal", 0)
    st = SimTime(ep.robot)
    w0, t0 = time.time(), ep.clock.t
    st.sleep(30.0)
    assert ep.clock.t == pytest.approx(t0 + 30.0) and time.time() - w0 < 5.0
    assert st.time() - w0 >= 30.0 - 1e-6          # a deadline loop sees the wait as having happened
    st.sleep(-1.0)
    assert ep.clock.t == pytest.approx(t0 + 30.0)


def test_a_deadline_wait_loop_costs_simulated_time_and_ends():
    ep = make_episode("senior_flat", 0, "ideal", 0)
    st = SimTime(ep.robot)
    t_end = st.time() + HEALTH_WAIT_S
    n = 0
    while st.time() < t_end:
        st.sleep(min(0.1, max(0.0, t_end - st.time())))
        n += 1
        assert n < 100
    assert ep.clock.t >= 0.9 * HEALTH_WAIT_S


def test_a_long_idle_clears_a_camera_fault_like_the_wait_skill():
    ep = make_episode("senior_flat", 0, "ideal", 0)
    _camera_down(ep)
    st = SimTime(ep.robot)
    st.sleep(2.0)
    assert "camera" in ep.world.faults          # too short, as for the wait skill (< 5 s)
    st.sleep(3.0)
    assert "camera" not in ep.world.faults


def test_a_skill_call_between_two_short_waits_restarts_the_idle_run():
    ep = make_episode("senior_flat", 0, "ideal", 0)
    _camera_down(ep)
    ep.robot.idle(3.0)
    ep.robot.call("say", text="hello")
    ep.robot.idle(3.0)
    assert "camera" in ep.world.faults
