"""Round 17: ``sage_s8n`` = ``sage_s8`` without ``relook``, ``sage_s9`` = ``sage_s8n`` + ``hazard_receiver``, and nothing else."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.planners import REGISTRY, planner_class  # noqa: E402


def test_registered():
    assert {"robot_agent:sage_s8n", "robot_agent:sage_s9"} <= set(REGISTRY)


def test_s8n_is_s8_without_relook_only():
    s8, s8n = planner_class("robot_agent:sage_s8"), planner_class("robot_agent:sage_s8n")
    assert s8n.loop_options == {k: v for k, v in s8.loop_options.items() if k != "relook"}
    assert "relook" in s8.loop_options and "relook" not in s8n.loop_options
    assert s8n.manifest_overlay == s8.manifest_overlay


def test_s9_is_s8n_plus_the_hazard_option_only():
    s8n, s9 = planner_class("robot_agent:sage_s8n"), planner_class("robot_agent:sage_s9")
    assert s9.loop_options == {**s8n.loop_options, "hazard_receiver": "1"}
    assert s9.manifest_overlay == s8n.manifest_overlay
    assert "hazard_receiver" not in planner_class("robot_agent:sage_s8").loop_options


def test_run_config_records_the_arms():
    c8, c8n, c9 = (planner_class(f"robot_agent:{n}").run_config() for n in ("sage_s8", "sage_s8n", "sage_s9"))
    assert c8["relook"] == 1 and "options_off" not in c8 and "hazard_receiver" not in c8
    assert "relook" not in c8n and c8n["options_off"] == ["relook"] and "hazard_receiver" not in c8n
    assert "relook" not in c9 and c9["options_off"] == ["relook"] and c9["hazard_receiver"] == 1
    for n in ("sage", "sage_s6", "sage_s7", "sage_s6d"):
        assert "options_off" not in planner_class(f"robot_agent:{n}").run_config()
    json.dumps(c9)


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_s8n_and_s9_under_fake_match_s8_when_nothing_is_searched_or_handed_over(tmp_path, lang):
    from homeloop_bench.runner import run_many
    tasks = fixture_tasks()[:3]
    out = {}
    for n in ("robot_agent:sage_s8", "robot_agent:sage_s8n", "robot_agent:sage_s9"):
        d = tmp_path / n.replace(":", "_")
        s = run_many(n, None, None, "ideal", 1, lang, "fake", d, tasks=tasks)
        out[n] = (s, [json.loads(line) for line in (d / "episodes.jsonl").read_text().splitlines()])
    assert all(s["n_episodes"] == 3 for s, _ in out.values())
    ref = [e["status"] for e in out["robot_agent:sage_s8"][1]]
    assert [e["status"] for e in out["robot_agent:sage_s8n"][1]] == ref == [e["status"] for e in out["robot_agent:sage_s9"][1]]
