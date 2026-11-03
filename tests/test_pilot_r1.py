"""Pilot round 1 fixes (docs/experiments.md "Pilot rounds"):
- an LLM budget that runs out inside robot_agent (which catches BudgetExceeded and goes on) is recorded:
  ``llm_budget_hit`` and, when the planner then gives up, status ``budget`` (hl-dev-000003 KO);
- robot_agent reads plans back with the ENV keys of people, so those keys are names, not raw ids
  (hl-dev-000010 'person_user', hl-dev-000013 'partner_b');
- said_to keywords cover the bench's own message wordings (hl-dev-000013 KO '나간다고')."""
import json
from pathlib import Path

import pytest

from homeloop_bench.env import Budgets, EpisodeEnv, Finish
from homeloop_bench.llm import BudgetExceeded, FakeLLM
from homeloop_bench.metrics import summarize

DATA = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks"


def _task(tid, split="dev"):
    for line in (DATA / f"{split}.jsonl").open(encoding="utf-8"):
        if f'"id":"{tid}"' in line:
            return json.loads(line)
    raise KeyError(tid)


def _env(max_llm_calls=1):
    return EpisodeEnv(_task("hl-dev-000003"), "ideal", 0, "en", Budgets(max_llm_calls=max_llm_calls), llm=FakeLLM())


@pytest.mark.parametrize("status,want", [("give_up", "budget"), ("done", "done"), ("refuse", "refuse")])
def test_caught_llm_budget_is_recorded(status, want):
    env = _env(1)
    env.llm().chat("one")
    with pytest.raises(BudgetExceeded):
        env.llm().chat("two")                 # refused; a planner may catch it and go on
    env.finish(status)
    rec = env.record()
    assert rec["llm_budget_hit"] is True and rec["status"] == want
    assert summarize([rec], {})["llm_budget_hit_rate"] == 1.0


def test_no_budget_hit_without_a_refused_call():
    env = _env(2)
    env.llm().chat("one")
    env.finish("give_up")
    rec = env.record()
    assert rec["llm_budget_hit"] is False and rec["status"] == "give_up"
    assert summarize([rec], {})["llm_budget_hit_rate"] == 0.0


def test_robot_agent_swallowed_budget_is_recorded():
    pytest.importorskip("robot_agent")
    from homeloop_bench.runner import run_episode
    e = run_episode(_task("hl-dev-000010"), "robot_agent:sage", "ideal", 0, "en", "fake",
                    Budgets(max_llm_calls=1))
    assert e["llm_calls"] == 1 and e["llm_budget_hit"] is True, (e["status"], e["llm_calls"])
    assert e["status"] in ("budget", "done", "refuse")


# ------------------------------------------------------------------------------------ person keys in read-backs
def test_read_back_names_people_not_ids():
    pytest.importorskip("robot_agent")
    from robot_agent.core.planning.assist_loop import AssistLoop

    from homeloop_robot.configs.tasks import env_for
    from homeloop_robot.episode import make_episode
    from homeloop_robot.houses import list_houses
    for h in list_houses():
        w = make_episode(h, 0, "ideal", 0).world
        for k, e in env_for(w).items():
            if not e.get("person"):
                continue
            s = AssistLoop.summary([{"type": "on", "object": "green mug", "from": "counter@kitchen", "to": k}])
            assert "_" not in s.split(" on the ")[-1], (h, s)      # 'person_user', 'partner_b', 'roommate_b'
    w = make_episode("couple_flat", 0, "ideal", 0).world
    keys = {e["person"]: k for k, e in env_for(w).items() if e.get("person")}
    assert AssistLoop.summary([{"type": "say", "object": "We're leaving soon.", "person": keys["partner_b"]}]) \
        == "I will say \"We're leaving soon.\" to husband."


# ------------------------------------------------------------------------------------ message wordings
# KO paraphrases that lost the message ("go to the kitchen and tell my husband" for "tell my husband to come to the
# kitchen"): a data defect, listed, not matched by widening the keywords
LOST_MESSAGE = {"hl-test-002020", "hl-test-002764"}


def test_every_message_instruction_matches_its_key():
    from homeloop_robot.catalog import message_matches
    bad = []
    for split in ("dev", "test"):
        for line in (DATA / f"{split}.jsonl").open(encoding="utf-8"):
            t = json.loads(line)
            for a in t["goal"].get("all") or []:
                if a.get("pred") != "said_to":
                    continue
                for L in ("en", "ko"):
                    if not message_matches(a["args"][1], t["text"][L], L) and not (
                            L == "ko" and t["id"] in LOST_MESSAGE):
                        bad.append((t["id"], L, a["args"][1], t["text"][L]))
    assert bad == [], bad[:10]


def test_pilot_message_said_by_sage_counts():
    from homeloop_robot.catalog import message_matches
    assert message_matches("leaving_soon", "10분 있다가 나간다고 합니다.", "ko")
    assert message_matches("leaving_soon", "We're leaving in ten minutes.", "en")
