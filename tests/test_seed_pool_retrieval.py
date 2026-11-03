"""Retrieval is live for robot_agent:sage and absent for robot_agent:sage_norag (R2-7b), shown on the prompt SAGE
itself builds (``built_prompt``: the episode set up as a run sets it up, --llm fake, the generator's first call
captured): sage's prompts carry 3 RETRIEVED EXAMPLE blocks from the seed pool, sage_norag's carry none, and the
prompts are otherwise identical."""
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("robot_agent")
pytest.importorskip("embodiplan")

from homeloop_bench.planners.robot_agent_adapter import built_prompt, seed_pool_path  # noqa: E402

DEV = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks" / "dev.jsonl"
IDS = ("hl-dev-000003", "hl-dev-000017")
BLOCK = re.compile(r"=== RETRIEVED EXAMPLE \d+ .*?(?==== )", re.S)


@pytest.fixture(scope="module")
def tasks():
    out = {}
    for line in DEV.open(encoding="utf-8"):
        t = json.loads(line)
        if t["id"] in IDS:
            out[t["id"]] = t
    return out


@pytest.fixture(scope="module")
def pool_tasks():
    return [json.loads(line)["task"] for line in seed_pool_path().read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.parametrize("tid", IDS)
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_sage_prompt_has_the_pool_and_norag_has_none(tasks, pool_tasks, tid, lang):
    a = built_prompt(tasks[tid], "robot_agent:sage", lang)
    b = built_prompt(tasks[tid], "robot_agent:sage_norag", lang)
    assert a["query"] == b["query"]                         # the same heard instruction
    assert a["seed_pool_n"] == len(pool_tasks) and b["seed_pool_n"] == 0
    assert len(a["retrieved"]) == 3 and all(r["source"] == "seed" and r["task"] in pool_tasks for r in a["retrieved"])
    assert b["retrieved"] == []
    assert a["prompt"].count("=== RETRIEVED EXAMPLE") == 3 and "RETRIEVED EXAMPLE" not in b["prompt"]
    for r in a["retrieved"]:
        assert f"Task: {r['task']}" in a["prompt"]
    assert a["prompts_with_examples"] == a["n_prompts"] >= 1 and b["prompts_with_examples"] == 0
    # nothing else differs
    assert BLOCK.sub("", a["prompt"]).split() == b["prompt"].split()


def test_english_retrieval_ranks_by_similarity(tasks):
    a = built_prompt(tasks["hl-dev-000017"], "robot_agent:sage", "en")
    scores = [r["score"] for r in a["retrieved"]]
    assert scores == sorted(scores, reverse=True) and scores[0] > 0
