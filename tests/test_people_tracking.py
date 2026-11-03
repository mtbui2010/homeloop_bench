"""People tracking (round 3, R3 user decision 06:40): robot_agent:sage (the ENV gives people's last-seen positions)
grounds "me" / 저한테 to the speaker without asking; robot_agent:sage_ask (no positions) asks "Where are you?" and
maps the answer onto the house: the support surface beside the named place, never the seat itself, or a hand-over.
Both run the real AssistLoop under --llm fake on a delivery to the speaker, in EN and KO; plus the run config
(planner_config.people_tracking / translate_model) and the translator's calls counted apart.
"""
import copy
import json
from pathlib import Path

import pytest

from fixtures import base
from homeloop_bench.planners import planner_class
from homeloop_bench.runner import run_episode

HB = Path(__file__).resolve().parents[1]


def _task(lang_text=("Bring me the red mug.", "빨간 머그컵 좀 저한테 가져다주세요.")):
    g = {"all": [{"pred": "delivered", "args": ["mug_1", "grandma"], "mode": "reach", "mode_reason": None}]}
    t = base("r3-pt-000", "senior_flat", 0, g, capability="fetch")
    t["subtasks"] = [{"kind": "feasible", "capability": "fetch", "ambiguity": "none", "goal": copy.deepcopy(g)}]
    t["n_subtasks"], t["structure"] = 1, "single"
    t["text"] = {"en": lang_text[0], "ko": lang_text[1]}
    return t


def _asks(e):
    return [c for c in e["calls"] if c["skill"] == "ask"]


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_tracking_grounds_me_without_asking(lang):
    pytest.importorskip("robot_agent")
    e = run_episode(_task(), "robot_agent:sage", "ideal", 0, lang, "fake")
    assert not [c for c in _asks(e) if (c["args"].get("meaning") or {}).get("qtype") == "where_are_you"]
    assert e["success"], (e["status"], e["finish_reason"])
    assert not any(c["skill"] == "handover" for c in e["calls"])


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_ask_then_map(lang):
    pytest.importorskip("robot_agent")
    e = run_episode(_task(), "robot_agent:sage_ask", "ideal", 0, lang, "fake")
    asks = _asks(e)
    assert asks and (asks[0]["args"].get("meaning") or {}).get("qtype") == "where_are_you"
    if lang == "ko":
        assert asks[0]["args"]["question"] == "지금 어디에 계세요?"            # the robot pack's phrase, no LLM
    places = [c["args"].get("target") for c in e["calls"] if c["skill"] == "place"]
    seats = {pid for pid, p in __import__("homeloop_robot.world", fromlist=["from_house"]).from_house(
        "senior_flat", 0).house.places.items() if p.kind in ("seat", "floor")}
    assert not (set(places) & seats)                                            # never the seat itself
    assert e["success"] or any(c["skill"] == "handover" for c in e["calls"]), (e["status"], e["finish_reason"])


def test_untracked_env_has_no_positions():
    pytest.importorskip("robot_agent")
    from homeloop_robot.configs.tasks import env_for
    from homeloop_robot.world import from_house
    env = env_for(from_house("senior_flat", 0), people_tracking=planner_class("robot_agent:sage_ask").people_tracking)
    assert all("loc" not in v for v in env.values() if v.get("person"))


def test_run_config_records_tracking_and_translate_model():
    ab = json.loads((HB / "data" / "quality" / "translate_ab.json").read_text(encoding="utf-8"))
    for name, tracking in (("robot_agent:sage", True), ("robot_agent:sage_ask", False), ("robot_agent:sage_norag", True)):
        c = planner_class(name).run_config()
        assert c["people_tracking"] is tracking
        assert c["translate_model"] == ab["chosen"] != "qwen3-vl:8b-instruct"
    assert planner_class("robot_agent:sage_nohazard").run_config()["hazard_rules"] == "off"
    assert planner_class("robot_agent:sage_complete").run_config()["gate_complete"] == 1
    assert planner_class("robot_agent:sage").run_config()["hazard_rules"] == "core"


def test_translate_calls_counted():
    """A Korean episode whose text needs the translator (no robot phrase for it): the translator's calls are
    on the episode's LLM count and counted apart (llm_calls_translate)."""
    pytest.importorskip("robot_agent")
    t = _task(("Bring me the red mug.", "빨간 머그컵 좀 저한테 가져다주세요."))
    e = run_episode(t, "robot_agent:sage_ask", "ideal", 0, "ko", "fake")
    assert "llm_calls_translate" in e and e["llm_calls_translate"] <= e["llm_calls"]
