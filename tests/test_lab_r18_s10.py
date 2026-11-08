"""Round 18: ``sage_s10`` = ``sage_s9`` + ``dialog_hold``; ``sage_s10h1`` = the ledger only; ``sage_s10w`` (wild card, outside the main set) = s10 + ``noun_relabel``."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.planners import REGISTRY, planner_class  # noqa: E402


def test_registered():
    assert {"robot_agent:sage_s10", "robot_agent:sage_s10h1", "robot_agent:sage_s10w"} <= set(REGISTRY)


def test_s10_is_s9_plus_the_hold_option_only():
    s9, s10, h1, w = (planner_class(f"robot_agent:{n}") for n in ("sage_s9", "sage_s10", "sage_s10h1", "sage_s10w"))
    assert s10.loop_options == {**s9.loop_options, "dialog_hold": "1"}
    assert h1.loop_options == {**s9.loop_options, "dialog_hold": "hold"}
    assert w.loop_options == {**s10.loop_options, "noun_relabel": "1"}
    assert "dialog_hold" not in s9.loop_options and "noun_relabel" not in s10.loop_options
    base = {k: v for k, v in s10.manifest_overlay["planner"].items() if k != "dialog_hold"}
    assert base == s9.manifest_overlay["planner"]


def test_options_are_recorded_in_planner_config_and_max_options_is_assumed():
    c9, c10, ch1, cw = (planner_class(f"robot_agent:{n}").run_config() for n in ("sage_s9", "sage_s10", "sage_s10h1", "sage_s10w"))
    assert "dialog_hold" not in c9 and c10["dialog_hold"] == 1 and ch1["dialog_hold"] == 1 and cw["noun_relabel"] == 1
    assert c10["loop_options"]["dialog_hold"] == "1" and ch1["loop_options"]["dialog_hold"] == "hold"
    assert c10["manifest_overlay"]["planner"]["dialog_hold"] == {"hold": True, "one_part": True, "max_options": 3}
    assert c10["manifest_overlay"]["assumed"] is True and "at most 3 options" in c10["manifest_overlay"]["note"]
    assert ch1["manifest_overlay"]["planner"]["dialog_hold"]["one_part"] is False
    json.dumps(c10)


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_s10_under_fake_matches_s9_when_no_dialogue_is_refused(tmp_path, lang):
    from homeloop_bench.runner import run_many
    tasks = fixture_tasks()[:3]
    out = {}
    for n in ("robot_agent:sage_s9", "robot_agent:sage_s10", "robot_agent:sage_s10h1"):
        d = tmp_path / n.replace(":", "_")
        s = run_many(n, None, None, "ideal", 1, lang, "fake", d, tasks=tasks)
        out[n] = [json.loads(line)["status"] for line in (d / "episodes.jsonl").read_text().splitlines()]
        assert s["n_episodes"] == 3
    assert out["robot_agent:sage_s10"] == out["robot_agent:sage_s9"] == out["robot_agent:sage_s10h1"]
