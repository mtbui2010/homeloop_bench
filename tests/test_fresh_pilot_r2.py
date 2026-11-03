"""Fresh pilot round 2 (docs/experiments.md "Pilot rounds", results/pilot_r27x/round2):
- a give_up after a refused LLM call is status ``budget`` only when no hardware fault ended the episode after the
  last refused call (sage_norag hl-dev-000057: the plan ran on, then Find hw_fault_persistent; the episode was
  labelled ``budget``); ``llm_budget_hit`` still records the refused call."""
import json
from pathlib import Path

import pytest

from homeloop_bench.env import Budgets, EpisodeEnv
from homeloop_bench.failures import cause
from homeloop_bench.llm import BudgetExceeded, FakeLLM

DATA = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks"


def _task(tid, split="dev"):
    for line in (DATA / f"{split}.jsonl").open(encoding="utf-8"):
        if f'"id":"{tid}"' in line:
            return json.loads(line)
    raise KeyError(tid)


def _refuse_llm(env):
    env.llm().chat("one")
    with pytest.raises(BudgetExceeded):
        env.llm().chat("two")                 # refused; robot_agent catches it and goes on


def _replay_057(env):
    """The robot's calls of sage_norag EN hl-dev-000057 after its questions (profile real, seed 0)."""
    env.call("move", target="kids_desk@kids")
    env.call("pose")
    return env.call("find", obj="green book")


def test_hw_fault_after_the_llm_budget_is_not_the_budget():
    env = EpisodeEnv(_task("hl-dev-000057"), "real", 0, "en", Budgets(max_llm_calls=1), llm=FakeLLM())
    _refuse_llm(env)
    r = _replay_057(env)
    assert not r["ok"] and r["code"] == "hw_fault", r
    env.finish("give_up", "the robot is not healthy after find failed (hw_fault)")
    rec = env.record()
    assert rec["status"] == "give_up" and rec["llm_budget_hit"] is True
    assert cause(rec) == "robot_failure"


def test_llm_budget_after_the_hw_fault_is_still_the_budget():
    # the refused call came after the fault (no call after it): the budget cut the recovery off
    env = EpisodeEnv(_task("hl-dev-000057"), "real", 0, "en", Budgets(max_llm_calls=1), llm=FakeLLM())
    r = _replay_057(env)
    assert r["code"] == "hw_fault", r
    _refuse_llm(env)
    env.finish("give_up")
    assert env.record()["status"] == "budget"


def test_give_up_after_the_llm_budget_without_a_fault_is_the_budget():
    env = EpisodeEnv(_task("hl-dev-000057"), "real", 0, "en", Budgets(max_llm_calls=1), llm=FakeLLM())
    _refuse_llm(env)
    env.call("move", target="kids_desk@kids")
    env.finish("give_up")
    rec = env.record()
    assert rec["status"] == "budget" and cause(rec) == "budget"


# ---- the baselines' give-up: said in the user's language, the status note kept apart -------------------------

@pytest.mark.parametrize("lang", ["en", "ko"])
def test_naive_give_up_is_said_in_the_users_language_without_raw_ids(lang):
    # naive hl-dev-000060 (profile real, seed 0): the glasses are not where it looks ("glasses_1 not found")
    from homeloop_bench.env import give_up_text
    from homeloop_bench.runner import run_episode
    e = run_episode(_task("hl-dev-000060"), "naive", "real", 0, lang, None, Budgets())
    assert e["status"] == "give_up", e["status"]
    assert e["final_say"] == give_up_text(lang)
    assert e["finish_reason"] == "glasses_1 not found", e["finish_reason"]
    assert e["final_say_not_in_lang"] == 0 and e["final_say_raw_ids"] == [] and e["dialog_raw_ids"] == []
    assert e["dialog_not_in_lang"] == 0


def test_a_status_note_said_as_the_last_message_is_still_counted():
    # the check itself is unchanged: an English last message with a raw id to a Korean user counts
    env = EpisodeEnv(_task("hl-dev-000060"), "real", 0, "ko", Budgets())
    env.finish("give_up", "glasses_1 not found")
    rec = env.record()
    assert rec["final_say_not_in_lang"] == 1 and rec["final_say_raw_ids"] == ["glasses_1"]
