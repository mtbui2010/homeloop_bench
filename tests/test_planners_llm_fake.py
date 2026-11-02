"""LLM baselines on the FakeLLM (tests only): loops, parsers, repairs, determinism (docs/planners.md)."""

import json

import pytest

from fixtures import fixture_tasks
from homeloop_bench.env import EpisodeEnv
from homeloop_bench.llm import CountingLLM, FakeLLM, parse_json
from homeloop_bench.planners import make_planner
from homeloop_bench.planners.knowno_like import prediction_set
from homeloop_bench.planners.progprompt_like import parse_program
from homeloop_bench.planners.saycan_like import AffordanceBelief, options
from homeloop_bench.runner import run_episode

TASKS = fixture_tasks()
LLM_PLANNERS = ("saycan_like", "inner_monologue_like", "progprompt_like", "knowno_like")


@pytest.mark.parametrize("planner", LLM_PLANNERS)
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_llm_planner_runs_on_fake(planner, lang):
    eps = [run_episode(t, planner, "ideal", 0, lang, "fake") for t in TASKS]
    assert not [e.get("error") for e in eps if e.get("error")]
    assert all(e["llm_calls"] >= 1 for e in eps)
    assert all(e["llm_calls"] <= 30 for e in eps)
    assert sum(e["success"] for e in eps) >= len(eps) // 2, [(e["task_id"], e["status"]) for e in eps]
    again = [run_episode(t, planner, "ideal", 0, lang, "fake") for t in TASKS]
    assert eps == again


def test_inner_monologue_and_knowno_ask_on_clarify():
    t = next(t for t in TASKS if t["id"] == "fx-clar-000")
    for p in ("inner_monologue_like", "knowno_like"):
        e = run_episode(t, p, "ideal", 0, "en", "fake")
        assert e["asked"] >= 1 and e["success"], (p, e["status"])
    e = run_episode(t, "saycan_like", "ideal", 0, "en", "fake")
    assert e["asked"] == 0                      # SayCan has no ask option


def test_refuse_unsafe_by_fake_common_sense():
    t = next(t for t in TASKS if t["id"] == "fx-ref-000")
    for p in LLM_PLANNERS:
        e = run_episode(t, p, "ideal", 0, "en", "fake")
        assert e["status"] == "refuse", p


class Garbage:
    model = "garbage"

    def __init__(self):
        self.n = 0

    def chat(self, prompt, format=None, temperature=0.0, seed=0):
        self.n += 1
        return "I think the robot should go to the kitchen"


def test_unparsable_answers_give_up_after_two_repairs():
    t = TASKS[0]
    for p in ("inner_monologue_like", "saycan_like", "progprompt_like"):
        g = Garbage()
        env = EpisodeEnv(t, "ideal", 0, "en", llm=g)
        make_planner(p, llm=env.llm()).run(env)
        assert env.status == "give_up" and env.llm_calls == 3 and g.n == 3, p


def test_llm_budget_is_enforced():
    t = TASKS[0]
    e = run_episode(t, "inner_monologue_like", "ideal", 0, "en", "fake",
                    budgets=__import__("homeloop_bench.env", fromlist=["Budgets"]).Budgets(max_llm_calls=2))
    assert e["status"] == "budget" and e["llm_calls"] == 2


def test_parse_json_tolerant():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('<think>x</think> sure: {"choice": 3} done') == {"choice": 3}
    assert parse_json('text [1, 2] more') == [1, 2]
    with pytest.raises(ValueError):
        parse_json("nothing here")


def test_progprompt_parser():
    prog = parse_program('```\nmove("counter@kitchen")\nfind("mug_1")\npick("mug_1")\n'
                         'assert holding("mug_1") else: pick("mug_1")\nbogus line\nsay("Hi.", "en")\n'
                         'decline("not the bleach")\nfinish("done")\n```')
    assert prog[0] == ("call", "move", {"target": "counter@kitchen"})
    assert prog[3][0] == "assert" and prog[3][2] == "holding" and prog[3][4] == ("pick", {"obj": "mug_1"})
    assert ("call", "say", {"text": "Hi.", "lang": "en"}) in prog
    assert prog[-1] == ("call", "finish", {"value": "done"})
    with pytest.raises(ValueError):
        parse_program("no program")


def test_saycan_options_follow_belief():
    t = TASKS[0]
    env = EpisodeEnv(t, "ideal", 0, "en")
    obs = env.observe()
    b = AffordanceBelief()
    b.people = {p.id for p in obs.people}
    b.at = obs.robot["at"]
    opts = options(obs, b)
    skills = {s for s, _ in opts}
    assert "pick" not in skills and "place" not in skills and ("finish", {"status": "done"}) in opts
    b.found_here = ["x_1"]
    assert ("pick", {"obj": "x_1"}) in options(obs, b)


def test_knowno_prediction_set():
    assert prediction_set({"a": 0.6, "b": 0.4}, 0.7) == ["a", "b"]
    assert prediction_set({"a": 1.0, "b": 0.0}, 0.7) == ["a"]
    assert prediction_set({"a": 0.2, "b": 0.2}, 0.7) == []


def test_fake_llm_is_deterministic_and_counted():
    env = EpisodeEnv(TASKS[0], "ideal", 0, "en", llm=FakeLLM())
    c = env.llm()
    assert isinstance(c, CountingLLM)
    from homeloop_bench.planners.prompts import step_prompt
    p = step_prompt("inner_monologue", env.observe())
    a, b = c.chat(p), c.chat(p)
    assert a == b and env.llm_calls == 2 and "action" in json.loads(a)
