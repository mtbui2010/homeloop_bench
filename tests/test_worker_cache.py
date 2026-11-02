"""run --workers N with a URL LLM: every worker writes the run's llm_cache (docs/live_smoke.md), and a rerun
is served from it."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fixtures import fixture_tasks
from homeloop_bench.llm import FakeLLM
from homeloop_bench.runner import run_many

TASKS = fixture_tasks()


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


def test_workers_write_the_llm_cache(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        a = run_many("progprompt_like", "dev", 6, "real", 1, "en", url, tmp_path / "a", model="m:1",
                     tasks=TASKS, workers=2)
        files = list((tmp_path / "a" / "llm_cache").glob("*.jsonl"))
        assert len(files) == 1
        rows = [json.loads(l) for l in files[0].read_text(encoding="utf-8").splitlines()]
        assert len(rows) == _Handler.n_chat and len(rows) >= a["n_episodes"]
        assert len({r["sha"] for r in rows}) == len(rows)
        # a rerun into the same directory is served from the cache: no new chat requests
        before = _Handler.n_chat
        b = run_many("progprompt_like", "dev", 6, "real", 1, "en", url, tmp_path / "a", model="m:1",
                     tasks=TASKS, workers=2)
        assert _Handler.n_chat == before
        assert a == b
    finally:
        srv.shutdown()
