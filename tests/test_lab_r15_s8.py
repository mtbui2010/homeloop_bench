"""Round 15: the ``sage_s8`` = ``sage_s7`` + ``reach_delivery`` and ``sage_s6d`` = ``sage_s6`` + ``reach_delivery`` variants, the one
new piece of pack data they carry (the person snapshot's trust time), and nothing else."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.planners import REGISTRY, planner_class  # noqa: E402


def test_registered():
    assert {"robot_agent:sage_s8", "robot_agent:sage_s6d"} <= set(REGISTRY)


def test_sage_s8_is_s7_plus_reach_delivery_only():
    s7, s8 = planner_class("robot_agent:sage_s7"), planner_class("robot_agent:sage_s8")
    assert s8.loop_options == {**s7.loop_options, "reach_delivery": "1", "unapplied_change": "1"}
    assert "reach_delivery" not in s7.loop_options and "unapplied_change" not in s7.loop_options
    mo7, mo8 = s7.manifest_overlay["planner"], s8.manifest_overlay["planner"]
    assert {k: v for k, v in mo8.items() if k != "person_snapshot"} == mo7
    assert set(mo8["person_snapshot"]) == {"trust_s"} and mo8["person_snapshot"]["trust_s"] > 0
    assert s8.manifest_overlay["assumed"] is True and "trust" in s8.manifest_overlay["note"]


def test_sage_s6d_is_s6_plus_reach_delivery_only():
    s6, s6d = planner_class("robot_agent:sage_s6"), planner_class("robot_agent:sage_s6d")
    assert s6d.loop_options == {**s6.loop_options, "reach_delivery": "1"}
    assert "dialog_agree2" not in s6d.loop_options and "relook" not in s6d.loop_options
    mo6, mo6d = s6.manifest_overlay["planner"], s6d.manifest_overlay["planner"]
    assert {k: v for k, v in mo6d.items() if k != "person_snapshot"} == mo6
    assert mo6d["person_snapshot"] == planner_class("robot_agent:sage_s8").manifest_overlay["planner"]["person_snapshot"]


def test_run_config_records_the_flag_only_where_it_is_set():
    for n in ("sage", "sage_ground2", "sage_r3u", "sage_s5", "sage_s6", "sage_s7"):
        c = planner_class(f"robot_agent:{n}").run_config()
        assert "reach_delivery" not in c and "person_snapshot" not in json.dumps(c)
    for n in ("sage_s8", "sage_s6d"):
        c = planner_class(f"robot_agent:{n}").run_config()
        assert c["reach_delivery"] == 1 and c["manifest_overlay"]["planner"]["person_snapshot"]["trust_s"] > 0


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_variants_under_fake_match_their_base_when_nobody_is_delivered_to(tmp_path, lang):
    from homeloop_bench.runner import run_many
    tasks = fixture_tasks()[:3]
    out = {}
    for n in ("robot_agent:sage_s7", "robot_agent:sage_s8", "robot_agent:sage_s6", "robot_agent:sage_s6d"):
        d = tmp_path / n.replace(":", "_")
        s = run_many(n, None, None, "ideal", 1, lang, "fake", d, tasks=tasks)
        out[n] = (s, [json.loads(line) for line in (d / "episodes.jsonl").read_text().splitlines()])
    assert all(s["n_episodes"] == 3 for s, _ in out.values())
    assert [e["status"] for e in out["robot_agent:sage_s7"][1]] == [e["status"] for e in out["robot_agent:sage_s8"][1]]
    assert [e["status"] for e in out["robot_agent:sage_s6"][1]] == [e["status"] for e in out["robot_agent:sage_s6d"][1]]
