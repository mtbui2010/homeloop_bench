"""Round 14: the ``sage_s7`` variant = ``sage_s6`` + ``dialog_agree2`` + ``relook`` and the guard's number, and nothing else."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.planners import REGISTRY, planner_class  # noqa: E402


def test_registered():
    assert "robot_agent:sage_s7" in REGISTRY and "robot_agent:sage_s6" in REGISTRY


def test_sage_s7_is_s6_plus_the_round_14_options_only():
    s6, s7 = planner_class("robot_agent:sage_s6"), planner_class("robot_agent:sage_s7")
    assert s7.loop_options == {**s6.loop_options, "dialog_agree2": "1", "relook": "1"}
    assert "dialog_agree2" not in s6.loop_options and "relook" not in s6.loop_options
    assert s7.manifest_overlay["planner"]["agree_guard"] == {"garble_ratio": 0.6}
    assert {k: v for k, v in s7.manifest_overlay["planner"].items() if k != "agree_guard"} == s6.manifest_overlay["planner"]
    c6, c7 = s6.run_config(), s7.run_config()
    assert c7.get("dialog_agree2") == 1 and c7.get("relook") == 1 and "relook" not in c6 and "dialog_agree2" not in c6


def test_s6_and_the_older_variants_record_no_round_14_flag():
    for n in ("sage", "sage_ground2", "sage_r3u", "sage_s5", "sage_s6"):
        c = planner_class(f"robot_agent:{n}").run_config()
        assert "relook" not in c and "dialog_agree2" not in c and "agree_guard" not in json.dumps(c)


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_s7_episodes_under_fake_match_s6_when_nothing_is_refused_or_missed(tmp_path, lang):
    from homeloop_bench.runner import run_many
    tasks = fixture_tasks()[:3]
    out = {}
    for n in ("robot_agent:sage_s6", "robot_agent:sage_s7"):
        d = tmp_path / n.replace(":", "_")
        s = run_many(n, None, None, "ideal", 1, lang, "fake", d, tasks=tasks)
        out[n] = (s, [json.loads(l) for l in (d / "episodes.jsonl").read_text().splitlines()])
    (s6, e6), (s7, e7) = out["robot_agent:sage_s6"], out["robot_agent:sage_s7"]
    assert s6["n_episodes"] == s7["n_episodes"] == 3
    assert all("lab_events" in e for e in e7)
    assert [e["status"] for e in e6] == [e["status"] for e in e7]
