"""H2 (lab round 3): paired runs share one read-through prompt-sha response cache (common random numbers), so two
configurations whose code sends the same prompt get the same answer, whatever the server's sampling noise."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fixtures import fixture_tasks
from homeloop_bench.llm import FakeLLM
from homeloop_bench.llm import CachedLLM
from homeloop_bench.runner import run_many

TASKS = fixture_tasks()[:2]


class _Noisy:
    """An LLM whose answer to the same prompt differs on every call (sampling noise)."""
    model = "m:1"

    def __init__(self):
        self.n = 0

    def chat(self, prompt, format=None, temperature=0.0, seed=0):
        self.n += 1
        return f"answer {self.n}"

    def chat_messages(self, messages, temperature=0.0, seed=0, format=None):
        self.n += 1
        return f"answer {self.n}"


def test_variant_reuses_the_baselines_answer_to_an_identical_prompt(tmp_path):
    shared = tmp_path / "shared" / "m_1.jsonl"
    base = CachedLLM(_Noisy(), tmp_path / "a" / "m_1.jsonl", shared=shared)
    var_inner = _Noisy()
    var_inner.n = 100
    var = CachedLLM(var_inner, tmp_path / "b" / "m_1.jsonl", shared=shared)
    a1 = base.chat("understand: put the mug away")
    b1 = var.chat("understand: put the mug away")                    # identical prompt: the baseline's answer
    assert b1 == a1 and var_inner.n == 100 and var.shared_hits == 1
    b2 = var.chat("understand: a prompt the variant changed")        # new sha: the variant's own answer ...
    assert b2 == "answer 101" and var.misses == 1
    a2 = base.chat("understand: a prompt the variant changed")       # ... which the baseline then reuses
    assert a2 == b2
    m1 = base.chat_messages([{"role": "user", "content": "translate: x"}])
    assert var.chat_messages([{"role": "user", "content": "translate: x"}]) == m1
    # the variant's own cache file holds everything it used, so the run replays on its own
    own = [json.loads(l) for l in (tmp_path / "b" / "m_1.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["response"] for r in own} >= {a1, b2, m1}
    # a different prompt, different seed: not shared
    assert var.chat("understand: put the mug away", seed=7) != a1


class _Handler(BaseHTTPRequestHandler):
    fake = FakeLLM()
    n_chat = 0

    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send({"models": [{"name": "m:1", "digest": "d0"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).n_chat += 1
        o = body.get("options") or {}
        txt = self.fake.chat(body["messages"][0]["content"], format=body.get("format"),
                             temperature=o.get("temperature", 0.0), seed=o.get("seed", 0))
        self._send({"message": {"role": "assistant", "content": txt}})


def test_two_configurations_with_identical_code_share_calls_and_asks(tmp_path, monkeypatch):
    monkeypatch.setenv("HOMELOOP_LLM_SHARED_CACHE", str(tmp_path / "shared"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        run_many("progprompt_like", "dev", 2, "real", 1, "en", url, tmp_path / "a", model="m:1", tasks=TASKS)
        n_a = _Handler.n_chat
        assert n_a >= 1 and (tmp_path / "shared" / "m_1.jsonl").exists()
        run_many("progprompt_like", "dev", 2, "real", 1, "en", url, tmp_path / "b", model="m:1", tasks=TASKS)
        assert _Handler.n_chat == n_a                               # the second run asked the server nothing
    finally:
        srv.shutdown()
    ea = [json.loads(l) for l in (tmp_path / "a" / "episodes.jsonl").read_text(encoding="utf-8").splitlines()]
    eb = [json.loads(l) for l in (tmp_path / "b" / "episodes.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(ea) == len(eb) == 2
    for x, y in zip(ea, eb):
        for k in ("calls", "asked"):
            assert json.dumps(x[k], sort_keys=True) == json.dumps(y[k], sort_keys=True), k
