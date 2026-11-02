"""run_many: same arguments -> identical files; workers do not change results (docs/runner.md)."""

import json

from fixtures import fixture_tasks
from homeloop_bench.runner import read_episodes, run_many

TASKS = fixture_tasks()


def test_same_args_identical_outputs(tmp_path):
    a = run_many("oracle", "dev", None, "real", 2, "en", None, tmp_path / "a", tasks=TASKS)
    b = run_many("oracle", "dev", None, "real", 2, "en", None, tmp_path / "b", tasks=TASKS)
    assert a == b
    for f in ("summary.json", "episodes.jsonl", "report.md"):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f
    s = json.loads((tmp_path / "a" / "summary.json").read_text())
    assert s["n_episodes"] == 2 * len(TASKS)
    eps = read_episodes(tmp_path / "a")
    assert [(e["task_id"], e["seed"]) for e in eps] == [(t["id"], s) for t in TASKS for s in range(2)]


def test_profiles_differ_and_lang_runs(tmp_path):
    i = run_many("oracle", "dev", None, "ideal", 1, "en", None, tmp_path / "i", tasks=TASKS)
    r = run_many("oracle", "dev", None, "real", 1, "en", None, tmp_path / "r", tasks=TASKS)
    k = run_many("oracle", "dev", None, "real", 1, "ko", None, tmp_path / "k", tasks=TASKS)
    assert i["success"] == 1.0 and i["config"]["profile_sha"] != r["config"]["profile_sha"]
    assert k["config"]["lang"] == "ko" and k["n_episodes"] == len(TASKS)


def test_workers_give_the_same_episodes(tmp_path):
    a = run_many("naive", "dev", 8, "real", 1, "en", None, tmp_path / "w1", tasks=TASKS, workers=1)
    b = run_many("naive", "dev", 8, "real", 1, "en", None, tmp_path / "w2", tasks=TASKS, workers=2)
    assert a == b
    assert (tmp_path / "w1" / "episodes.jsonl").read_bytes() == (tmp_path / "w2" / "episodes.jsonl").read_bytes()


def test_no_wall_clock_in_summary(tmp_path):
    run_many("oracle", "dev", 3, "real", 1, "en", None, tmp_path / "s", tasks=TASKS)
    txt = (tmp_path / "s" / "summary.json").read_text()
    for word in ("wall", "elapsed", "timestamp", "date"):
        assert word not in txt
