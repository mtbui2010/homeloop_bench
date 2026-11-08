"""Lab round 12: the ``sage_s6`` variant = ``sage_s5`` + ``dialog_agree``, and nothing else."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.planners import REGISTRY, planner_class  # noqa: E402


def test_registered():
    assert "robot_agent:sage_s6" in REGISTRY and "robot_agent:sage_s5" in REGISTRY


def test_sage_s6_is_s5_plus_dialog_agree_only():
    s5, s6 = planner_class("robot_agent:sage_s5"), planner_class("robot_agent:sage_s6")
    assert s6.loop_options == {**s5.loop_options, "dialog_agree": "1"}
    assert s6.manifest_overlay == s5.manifest_overlay                      # no new pack data, no new number
    assert "dialog_agree" not in s5.loop_options
    c5, c6 = s5.run_config(), s6.run_config()
    assert c6.get("dialog_agree") == 1 and "dialog_agree" not in c5        # recorded only where set
    assert {k: v for k, v in c6.items() if k not in ("dialog_agree", "loop_options")} == {k: v for k, v in c5.items() if k != "loop_options"}
    assert {k: v for k, v in c6["loop_options"].items() if k != "dialog_agree"} == c5["loop_options"]


def test_the_other_variants_record_no_dialog_agree():
    for n in ("sage", "sage_ground2", "sage_r3u", "sage_s5"):
        assert "dialog_agree" not in planner_class(f"robot_agent:{n}").run_config()


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_s6_episodes_under_fake_carry_lab_events_and_match_s5_when_nothing_is_refused(tmp_path, lang):
    from homeloop_bench.runner import run_many
    tasks = fixture_tasks()[:3]
    out = {}
    for n in ("robot_agent:sage_s5", "robot_agent:sage_s6"):
        d = tmp_path / n.replace(":", "_")
        s = run_many(n, None, None, "ideal", 1, lang, "fake", d, tasks=tasks)
        out[n] = (s, [json.loads(l) for l in (d / "episodes.jsonl").read_text().splitlines()])
    (s5, e5), (s6, e6) = out["robot_agent:sage_s5"], out["robot_agent:sage_s6"]
    assert s5["n_episodes"] == s6["n_episodes"] == 3
    assert all("lab_events" in e for e in e6)
    # a fake LLM and an ideal user refuse nothing: the option never acts, so the outcome of every episode is the same
    assert [e["status"] for e in e5] == [e["status"] for e in e6]
    assert not any(ev.get("flag") == "dialog_agree" and ev.get("fire") for e in e6 for ev in e["lab_events"])
