"""Fresh pilot round 1 (docs/experiments.md "Pilot rounds", results/pilot_r27x/round1):

* raw world ids reached the user in robot_agent's EN read-backs ("the green book from the kids_desk in the kids on
  the coffee_table in the living"), in 5 of the 9 questions of each EN sage condition, but only the last message was
  checked (``final_say_raw_ids``): ``dialog_raw_ids`` / ``dialog_raw_id_utterances`` check every question, Say and
  the last message; a place key's head with an underscore counts;
* the baselines' whole-task refusal was English to a Korean user ("I can't do that safely."): it is said in the
  user's language. Neither is scored.
"""
import pytest

from homeloop_bench.env import EpisodeEnv, raw_ids
from homeloop_bench.metrics import summarize
from homeloop_bench.runner import run_episode
from homeloop_bench.tasks import task_by_id

READ_BACK = ('I am not sure I understood (the you you mentioned is not in my plan). I will put the green book from the '
             'kids_desk in the kids on the coffee_table in the living, then say "It\'s time for bed, kid." in the kid. '
             'Is that right?')


def test_place_key_heads_are_raw_ids():
    env = EpisodeEnv(task_by_id("hl-dev-000057"), "ideal", 0, "en")
    assert raw_ids(READ_BACK, env._world) == ["coffee_table", "kids_desk"]
    assert raw_ids("I will put the green book on the coffee table in the living room.", env._world) == []


def test_every_robot_utterance_is_checked():
    env = EpisodeEnv(task_by_id("hl-dev-000057"), "ideal", 0, "en")
    env.call("ask", question="Which book do you mean?", lang="en")
    env.call("ask", question=READ_BACK, lang="en")
    env.call("say", text="Kid, it is time for bed.", lang="en")
    env.finish("give_up", "could not find the book (looked at kids_desk@kids)")
    rec = env.record()
    assert rec["final_say_raw_ids"] == ["kids_desk@kids"]
    assert rec["dialog_raw_ids"] == ["coffee_table", "kids_desk", "kids_desk@kids"]
    assert rec["dialog_raw_id_utterances"] == 2
    s = summarize([rec], {})
    assert s["dialog_raw_ids"] == 1 and s["dialog_raw_id_utterances"] == 2


def test_readable_episode_has_none():
    e = run_episode(task_by_id("hl-dev-000057"), "oracle", "ideal", 0, "en", None)
    assert e["dialog_raw_ids"] == [] and e["dialog_raw_id_utterances"] == 0


@pytest.mark.parametrize("planner", ["oracle", "naive"])
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_baseline_refusal_in_the_users_language(planner, lang):
    e = run_episode(task_by_id("hl-dev-000035"), planner, "ideal", 0, lang, None)      # a refuse task
    assert e["status"] == "refuse" and e["success"], e["status"]
    assert e["final_say_not_in_lang"] == 0, e["final_say"]
    assert e["final_say"] == ("I can't do that safely." if lang == "en" else "그건 안전하게 할 수 없어요.")
