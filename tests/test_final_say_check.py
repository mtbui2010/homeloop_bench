"""Pilot round 4: the planner's last message is heard too.

* KO episodes of robot_agent ended with "Task completed" (robot_agent's Announcer had no Korean milestone of the
  robot; fixed in homeloop_robot configs/adapter.py). The language check counted only questions, so the gate missed
  it: ``final_say_not_in_lang`` now counts the last message, and ``dialog_not_in_lang`` includes it.
* robot_agent's give-up joins the searched ENV keys verbatim ("could not find the green mug (looked at
  counter@kitchen, ...)", EN hl-dev-000010; KO '김치_냉장고@주방'). ``final_say_raw_ids`` lists the raw ids so the
  gap is reported, not hidden (docs/experiments.md "Known SAGE-v2 gaps"). Neither field is scored.
"""
import json
from pathlib import Path

import pytest

from homeloop_bench.env import EpisodeEnv, raw_ids
from homeloop_bench.metrics import summarize
from homeloop_bench.tasks import task_by_id

DELIVERY = "hl-dev-000010"
DEV = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks" / "dev.jsonl"


def _finish(lang, status, say):
    env = EpisodeEnv(task_by_id(DELIVERY), "ideal", 0, lang)
    env.finish(status, say)
    return env.record()


@pytest.mark.parametrize("lang,status,say,bad", [
    ("ko", "done", "Task completed", 1),                         # pilot round 4, KO 013 / 001
    ("ko", "give_up", "Task failed", 1),
    ("ko", "done", "작업을 완료했습니다", 0),
    ("ko", "give_up", "사용자가 작업을 확인하지 않았습니다.", 0),
    ("ko", "done", "", 0),                                        # nothing said
    ("en", "done", "Task completed", 0),
    ("en", "give_up", "작업에 실패했습니다", 1),
    ("ko", "refuse", "I can't do that safely.", 1),
])
def test_last_message_language(lang, status, say, bad):
    rec = _finish(lang, status, say)
    assert rec["final_say_not_in_lang"] == bad
    assert rec["dialog_not_in_lang"] == bad                       # no question was asked
    s = summarize([rec], {})
    assert s["final_say_not_in_lang"] == bad and s["dialog_not_in_lang"] == bad


def test_questions_and_last_message_add_up():
    env = EpisodeEnv(task_by_id("hl-dev-000003"), "ideal", 0, "ko")
    env.call("ask", question="Fridge or kimchi fridge?", lang="ko")
    env.finish("done", "Task completed")
    rec = env.record()
    assert rec["final_say_not_in_lang"] == 1 and rec["dialog_not_in_lang"] == 2


def test_raw_ids_of_the_round4_give_up():
    rec = _finish("en", "give_up", "could not find the green mug (looked at counter@kitchen, spot near you, grandpa, "
                                   "sofa@living, coffee_table@living)")
    assert rec["final_say_raw_ids"] == ["counter@kitchen", "sofa@living", "coffee_table@living"]
    assert summarize([rec], {})["final_say_raw_ids"] == 1


def test_raw_ids_translated_and_underscore_ids():
    env = EpisodeEnv(task_by_id("hl-dev-000003"), "ideal", 0, "ko")
    w = env._world
    assert raw_ids("우유를 찾지 못했습니다 (김치_냉장고@주방 확인).", w) == ["김치_냉장고@주방"]
    assert "kimchi_fridge@kitchen" in w.house.places
    assert raw_ids("cannot reach the handle of kimchi_fridge@kitchen", w) == ["kimchi_fridge@kitchen"]
    pid = next((p for p in w.people if "_" in p), None)
    if pid is not None:
        assert raw_ids(f"I told {pid}.", w) == [pid]


@pytest.mark.parametrize("say", ["Task completed", "I will put the milk in the kimchi fridge in the kitchen.",
                                 "작업을 완료했습니다", "email me at someone@example.com", ""])
def test_readable_messages_have_no_raw_ids(say):
    env = EpisodeEnv(task_by_id("hl-dev-000003"), "ideal", 0, "en")
    got = raw_ids(say, env._world)
    if "@example" in say:                       # an '@' between words is flagged whatever it is: conservative
        assert got == ["someone@example.com"]
    else:
        assert got == []


def test_robot_agent_ko_episode_ends_in_korean(monkeypatch):
    """The real AssistLoop (robot_agent:sage, --llm fake) on a KO message task: the done narration is Korean."""
    pytest.importorskip("robot_agent")
    import ko_fake_translation
    from homeloop_bench.runner import run_episode
    from homeloop_robot.world import from_house
    t = next(json.loads(line) for line in DEV.open(encoding="utf-8") if '"id":"hl-dev-000040"' in line)
    ko_fake_translation.install(monkeypatch, from_house(t["house"], int(t.get("seed_state") or 0)))
    e = run_episode(t, "robot_agent:sage", "ideal", 0, "ko", "fake")
    assert e["status"] == "done" and e["final_say"] == "작업을 완료했습니다", e["final_say"]
    assert e["final_say_not_in_lang"] == 0 and e["final_say_raw_ids"] == []


def test_failure_codes_are_raw_ids():
    """Milestone 5 round 1 (EN hl-dev-000002): robot_agent said 'the robot is not healthy after move failed
    (hw_fault)'; the internal code reached the user and no counter saw it. Codes that are plain English words
    ('timeout', 'blocked') are not flagged."""
    rec = _finish("en", "give_up", "the robot is not healthy after move failed (hw_fault): wheel motor fault")
    assert rec["final_say_raw_ids"] == ["hw_fault"]
    w = EpisodeEnv(task_by_id(DELIVERY), "ideal", 0, "en")._world
    assert raw_ids("pick failed (grasp_failed), then hw_fault_persistent", w) == ["grasp_failed", "hw_fault_persistent"]
    assert raw_ids("I have to stop: something is wrong with my hardware.", w) == []
    assert raw_ids("The way is blocked and the call timed out (timeout).", w) == []
