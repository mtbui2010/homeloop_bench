"""The shared cache is race-safe for common random numbers: lock mode (write-once per key), the refusal of parallel configurations
without it, and aa-check --concurrent on a cold cache."""
import json
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from fixtures import fixture_tasks
from homeloop_bench import cli, shared_cache as sc
from homeloop_bench.llm import CachedLLM
from test_shared_llm_cache import _Handler

ROOT = Path(__file__).resolve().parents[1]


class _Slow:
    """Each call takes a while and returns a different text: the cold-cache race."""
    model = "m:1"

    def __init__(self, start=0):
        self.n = start

    def chat(self, prompt, format=None, temperature=0.0, seed=0):
        time.sleep(0.3)
        self.n += 1
        return f"answer {self.n}"


def _race(tmp_path, n=4):
    shared = tmp_path / "shared" / "m_1.jsonl"
    llms = [CachedLLM(_Slow(100 * i), tmp_path / f"r{i}" / "m_1.jsonl", shared=shared) for i in range(n)]
    out = [None] * n

    def go(i):
        out[i] = llms[i].chat("the same prompt")
    ts = [threading.Thread(target=go, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return llms, out, shared


def test_without_lock_mode_the_race_gives_different_answers(tmp_path, monkeypatch):
    monkeypatch.delenv(sc.LOCK_ENV, raising=False)
    _, out, _ = _race(tmp_path)
    assert len(set(out)) > 1                      # the problem this module exists for


def test_lock_mode_is_write_once_per_key(tmp_path, monkeypatch):
    monkeypatch.setenv(sc.LOCK_ENV, "1")
    llms, out, shared = _race(tmp_path)
    assert len(set(out)) == 1, out                # every configuration got the first completed answer
    assert sum(l.inner.n - 100 * i for i, l in enumerate(llms)) == 1          # the server was asked once
    assert sum(l.misses for l in llms) == 1 and sum(l.shared_hits for l in llms) == len(llms) - 1
    rows = [json.loads(x) for x in shared.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["response"] == out[0]                   # one line per key
    # every run's own cache replays the same answer
    for i in range(len(llms)):
        assert json.loads((tmp_path / f"r{i}" / "m_1.jsonl").read_text(encoding="utf-8").splitlines()[0])["response"] == out[0]


def test_lock_mode_lets_a_failed_call_be_retried_by_the_next_run(tmp_path, monkeypatch):
    monkeypatch.setenv(sc.LOCK_ENV, "1")
    shared = tmp_path / "s" / "m_1.jsonl"

    class Boom(_Slow):
        def chat(self, *a, **k):
            raise RuntimeError("server down")
    with pytest.raises(RuntimeError):
        CachedLLM(Boom(), tmp_path / "a" / "m_1.jsonl", shared=shared).chat("p")
    assert CachedLLM(_Slow(), tmp_path / "b" / "m_1.jsonl", shared=shared).chat("p") == "answer 1"      # the lock was released


def test_registration_refuses_parallel_runs_unless_every_run_locks(tmp_path):
    d = tmp_path / "c"
    sc.register_run(d, False, "first")
    try:
        with pytest.raises(sc.SharedCacheError, match="another run is live"):
            sc.register_run(d, False, "second")
        with pytest.raises(sc.SharedCacheError):
            sc.register_run(d, True, "second, locking next to a non-locking run")
        assert len(sc.live_runs(d)) == 1                              # a refused run does not stay registered
    finally:
        sc.release_runs()
    assert sc.live_runs(d) == []                                      # sequential runs are fine
    sc.register_run(d, True, "a")
    try:
        sc.register_run(d, True, "b")                                 # both in lock mode
        assert len(sc.live_runs(d)) == 2
    finally:
        sc.release_runs()
    sc.register_run(d, False, "after")                                # and one at a time again
    sc.release_runs()


def test_a_dead_runs_registration_is_ignored_and_removed(tmp_path):
    d = tmp_path / "c" / sc.RUNS_DIR
    d.mkdir(parents=True)
    (d / "999-dead.run").write_text('{"id": "999-dead", "lock": false}')
    assert sc.live_runs(tmp_path / "c") == [] and not list(d.glob("*.run"))
    sc.register_run(tmp_path / "c", False)
    sc.release_runs()


HOLDER = """
import sys
from homeloop_bench import shared_cache as sc
sc.register_run(sys.argv[1], sys.argv[2] == "1", "other process")
print("ready", flush=True)
sys.stdin.read()
"""


@pytest.fixture
def other_run(tmp_path):
    procs = []

    def start(cache_dir, lock):
        p = subprocess.Popen([sys.executable, "-c", HOLDER, str(cache_dir), "1" if lock else "0"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True, cwd=ROOT)
        assert p.stdout.readline().strip() == "ready"
        procs.append(p)
    yield start
    for p in procs:
        p.stdin.close()
        p.wait(timeout=10)


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("HOMELOOP_LLM_SHARED_CACHE", "")
    monkeypatch.setenv(sc.LOCK_ENV, "")
    _Handler.n_chat = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _args(tmp_path, server, out, *extra, cmd="run"):
    tf = tmp_path / "t.jsonl"
    tf.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in fixture_tasks()[:2]), encoding="utf-8")
    return [cmd, "--planner", "progprompt_like", "--split", "dev", "--tasks", str(tf), "--profile", "real", "--llm", server,
            "--model", "m:1", "--shared-cache", str(tmp_path / "sc"), "--replicate", "r1", "--out", str(tmp_path / out), *extra]


def test_the_runner_refuses_a_parallel_configuration_without_lock_mode(tmp_path, server, other_run, capsys):
    other_run(tmp_path / "sc" / "r1", False)
    assert cli.main(_args(tmp_path, server, "o1")) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "--cache-lock" in err
    assert _Handler.n_chat == 0 and not (tmp_path / "o1" / "episodes.jsonl").exists()
    assert cli.main(_args(tmp_path, server, "o2", "--cache-lock")) == 2          # the other run is not locking
    assert cli.main(_args(tmp_path, server, "o3", cmd="aa-check")) == 2


def test_the_runner_runs_next_to_a_locking_run_when_it_locks_too(tmp_path, server, other_run):
    other_run(tmp_path / "sc" / "r1", True)
    assert cli.main(_args(tmp_path, server, "o1", "--cache-lock")) == 0
    assert (tmp_path / "o1" / "episodes.jsonl").exists()


def test_the_runner_runs_a_configuration_after_the_other_has_ended(tmp_path, server):
    assert cli.main(_args(tmp_path, server, "o1")) == 0
    assert cli.main(_args(tmp_path, server, "o2")) == 0                           # sequential per replicate: the default
    assert sc.live_runs(tmp_path / "sc" / "r1") == []


def test_aa_check_concurrent_on_a_cold_cache_requires_identical_episodes(tmp_path, server):
    assert not (tmp_path / "sc").exists()                                         # cold
    rc = cli.main(_args(tmp_path, server, "o", "--concurrent", cmd="aa-check"))
    assert rc == 0
    res = json.loads((tmp_path / "o" / "aa_check.json").read_text(encoding="utf-8"))
    assert res["ok"] and res["n_untouched"] == 2 and res["n_differ_untouched"] == 0      # strict: every episode compared
    rows = [json.loads(x)["sha"] for x in (tmp_path / "sc" / "r1" / "m_1.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(set(rows))                                            # one line per key
    assert _Handler.n_chat == len(rows)                                           # each key asked the server once


def test_aa_compare_strict_counts_every_episode():
    from homeloop_bench.runner import aa_compare
    a = [{"task_id": "t", "seed": 0, "n": 1, "llm_cache": {"misses": 3}}]
    b = [{"task_id": "t", "seed": 0, "n": 2, "llm_cache": {"misses": 3}}]
    assert aa_compare(a, b)["ok"] is False                                        # (nothing untouched: nothing verified)
    r = aa_compare(a, b, strict=True)
    assert not r["ok"] and r["differ_untouched"] == ["t#0"]
    b[0]["n"] = 1
    assert aa_compare(a, b, strict=True)["ok"]
