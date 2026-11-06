"""Consistency fix (not tuning): sage_gold's gold goals write a hand delivery to another person the way robot_agent's
own understanding writes it (kind ``on``, the person as destination, ``hand``), not as the kind ``deliver``, which
robot_agent compiles to MoveTo + WaitForUnload without a fetch and its plan gate refuses (hl-dev-000017 EN and KO,
sage_gold: 'the robot has no action WaitForUnload'). The ceiling of sage_gold is then not lowered by the artifact."""
import json
from pathlib import Path

import pytest

pytest.importorskip("robot_agent")

from homeloop_bench.env import EpisodeEnv  # noqa: E402
from homeloop_bench.gold_goals import understand_goals  # noqa: E402

DEV = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks" / "dev.jsonl"


def _task(tid):
    for line in DEV.read_text().splitlines():
        r = json.loads(line)
        if r["id"] == tid:
            return r
    pytest.skip(f"{tid} not in the dev split")


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_hand_delivery_to_another_person_is_on_with_the_person_and_hand(lang):
    env = EpisodeEnv(_task("hl-dev-000017"), "ideal", 0, lang, llm=None, privileged=True)
    goals = understand_goals(env, with_source=False)
    assert [g["type"] for g in goals] == ["on"] and goals[0]["hand"] is True
    assert goals[0]["to"] == "kid"            # the same person key robot_agent's understanding wrote for it


def test_no_gold_goal_is_the_deliver_kind():
    from robot_agent.core.planning.goals import missing_actions
    for tid in ("hl-dev-000017", "hl-dev-000018"):
        env = EpisodeEnv(_task(tid), "ideal", 0, "en", llm=None, privileged=True)
        for g in understand_goals(env, with_source=False):
            assert g["type"] != "deliver"
            assert not missing_actions(g, ["MoveTo", "Find", "Pick", "Place", "PutIn", "Open", "Close", "Handover"])
