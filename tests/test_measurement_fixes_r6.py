"""Lab round 6, step 1: measurement fixes (no scoring change).
H1  a --tasks file that differs from the packaged records is refused unless --allow-stale (tasks-file writes a fresh one)
H2  the bench object memory names the instance behind a name (inventory_ask counts instances, not names)
H3  a give_up with the call or time budget used up is status budget
H4  per-episode cache accounting (llm_cache, touched), one shared cache per replicate, the A/A self-check"""
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from homeloop_bench import cli
from homeloop_bench.env import Budgets, EpisodeEnv
from homeloop_bench.runner import StaleTasksError, aa_compare, load_tasks, run_many, stale_records

DATA = Path(__file__).resolve().parents[1] / "homeloop_bench" / "data" / "tasks"


def _rec(tid, split="dev"):
    for line in (DATA / f"{split}.jsonl").open(encoding="utf-8"):
        if f'"id":"{tid}"' in line:
            return json.loads(line)
    raise KeyError(tid)


def _write(path, recs):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return str(path)


# ── H1 ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_current_tasks_file_is_accepted_and_a_stale_one_refused(tmp_path):
    cur = _rec("hl-dev-000015")
    f = _write(tmp_path / "ok.jsonl", [cur])
    assert [t["id"] for t in load_tasks("dev", None, f)] == ["hl-dev-000015"]
    old = json.loads(json.dumps(cur))
    old["text"]["en"] = "Hey, tell Grandpa to head to the kitchen and bring that red book over to me."
    g = _write(tmp_path / "stale.jsonl", [old])
    assert stale_records([old]) == ["hl-dev-000015"]
    with pytest.raises(StaleTasksError, match="--allow-stale"):
        load_tasks("dev", None, g)
    assert len(load_tasks("dev", None, g, allow_stale=True)) == 1


def test_a_record_that_is_not_packaged_is_never_stale(tmp_path):
    r = _rec("hl-dev-000015")
    r["id"] = "custom-001"
    assert stale_records([r]) == []
    assert len(load_tasks(None, None, _write(tmp_path / "c.jsonl", [r]))) == 1


def test_the_cli_refuses_a_stale_file_and_allow_stale_runs_it(tmp_path, capsys):
    old = _rec("hl-dev-000015")
    old["text"]["en"] += " (old)"
    f = _write(tmp_path / "stale.jsonl", [old])
    args = ["run", "--planner", "oracle", "--split", "dev", "--tasks", f, "--profile", "ideal", "--out"]
    assert cli.main(args + [str(tmp_path / "o1")]) == 2
    assert "differ from the packaged split" in capsys.readouterr().err and not (tmp_path / "o1").exists()
    assert cli.main(args + [str(tmp_path / "o2"), "--allow-stale"]) == 0
    assert cli.main(["show", "hl-dev-000015", "--tasks", f]) == 2


def test_tasks_file_writes_the_current_records_and_refuses_test(tmp_path, capsys):
    out = tmp_path / "t.jsonl"
    assert cli.main(["tasks-file", "--split", "dev", "--ids", "14,hl-dev-000015", "--out", str(out)]) == 0
    got = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert got == [_rec("hl-dev-000014"), _rec("hl-dev-000015")]
    assert stale_records(got) == []
    assert cli.main(["tasks-file", "--split", "test", "--out", str(tmp_path / "x.jsonl")]) == 2
    assert not (tmp_path / "x.jsonl").exists()
    assert cli.main(["tasks-file", "--split", "dev", "--ids", "999999", "--out", str(tmp_path / "y.jsonl")]) == 1


# ── H3 ──────────────────────────────────────────────────────────────────────────────────────────────────

def _env(**b):
    return EpisodeEnv(_rec("hl-dev-000057"), "real", 0, "en", Budgets(**b))


def test_a_give_up_with_the_call_budget_used_up_is_budget():
    env = _env(max_calls=3)
    for _ in range(3):
        env.call("pose")
    assert env.n_calls == 3 and not env.budget_hit        # the planner never asked for a 4th call
    env.finish("give_up", "Sorry.")
    assert env.status == "budget"


def test_a_give_up_with_the_time_budget_used_up_is_budget():
    env = _env(max_sim_time_s=0.5)
    env.call("pose")
    env.finish("give_up", "Sorry.")
    assert env.status == "budget"


def test_give_up_with_budget_left_and_done_with_the_budget_used_up_keep_their_status():
    env = _env(max_calls=50)
    env.call("pose")
    env.finish("give_up", "Sorry.")
    assert env.status == "give_up"
    env = _env(max_calls=1)
    env.call("pose")
    env.finish("done", "Task completed")                   # the judge is unchanged: a claimed done stays done
    assert env.status == "done"


def test_a_persistent_fault_on_the_last_budgeted_call_stays_give_up():
    env = _env(max_calls=3)
    env.call("move", target="kids_desk@kids")
    env.call("pose")
    env.call("find", obj="green book")
    env.calls[-1].update(ok=False, code="hw_fault", event="hw_fault_persistent")
    env.finish("give_up", "Sorry.")
    assert env.status == "give_up"


# ── H2 ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_object_memory_names_the_instance_so_synonyms_are_one_candidate(tmp_path):
    pytest.importorskip("robot_agent")
    from homeloop_bench.planners.robot_agent_adapter import seed_memory
    from robot_agent.core.planning import goal_fix
    env = EpisodeEnv(_rec("hl-dev-000014"), "real", 0, "en", Budgets())
    f = tmp_path / "mem.json"
    seed_memory(env, f)
    objs = json.loads(f.read_text(encoding="utf-8"))["objects"]
    assert objs["black mug"]["instance"] == objs["black coffee mug"]["instance"] != objs["white mug"]["instance"]
    assert "mug" not in objs                                # two usual places: the bare name is left out
    names = [n for n in objs if n.endswith("mug")]
    groups = goal_fix.instances(names, objs, [])
    assert len(groups) == 2                                 # two mugs, not four names
    assert sorted(g[0] for g in groups) == ["black mug", "white mug"]


def test_a_record_of_a_name_shared_by_two_objects_has_no_instance(tmp_path):
    pytest.importorskip("robot_agent")
    from homeloop_bench.planners.robot_agent_adapter import seed_memory
    env = EpisodeEnv(_rec("hl-dev-000003"), "real", 0, "en", Budgets())
    f = tmp_path / "mem.json"
    seed_memory(env, f)
    objs = json.loads(f.read_text(encoding="utf-8"))["objects"]
    assert "book" in objs and "instance" not in objs["book"]        # two books on one shelf: the name means both


# ── H4 ──────────────────────────────────────────────────────────────────────────────────────────────────

def _episode(task_id, seed=0, misses=None, **kw):
    e = {"task_id": task_id, "seed": seed, "status": "done", "n_calls": 3, **kw}
    if misses is not None:
        e["llm_cache"] = {"hits": 1, "shared": 2, "misses": misses, "touched": misses > 0}
    return e


def test_aa_compare_requires_identical_untouched_episodes():
    a = [_episode("t1"), _episode("t2"), _episode("t3")]
    b = [_episode("t1", misses=0), _episode("t2", misses=0, n_calls=4), _episode("t3", misses=2, n_calls=9)]
    r = aa_compare(a, b)
    assert r["differ_untouched"] == ["t2#0"] and r["touched"] == ["t3#0"] and not r["ok"]
    assert r["n_untouched"] == 2 and r["n_identical_untouched"] == 1
    b[1]["n_calls"] = 3
    r = aa_compare(a, b)
    assert r["ok"] and r["n_touched"] == 1
    assert not aa_compare(a, [_episode("zz")])["ok"]                       # unpaired episodes
    assert not aa_compare(a, [_episode("t1", misses=5)])["ok"]            # nothing untouched: nothing verified


from test_shared_llm_cache import _Handler  # noqa: E402  (a local server in front of the keyword FakeLLM)


@pytest.fixture
def server():
    _Handler.n_chat = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _eps(d):
    return [json.loads(l) for l in (Path(d) / "episodes.jsonl").read_text(encoding="utf-8").splitlines()]


def test_episodes_count_cache_hits_misses_and_touched(tmp_path, monkeypatch, server):
    from fixtures import fixture_tasks
    tasks = fixture_tasks()[:2]
    monkeypatch.setenv("HOMELOOP_LLM_SHARED_CACHE", str(tmp_path / "shared"))
    run_many("progprompt_like", "dev", 2, "real", 1, "en", server, tmp_path / "a", model="m:1", tasks=tasks)
    run_many("progprompt_like", "dev", 2, "real", 1, "en", server, tmp_path / "b", model="m:1", tasks=tasks)
    ea, eb = _eps(tmp_path / "a"), _eps(tmp_path / "b")
    assert all(e["llm_cache"]["touched"] and e["llm_cache"]["misses"] >= 1 for e in ea)
    assert all(not e["llm_cache"]["touched"] and e["llm_cache"]["misses"] == 0 and e["llm_cache"]["shared"] >= 1
               for e in eb)
    assert aa_compare(ea, eb)["ok"]
    # a run without a cache (the fake LLM) writes the record as before
    run_many("progprompt_like", "dev", 2, "real", 1, "en", "fake", tmp_path / "c", tasks=tasks)
    assert all("llm_cache" not in e for e in _eps(tmp_path / "c"))


def test_replicates_have_their_own_shared_cache_and_aa_check_passes(tmp_path, server, monkeypatch, capsys):
    from fixtures import fixture_tasks
    tf = _write(tmp_path / "t.jsonl", fixture_tasks()[:2])
    monkeypatch.setenv("HOMELOOP_LLM_SHARED_CACHE", "")      # the cli sets it; monkeypatch restores it
    base = ["aa-check", "--planner", "progprompt_like", "--split", "dev", "--tasks", tf, "--profile", "real",
            "--llm", server, "--model", "m:1", "--shared-cache", str(tmp_path / "sc"), "--replicate", "r1"]
    assert cli.main(base + ["--out", str(tmp_path / "o")]) == 0
    res = json.loads((tmp_path / "o" / "aa_check.json").read_text(encoding="utf-8"))
    assert res["ok"] and res["n_untouched"] == 2 and res["n_touched"] == 0
    assert (tmp_path / "sc" / "r1" / "m_1.jsonl").exists()
    n = _Handler.n_chat
    # a second replicate has its own cache: it asks the server again
    assert cli.main(base[:-1] + ["r2", "--out", str(tmp_path / "o2")]) == 0
    assert _Handler.n_chat > n and (tmp_path / "sc" / "r2" / "m_1.jsonl").exists()
    # a URL without a shared cache cannot be checked
    assert cli.main(["aa-check", "--planner", "progprompt_like", "--tasks", tf, "--llm", server, "--out",
                     str(tmp_path / "o3")]) == 2


def test_the_user_intent_classifier_reads_the_shared_cache(tmp_path, monkeypatch):
    from homeloop_bench import user_intent
    from homeloop_bench.llm import CachedLLM

    class Raw:
        model = "m:1"
    monkeypatch.setenv("HOMELOOP_LLM_SHARED_CACHE", str(tmp_path / "sc"))
    user_intent._SHARED.clear()
    own = CachedLLM(Raw(), tmp_path / "run" / "m_1.jsonl")
    clf = user_intent.make_classifier(own)
    assert clf is not None
    inner = clf.llm if hasattr(clf, "llm") else None
    cached = inner if isinstance(inner, CachedLLM) else next(
        (v for v in vars(clf).values() if isinstance(v, CachedLLM)), None)
    assert cached is not None and cached.shared == tmp_path / "sc" / "m_1.jsonl"
    user_intent._SHARED.clear()
