"""D1 bench-side retry: RobotProxy repeats only safe skills on transient failures, attempts counts the first call."""
import types
from homeloop_bench.planners.robot_agent_adapter import RobotProxy, SageS8nD1Planner, SageS8nPlanner
from homeloop_robot.types import FailureCode, SkillResult


def _proxy(codes, attempts):
    seq = list(codes)
    p = RobotProxy.__new__(RobotProxy)
    p.attempts, p.retries = attempts, 0
    p.calls = []

    def once(skill, **a):
        p.calls.append(skill)
        c = seq.pop(0)
        return SkillResult(ok=c is None, code=c or FailureCode.SOFTWARE, msg="", data={}, duration_s=0.0)
    p._call_once = once
    return p


def test_default_is_single_call():
    p = _proxy([FailureCode.HW_FAULT], 1)
    assert not p.call("move", target="a").ok and p.calls == ["move"]


def test_transient_failure_retried_once_in_total_two():
    p = _proxy([FailureCode.HW_FAULT, None], 2)
    assert p.call("move", target="a").ok and p.calls == ["move", "move"] and p.retries == 1
    q = _proxy([FailureCode.HW_FAULT, FailureCode.HW_FAULT, None], 2)
    assert not q.call("move", target="a").ok and len(q.calls) == 2


def test_unsafe_or_final_failures_not_retried():
    for skill, code in (("pick", FailureCode.HW_FAULT), ("place", FailureCode.TIMEOUT), ("move", FailureCode.ESTOP),
                        ("move", FailureCode.CANCELLED), ("ask", FailureCode.TIMEOUT), ("look", FailureCode.ABSENT)):
        p = _proxy([code, None], 2)
        p.call(skill)
        assert len(p.calls) == 1, (skill, code)
    p = _proxy([FailureCode.ABSENT, None], 2)
    assert p.call("find", obj="x").ok


def test_variant_setup_is_declared_and_base_unchanged():
    assert SageS8nD1Planner.skill_attempts == 2
    o = SageS8nD1Planner.loop_options
    assert (o["search_legs"], o["search_total"], o["detector_miss_rate"]) == (1, 6, 0)
    assert not hasattr(SageS8nPlanner, "skill_attempts") and "search_total" not in SageS8nPlanner.loop_options
