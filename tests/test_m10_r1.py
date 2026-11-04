"""Milestone 10, round 1 fixes on the bench side (docs/experiments.md "SAGE-v2 changes")."""
import pytest

pytest.importorskip("robot_agent")

from homeloop_bench.planners import robot_agent_adapter as ad  # noqa: E402


def test_a_stopped_run_never_says_an_english_placeholder_in_korean():
    assert ad.stopped_say(None, "ko") == "멈췄어요."
    assert ad.stopped_say({"say": ""}, "en") == "Stopped."
    assert ad.stopped_say({"say": "알겠어요, 멈출게요."}, "ko") == "알겠어요, 멈출게요."
