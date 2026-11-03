"""``run --shard K/N`` + ``merge`` (R2-7c): on 12 dev tasks with --llm fake, the merged shards give the same
episodes.jsonl and the same summary.json (except ``config``) as the unsharded run; an incomplete or mismatched
set of shards is refused; the shards' LLM caches are merged one line per key."""
import json

import pytest

from homeloop_bench.runner import MergeError, merge_shards, run_many


def _run(planner, out, shard=None, lang="en"):
    return run_many(planner, "dev", 12, "real", 1, lang, "fake", out, shard=shard)


@pytest.mark.parametrize("planner", ["oracle", pytest.param("robot_agent:sage", marks=pytest.mark.skipif(
    __import__("importlib").util.find_spec("robot_agent") is None, reason="robot_agent not importable"))])
def test_sharded_merge_equals_unsharded(tmp_path, planner):
    for k in range(3):
        _run(planner, tmp_path / "sh", (k, 3))
    assert sorted(p.name for p in (tmp_path / "sh").iterdir() if p.is_dir()) == ["shard0", "shard1", "shard2"]
    # each shard holds tasks i % 3 == k, in dataset order
    ids = [json.loads(line)["task_id"] for line in (tmp_path / "sh" / "shard1" / "episodes.jsonl").open()]
    allids = json.loads((tmp_path / "sh" / "shard1" / "shard.json").read_text())["task_ids"]
    assert ids == allids[1::3] and len(allids) == 12
    merged = merge_shards(tmp_path / "sh")
    whole = _run(planner, tmp_path / "un")
    assert (tmp_path / "sh" / "episodes.jsonl").read_bytes() == (tmp_path / "un" / "episodes.jsonl").read_bytes()
    a = json.loads((tmp_path / "sh" / "summary.json").read_text())
    b = json.loads((tmp_path / "un" / "summary.json").read_text())
    assert {k: v for k, v in a.items() if k != "config"} == {k: v for k, v in b.items() if k != "config"}
    assert {k: v for k, v in a["config"].items() if k != "merged_shards"} == b["config"]
    assert a["config"]["merged_shards"] == 3 and merged["n_episodes"] == whole["n_episodes"] == 12


def test_incomplete_or_mismatched_shards_are_refused(tmp_path):
    with pytest.raises(MergeError):
        merge_shards(tmp_path)                                   # nothing to merge
    _run("oracle", tmp_path / "a", (0, 3))
    _run("oracle", tmp_path / "a", (2, 3))
    with pytest.raises(MergeError, match="need 0..2"):
        merge_shards(tmp_path / "a")
    _run("oracle", tmp_path / "a", (1, 3), lang="ko")           # other settings
    with pytest.raises(MergeError, match="other settings"):
        merge_shards(tmp_path / "a")
    _run("oracle", tmp_path / "a", (1, 3))
    lines = (tmp_path / "a" / "shard1" / "episodes.jsonl").read_text().splitlines()
    (tmp_path / "a" / "shard1" / "episodes.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(MergeError, match="incomplete"):
        merge_shards(tmp_path / "a")


def test_llm_caches_are_merged_one_line_per_key(tmp_path):
    for k in range(2):
        _run("oracle", tmp_path, (k, 2))
    rows = {0: [{"sha": "a", "response": "1"}, {"sha": "b", "response": "2"}],
            1: [{"sha": "b", "response": "2"}, {"sha": "c", "response": "3"}]}
    for k, rs in rows.items():
        d = tmp_path / f"shard{k}" / "llm_cache"
        d.mkdir()
        (d / "m.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rs))
    merge_shards(tmp_path)
    got = [json.loads(line)["sha"] for line in (tmp_path / "llm_cache" / "m.jsonl").read_text().splitlines()]
    assert got == ["a", "b", "c"]
