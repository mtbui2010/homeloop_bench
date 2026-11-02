"""oracle / naive: the reference planner and its open-loop ablation (docs/planners.md)."""

from fixtures import fixture_tasks
from homeloop_bench.runner import run_episode

TASKS = fixture_tasks()


def _run(planner, profile, seeds=2):
    return [run_episode(t, planner, profile, s, "en", None) for t in TASKS for s in range(seeds)]


def test_oracle_ideal_solves_everything_without_false_success():
    eps = _run("oracle", "ideal")
    bad = [(e["task_id"], e["status"]) for e in eps if not e["success"]]
    assert not bad, bad
    assert not any(e["false_success"] for e in eps)


def test_oracle_asks_on_clarify_and_refuses_refuse():
    eps = {e["task_id"]: e for e in _run("oracle", "ideal", 1)}
    assert eps["fx-clar-000"]["asked"] == 1 and eps["fx-clar-000"]["help_correct"] is True
    assert eps["fx-ref-000"]["status"] == "refuse" and eps["fx-ref-001"]["status"] == "refuse"
    assert eps["fx-cmp-001"]["status"] == "done" and eps["fx-cmp-001"]["refused"]
    assert eps["fx-cor-000"]["goal_changed"]


def test_real_profile_oracle_beats_naive_and_never_claims_falsely():
    o = _run("oracle", "real", 6)
    n = _run("naive", "real", 6)
    so = sum(e["success"] for e in o) / len(o)
    sn = sum(e["success"] for e in n) / len(n)
    assert sn < so < 1.0, (sn, so)
    assert not any(e["false_success"] for e in o)
    assert any(f["code"] for e in o for f in e["failures"])          # injected failures happen


def test_naive_ideal_fails_only_the_correction():
    eps = _run("naive", "ideal", 1)
    bad = sorted(e["task_id"] for e in eps if not e["success"])
    assert bad == ["fx-cor-000"]
