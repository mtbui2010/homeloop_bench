"""progprompt_like's example programs (R2-5 B4; ProgPrompt, arXiv:2209.11302): exactly three, from train-split
tasks, in a house no split uses, each runnable by the planner's own interpreter."""
import json
import re
from pathlib import Path

import pytest

from fixtures import fixture_tasks
from homeloop_bench.env import EpisodeEnv
from homeloop_bench.planners import progprompt_examples as PE
from homeloop_bench.planners.progprompt_like import ProgPromptLike, parse_program

DATA = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks"


def _split(name):
    return [json.loads(line) for line in (DATA / f"{name}.jsonl").open(encoding="utf-8")]


class _Capture:
    """An LLM that records the prompt and answers one finish line."""

    model = "capture"

    def __init__(self):
        self.prompts = []

    def chat(self, prompt, format=None, temperature=0.0, seed=0):
        self.prompts.append(prompt)
        return 'finish("done")'


@pytest.fixture(scope="module")
def prompt():
    t = fixture_tasks()[0]
    llm = _Capture()
    env = EpisodeEnv(t, "ideal", 0, "en")
    ProgPromptLike(llm).run(env)
    return llm.prompts[0]


def test_prompt_has_exactly_three_example_programs(prompt):
    assert len(PE.EXAMPLES) == 3
    assert len(re.findall(r"^def \w+\(\):$", prompt, re.M)) == 3
    for ex in PE.EXAMPLES:
        assert ex["program"] in prompt and ex["instruction"] in prompt
        assert ex["program"].count("assert ") >= 1 or ex["status"] == "refuse"
        assert "#" in ex["program"]                      # commented, as ProgPrompt's examples


def test_examples_come_from_train_tasks_not_dev_or_test():
    train = {r["id"]: r for r in _split("train")}
    held = {r["id"] for s in ("dev", "test") for r in _split(s)}
    held_houses = {r["house"] for s in ("dev", "test") for r in _split(s)}
    all_houses = held_houses | {r["house"] for r in train.values()}
    from homeloop_robot.houses import list_houses
    assert PE.HOUSE_NAME == PE.example_house().house
    assert PE.HOUSE_NAME not in all_houses and PE.HOUSE_NAME not in list_houses()
    for ex in PE.EXAMPLES:
        assert ex["source_id"] in train and ex["source_id"] not in held
        assert ex["instruction"] == train[ex["source_id"]]["text"]["en"]
        assert ex["source_id"] not in ex["program"]
    # no dev / test task id appears anywhere in the example text
    text = PE.examples_text()
    assert not re.search(r"hl-(dev|test)-\d+", text)


def test_example_house_is_a_valid_house():
    from homeloop_robot.houses import validate_house
    assert validate_house(PE.example_house()) == []


@pytest.mark.parametrize("ex", PE.EXAMPLES, ids=[e["shows"] for e in PE.EXAMPLES])
def test_each_example_runs_in_the_interpreter(ex):
    prog = parse_program(ex["program"])
    assert prog
    env, ok = PE.run_example(ex)
    assert ok, (ex["source_id"], env.calls)
    assert env.status == ex["status"]
    assert all(c[2] for c in env.calls), env.calls      # ideal profile: every call of the example succeeds


def test_examples_show_the_three_habits():
    by = {e["shows"]: parse_program(e["program"]) for e in PE.EXAMPLES}
    calls = lambda prog: [(st[1], next(iter(st[2].values()), None)) for st in prog if st[0] == "call"]  # noqa: E731
    c1 = calls(by["move to the source before find"])
    assert c1.index(("move", "dining_table@kitchen")) < c1.index(("find", "mug_2"))
    c2 = calls(by["open a closed container before find"])
    assert c2.index(("open", "laundry_cabinet@utility")) < c2.index(("find", "towel_1"))
    w = PE.example_house()
    assert next(o for o in w.objects if o.id == "towel_1").at == "laundry_cabinet@utility"
    c3 = by["decline an unsafe request"]
    assert c3[0][:2] == ("call", "decline") and c3[-1] == ("call", "finish", {"value": "refuse"})
