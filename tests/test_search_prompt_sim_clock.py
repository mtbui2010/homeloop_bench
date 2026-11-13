"""The search ranking prompt ("The X was seen at P 60 s ago") is built on the episode's simulated clock: the same episode
run on a fast and on a slow machine (the wall clock stepping differently, a real sleep inside the loop) gives the same
confidences and the same ranking prompt text. seed_memory stamps the seed on the simulated clock too."""
import json

import pytest

pytest.importorskip("robot_agent")

from fixtures import fixture_tasks  # noqa: E402
from homeloop_bench.env import EpisodeEnv  # noqa: E402
from homeloop_bench.planners.robot_agent_adapter import seed_memory  # noqa: E402
from homeloop_bench.runner import run_episode  # noqa: E402
from robot_agent.core.planning import search as S  # noqa: E402

TASKS = {t["id"]: t for t in fixture_tasks()}


def _run(monkeypatch, step, sleep):
    with monkeypatch.context() as mp:
        return _run_in(mp, step, sleep)


def _run_in(monkeypatch, step, sleep):
    import time as _time
    real, state, seen = _time.time, {"n": 0}, []

    def fake_time():
        state["n"] += 1
        return 1_700_000_000.0 + state["n"] * step

    orig = S.SearchBelief.see

    def spy(self, obj, *a, **k):
        out = orig(self, obj, *a, **k)
        _time.sleep(sleep)                                   # a slow machine / a slow LLM stub
        seen.append((obj, sorted(self.prior(obj).items()), self.rank_prompt(obj)))
        return out

    monkeypatch.setattr(S.SearchBelief, "see", spy)
    monkeypatch.setattr(_time, "time", fake_time)
    try:
        run_episode(TASKS["fx-feas-000"], "robot_agent:sage_s8n_d1", "ideal", 0, "en", "fake")
    finally:
        monkeypatch.setattr(_time, "time", real)
    return seen


def test_ranking_prompt_does_not_depend_on_machine_speed(monkeypatch):
    a = _run(monkeypatch, 0.0003, 0.0)
    b = _run(monkeypatch, 0.9, 0.02)
    assert a, "the search belief was consulted"
    assert json.dumps(a) == json.dumps(b)
    assert any(" ago." in p for _o, _s, p in a)


def test_seed_memory_is_stamped_on_the_simulated_clock(tmp_path):
    env = EpisodeEnv(TASKS["fx-feas-000"], "ideal", 0, "en")
    seed_memory(env, tmp_path / "m.json")
    ts = {e["ts"] for e in json.loads((tmp_path / "m.json").read_text())["objects"].values()}
    assert ts == {float(env.robot.clock.t)}
