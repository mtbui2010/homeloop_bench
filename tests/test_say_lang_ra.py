"""R2-6 H1 through robot_agent's REAL AssistLoop (robot_agent:sage, --llm fake): a Korean message task
(hl-dev-000040, "tell dad lunch is ready") is said in Korean, so the Korean listener gets it (said_to holds).
robot_agent passes ``lang`` only to Ask; the robot package's Say takes the language of the text."""
import json
from pathlib import Path

import pytest

pytest.importorskip("robot_agent")

from homeloop_bench.runner import run_episode  # noqa: E402

DEV = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks" / "dev.jsonl"


def _task(tid):
    for line in DEV.open(encoding="utf-8"):
        if f'"id":"{tid}"' in line:
            return json.loads(line)
    raise KeyError(tid)


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_message_task_is_said_in_the_episode_language(lang):
    t = _task("hl-dev-000040")
    assert any(a.get("pred") == "said_to" for a in t["goal"]["all"])
    e = run_episode(t, "robot_agent:sage", "ideal", 0, lang, "fake")
    says = [c for c in e["calls"] if c["skill"] in ("say", "announce")]
    assert says, e["calls"]
    assert all(c["args"]["lang"] == lang for c in says), says
    assert e["goal_atoms"] == [["said_to(dad, lunch_ready)", True]] and e["success"]
